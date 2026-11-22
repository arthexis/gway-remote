"""MCP alerting observes distinct systemd results without MCP or credentials."""
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mcp_health_alert', ROOT / 'scripts/mcp-health-alert.py')
alert = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alert)
spec_probe = importlib.util.spec_from_file_location('mcp_external_health_alert', ROOT / 'scripts/mcp-external-health.py')
probe = importlib.util.module_from_spec(spec_probe)
spec_probe.loader.exec_module(probe)
spec_local = importlib.util.spec_from_file_location('mcp_local_health_alert', ROOT / 'scripts/mcp-health-monitor.py')
local = importlib.util.module_from_spec(spec_local)
spec_local.loader.exec_module(local)


class AlertTests(unittest.TestCase):
    def test_initial_healthy_samples_are_silent(self):
        state = alert.initial_state()
        for ident in ('a', 'b'):
            state, event = alert.advance(state, {'status': 'healthy', 'id': ident}, 1000)
            self.assertIsNone(event)
        self.assertFalse(state['alerted'])

    def test_debounce_repeats_and_recovery_use_distinct_samples(self):
        state = alert.initial_state()
        state, event = alert.advance(state, {'status': 'failed', 'id': 'a'}, 1000)
        self.assertIsNone(event)
        state, event = alert.advance(state, {'status': 'failed', 'id': 'a'}, 1030)
        self.assertIsNone(event)  # the same systemd failure cannot count twice
        state, event = alert.advance(state, {'status': 'failed', 'id': 'b'}, 1120)
        self.assertEqual(event, 'failed')
        state, event = alert.advance(state, {'status': 'failed', 'id': 'b'}, 2019)
        self.assertIsNone(event)
        state, event = alert.advance(state, {'status': 'failed', 'id': 'b'}, 2020)
        self.assertEqual(event, 'failed')
        state, event = alert.advance(state, {'status': 'healthy', 'id': 'c'}, 2030)
        self.assertIsNone(event)
        state, event = alert.advance(state, {'status': 'healthy', 'id': 'c'}, 2060)
        self.assertIsNone(event)
        state, event = alert.advance(state, {'status': 'healthy', 'id': 'd'}, 2150)
        self.assertEqual(event, 'recovered')
        state, event = alert.advance(state, {'status': 'healthy', 'id': 'd'}, 2200)
        self.assertIsNone(event)

    def test_intervening_success_resets_failure_streak(self):
        state = alert.initial_state()
        for sample in ({'status': 'failed', 'id': 'a'}, {'status': 'healthy', 'id': 'b'},
                       {'status': 'failed', 'id': 'c'}):
            state, event = alert.advance(state, sample, 1000)
            self.assertIsNone(event)
        self.assertEqual(state['failures'], 1)

    def test_timer_disabled_and_stale_checks_are_failures_not_recovery(self):
        def runner(service, timer):
            def run(argv, **kwargs):
                data = timer if alert.TIMER in argv else service
                return SimpleNamespace(stdout='\n'.join(f'{key}={value}' for key, value in data.items()))
            return run
        timer = {'LoadState': 'loaded', 'ActiveState': 'active', 'ActiveEnterTimestampMonotonic': '1000000'}
        service = {'LoadState': 'loaded', 'ActiveState': 'inactive', 'Result': 'success',
                   'ExecMainStatus': '0', 'ExecMainStartTimestampMonotonic': '1000000',
                   'ExecMainExitTimestampMonotonic': '2000000', 'InvocationID': 'a' * 32}
        self.assertEqual(alert.observe(now_monotonic=10, runner=runner(service, timer))['status'], 'healthy')
        self.assertEqual(alert.observe(now_monotonic=500, runner=runner(service, timer))['status'], 'failed')
        timer['ActiveState'] = 'inactive'
        self.assertEqual(alert.observe(now_monotonic=10, runner=runner(service, timer))['status'], 'failed')

    def test_outputs_are_bounded_owned_and_sound_only_on_transitions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state, lcd = root / 'state', root / 'lcd'
            state.mkdir(mode=0o700); lcd.mkdir(mode=0o700)
            sound = root / 'sound'
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                return SimpleNamespace(returncode=0)
            for sample, now in (({'status': 'failed', 'id': 'a'}, 1000),
                                ({'status': 'failed', 'id': 'b'}, 1120),
                                ({'status': 'failed', 'id': 'b'}, 1150),
                                ({'status': 'healthy', 'id': 'c'}, 1240),
                                ({'status': 'healthy', 'id': 'd'}, 1360)):
                self.assertEqual(alert.run_once(state_dir=state, lcd_dir=lcd, sound=sound,
                                                sample=sample, now=now, runner=runner), 0)
            self.assertEqual([call[1] for call in calls], ['warning', 'ok'])
            text = (lcd / alert.LCD_FILE).read_text()
            self.assertIn('MCP CHECK OK\nRECOVERED\n', text)
            self.assertNotIn('token', text.lower())
            self.assertFalse(json.loads((state / alert.STATE_FILE).read_text())['alerted'])

    def test_unsafe_lcd_symlink_does_not_overwrite_other_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / 'state'; lcd = root / 'lcd'
            state.mkdir(mode=0o700); lcd.mkdir(mode=0o700)
            target = root / 'other'; target.write_text('untouched')
            (lcd / alert.LCD_FILE).symlink_to(target)
            alert.run_once(state_dir=state, lcd_dir=lcd, sample={'status': 'failed', 'id': 'a'}, now=1000)
            with self.assertRaises(ValueError):
                alert.run_once(state_dir=state, lcd_dir=lcd, sample={'status': 'failed', 'id': 'b'}, now=1120)
            self.assertEqual(target.read_text(), 'untouched')

    def test_running_probe_is_pending_not_false_recovery(self):
        timer = {'LoadState': 'loaded', 'ActiveState': 'active', 'ActiveEnterTimestampMonotonic': '1000000'}
        service = {'LoadState': 'loaded', 'ActiveState': 'activating', 'Result': 'success',
                   'ExecMainStatus': '0', 'ExecMainStartTimestampMonotonic': '9000000',
                   'ExecMainExitTimestampMonotonic': '2000000', 'InvocationID': 'b' * 32}
        def runner(argv, **kwargs):
            data = timer if alert.TIMER in argv else service
            return SimpleNamespace(stdout='\n'.join(f'{key}={value}' for key, value in data.items()))
        self.assertEqual(alert.observe(now_monotonic=10, runner=runner)['status'], 'pending')
        self.assertEqual(alert.observe(now_monotonic=500, runner=runner)['status'], 'failed')

    def test_test_notification_never_overwrites_an_active_real_alert(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / 'state'; lcd = root / 'lcd'
            state.mkdir(mode=0o700); lcd.mkdir(mode=0o700)
            current = alert.initial_state(); current['alerted'] = True
            (state / alert.STATE_FILE).write_text(json.dumps(current))
            (state / alert.STATE_FILE).chmod(0o600)
            sound = Mock(return_value=SimpleNamespace(returncode=0))
            with self.assertRaises(ValueError):
                alert.test_notice('failure', state_dir=state, lcd_dir=lcd, runner=sound)
            self.assertFalse((lcd / alert.LCD_FILE).exists())
            sound.assert_not_called()

    def test_test_notification_is_labelled_and_does_not_change_health_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / 'state'; lcd = root / 'lcd'
            state.mkdir(mode=0o700); lcd.mkdir(mode=0o700)
            sound = Mock(return_value=SimpleNamespace(returncode=0))
            self.assertEqual(alert.test_notice('failure', state_dir=state, lcd_dir=lcd, runner=sound), 0)
            self.assertIn('MCP TEST FAIL\n', (lcd / alert.LCD_FILE).read_text())
            self.assertFalse((state / alert.STATE_FILE).exists())
            self.assertEqual(sound.call_args.args[0][1], 'warning')

    def test_watchtower_failure_reaches_local_alert_then_recovery(self):
        class Response(io.BytesIO):
            status = 200
        def external(status):
            body = {'jsonrpc': '2.0', 'id': 1, 'result': {'content': [
                {'type': 'text', 'text': json.dumps({'schema': 1, 'nodes': [],
                                                     'watchtower_monitor': {'status': status}})}]}}
            return probe.probe('private-token', opener=lambda *a, **kw:
                               Response(json.dumps(body).encode()))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / 'state'; lcd = root / 'lcd'
            state.mkdir(mode=0o700); lcd.mkdir(mode=0o700)
            sound = Mock(return_value=SimpleNamespace(returncode=0))
            failed = {'schema': 1, 'observed_at': '2026-11-22T00:00:00+00:00', 'status': 'failed'}
            projected = local.public_projection(failed, None, 1000)
            self.assertEqual(external(projected['status']), 'watchtower_monitor_failed')
            for ident, now in (('a', 1120), ('b', 1240)):
                alert.run_once(state_dir=state, lcd_dir=lcd, sample={'status': 'failed', 'id': ident},
                               now=now, runner=sound)
            self.assertIn('MCP CHECK FAIL', (lcd / alert.LCD_FILE).read_text())
            healthy = {'schema': 1, 'observed_at': '2026-11-22T00:06:00+00:00', 'status': 'ok'}
            projected = local.public_projection(healthy, failed, 1301)
            self.assertEqual(external(projected['status']), 'ok')
            for ident, now in (('c', 1360), ('d', 1480)):
                alert.run_once(state_dir=state, lcd_dir=lcd, sample={'status': 'healthy', 'id': ident},
                               now=now, runner=sound)
            self.assertIn('MCP CHECK OK', (lcd / alert.LCD_FILE).read_text())
            self.assertEqual([call.args[0][1] for call in sound.call_args_list], ['warning', 'ok'])

    def test_failed_sound_attempt_does_not_repeat_every_timer_tick(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / 'state'; lcd = root / 'lcd'
            state.mkdir(mode=0o700); lcd.mkdir(mode=0o700)
            sound = Mock(return_value=SimpleNamespace(returncode=1))
            self.assertEqual(alert.run_once(state_dir=state, lcd_dir=lcd,
                sample={'status': 'failed', 'id': 'a'}, now=1000, runner=sound), 0)
            self.assertEqual(alert.run_once(state_dir=state, lcd_dir=lcd,
                sample={'status': 'failed', 'id': 'b'}, now=1120, runner=sound), 1)
            self.assertEqual(alert.run_once(state_dir=state, lcd_dir=lcd,
                sample={'status': 'failed', 'id': 'b'}, now=1150, runner=sound), 0)
            self.assertEqual(sound.call_count, 1)


if __name__ == '__main__':
    unittest.main()
