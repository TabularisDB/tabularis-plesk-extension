import unittest
import threading
import os
import socket
import subprocess
import sys
from types import SimpleNamespace
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
            service = Provisioner(server.server_port, 'private-machine-token', 'https://panel.example.test:8443', SimpleNamespace(pid=os.getpid(), poll=lambda: None), os.getuid())
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
            service = Provisioner(server.server_port, 'private-machine-token', 'https://panel.example.test', SimpleNamespace(pid=os.getpid(), poll=lambda: None), os.getuid())
            with self.assertRaises(ProvisioningError):
                service.request('GET')
            thread.join(timeout=3)

    def test_replaced_runtime_port_receives_no_token_or_database_password(self):
        child = subprocess.Popen([sys.executable, '-c',
            "import socket,time; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); "
            "s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1],flush=True); time.sleep(30)"],
            stdout=subprocess.PIPE, text=True)
        port = int(child.stdout.readline())
        from tabularis_plesk.broker import owns_loopback_listener
        self.assertTrue(owns_loopback_listener(child.pid, port))
        child.terminate()
        child.wait(timeout=3)
        child.stdout.close()
        received = []
        with socket.socket() as replacement:
            replacement.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            replacement.bind(('127.0.0.1', port))
            replacement.listen()
            replacement.settimeout(3)

            def capture():
                connection, _ = replacement.accept()
                with connection:
                    received.append(connection.recv(65536))

            thread = threading.Thread(target=capture)
            thread.start()
            service = Provisioner(port, 'must-not-leak-token', 'https://panel.example.test', child, os.getuid())
            with self.assertRaises(ProvisioningError):
                service.request('PUT', '/plesk-db-1', {'params': {'password': 'must-not-leak-password'}})
            thread.join(timeout=3)
        self.assertEqual(received, [b''])
