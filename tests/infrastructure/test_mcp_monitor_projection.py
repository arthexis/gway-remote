"""Only a fresh, root-owned minimal monitor class is exposed to MCP."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gway_remote.mcp_monitor_projection import monitor_status


class MonitorProjectionTests(unittest.TestCase):
    def test_fresh_safe_projection_and_stale_failure(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'status.json'
            def write(**changes):
                value = {'schema': 1, 'observed_at': now.isoformat(), 'status': 'ok'}
                value.update(changes)
                path.write_text(json.dumps(value)); path.chmod(0o644)
            actual_fstat = os.fstat
            def root_owned(fd):
                info = actual_fstat(fd)
                return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_size=info.st_size)
            with patch('gway_remote.mcp_monitor_projection.os.fstat', side_effect=root_owned):
                write()
                self.assertEqual(monitor_status(path, now=now), {'status': 'ok'})
                write(status='failed')
                self.assertEqual(monitor_status(path, now=now), {'status': 'failed'})
                write(observed_at=(now - timedelta(seconds=181)).isoformat())
                self.assertEqual(monitor_status(path, now=now), {'status': 'unknown'})
                write(observed_at=(now + timedelta(seconds=1)).isoformat())
                self.assertEqual(monitor_status(path, now=now), {'status': 'unknown'})
                write(status='ok', private='must-not-be-returned')
                self.assertEqual(monitor_status(path, now=now), {'status': 'unknown'})
                write(schema=True)
                self.assertEqual(monitor_status(path, now=now), {'status': 'unknown'})
                write()
                path.chmod(0o666)
                self.assertEqual(monitor_status(path, now=now), {'status': 'unknown'})

    def test_missing_and_symlink_are_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'missing'
            self.assertEqual(monitor_status(path), {'status': 'unknown'})
            target = Path(temp) / 'target'; target.write_text('{}')
            path.symlink_to(target)
            self.assertEqual(monitor_status(path), {'status': 'unknown'})
