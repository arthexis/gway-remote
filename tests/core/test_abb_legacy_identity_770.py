"""No generic legacy identity bypass: explicit empty-state ABB cutover only."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from gway_remote.abb_relay_provision import resolve_abb_user


class AbbLegacyIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        self.args = dict(hostname='ocpp-abb-1', policy=root/'config'/'identity.json',
                         legacy_state=self.state, legacy_relay=root/'relay', legacy_sudoers=root/'sudoers')
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        for name, kwargs in [('os.geteuid', dict(return_value=0)),
                             ('resolve_executor_user', dict(side_effect=PermissionError('legacy'))),
                             ('validated_account', dict(return_value=account))]:
            p = patch('gway_remote.abb_relay_provision.' + name, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def test_explicit_empty_legacy_cutover_preserves_directory(self):
        self.assertEqual(resolve_abb_user(allow_empty_legacy=True, **self.args), 'ubuntu')
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertFalse(self.args['policy'].exists())

    def test_refuses_without_opt_in_or_wrong_host(self):
        with self.assertRaises(PermissionError):
            resolve_abb_user(**self.args)
        with self.assertRaises(PermissionError):
            resolve_abb_user(allow_empty_legacy=True, **{**self.args, 'hostname':'gway-001'})

    def test_refuses_any_legacy_file_or_relay(self):
        for path in (self.state/'jobs.sqlite3', self.args['legacy_relay'], self.args['legacy_sudoers']):
            path.touch()
            with self.subTest(path=path), self.assertRaises(PermissionError):
                resolve_abb_user(allow_empty_legacy=True, **self.args)
            path.unlink()

    def test_refuses_unsafe_mode_and_symlink(self):
        self.state.chmod(0o755)
        with self.assertRaises(PermissionError):
            resolve_abb_user(allow_empty_legacy=True, **self.args)
        self.state.rmdir()
        self.state.symlink_to(self.state.parent)
        with self.assertRaises(PermissionError):
            resolve_abb_user(allow_empty_legacy=True, **self.args)
