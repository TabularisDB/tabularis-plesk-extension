"""Server-to-server connection reconciliation; never edit Tabularis persistence."""
import json
import urllib.error
import urllib.request


class ProvisioningError(Exception):
    pass


class Provisioner:
    def __init__(self, port, token):
        self.base = f'http://127.0.0.1:{port}/api/v1/provisioning/connections'
        self.token = token

    def request(self, method, suffix='', body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + suffix, data=data, method=method,
                                         headers={'Authorization': 'Bearer ' + self.token,
                                                  'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read(2 * 1024 * 1024)
                return json.loads(payload) if payload else None
        except (OSError, ValueError, urllib.error.HTTPError) as error:
            # HTTP errors may contain database passwords in a downstream message.
            raise ProvisioningError('Connection provisioning failed') from None

    def reconcile(self, connections):
        existing = self.request('GET')
        if isinstance(existing, dict):
            existing = existing.get('connections', [])
        desired = {str(item['external_ref']): item for item in connections}
        # Never admit requests while a removed connection is still usable.
        for item in existing:
            if item['external_ref'] not in desired:
                self.request('DELETE', '/' + item['external_ref'])
        result = {}
        for reference, item in desired.items():
            response = self.request('PUT', '/' + reference,
                                    {'name': item['name'], 'params': item['params']})
            result[reference] = response['id']
        return result
