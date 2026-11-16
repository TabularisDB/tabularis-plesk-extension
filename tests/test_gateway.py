import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

import common
from aiohttp import ClientSession, WSMsgType, web
from aiohttp.test_utils import TestServer, make_mocked_request
from tabularis_plesk.gateway import Gateway, upstream_headers


class GatewayHeaderTests(unittest.TestCase):
    def test_panel_cookies_and_browser_identity_headers_never_reach_runtime(self):
        request = make_mocked_request('GET', '/', headers={
            'Cookie': 'PHPSESSID=panel-secret; tabularis_session=runtime-session',
            'X-Tabularis-User': 'administrator', 'X-Tabularis-Proxy-Secret': 'forged',
            'Authorization': 'Bearer attacker', 'Host': 'panel.example.test',
            'X-Real-IP': '192.0.2.1', 'X-Forwarded-For': '127.0.0.1'})
        headers = upstream_headers(request, {'identity': 'verified', 'proxy_secret': 'private'}, 'https://panel.example.test')
        self.assertEqual(headers['Cookie'], 'tabularis_session=runtime-session')
        self.assertEqual(headers['X-Tabularis-User'], 'verified')
        self.assertEqual(headers['X-Tabularis-Proxy-Secret'], 'private')
        self.assertEqual(headers['X-Forwarded-For'], '192.0.2.1')
        self.assertNotIn('Authorization', headers)


class GatewaySecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        key = Path(self.directory.name) / 'callback'
        key.write_text('local-secret')
        self.gateway = Gateway({'callback_key': str(key), 'public_origin': 'https://panel.example.test'})

    async def asyncTearDown(self):
        self.directory.cleanup()

    async def test_callback_set_cookie_cannot_override_another_panel_session(self):
        from test_policy import grant, signed
        observed = []

        async def callback(request):
            observed.append(request.headers.get('Cookie'))
            response = web.json_response(signed(grant()))
            response.set_cookie('PHPSESSID', 'server-cookie-from-first-user')
            return response

        app = web.Application()
        app.router.add_get('/authorize', callback)
        runner = web.AppRunner(app)
        await runner.setup()
        path = str(Path(self.directory.name) / 'auth.sock')
        await web.UnixSite(runner, path).start()
        self.gateway.config['auth_socket'] = path
        await self.gateway.start(None)
        try:
            for identity in ('first-user', 'second-user'):
                request = make_mocked_request('GET', '/', headers={
                    'Host': 'panel.example.test', 'Cookie': 'PHPSESSID=' + identity,
                    'X-Real-IP': '192.0.2.1'})
                await self.gateway.authorize(request)
            self.assertEqual(observed, ['PHPSESSID=first-user', 'PHPSESSID=second-user'])
            self.assertEqual(len(self.gateway.authorizer.cookie_jar), 0)
            self.assertEqual(len(self.gateway.client.cookie_jar), 0)
        finally:
            await self.gateway.cleanup(None)
            await runner.cleanup()

    async def test_untrusted_host_origin_and_cross_site_requests_fail_before_panel_auth(self):
        for method, headers in (
            ('GET', {'Host': 'attacker.example'}),
            ('POST', {'Host': 'panel.example.test'}),
            ('GET', {'Host': 'panel.example.test', 'Origin': 'https://attacker.example'}),
            ('GET', {'Host': 'panel.example.test', 'Sec-Fetch-Site': 'cross-site'}),
        ):
            with self.assertRaises(web.HTTPForbidden):
                await self.gateway.authorize(make_mocked_request(method, '/', headers=headers))

    async def test_guessed_workspace_does_not_reach_broker_or_revoke_other_users(self):
        self.gateway.authorize = AsyncMock(return_value=({'payload': 'verified'}, 'a' * 32))
        self.gateway.broker = AsyncMock()
        request = make_mocked_request('GET', '/', match_info={'workspace': 'b' * 32, 'tail': ''})
        with self.assertRaises(web.HTTPForbidden):
            await self.gateway.handle(request)
        self.gateway.broker.assert_not_awaited()

    async def test_revoked_stream_stops_its_previously_authorized_runtime(self):
        self.gateway.authorize = AsyncMock(side_effect=web.HTTPForbidden())
        self.gateway.broker = AsyncMock()
        with self.assertRaises(web.HTTPForbidden):
            await self.gateway.revalidate(make_mocked_request('GET', '/'), 'a' * 32)
        await asyncio.sleep(0)
        await asyncio.gather(*list(self.gateway.revocations.values()))
        self.gateway.broker.assert_awaited_once_with({'action': 'revoke', 'workspace': 'a' * 32})

    async def test_denial_is_immediate_even_when_privileged_revocation_is_blocked(self):
        blocked = asyncio.Event()
        self.gateway.authorize = AsyncMock(side_effect=web.HTTPForbidden())
        # A separate coroutine deliberately holds cleanup indefinitely.
        async def slow_broker(_):
            await blocked.wait()
        self.gateway.broker = slow_broker
        try:
            with self.assertRaises(web.HTTPForbidden):
                await asyncio.wait_for(self.gateway.revalidate(make_mocked_request('GET', '/'), 'a' * 32), timeout=0.1)
            self.assertIn('a' * 32, self.gateway.revocations)
        finally:
            blocked.set()
            await asyncio.gather(*list(self.gateway.revocations.values()))

    async def test_waiting_http_query_is_cut_off_after_permission_revocation(self):
        release = asyncio.Event()

        async def slow_query(request):
            await release.wait()
            return web.Response(text='result must not reach revoked user')

        async def denied(request, identifier):
            raise web.HTTPForbidden()

        upstream_app = web.Application()
        upstream_app.router.add_get('/query', slow_query)
        async with TestServer(upstream_app) as upstream_server:
            async with ClientSession() as client:
                self.gateway.client = client
                self.gateway.revalidate = denied
                app = web.Application()

                async def endpoint(request):
                    return await self.gateway.http(request, str(upstream_server.make_url('/query')), {}, 'a' * 32)

                app.router.add_get('/query', endpoint)
                async with TestServer(app) as server:
                    try:
                        from aiohttp import ServerDisconnectedError
                        with self.assertRaises(ServerDisconnectedError):
                            await asyncio.wait_for(client.get(server.make_url('/query')), timeout=6)
                    finally:
                        release.set()

    async def test_revoked_slow_upload_closes_before_reaching_runtime(self):
        authorized = True
        started = asyncio.Event()
        received = []

        async def validate(request):
            started.set()
            if not authorized:
                raise web.HTTPForbidden()
            return {}, 'a' * 32

        async def upstream(request):
            received.append(await request.read())
            return web.Response(text='query executed')

        upstream_app = web.Application()
        upstream_app.router.add_post('/query', upstream)
        async with TestServer(upstream_app) as upstream_server, ClientSession() as client:
            self.gateway.client = client
            self.gateway.authorize = validate

            async def broker(value):
                return {'id': 'a' * 32, 'port': upstream_server.port,
                        'identity': 'verified', 'proxy_secret': 'private',
                        'connections': {}, 'created': False}

            self.gateway.broker = broker
            app = web.Application()
            app.router.add_post('/tabularis/w/{workspace}/{tail:.*}', self.gateway.handle)
            async with TestServer(app) as server:
                reader, writer = await asyncio.open_connection(server.host, server.port)
                writer.write(('POST /tabularis/w/' + 'a' * 32 + '/query HTTP/1.1\r\n'
                              'Host: panel.example.test\r\nContent-Length: 2\r\n\r\n{').encode())
                await writer.drain()
                try:
                    await started.wait()
                    authorized = False
                    self.assertEqual(await asyncio.wait_for(reader.read(), timeout=5), b'')
                    self.assertEqual(received, [])
                    # Finishing the old upload after denial must not resurrect the relay.
                    writer.write(b'}')
                    try:
                        await writer.drain()
                    except ConnectionError:
                        pass
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except ConnectionError:
                        pass
                    await asyncio.gather(*list(self.gateway.revocations.values()))
                self.assertEqual(received, [])

    async def test_authorized_post_body_is_forwarded_unchanged(self):
        received = []

        async def upstream(request):
            received.append(await request.read())
            return web.Response(text='query completed')

        upstream_app = web.Application()
        upstream_app.router.add_post('/query', upstream)
        async with TestServer(upstream_app) as upstream_server, ClientSession() as client:
            self.gateway.client = client
            self.gateway.authorize = AsyncMock(return_value=({}, 'a' * 32))
            self.gateway.broker = AsyncMock(return_value={
                'id': 'a' * 32, 'port': upstream_server.port, 'identity': 'verified',
                'proxy_secret': 'private', 'connections': {}, 'created': False})
            app = web.Application()
            app.router.add_post('/tabularis/w/{workspace}/{tail:.*}', self.gateway.handle)
            async with TestServer(app) as server:
                async with client.post(server.make_url('/tabularis/w/' + 'a' * 32 + '/query'),
                                       data=b'{"query":"SELECT 1"}') as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(await response.text(), 'query completed')
            self.assertEqual(received, [b'{"query":"SELECT 1"}'])

    async def test_established_websocket_closes_after_permission_revocation(self):
        authorized = True

        blocked_cleanup = asyncio.Event()

        async def validate(request):
            if not authorized:
                raise web.HTTPForbidden()
            return {'payload': 'verified'}, 'a' * 32

        async def broker(value):
            if value['action'] == 'revoke':
                await blocked_cleanup.wait()
            return {'active': True}

        async def echo(request):
            websocket = web.WebSocketResponse()
            await websocket.prepare(request)
            async for message in websocket:
                if message.type == WSMsgType.TEXT:
                    await websocket.send_str(message.data)
            return websocket

        upstream_app = web.Application()
        upstream_app.router.add_get('/events', echo)
        async with TestServer(upstream_app) as upstream_server:
            async with ClientSession() as client:
                self.gateway.client = client
                self.gateway.authorize = validate
                self.gateway.broker = broker
                app = web.Application()
                async def endpoint(request):
                    return await self.gateway.websocket(request, str(upstream_server.make_url('/events')), {}, 'a' * 32)

                app.router.add_get('/events', endpoint)
                async with TestServer(app) as server:
                    async with client.ws_connect(server.make_url('/events')) as connection:
                        await connection.send_str('before-revocation')
                        self.assertEqual((await connection.receive()).data, 'before-revocation')
                        authorized = False
                        message = await asyncio.wait_for(connection.receive(), timeout=5)
                        self.assertEqual(message.type, WSMsgType.CLOSE)
                        self.assertEqual(message.data, 1008)
                        self.assertIn('a' * 32, self.gateway.revocations)
                        blocked_cleanup.set()
                        await asyncio.gather(*list(self.gateway.revocations.values()))
