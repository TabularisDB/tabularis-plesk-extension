"""Server-to-server connection reconciliation; never edit Tabularis persistence."""
import http.client
import json
import re
from urllib.parse import urlsplit

from .transport import owns_connected_peer


class ProvisioningError(Exception):
    pass


class RuntimeConnection(http.client.HTTPConnection):
    def __init__(self, port, process, expected_uid):
        super().__init__('127.0.0.1', port, timeout=20)
        self.process = process
        self.expected_uid = expected_uid

    def connect(self):
        super().connect()
        if not owns_connected_peer(self.process, self.expected_uid, self.sock.getsockname(), self.sock.getpeername()):
            self.close()
            raise ProvisioningError('The private runtime connection could not be verified')


class Provisioner:
    def __init__(self, port, token, public_origin, process, expected_uid):
        self.port = port
        self.token = token
        self.host = urlsplit(public_origin).netloc
        self.process = process
        self.expected_uid = expected_uid

    def request(self, method, suffix='', body=None):
        data = None if body is None else json.dumps(body).encode()
        connection = RuntimeConnection(self.port, self.process, self.expected_uid)
        try:
            # connect() attests the accepted TCP endpoint before request() writes
            # headers or credentials. HTTPConnection never follows redirects.
            connection.request(method, '/api/v1/provisioning/connections' + suffix, body=data,
                               headers={'Host': self.host, 'Authorization': 'Bearer ' + self.token,
                                        'Content-Type': 'application/json'})
            response = connection.getresponse()
            payload = response.read(2 * 1024 * 1024 + 1)
            if not 200 <= response.status < 300 or len(payload) > 2 * 1024 * 1024:
                raise ProvisioningError('Connection provisioning failed')
            return json.loads(payload) if payload else None
        except (OSError, ValueError, http.client.HTTPException):
            raise ProvisioningError('Connection provisioning failed') from None
        finally:
            connection.close()

    def reconcile(self, connections):
        existing = self.request('GET')
        if not isinstance(existing, list) or any(
            not isinstance(item, dict) or not isinstance(item.get('external_ref'), str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', item['external_ref']) for item in existing
        ):
            raise ProvisioningError('Invalid provisioning catalogue')
        desired = {str(item['external_ref']): item for item in connections}
        for item in existing:
            if item['external_ref'] not in desired:
                self.request('DELETE', '/' + item['external_ref'])
        result = {}
        for reference, item in desired.items():
            response = self.request('PUT', '/' + reference,
                                    {'name': item['name'], 'params': item['params']})
            if not isinstance(response, dict) or not isinstance(response.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]+', response['id']):
                raise ProvisioningError('Invalid provisioned identity')
            result[reference] = response['id']
        return result
