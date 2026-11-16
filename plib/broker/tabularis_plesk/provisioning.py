"""Server-to-server connection reconciliation; never edit Tabularis persistence."""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class ProvisioningError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class Provisioner:
    def __init__(self, port, token, public_origin):
        self.base = f'http://127.0.0.1:{port}/api/v1/provisioning/connections'
        self.token = token
        self.host = urlsplit(public_origin).netloc
        self.client = urllib.request.build_opener(NoRedirect())

    def request(self, method, suffix='', body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + suffix, data=data, method=method,
                                         headers={'Host': self.host, 'Authorization': 'Bearer ' + self.token,
                                                  'Content-Type': 'application/json'})
        try:
            with self.client.open(request, timeout=20) as response:
                payload = response.read(2 * 1024 * 1024)
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as error:
            error.close()
            raise ProvisioningError('Connection provisioning failed') from None
        except (OSError, ValueError):
            # Error responses may contain private downstream details.
            raise ProvisioningError('Connection provisioning failed') from None

    def reconcile(self, connections):
        existing = self.request('GET')
        if not isinstance(existing, list) or any(
            not isinstance(item, dict) or not isinstance(item.get('external_ref'), str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', item['external_ref']) for item in existing
        ):
            raise ProvisioningError('Invalid provisioning catalogue')
        desired = {str(item['external_ref']): item for item in connections}
        # Never admit requests while a removed connection is still usable.
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
