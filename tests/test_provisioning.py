import unittest
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import common
from tabularis_plesk.provisioning import Provisioner, ProvisioningError


class RecordingProvisioner(Provisioner):
    def __init__(self, fail_delete=False):
        self.events = []
        self.fail_delete = fail_delete

    def request(self, method, suffix='', body=None):
        self.events.append((method, suffix))
        if method == 'GET':
            return [{'id': 'old', 'external_ref': 'plesk-db-9'}]
        if method == 'DELETE' and self.fail_delete:
            raise ProvisioningError('unavailable')
        if method == 'PUT':
            return {'id': 'stable-id', 'external_ref': suffix[1:]}


class ReconciliationTests(unittest.TestCase):
    def test_removal_completes_before_any_new_connection_is_exposed(self):
        service = RecordingProvisioner()
        result = service.reconcile([{'external_ref': 'plesk-db-1', 'name': 'shop', 'params': {'driver': 'mysql'}}])
        self.assertEqual(result, {'plesk-db-1': 'stable-id'})
        self.assertEqual(service.events, [('GET', ''), ('DELETE', '/plesk-db-9'), ('PUT', '/plesk-db-1')])

    def test_failed_revocation_aborts_reconciliation(self):
        service = RecordingProvisioner(fail_delete=True)
        with self.assertRaises(ProvisioningError):
            service.reconcile([{'external_ref': 'plesk-db-1', 'name': 'shop', 'params': {}}])
        self.assertEqual(service.events, [('GET', ''), ('DELETE', '/plesk-db-9')])


class ProvisioningTransportTests(unittest.TestCase):
    def test_public_host_and_machine_auth_without_browser_origin(self):
        observed = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                observed.update(dict(self.headers))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'[]')

            def log_message(self, *_):
                pass

        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            service = Provisioner(server.server_port, 'private-machine-token', 'https://panel.example.test:8443')
            self.assertEqual(service.request('GET'), [])
            thread.join(timeout=3)
        self.assertEqual(observed['Host'], 'panel.example.test:8443')
        self.assertEqual(observed['Authorization'], 'Bearer private-machine-token')
        self.assertNotIn('Origin', observed)
        self.assertNotIn('Cookie', observed)

    def test_machine_token_is_never_forwarded_through_a_redirect(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', 'http://127.0.0.1:1/stolen')
                self.end_headers()

            def log_message(self, *_):
                pass

        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            service = Provisioner(server.server_port, 'private-machine-token', 'https://panel.example.test')
            with self.assertRaises(ProvisioningError):
                service.request('GET')
            thread.join(timeout=3)
