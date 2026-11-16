import os
import socket
import subprocess
import sys
import threading
import unittest

import common
from tabularis_plesk.provisioning import Provisioner, ProvisioningError


@unittest.skipUnless(os.geteuid() == 0, 'Cross-UID proof runs as root in the real Plesk lab')
class CrossUidTransportTests(unittest.TestCase):
    def test_live_child_cannot_authorize_another_uid_replacing_its_listener(self):
        child = subprocess.Popen([sys.executable, '-c',
            "import os,socket,sys,time; os.setgroups([]); os.setgid(65534); os.setuid(65534); "
            "s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); "
            "s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1],flush=True); "
            "sys.stdin.readline(); s.close(); print('closed',flush=True); time.sleep(30)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            port = int(child.stdout.readline())
            from tabularis_plesk.broker import owns_loopback_listener
            self.assertTrue(owns_loopback_listener(child.pid, port))
            child.stdin.write('close\n')
            child.stdin.flush()
            self.assertEqual(child.stdout.readline().strip(), 'closed')
            self.assertIsNone(child.poll())
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
                client = Provisioner(port, 'must-not-leak-token', 'https://panel.example.test', child, 65534)
                with self.assertRaises(ProvisioningError):
                    client.request('PUT', '/plesk-db-1', {'params': {'password': 'must-not-leak-password'}})
                thread.join(timeout=3)
            self.assertEqual(received, [b''])
        finally:
            child.terminate()
            child.wait(timeout=3)
            child.stdin.close()
            child.stdout.close()
