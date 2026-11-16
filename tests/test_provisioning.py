import unittest

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
