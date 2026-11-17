"""Operator-managed SQL assistance; provider secrets never enter panel grants."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from .policy import Denied


def trusted_file(value, private=False):
    """Reject symlinks and files beneath a writable or non-root-owned ancestor."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise Denied('Invalid AI file path')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise Denied('AI file paths must be absolute')
    try:
        for index, item in enumerate((path, *path.parents)):
            info = os.lstat(item)
            expected_kind = stat.S_ISREG if index == 0 else stat.S_ISDIR
            if not expected_kind(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise Denied('AI files and parents must be root-owned and not writable by others')
            if index == 0 and private and info.st_mode & 0o077:
                raise Denied('AI configuration and keys must be accessible only to root')
    except OSError:
        raise Denied('AI file is unavailable') from None
    return path


def read_bounded(path, maximum):
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise Denied('AI file exceeds its size limit')
    return data


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate object key')
        result[key] = value
    return result


def strict_json(data):
    def invalid_constant(_):
        raise ValueError('Non-finite number')
    return json.loads(data, object_pairs_hook=unique_keys, parse_constant=invalid_constant)


def text_value(value, maximum=256):
    return (isinstance(value, str) and 0 < len(value) <= maximum
            and value == value.strip() and all(ord(character) >= 32 and ord(character) != 127 for character in value))


def provider_files(path, provider):
    """Read a bounded declarative package without extracting paths from a ZIP."""
    if path.stat().st_size > 4 * 1024 * 1024:
        raise Denied('AI provider package exceeds its size limit')
    files = {}
    total = 0
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not 1 <= len(members) <= 64:
            raise Denied('Invalid AI provider package')
        for member in members:
            name = PurePosixPath(member.filename)
            kind = stat.S_IFMT(member.external_attr >> 16)
            if (name.is_absolute() or '..' in name.parts or '\\' in member.filename
                    or str(name) != member.filename or member.is_dir()
                    or kind not in (0, stat.S_IFREG) or member.filename in files):
                raise Denied('Unsafe AI provider package member')
            total += member.file_size
            if member.file_size > 1024 * 1024 or total > 2 * 1024 * 1024:
                raise Denied('AI provider package exceeds its size limit')
            files[member.filename] = archive.read(member)
    manifest = strict_json(files.get('.tabularium', b''))
    if (not isinstance(manifest, dict) or manifest.get('id') != provider
            or manifest.get('kind') != 'ai-assistant' or not isinstance(manifest.get('ai_assistant'), dict)):
        raise Denied('AI provider package does not match the selected declarative provider')
    # AI providers are declarative. Install only their manifest and license;
    # arbitrary archives cannot place executables, frontend assets or settings.
    selected = {'.tabularium': files['.tabularium']}
    if 'LICENSE' in files:
        selected['LICENSE'] = files['LICENSE']
    specification = manifest['ai_assistant']
    optional_key = specification.get('optional_api_key', False)
    if type(optional_key) is not bool:
        raise Denied('Invalid optional AI key declaration')
    return selected, specification.get('authentication') == 'api-key' and not optional_key


def private_directory(path, uid, gid):
    path.mkdir(mode=0o700)
    os.chown(path, uid, gid)
    os.chmod(path, 0o700)


def private_file(path, data, uid, gid):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        os.fchown(stream.fileno(), uid, gid)
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)


class ManagedAI:
    """A startup snapshot. Restart the broker to rotate or revoke its AI policy."""

    def __init__(self, provider, model, files, settings, key, databases):
        self.provider, self.model, self.files = provider, model, files
        self.settings, self.key, self.databases = settings, key, databases

    @classmethod
    def load(cls, filename):
        if filename is None:
            return None
        try:
            config = strict_json(read_bounded(trusted_file(filename, private=True), 65536))
            required = {'provider', 'model', 'provider_package', 'databases'}
            if (not isinstance(config, dict) or not required <= config.keys()
                    or config.keys() - required - {'settings', 'api_key_file'}):
                raise Denied('Invalid AI operator configuration fields')
            provider, model = config['provider'], config['model']
            if not isinstance(provider, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', provider) or not text_value(model):
                raise Denied('Invalid AI provider or model')
            settings = config.get('settings', {})
            if not isinstance(settings, dict):
                raise Denied('AI provider settings must be an object')
            # Validate nested JSON and preserve an independent snapshot.
            settings = json.loads(json.dumps(settings, allow_nan=False))
            databases = config['databases']
            if not isinstance(databases, list) or not 1 <= len(databases) <= 64:
                raise Denied('Invalid AI database allowlist')
            grants = {}
            for database in databases:
                if not isinstance(database, dict) or set(database) != {'id', 'schemas'}:
                    raise Denied('Invalid AI database grant')
                identifier, schemas = database['id'], database['schemas']
                if type(identifier) is not int or identifier <= 0 or identifier in grants:
                    raise Denied('Invalid AI database identity')
                if (not isinstance(schemas, list) or not 1 <= len(schemas) <= 64
                        or any(not text_value(schema) for schema in schemas)
                        or len(set(schemas)) != len(schemas) or '*' in schemas):
                    raise Denied('AI schemas must be explicit, unique names')
                grants[identifier] = tuple(schemas)
            files, requires_key = provider_files(trusted_file(config['provider_package']), provider)
            key = None
            if 'api_key_file' in config:
                key = read_bounded(trusted_file(config['api_key_file'], private=True), 16384).strip()
                if not key or any(character <= 32 or character == 127 for character in key):
                    raise Denied('Invalid AI provider key file')
                key.decode('utf-8')
            if requires_key and key is None:
                raise Denied('Selected AI provider requires a key file')
            return cls(provider, model, files, settings, key, grants)
        except Denied:
            raise
        except (OSError, ValueError, TypeError, KeyError, RecursionError, zipfile.BadZipFile, RuntimeError):
            raise Denied('Invalid AI operator configuration or provider package') from None

    def connections(self, catalogue):
        result = []
        for database in catalogue:
            schemas = self.databases.get(database['id'])
            if schemas is None:
                continue
            # A MySQL schema is the selected database. Never authorize another
            # database through an operator typo in its schema list.
            if database['driver'] == 'mysql':
                schemas = tuple(schema for schema in schemas if schema == database['name'])
            if schemas:
                result.append({'id': f"provisioned-plesk-db-{database['id']}",
                               'database': database['name'], 'schemas': list(schemas)})
        return result

    def install(self, home, catalogue, uid, gid):
        connections = self.connections(catalogue)
        if not connections:
            return {}
        # The fresh home belongs exclusively to this workspace; refuse existing
        # targets, including symlinks, instead of following or overwriting them.
        directories = ('.config', '.config/tabularis', '.local', '.local/share',
                       '.local/share/tabularis', '.local/share/tabularis/plugins',
                       '.local/share/tabularis/plugins/ai-assistant',
                       f'.local/share/tabularis/plugins/ai-assistant/{self.provider}', 'ai')
        for directory in directories:
            private_directory(home / directory, uid, gid)
        destination = home / '.local/share/tabularis/plugins/ai-assistant' / self.provider
        for name, data in self.files.items():
            private_file(destination / name, data, uid, gid)
        runtime = {'plugins': {self.provider: {'settings': self.settings}}}
        private_file(home / '.config/tabularis/config.json', json.dumps(runtime).encode(), uid, gid)
        scoped = {'provider': self.provider, 'model': self.model, 'connections': connections}
        if self.key is not None:
            key_file = home / 'ai/provider.key'
            private_file(key_file, self.key, uid, gid)
            scoped['api_key_file'] = str(key_file)
        config_file = home / 'ai/scoped.json'
        private_file(config_file, json.dumps(scoped).encode(), uid, gid)
        return {'TABULARIS_WEB_AI_CONFIG_FILE': str(config_file)}
