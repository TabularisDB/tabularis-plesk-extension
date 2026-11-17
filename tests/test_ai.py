import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import common
from tabularis_plesk.ai import ManagedAI, trusted_file
from tabularis_plesk.broker import Supervisor
from tabularis_plesk.policy import Denied


class ManagedAITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.operator = self.root / 'operator.json'
        self.key = self.root / 'provider.key'
        self.key.write_text('test-provider-secret\n')
        self.key.chmod(0o600)
        self.package = self.root / 'provider.zip'
        self.package_with()
        self.config = {'provider': 'test-provider', 'model': 'operator-selected-model',
                       'provider_package': str(self.package), 'api_key_file': str(self.key),
                       'settings': {'base_url': 'https://provider.example.test/v1'},
                       'databases': [{'id': 1, 'schemas': ['public']},
                                     {'id': 2, 'schemas': ['shop_mysql', 'another_database']}]}
        self.catalogue = [{'id': 1, 'driver': 'postgres', 'name': 'shop_pg'},
                          {'id': 2, 'driver': 'mysql', 'name': 'shop_mysql'},
                          {'id': 3, 'driver': 'postgres', 'name': 'other_shop'}]
        self.write_config()
        # Emulate root ownership for the test-owned temporary tree while keeping
        # its actual file types/modes. The shared temporary ancestors are treated
        # as protected deployment ancestors; unsafe ancestors inside the fixture
        # retain their real mode and are rejected.
        actual_lstat = os.lstat

        def deployed_metadata(path, *args, **kwargs):
            info = actual_lstat(path, *args, **kwargs)
            mode = info.st_mode
            if Path(path) != self.root and self.root not in Path(path).parents:
                mode &= ~0o022
            fields = list(info)
            fields[0], fields[4] = mode, 0
            return os.stat_result(fields)

        self.metadata = patch('tabularis_plesk.ai.os.lstat', side_effect=deployed_metadata)
        self.metadata.start()
        self.addCleanup(self.metadata.stop)

    def package_with(self, *, kind='ai-assistant', identifier='test-provider', extra=None, authentication='api-key', optional_key=False):
        manifest = {'id': identifier, 'kind': kind,
                    'ai_assistant': {'api_version': 1, 'authentication': authentication, 'optional_api_key': optional_key}}
        with zipfile.ZipFile(self.package, 'w') as archive:
            archive.writestr('.tabularium', json.dumps(manifest))
            archive.writestr('LICENSE', 'Fixture license')
            if extra is not None:
                archive.writestr(*extra)
        self.package.chmod(0o600)

    def write_config(self):
        self.operator.write_text(json.dumps(self.config))
        self.operator.chmod(0o600)

    def load(self):
        return ManagedAI.load(str(self.operator))

    def home(self, name='home'):
        path = self.root / name
        path.mkdir(mode=0o700)
        return path

    def test_disabled_mode_does_not_read_any_operator_file(self):
        with patch('tabularis_plesk.ai.trusted_file', side_effect=AssertionError('Unexpected access')):
            self.assertIsNone(ManagedAI.load(None))

    def test_missing_malformed_duplicate_and_unknown_fields_fail_closed_without_echoing_values(self):
        missing = str(self.root / 'missing.json')
        with self.assertRaises(Denied):
            ManagedAI.load(missing)
        for content in ('{malformed', '{"provider":"first","provider":"second"}',
                        json.dumps({**self.config, 'unexpected': 'test-provider-secret'})):
            self.operator.write_text(content)
            with self.assertRaises(Denied) as error:
                self.load()
            self.assertNotIn('test-provider-secret', str(error.exception))

    def test_private_files_and_ancestors_reject_readable_keys_symlinks_and_writable_parents(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(Denied, 'accessible only to root'):
            self.load()
        self.key.chmod(0o600)
        link = self.root / 'key-link'
        link.symlink_to(self.key)
        with self.assertRaises(Denied):
            trusted_file(str(link), private=True)
        self.root.chmod(0o777)
        with self.assertRaisesRegex(Denied, 'not writable by others'):
            self.load()
        self.root.chmod(0o700)

    def test_non_root_owner_is_rejected(self):
        with patch('tabularis_plesk.ai.os.lstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=1001)):
            with self.assertRaises(Denied):
                trusted_file(str(self.operator), private=True)

    def test_package_requires_matching_declarative_provider_and_safe_archive_paths(self):
        for arguments in ({'kind': 'database-driver'}, {'identifier': 'other-provider'},
                          {'extra': ('../outside', 'not allowed')}):
            self.package_with(**arguments)
            with self.assertRaises(Denied):
                self.load()
        link = zipfile.ZipInfo('link')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.package_with(extra=(link, '/etc/passwd'))
        with self.assertRaises(Denied):
            self.load()

    def test_missing_required_key_and_invalid_schema_grants_fail_closed(self):
        self.config.pop('api_key_file')
        self.write_config()
        with self.assertRaisesRegex(Denied, 'requires a key'):
            self.load()
        self.config['api_key_file'] = str(self.key)
        for databases in ([], [{'id': True, 'schemas': ['public']}],
                          [{'id': 1, 'schemas': ['*']}], [{'id': 1, 'schemas': []}],
                          [{'id': 1, 'schemas': ['public', 'public']}],
                          [{'id': 1, 'schemas': ['public']}, {'id': 1, 'schemas': ['private']}]):
            self.config['databases'] = databases
            self.write_config()
            with self.assertRaises(Denied):
                self.load()

    def test_runtime_allowlist_intersects_current_catalogue_and_mysql_database(self):
        ai = self.load()
        self.assertEqual(ai.connections(self.catalogue), [
            {'id': 'provisioned-plesk-db-1', 'database': 'shop_pg', 'schemas': ['public']},
            {'id': 'provisioned-plesk-db-2', 'database': 'shop_mysql', 'schemas': ['shop_mysql']}])
        self.assertEqual(ai.connections(self.catalogue[1:]), [
            {'id': 'provisioned-plesk-db-2', 'database': 'shop_mysql', 'schemas': ['shop_mysql']}])

    def test_workspace_without_allowed_databases_receives_no_provider_or_key(self):
        home = self.home()
        self.assertEqual(self.load().install(home, self.catalogue[2:], os.getuid(), os.getgid()), {})
        self.assertEqual(list(home.iterdir()), [])

    def test_private_runtime_copies_use_exact_xdg_paths_and_no_provider_secret_in_environment(self):
        home = self.home()
        environment = self.load().install(home, self.catalogue, os.getuid(), os.getgid())
        self.assertEqual(set(environment), {'TABULARIS_WEB_AI_CONFIG_FILE'})
        self.assertNotIn('test-provider-secret', json.dumps(environment))
        scoped = json.loads(Path(environment['TABULARIS_WEB_AI_CONFIG_FILE']).read_text())
        self.assertEqual(scoped['provider'], 'test-provider')
        self.assertEqual(scoped['model'], 'operator-selected-model')
        self.assertEqual(Path(scoped['api_key_file']).read_text(), 'test-provider-secret')
        self.assertNotEqual(Path(scoped['api_key_file']), self.key)
        manifest = home / '.local/share/tabularis/plugins/ai-assistant/test-provider/.tabularium'
        self.assertEqual(json.loads(manifest.read_text())['kind'], 'ai-assistant')
        runtime = json.loads((home / '.config/tabularis/config.json').read_text())
        self.assertEqual(runtime, {'plugins': {'test-provider': {'settings': self.config['settings']}}})
        for path in home.rglob('*'):
            info = path.stat()
            self.assertEqual(info.st_uid, os.getuid())
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o700 if path.is_dir() else 0o600)

    def test_keyless_local_provider_installs_without_key_file(self):
        self.package_with(authentication='none')
        self.config.pop('api_key_file')
        self.write_config()
        home = self.home()
        environment = self.load().install(home, self.catalogue, os.getuid(), os.getgid())
        scoped = json.loads(Path(environment['TABULARIS_WEB_AI_CONFIG_FILE']).read_text())
        self.assertNotIn('api_key_file', scoped)
        self.assertFalse((home / 'ai/provider.key').exists())

    def test_compatible_provider_can_explicitly_declare_an_optional_key(self):
        self.package_with(optional_key=True)
        self.config.pop('api_key_file')
        self.write_config()
        self.assertIsNone(self.load().key)
        self.package_with(optional_key='true')
        with self.assertRaises(Denied):
            self.load()

    def test_existing_or_symlinked_runtime_targets_are_never_overwritten(self):
        home = self.home()
        target = self.root / 'outside'
        target.mkdir()
        (home / '.config').symlink_to(target, target_is_directory=True)
        with self.assertRaises(FileExistsError):
            self.load().install(home, self.catalogue, os.getuid(), os.getgid())
        self.assertEqual(list(target.iterdir()), [])

    def test_rotation_requires_a_new_broker_snapshot(self):
        before = self.load()
        self.key.write_text('rotated-provider-secret')
        self.config['model'] = 'rotated-model'
        self.write_config()
        after = self.load()
        for name, ai, expected in [('before', before, 'test-provider-secret'),
                                   ('after', after, 'rotated-provider-secret')]:
            home = self.home(name)
            environment = ai.install(home, self.catalogue, os.getuid(), os.getgid())
            scoped = json.loads(Path(environment['TABULARIS_WEB_AI_CONFIG_FILE']).read_text())
            self.assertEqual(Path(scoped['api_key_file']).read_text(), expected)
        self.assertEqual(before.model, 'operator-selected-model')
        self.assertEqual(after.model, 'rotated-model')

    def test_workspace_cleanup_removes_runtime_provider_and_key_but_preserves_operator_source(self):
        supervisor = object.__new__(Supervisor)
        supervisor.state = self.root / 'workspaces'
        supervisor.state.mkdir()
        identifier = 'a' * 32
        directory = supervisor.state / identifier
        directory.mkdir()
        home = directory / 'home'
        home.mkdir()
        self.load().install(home, self.catalogue, os.getuid(), os.getgid())
        workspace = {'id': identifier, 'account': 'tbw_test', 'uid': os.getuid(), 'credentials': []}
        with patch('tabularis_plesk.broker.pwd.getpwnam', side_effect=KeyError):
            supervisor.cleanup(workspace)
        self.assertFalse(directory.exists())
        self.assertTrue(self.key.exists())
        self.assertFalse((self.root / 'journals' / (identifier + '.json')).exists())

    def test_partial_ai_preparation_failure_is_journaled_and_cleaned_before_launch(self):
        supervisor = object.__new__(Supervisor)
        supervisor.state = self.root / 'workspaces'
        supervisor.state.mkdir()
        supervisor.config = {'binary': '/unused', 'web_root': '/unused', 'public_origin': 'https://panel.example.test'}
        class BrokenAI:
            def install(self, home, *_):
                (home / 'partial-key').write_text('test-provider-secret')
                raise RuntimeError('test-provider-secret')
        supervisor.ai = BrokenAI()
        account = SimpleNamespace(pw_uid=os.getuid() or 65534, pw_gid=os.getgid())
        with patch('tabularis_plesk.broker.pwd.getpwnam', return_value=account), \
                patch('tabularis_plesk.broker.subprocess.run') as release, \
                patch('tabularis_plesk.broker.subprocess.Popen') as launch:
            with self.assertRaises(Denied) as error:
                supervisor.start('b' * 32, {'session': 'session', 'identity': 'identity', 'databases': self.catalogue})
            self.assertNotIn('test-provider-secret', str(error.exception))
            launch.assert_not_called()
            release.assert_called_once_with(['/usr/sbin/userdel', 'tbw_' + 'b' * 20],
                                            check=True, capture_output=True)
        self.assertEqual(list(supervisor.state.iterdir()), [])
