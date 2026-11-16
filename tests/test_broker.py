import os
import socket
import unittest

import common
from tabularis_plesk.broker import owns_loopback_listener


class BrokerListenerTests(unittest.TestCase):
    def test_listener_must_belong_to_expected_process_before_sending_credentials(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            listener.listen(1)
            self.assertTrue(owns_loopback_listener(os.getpid(), port))
            self.assertFalse(owns_loopback_listener(99999999, port))
        self.assertFalse(owns_loopback_listener(os.getpid(), port))
