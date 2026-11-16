import base64
import copy
import hashlib
import hmac
import json
import unittest

import common
from tabularis_plesk.policy import Denied, verify_grant, workspace_key, same_database, connection_params


def grant():
    return {'identity': 'client:2:user:3:actor:', 'session': 'a' * 64,
            'issued_at': 1000, 'expires_at': 1010, 'databases': [
                {'id': 1, 'name': 'shop', 'driver': 'postgres', 'server_id': 1,
                 'domain_id': 3, 'domain': 'shop.example.test', 'owner': '2',
                 'host': '127.0.0.1', 'port': 5432}]}


def signed(value, key=b'private-key'):
    payload = base64.b64encode(json.dumps(value).encode()).decode()
    return {'payload': payload, 'signature': hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()}


class PolicyTests(unittest.TestCase):
    def test_only_fresh_authentic_panel_assertions_are_accepted(self):
        self.assertEqual(verify_grant(signed(grant()), b'private-key', now=1001), grant())
        for key, now in ((b'attacker', 1001), (b'private-key', 1010), (b'private-key', 997)):
            with self.assertRaises(Denied):
                verify_grant(signed(grant()), key, now=now)
        altered = signed(grant())
        altered['payload'] = base64.b64encode(b'{"identity":"admin"}').decode()
        with self.assertRaises(Denied):
            verify_grant(altered, b'private-key', now=1001)

    def test_workspace_changes_on_identity_session_permissions_or_ownership_change(self):
        original = grant()
        for field, value in (('identity', 'client:1'), ('session', 'b' * 64)):
            updated = copy.deepcopy(original)
            updated[field] = value
            self.assertNotEqual(workspace_key(original), workspace_key(updated))
        for field, value in (('owner', '8'), ('host', 'db.example.test'), ('name', 'other')):
            updated = copy.deepcopy(original)
            updated['databases'][0][field] = value
            self.assertNotEqual(workspace_key(original), workspace_key(updated))
            self.assertFalse(same_database(original['databases'][0], updated['databases'][0]))

    def test_empty_duplicate_and_unsupported_catalogues_fail_closed(self):
        for databases in ([], [grant()['databases'][0]] * 2,
                          [{**grant()['databases'][0], 'driver': 'sqlite'}],
                          [{**grant()['databases'][0], 'id': True}]):
            value = grant()
            value['databases'] = databases
            with self.assertRaises(Denied):
                verify_grant(signed(value), b'private-key', now=1001)


class DatabaseTransportPolicyTests(unittest.TestCase):
    def test_only_literal_loopback_mysql_can_disable_tls(self):
        database = {**grant()['databases'][0], 'driver': 'mysql'}
        for host in ('127.0.0.1', '::1'):
            self.assertEqual(connection_params({**database, 'host': host}, 'user', 'secret')['ssl_mode'], 'disabled')
        for host in ('192.0.2.1', 'db.example.test', 'localhost.example.test'):
            self.assertEqual(connection_params({**database, 'host': host}, 'user', 'secret')['ssl_mode'], 'verify_identity')
        self.assertEqual(connection_params(grant()['databases'][0], 'user', 'secret')['ssl_mode'], 'prefer')
