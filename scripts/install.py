#!/usr/bin/env python3
"""Configure a previously installed Plesk extension with a verified local runtime."""
import argparse
import hashlib
import ipaddress
import re
import grp
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

MODULE = Path('/usr/local/psa/admin/plib/modules/tabularis')
VARIABLE = Path('/usr/local/psa/var/modules/tabularis')
CONFIG = Path('/etc/tabularis-plesk')


def write(path, content, mode=0o600, group=0):
    temporary = path.with_suffix('.new')
    descriptor = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(content)
    os.chown(temporary, 0, group)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def root_owned(path):
    path = path.resolve(strict=True)
    for item in (path, *path.parents):
        info = item.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Runtime files and their parents must be root-owned and not writable by others')
    return path


def proxy_map(addresses):
    addresses = [str(ipaddress.ip_address(value)) for value in addresses]
    lines = ['map "$remote_addr|$http_x_forwarded_for" $tabularis_client_ip {',
             '    default $remote_addr;']
    if addresses:
        trusted = '|'.join(re.escape(value) for value in addresses)
        lines.append('    ~^(?:' + trusted + r')\|(?<tabularis_forwarded_ip>[0-9a-fA-F:.]+)$ $tabularis_forwarded_ip;')
    return '\n'.join(lines + ['}', ''])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--web-root', type=Path, required=True)
    parser.add_argument('--public-origin', required=True)
    parser.add_argument('--max-workspaces', type=int, default=8)
    parser.add_argument('--trusted-panel-proxy', action='append', default=[],
                        help='Exact trusted reverse-proxy IP; pair with Plesk panel realIpFrom')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run the installer as root on the Plesk server')
    if sys.version_info < (3, 10):
        parser.error('Python 3.10 or newer is required')
    import aiohttp  # Validate dependencies before making changes.
    forwarded_map = proxy_map(args.trusted_panel_proxy)
    origin = urlsplit(args.public_origin)
    if origin.scheme != 'https' or not origin.netloc or origin.path not in ('', '/') or origin.query or origin.fragment or origin.username:
        parser.error('--public-origin must be the exact HTTPS origin used by the browser')
    if any(character.isspace() or character in '{};$"' for character in origin.netloc):
        parser.error('Invalid origin hostname')
    if not 1 <= args.max_workspaces <= 64:
        parser.error('--max-workspaces must be between 1 and 64')
    binary, web_root = root_owned(args.binary), root_owned(args.web_root)
    for asset in web_root.rglob('*'):
        if asset.is_symlink():
            parser.error('The Web UI build must not contain symlinks')
        root_owned(asset)
    if hashlib.sha256(binary.read_bytes()).hexdigest() != args.sha256.lower():
        parser.error('The runtime SHA-256 does not match')
    if not (web_root / 'index.html').is_file() or not (MODULE / 'broker').is_dir():
        parser.error('Install the extension ZIP and provide a complete Web UI build first')
    help_output = subprocess.run([str(binary), 'web', '--help'], capture_output=True, text=True, check=True).stdout
    if '--base-path' not in help_output or '--connection-mode' not in help_output:
        parser.error('The pinned runtime lacks required base-path or managed-only support')
    try:
        gateway = pwd.getpwnam('tabularis-gateway')
    except KeyError:
        subprocess.run(['useradd', '--system', '--user-group', '--no-create-home', '--shell', '/usr/sbin/nologin',
                        'tabularis-gateway'], check=True)
        gateway = pwd.getpwnam('tabularis-gateway')
    panel = pwd.getpwnam('psaadm')
    grp.getgrnam('sw-cp-server')
    CONFIG.mkdir(mode=0o755, exist_ok=True)
    VARIABLE.mkdir(mode=0o750, exist_ok=True)
    os.chown(VARIABLE, 0, panel.pw_gid)
    os.chmod(VARIABLE, 0o750)
    for name in ('grant.key', 'callback.key'):
        if not (VARIABLE / name).exists():
            write(VARIABLE / name, secrets.token_hex(48), mode=0o640, group=panel.pw_gid)
    write(CONFIG / 'callback.key', (VARIABLE / 'callback.key').read_text(), 0o640, gateway.pw_gid)
    settings = {'public_origin': args.public_origin.rstrip('/'), 'binary': str(binary), 'binary_sha256': args.sha256,
                'web_root': str(web_root), 'state_dir': '/var/lib/tabularis-plesk/workspaces',
                'grant_key': str(VARIABLE / 'grant.key'), 'callback_key': str(CONFIG / 'callback.key'),
                'broker_socket': '/run/tabularis-broker/control.sock',
                'gateway_socket': '/run/tabularis-gateway/http.sock',
                'auth_socket': '/run/tabularis-auth.sock', 'max_workspaces': args.max_workspaces,
                'idle_seconds': 900, 'workspace_memory_mb': 8192,
                'trusted_panel_proxies': args.trusted_panel_proxy,
                'plesk_php': '/usr/local/psa/admin/bin/php', 'credential_helper': str(MODULE / 'credentials.php')}
    if (CONFIG / 'config.json').exists():
        previous = json.loads((CONFIG / 'config.json').read_text())
        if previous != settings:
            write(CONFIG / 'config.previous.json', json.dumps(previous, indent=2))
    write(CONFIG / 'config.json', json.dumps(settings, indent=2))
    public = {name: settings[name] for name in ('public_origin', 'callback_key', 'broker_socket', 'gateway_socket', 'auth_socket')}
    write(CONFIG / 'gateway.json', json.dumps(public, indent=2), 0o640, gateway.pw_gid)
    module_path = str(MODULE / 'broker')
    broker_unit = f'''[Unit]
Description=Tabularis Plesk workspace broker
After=network.target sw-engine.service
[Service]
Type=simple
Environment=PYTHONPATH={module_path}
ExecStart=/usr/bin/python3 -m tabularis_plesk.broker
RuntimeDirectory=tabularis-broker
RuntimeDirectoryMode=0755
UMask=0077
Restart=on-failure
RestartSec=5
TimeoutStopSec=120
KillMode=control-group
TasksMax=2048
[Install]
WantedBy=multi-user.target
'''
    gateway_unit = f'''[Unit]
Description=Tabularis Plesk authenticated gateway
After=tabularis-broker.service sw-cp-server.service
Requires=tabularis-broker.service
[Service]
User=tabularis-gateway
Group=sw-cp-server
SupplementaryGroups=tabularis-gateway
Environment=PYTHONPATH={module_path}
ExecStart=/usr/bin/python3 -m tabularis_plesk.gateway
RuntimeDirectory=tabularis-gateway
RuntimeDirectoryMode=0750
UMask=0007
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/run/tabularis-gateway
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=512M
TasksMax=128
[Install]
WantedBy=multi-user.target
'''
    write(Path('/etc/systemd/system/tabularis-broker.service'), broker_unit, 0o644)
    write(Path('/etc/systemd/system/tabularis-gateway.service'), gateway_unit, 0o644)
    nginx = '''# Managed by Tabularis. This private server is reachable only over a local socket.
server {
    listen unix:/run/tabularis-auth.sock;
    server_name localhost;
    access_log off;
    location = /authorize {
        include /etc/sw-cp-server/fastcgi_params;
        fastcgi_pass unix:/var/run/sw-engine.sock;
        fastcgi_param SCRIPT_FILENAME /usr/local/psa/admin/htdocs/modules/tabularis/index.php;
        fastcgi_param SCRIPT_NAME /modules/tabularis/index.php;
        fastcgi_param REQUEST_URI /modules/tabularis/index.php/index/authorize;
        fastcgi_param PATH_INFO /index/authorize;
        fastcgi_param REMOTE_ADDR $http_x_tabularis_client_ip;
        fastcgi_param HTTPS on;
        fastcgi_param SERVER_PORT 8443;
        fastcgi_param HTTP_X_TABULARIS_CALLBACK $http_x_tabularis_callback;
    }
    location / { return 404; }
}
'''
    location = '''# Managed by Tabularis. Uses the panel's HTTPS certificate and origin.
location ^~ /tabularis/ {
    if ($scheme != https) { return 403; }
    proxy_pass http://unix:/run/tabularis-gateway/http.sock:;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $tabularis_client_ip;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 3600s;
    client_max_body_size 1m;
    access_log off;
}
'''
    write(Path('/etc/sw-cp-server/conf.d/tabularis.conf'), forwarded_map + nginx, 0o644)
    write(Path('/etc/sw-cp-server/conf.d/tabularis_plesk.inc'), location, 0o644)
    subprocess.run(['/usr/sbin/sw-cp-serverd', '-t', '-c', '/etc/sw-cp-server/config'], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'reload', 'sw-cp-server'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'tabularis-broker', 'tabularis-gateway'], check=True)
    subprocess.run(['systemctl', 'restart', 'tabularis-broker', 'tabularis-gateway'], check=True)
    write(VARIABLE / 'configured', '0.1.0\n', 0o640, panel.pw_gid)
    print('Tabularis services configured. Open Tabularis from the Plesk navigation.')


if __name__ == '__main__':
    main()
