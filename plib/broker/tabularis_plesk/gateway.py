"""Unprivileged HTTP/WebSocket bridge. Every request obtains a fresh Plesk grant."""
import argparse
import asyncio
import json
import hashlib
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientConnectionError, ClientSession, ClientTimeout, DummyCookieJar, TCPConnector, UnixConnector, WSMsgType, web

from .policy import workspace_key

HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length'}
BLOCKED_HEADERS = HOP_HEADERS | {'host', 'cookie', 'authorization', 'forwarded',
                                 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto',
                                 'x-tabularis-user', 'x-tabularis-proxy-secret',
                                 'x-tabularis-client-ip', 'x-tabularis-callback',
                                 'sec-websocket-key', 'sec-websocket-version',
                                 'sec-websocket-extensions', 'sec-websocket-protocol'}


def upstream_headers(request, workspace, origin):
    headers = {key: value for key, value in request.headers.items() if key.lower() not in BLOCKED_HEADERS}
    headers.update({'Host': urlsplit(origin).netloc, 'X-Tabularis-User': workspace['identity'],
                    'X-Tabularis-Proxy-Secret': workspace['proxy_secret'],
                    'X-Forwarded-For': request.headers.get('X-Real-IP', '127.0.0.1'),
                    'X-Forwarded-Proto': 'https'})
    # The Plesk session never reaches Tabularis. Each workspace has an independent
    # cookie path, session-derived identity and server process.
    if request.cookies.get('tabularis_session'):
        headers['Cookie'] = 'tabularis_session=' + request.cookies['tabularis_session']
    return headers


class RuntimeConnector(TCPConnector):
    def __init__(self, attest):
        super().__init__()
        self.attest = attest

    async def _wrap_create_connection(self, *args, **kwargs):
        transport, protocol = await super()._wrap_create_connection(*args, **kwargs)
        try:
            await self.attest(transport.get_extra_info('socket'))
            return transport, protocol
        except Exception:
            transport.close()
            raise ClientConnectionError('Private runtime transport verification failed') from None


class Gateway:
    def __init__(self, config):
        self.config = config
        self.callback_secret = Path(config['callback_key']).read_text().strip()
        self.limit = asyncio.Semaphore(config.get('max_requests', 64))
        self.authorizer = None
        self.client = None
        self.bindings = {}
        self.revocations = {}
        self.targets = {}

    async def start(self, app):
        self.authorizer = ClientSession(connector=UnixConnector(path=self.config['auth_socket']),
                                        timeout=ClientTimeout(total=15), cookie_jar=DummyCookieJar())
        self.client = ClientSession(timeout=ClientTimeout(total=None, sock_connect=10, sock_read=300),
                                    connector=RuntimeConnector(self.attest),
                                    cookie_jar=DummyCookieJar(), auto_decompress=False)

    async def cleanup(self, app):
        for task in list(self.revocations.values()):
            task.cancel()
        await asyncio.gather(*list(self.revocations.values()), return_exceptions=True)
        await self.authorizer.close()
        await self.client.close()

    async def attest(self, connection):
        client = connection.getsockname()
        server = connection.getpeername()
        workspace = self.targets.get(server[1])
        if client[0] != '127.0.0.1' or server[0] != '127.0.0.1' or not workspace:
            raise ClientConnectionError('Unknown runtime connection')
        await asyncio.wait_for(self.broker({'action': 'attest', 'workspace': workspace,
                                            'client_port': client[1], 'server_port': server[1]}), timeout=2)

    async def broker(self, value):
        reader, writer = await asyncio.open_unix_connection(self.config['broker_socket'], limit=196608)
        try:
            writer.write(json.dumps(value).encode() + b'\n')
            await writer.drain()
            response = json.loads(await asyncio.wait_for(reader.readline(), timeout=120))
            if 'error' in response:
                raise web.HTTPServiceUnavailable(text='Workspace preparation failed. Contact the administrator.')
            return response['result']
        finally:
            writer.close()
            await writer.wait_closed()

    async def authorize(self, request):
        # Both HTTP Host and browser origin are checked before touching panel cookies.
        expected = urlsplit(self.config['public_origin'])
        if request.host != expected.netloc:
            raise web.HTTPForbidden(text='Invalid panel origin')
        origin = request.headers.get('Origin')
        if origin and origin != self.config['public_origin']:
            raise web.HTTPForbidden(text='Invalid browser origin')
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise web.HTTPForbidden(text='Cross-site access denied')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin != self.config['public_origin']:
            raise web.HTTPForbidden(text='Browser origin required')
        headers = {'Cookie': request.headers.get('Cookie', ''),
                   'X-Tabularis-Callback': self.callback_secret,
                   'X-Tabularis-Client-IP': request.headers.get('X-Real-IP', ''),
                   'Host': expected.netloc}
        async with self.authorizer.get('http://localhost/authorize', headers=headers, allow_redirects=False) as response:
            if response.status != 200:
                raise web.HTTPForbidden(text='The Plesk session or database permission is no longer valid.')
            envelope = await response.json()
        # Signature verification happens in the privileged broker. This local parse
        # is only for early path rejection and is never sufficient to start a runtime.
        import base64
        grant = json.loads(base64.b64decode(envelope['payload'], validate=True))
        return envelope, workspace_key(grant)

    def revoke_later(self, identifier):
        if identifier in self.revocations:
            return

        async def revoke():
            try:
                await asyncio.wait_for(self.broker({'action': 'revoke', 'workspace': identifier}), timeout=5)
            except Exception:
                # Relays are already closed. The broker's idle/recovery cleanup is
                # the fallback if local cleanup cannot complete in this bound.
                pass
            finally:
                self.revocations.pop(identifier, None)

        self.revocations[identifier] = asyncio.create_task(revoke())

    async def revalidate(self, request, identifier):
        try:
            envelope, current = await self.authorize(request)
            if current != identifier:
                raise web.HTTPForbidden(text='Database access changed. Open Tabularis again from Plesk.')
            # This operation never waits for unrelated workspace provisioning.
            await asyncio.wait_for(self.broker({'action': 'touch', 'grant': envelope,
                                                'workspace': identifier}), timeout=2)
        except Exception:
            # Never await privileged cleanup before the caller closes both relays.
            self.revoke_later(identifier)
            raise

    async def handle(self, request):
        async with self.limit:
            identifier = request.match_info.get('workspace')
            panel_cookies = {key: value for key, value in request.cookies.items() if key != 'tabularis_session'}
            binding = hashlib.sha256(json.dumps(panel_cookies, sort_keys=True).encode()).hexdigest()
            try:
                envelope, authorized = await self.authorize(request)
                if identifier and identifier != authorized:
                    raise web.HTTPForbidden(text='This workspace does not belong to the current Plesk session.')
                workspace = await self.broker({'action': 'acquire', 'grant': envelope})
                if workspace['id'] != authorized:
                    raise web.HTTPForbidden(text='Workspace identity mismatch')
                if len(self.targets) >= 4096:
                    self.targets.pop(next(iter(self.targets)))
                self.targets[workspace['port']] = authorized
                if workspace.get('created'):
                    await self.revalidate(request, authorized)
                if len(self.bindings) >= 4096:
                    self.bindings.pop(next(iter(self.bindings)))
                self.bindings[binding] = authorized
                if 'database' in request.match_info:
                    connection = workspace['connections'].get('plesk-db-' + request.match_info['database'])
                    if not connection:
                        raise web.HTTPNotFound(text='Database is unavailable')
                    raise web.HTTPSeeOther(location='/tabularis/w/' + authorized + '/connections/' + connection + '/editor')
                path = '/' + request.match_info.get('tail', '')
                if path.startswith('/api/v1/provisioning'):
                    raise web.HTTPForbidden(text='This endpoint is restricted to the local broker')
                if request.query_string:
                    path += '?' + request.query_string
                target = f"http://127.0.0.1:{workspace['port']}" + path
                headers = upstream_headers(request, workspace, self.config['public_origin'])
                if request.headers.get('Upgrade', '').lower() == 'websocket':
                    return await self.websocket(request, target, headers, authorized)
                data = await request.read() if request.can_read_body else None
                return await self.http(request, target, headers, data, authorized)
            except web.HTTPException as error:
                if identifier and error.status in (401, 403) and self.bindings.get(binding) == identifier:
                    self.bindings.pop(binding, None)
                    self.revoke_later(identifier)
                raise
            except (OSError, ValueError, KeyError, ClientError, asyncio.TimeoutError):
                raise web.HTTPServiceUnavailable(text='Tabularis is temporarily unavailable.') from None

    async def http(self, request, target, headers, data, identifier):
        async def relay():
            async with self.client.request(request.method, target, headers=headers, data=data,
                                           allow_redirects=False) as upstream:
                response = web.StreamResponse(status=upstream.status)
                for key, value in upstream.headers.items():
                    if key.lower() not in HOP_HEADERS:
                        if key.lower() == 'set-cookie' and f'Path=/tabularis/w/{identifier}' not in value:
                            raise web.HTTPBadGateway(text='Unsafe runtime cookie scope')
                        response.headers.add(key, value)
                response.headers['Cache-Control'] = 'no-store'
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)
                await response.write_eof()
                return response

        async def watch():
            while True:
                await asyncio.sleep(2)
                await self.revalidate(request, identifier)

        operation, monitor = asyncio.create_task(relay()), asyncio.create_task(watch())
        try:
            finished, _ = await asyncio.wait((operation, monitor), return_when=asyncio.FIRST_COMPLETED)
            if monitor in finished:
                # Close an active query even if it has not returned its first byte.
                if request.transport is not None:
                    request.transport.close()
                await monitor
            return await operation
        finally:
            operation.cancel()
            monitor.cancel()
            await asyncio.gather(operation, monitor, return_exceptions=True)

    async def websocket(self, request, target, headers, identifier):
        async with self.client.ws_connect(target, headers=headers, max_msg_size=1024 * 1024) as upstream:
            downstream = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=20)
            await downstream.prepare(request)

            async def forward(source, destination):
                async for message in source:
                    if message.type == WSMsgType.TEXT:
                        await destination.send_str(message.data)
                    elif message.type == WSMsgType.BINARY:
                        await destination.send_bytes(message.data)
                    elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED):
                        break

            async def check_session():
                while True:
                    await asyncio.sleep(2)
                    await self.revalidate(request, identifier)

            tasks = [asyncio.create_task(forward(downstream, upstream)),
                     asyncio.create_task(forward(upstream, downstream)),
                     asyncio.create_task(check_session())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await downstream.close(code=1008, message=b'Plesk authorization ended')
            return downstream


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/tabularis-plesk/gateway.json')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('The HTTP gateway must not run as root')
    config = json.loads(Path(args.config).read_text())
    service = Gateway(config)
    application = web.Application(client_max_size=1024 * 1024)
    application.on_startup.append(service.start)
    application.on_cleanup.append(service.cleanup)
    application.router.add_get('/tabularis/open/{database:[0-9]+}', service.handle)
    application.router.add_route('*', '/tabularis/w/{workspace:[a-f0-9]{32}}/{tail:.*}', service.handle)
    path = Path(config['gateway_socket'])
    path.unlink(missing_ok=True)
    # systemd creates the private directory and sets the process umask.
    web.run_app(application, path=str(path), access_log=None, print=None)


if __name__ == '__main__':
    main()
