"""Root-only supervisor. Accepts signed Plesk assertions over a restricted socket."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import signal
import shutil
import re
import socket
import socketserver
import struct
import subprocess
import threading
import time
import urllib.request

from .policy import Denied, verify_grant, workspace_key, same_database
from .provisioning import Provisioner
from .transport import owns_connected_peer


def atomic_json(path, value, mode=0o600):
    temporary = path.with_suffix('.new')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def owns_loopback_listener(pid, port):
    """Do not send provisioning secrets to a process that won an ephemeral-port race."""
    expected = f'0100007F:{port:04X}'
    try:
        uid = Path(f'/proc/{pid}').stat().st_uid
        return any(line.split()[1] == expected and line.split()[3] == '0A'
                   and int(line.split()[7]) == uid
                   for line in Path('/proc/net/tcp').read_text().splitlines()[1:])
    except (OSError, IndexError):
        return False


class Supervisor:
    def __init__(self, config):
        self.config = config
        self.key = Path(config['grant_key']).read_bytes().strip()
        self.state = Path(config['state_dir'])
        self.state.parent.mkdir(mode=0o711, parents=True, exist_ok=True)
        os.chmod(self.state.parent, 0o711)
        self.state.mkdir(mode=0o711, exist_ok=True)
        self.workspaces = {}
        self.lock = threading.RLock()
        self.recover()

    def recover(self):
        # systemd KillMode=control-group terminates descendants on service restart.
        # Journaled credentials are then revoked before their directories are reused.
        journals = self.state.parent / 'journals'
        if not journals.exists():
            return
        for path in journals.glob('*.json'):
            record = json.loads(path.read_text())
            if not re.fullmatch(r'[a-f0-9]{32}', record['id']) or path.stem != record['id']:
                raise Denied('Invalid recovery journal')
            self.cleanup(record)

    def cleanup(self, workspace):
        failures = []
        for credential in workspace['credentials']:
            try:
                self.credential('revoke', credential['database'], credential['username'])
            except Exception:
                failures.append(credential)
        workspace['credentials'] = failures
        self.journal(workspace)
        # Remove secret-bearing runtime files before releasing the Unix UID.
        directory = self.state / workspace['id']
        if directory.exists():
            shutil.rmtree(directory)
        try:
            account = pwd.getpwnam(workspace['account'])
            if account.pw_uid != workspace['uid'] or account.pw_uid == 0:
                raise Denied('Runtime account identity changed')
            subprocess.run(['/usr/sbin/userdel', workspace['account']], check=True, capture_output=True)
        except KeyError:
            pass
        if not failures:
            (self.state.parent / 'journals' / (workspace['id'] + '.json')).unlink(missing_ok=True)

    def credential(self, action, database, username=None, password=None):
        request = {'action': action, 'databaseId': database['id']}
        if username:
            request['username'] = username
        if password:
            request['password'] = password
        completed = subprocess.run([self.config['plesk_php'], self.config['credential_helper']],
                                   input=json.dumps(request), text=True, capture_output=True, timeout=60)
        if completed.returncode:
            raise Denied('Database credential operation failed')
        try:
            payload = json.loads(completed.stdout)['result']
            if action == 'inspect':
                return {'id': payload['databaseId'], 'name': payload['database'],
                        'driver': 'postgres' if payload['driver'] == 'postgresql' else payload['driver'],
                        'host': '127.0.0.1' if payload['host'] == 'localhost' else payload['host'],
                        'port': payload['port'], 'domain_id': payload['domainId'],
                        'server_id': payload['serverId'], 'owner': str(payload['ownerId'])}
            return payload
        except (ValueError, KeyError, TypeError):
            raise Denied('Invalid database credential response') from None

    def validate_catalogue(self, grant):
        for database in grant['databases']:
            actual = self.credential('inspect', database)
            if not same_database(database, actual):
                raise Denied('Database access changed')

    def acquire(self, envelope):
        grant = verify_grant(envelope, self.key)
        identifier = workspace_key(grant)
        with self.lock:
            verify_grant(envelope, self.key)
            # A grant with changed permissions retires other runtimes for this session.
            for old, workspace in list(self.workspaces.items()):
                if workspace['session'] == grant['session'] and old != identifier:
                    self.stop(old)
            workspace = self.workspaces.get(identifier)
            if workspace and workspace['process'].poll() is None:
                workspace['used'] = time.monotonic()
                return {**self.public(workspace), 'created': False}
            if workspace:
                self.stop(identifier)
            if len(self.workspaces) >= self.config.get('max_workspaces', 8):
                raise Denied('Workspace capacity reached; try again later')
            if (self.state.parent / 'journals' / (identifier + '.json')).exists():
                raise Denied('Previous credential cleanup requires administrator review')
            self.validate_catalogue(grant)
            workspace = self.start(identifier, grant)
            self.workspaces[identifier] = workspace
            try:
                connections = []
                for database in grant['databases']:
                    if workspace['cancelled'].is_set():
                        raise Denied('Workspace authorization was revoked')
                    username = 'tab_' + secrets.token_hex(12)
                    password = secrets.token_urlsafe(36)
                    # Journal intent first, so a helper timeout cannot lose cleanup ownership.
                    record = {'database': database, 'username': username}
                    workspace['credentials'].append(record)
                    self.journal(workspace)
                    self.credential('provision', database, username, password)
                    connections.append({'external_ref': f"plesk-db-{database['id']}",
                                        'name': database['domain'] + ' / ' + database['name'],
                                        'params': {'driver': database['driver'], 'host': database['host'],
                                                   'port': database['port'], 'database': database['name'],
                                                   'username': username, 'password': password,
                                                   'read_only': False}})
                workspace['connections'] = Provisioner(workspace['port'], workspace['provisioning'], self.config['public_origin'], workspace['process'], workspace['uid']).reconcile(connections)
                self.validate_catalogue(grant)
                if workspace['cancelled'].is_set():
                    raise Denied('Workspace authorization was revoked')
                workspace['ready'] = True
                return {**self.public(workspace), 'created': True}
            except Exception:
                self.stop(identifier)
                raise Denied('Workspace preparation failed; no database access was granted') from None

    def start(self, identifier, grant):
        account = 'tbw_' + identifier[:20]
        try:
            user = pwd.getpwnam(account)
        except KeyError:
            subprocess.run(['/usr/sbin/useradd', '--system', '--user-group', '--no-create-home',
                            '--shell', '/usr/sbin/nologin', account], check=True, capture_output=True)
            user = pwd.getpwnam(account)
        directory = self.state / identifier
        directory.mkdir(mode=0o700, exist_ok=True)
        home = directory / 'home'
        home.mkdir(mode=0o700, exist_ok=True)
        os.chown(directory, user.pw_uid, user.pw_gid)
        os.chown(home, user.pw_uid, user.pw_gid)
        # Parent must be searchable, never readable, by workspace accounts.
        os.chmod(self.state, 0o711)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        proxy_secret, provisioning = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        prefix = '/tabularis/w/' + identifier + '/'
        command = [self.config['binary'], 'web', '--host', '127.0.0.1', '--port', str(port),
                   '--no-open', '--web-root', self.config['web_root'], '--auth', 'proxy',
                   '--public-url', self.config['public_origin'], '--allowed-origin', self.config['public_origin'],
                   '--trusted-proxy', '127.0.0.1/32', '--connection-mode', 'managed-only',
                   '--base-path', prefix]
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(home),
                       'XDG_CONFIG_HOME': str(home / '.config'), 'XDG_DATA_HOME': str(home / '.local/share'),
                       'TABULARIS_WEB_PROXY_SECRET': proxy_secret,
                       'TABULARIS_PROVISIONING_TOKEN': provisioning, 'RUST_LOG': 'warn',
                       'TOKIO_WORKER_THREADS': '4', 'RAYON_NUM_THREADS': '2'}

        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
        memory = self.config.get('workspace_memory_mb', 8192) * 1024 * 1024
        launch = ['/usr/bin/python3', '-m', 'tabularis_plesk.runner', str(user.pw_uid), str(user.pw_gid), str(memory)]
        process = subprocess.Popen(launch + command, env=environment, cwd=home, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        workspace = {'id': identifier, 'session': grant['session'], 'identity': grant['identity'],
                     'port': port, 'proxy_secret': proxy_secret, 'provisioning': provisioning,
                     'process': process, 'used': time.monotonic(), 'connections': {},
                     'credentials': [], 'ready': False, 'uid': user.pw_uid, 'account': account,
                     'cancelled': threading.Event()}
        self.journal(workspace)
        for _ in range(100):
            if process.poll() is not None:
                self.cleanup(workspace)
                raise Denied('Tabularis runtime failed to start')
            if not owns_loopback_listener(process.pid, port):
                time.sleep(0.1)
                continue
            try:
                request = urllib.request.Request(f'http://127.0.0.1:{port}/healthz',
                                                 headers={'Host': self.config['public_origin'].split('://', 1)[1]})
                with urllib.request.urlopen(request, timeout=0.3) as response:
                    if response.status == 200:
                        return workspace
            except OSError:
                time.sleep(0.1)
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        self.cleanup(workspace)
        raise Denied('Tabularis runtime did not become ready')

    def journal(self, workspace):
        journals = self.state.parent / 'journals'
        journals.mkdir(mode=0o700, exist_ok=True)
        atomic_json(journals / (workspace['id'] + '.json'),
                    {key: workspace[key] for key in ('id', 'credentials', 'account', 'uid')})

    @staticmethod
    def public(workspace):
        if not workspace['ready']:
            raise Denied('Workspace is not ready')
        return {key: workspace[key] for key in ('id', 'port', 'proxy_secret', 'identity', 'connections')}

    def attest(self, identifier, client_port, server_port):
        workspace = self.workspaces.get(identifier)
        if not workspace or not workspace['ready'] or workspace['cancelled'].is_set():
            raise Denied('Workspace is unavailable')
        if type(client_port) is not int or not 1 <= client_port <= 65535 or server_port != workspace['port']:
            raise Denied('Invalid runtime connection')
        if not owns_connected_peer(workspace['process'], workspace['uid'], ('127.0.0.1', client_port), ('127.0.0.1', server_port)):
            raise Denied('Runtime connection ownership changed')
        return {'verified': True}

    def touch(self, identifier, envelope):
        grant = verify_grant(envelope, self.key)
        if workspace_key(grant) != identifier:
            raise Denied('Workspace access changed')
        workspace = self.workspaces.get(identifier)
        if not workspace or not workspace['ready'] or workspace['cancelled'].is_set():
            raise Denied('Workspace is not available')
        workspace['used'] = time.monotonic()
        return {'active': True}

    def interrupt(self, identifier):
        # The process record is immutable after insertion. Signal immediately,
        # even while another worker holds the provisioning lock; cleanup follows.
        workspace = self.workspaces.get(identifier)
        if workspace:
            workspace['cancelled'].set()
            process = workspace['process']
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def stop(self, identifier):
        workspace = self.workspaces.pop(identifier, None)
        if not workspace:
            return
        process = workspace['process']
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        self.cleanup(workspace)

    def reap(self):
        with self.lock:
            for identifier, workspace in list(self.workspaces.items()):
                if time.monotonic() - workspace['used'] > self.config.get('idle_seconds', 900):
                    self.stop(identifier)


class BrokerHandler(socketserver.StreamRequestHandler):
    def handle(self):
        _, uid, _ = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != self.server.gateway_uid:
            return
        self.request.settimeout(120)
        try:
            line = self.rfile.readline(196609)
            if len(line) > 196608 or not line.endswith(b'\n'):
                raise Denied('Invalid request')
            request = json.loads(line)
            if request.get('action') == 'acquire':
                response = self.server.supervisor.acquire(request['grant'])
            elif request.get('action') == 'attest':
                response = self.server.supervisor.attest(str(request['workspace']), request['client_port'], request['server_port'])
            elif request.get('action') == 'touch':
                response = self.server.supervisor.touch(str(request['workspace']), request['grant'])
            elif request.get('action') == 'revoke':
                self.server.supervisor.interrupt(str(request['workspace']))
                with self.server.supervisor.lock:
                    self.server.supervisor.stop(str(request['workspace']))
                response = {'revoked': True}
            else:
                raise Denied('Unsupported operation')
            self.wfile.write(json.dumps({'result': response}).encode() + b'\n')
        except Exception:
            self.wfile.write(b'{"error":"Workspace access unavailable"}\n')


class BrokerServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/tabularis-plesk/config.json')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('The broker requires root; its child runtimes do not')
    config = json.loads(Path(args.config).read_text())
    gateway = pwd.getpwnam('tabularis-gateway')
    path = Path(config['broker_socket'])
    path.unlink(missing_ok=True)
    supervisor = Supervisor(config)
    with BrokerServer(str(path), BrokerHandler) as server:
        server.gateway_uid = gateway.pw_uid
        server.supervisor = supervisor
        os.chown(path, 0, gateway.pw_gid)
        os.chmod(path, 0o660)
        server.timeout = 2
        stopping = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stopping.set())
        while not stopping.is_set():
            server.handle_request()
            supervisor.reap()
        for identifier in list(supervisor.workspaces):
            supervisor.stop(identifier)


if __name__ == '__main__':
    main()
