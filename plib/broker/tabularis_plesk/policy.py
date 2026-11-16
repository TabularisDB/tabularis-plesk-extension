"""Validate short-lived Plesk assertions before any privileged operation."""
import base64
import hashlib
import hmac
import json
import re
import time


class Denied(Exception):
    """A deliberately non-sensitive authorization failure."""


def verify_grant(envelope, key, now=None):
    now = time.time() if now is None else now
    try:
        encoded = envelope['payload']
        if not isinstance(encoded, str) or len(encoded) > 131072:
            raise Denied('Invalid assertion')
        expected = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, envelope['signature']):
            raise Denied('Invalid assertion')
        grant = json.loads(base64.b64decode(encoded, validate=True))
        if not now - 15 <= grant['issued_at'] <= now + 2 or not now < grant['expires_at'] <= now + 15:
            raise Denied('Expired assertion')
        if not isinstance(grant['identity'], str) or not 1 <= len(grant['identity']) <= 256:
            raise Denied('Invalid identity')
        if not re.fullmatch(r'[a-f0-9]{64}', grant['session']):
            raise Denied('Invalid session')
        databases = grant['databases']
        if not isinstance(databases, list) or not 1 <= len(databases) <= 64:
            raise Denied('Unsupported catalogue size')
        identifiers = set()
        for database in databases:
            if type(database['id']) is not int or database['id'] <= 0 or database['id'] in identifiers:
                raise Denied('Invalid database identity')
            identifiers.add(database['id'])
            if database['driver'] not in ('mysql', 'postgres'):
                raise Denied('Unsupported database engine')
            for name in ('name', 'host', 'domain', 'owner'):
                if not isinstance(database[name], str) or not database[name] or len(database[name]) > 256:
                    raise Denied('Invalid database metadata')
            if type(database['port']) is not int or not 1 <= database['port'] <= 65535:
                raise Denied('Invalid database endpoint')
            if type(database['server_id']) is not int or type(database['domain_id']) is not int:
                raise Denied('Invalid database scope')
        return grant
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        raise Denied('Invalid assertion') from error


def workspace_key(grant):
    # Sessions get independent runtimes as well as identities and effective rights.
    # Impersonation and a catalogue change therefore invalidate old workspace URLs.
    scope = {'identity': grant['identity'], 'session': grant['session'],
             'databases': sorted(grant['databases'], key=lambda value: value['id'])}
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:32]


def same_database(expected, actual):
    return all(expected.get(key) == actual.get(key) for key in
               ('id', 'name', 'driver', 'server_id', 'domain_id', 'host', 'port', 'owner'))


def connection_params(database, username, password):
    """Allow plain MySQL only on literal loopback; remote targets verify TLS identity."""
    import ipaddress
    try:
        loopback = ipaddress.ip_address(database['host']).is_loopback
    except ValueError:
        loopback = False
    if database['driver'] == 'mysql':
        tls = 'disabled' if loopback else 'verify_identity'
    else:
        tls = 'prefer' if loopback else 'verify-full'
    return {'driver': database['driver'], 'host': database['host'], 'port': database['port'],
            'database': database['name'], 'username': username, 'password': password,
            'read_only': False, 'ssl_mode': tls}
