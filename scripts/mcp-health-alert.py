#!/usr/bin/env python3
"""Notify locally when the independent public MCP health probe fails or recovers.

Only fixed messages are displayed. This unprivileged observer never reads OAuth
credentials and never sends a command through MCP.
"""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time

SERVICE = 'gway-mcp-external-health.service'
TIMER = 'gway-mcp-external-health.timer'
STATE_DIR = Path.home() / '.local/state/gway-remote'
LCD_DIR = Path.home() / '.local/state/lcd-lockfiles'
SOUND = Path.home() / '.local/bin/sound'
STATE_FILE = 'mcp-health-alert.json'
LCD_FILE = 'lcd-event-mcp-health.lck'
REPEAT_SECONDS = 900
STALE_SECONDS = 420
FAILURE_THRESHOLD = 2
RECOVERY_THRESHOLD = 2
_ID = re.compile(r'^[0-9a-f]{32}$')


def _show(unit, properties, runner=subprocess.run):
    result = runner(['/usr/bin/systemctl', 'show', unit,
                     *['--property=' + item for item in properties]],
                    capture_output=True, text=True, timeout=5, check=True)
    pairs = {}
    for line in result.stdout.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key in properties:
                pairs[key] = value
    if set(pairs) != set(properties):
        raise ValueError('incomplete systemd state')
    return pairs


def observe(*, now_monotonic=None, runner=subprocess.run):
    """Read unit state only; each completed probe has one unique sample ID."""
    now = time.monotonic() if now_monotonic is None else now_monotonic
    slot = int(now // 30)
    def fault(reason):
        return {'status': 'failed', 'id': f'{reason}:{slot}'}
    try:
        timer = _show(TIMER, ('LoadState', 'ActiveState', 'ActiveEnterTimestampMonotonic'), runner)
        service = _show(SERVICE, ('LoadState', 'ActiveState', 'Result', 'ExecMainStatus',
                                 'ExecMainStartTimestampMonotonic',
                                 'ExecMainExitTimestampMonotonic', 'InvocationID'), runner)
        if timer['LoadState'] != 'loaded' or timer['ActiveState'] != 'active':
            return fault('timer_unavailable')
        if service['LoadState'] != 'loaded':
            return fault('probe_unavailable')
        entered = int(timer['ActiveEnterTimestampMonotonic']) / 1_000_000
        started = int(service['ExecMainStartTimestampMonotonic']) / 1_000_000
        ended = int(service['ExecMainExitTimestampMonotonic']) / 1_000_000
        if min(entered, started, ended) < 0 or max(entered, started, ended) > now + 1:
            return fault('invalid_clock')
        if service['ActiveState'] in ('activating', 'active', 'deactivating'):
            if started and now - started > STALE_SECONDS:
                return fault('probe_stuck')
            return {'status': 'pending', 'id': ''}
        if not ended:
            return fault('probe_missing') if entered and now - entered > STALE_SECONDS else {'status': 'pending', 'id': ''}
        if now - ended > STALE_SECONDS:
            return fault('probe_stale')
        sample_id = service['InvocationID']
        if not _ID.fullmatch(sample_id) or sample_id == '0' * 32:
            return fault('invalid_sample')
        ok = (service['ActiveState'] == 'inactive' and service['Result'] == 'success'
              and service['ExecMainStatus'] == '0')
        return {'status': 'healthy' if ok else 'failed', 'id': sample_id}
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return fault('monitor_unavailable')


def initial_state():
    return {'version': 1, 'last_id': '', 'failures': 0, 'successes': 0,
            'alerted': False, 'last_notice': 0}


def advance(previous, sample, now):
    """Debounce distinct probe runs and repeat active alerts at a bounded rate."""
    state = dict(previous)
    status, sample_id = sample['status'], sample['id']
    if status in ('healthy', 'failed') and sample_id != state['last_id']:
        state['last_id'] = sample_id
        if status == 'failed':
            state['failures'] = min(state['failures'] + 1, FAILURE_THRESHOLD)
            state['successes'] = 0
        else:
            state['successes'] = min(state['successes'] + 1, RECOVERY_THRESHOLD)
            state['failures'] = 0
    if state['alerted'] and state['successes'] >= RECOVERY_THRESHOLD:
        state['alerted'] = False
        state['last_notice'] = now
        return state, 'recovered'
    elapsed = now - state['last_notice']
    repeat_due = elapsed >= REPEAT_SECONDS or elapsed < 0
    if state['failures'] >= FAILURE_THRESHOLD and (not state['alerted'] or repeat_due):
        state['alerted'] = True
        state['last_notice'] = now
        return state, 'failed'
    return state, None


def _safe_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('unsafe state directory')


def _atomic_write(path, data):
    _safe_directory(path.parent)
    if path.is_symlink():
        raise ValueError('unsafe output')
    fd, tmp = tempfile.mkstemp(prefix='.mcp-health-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_state(path):
    if not path.exists() and not path.is_symlink():
        return initial_state()
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or info.st_size > 4096):
        raise ValueError('unsafe state')
    data = json.loads(path.read_text(encoding='utf-8'))
    expected = initial_state()
    if (type(data) is not dict or set(data) != set(expected) or data['version'] != 1
            or type(data['last_id']) is not str or len(data['last_id']) > 80
            or type(data['alerted']) is not bool
            or any(type(data[key]) is not int or data[key] < 0 for key in ('failures', 'successes', 'last_notice'))
            or data['failures'] > FAILURE_THRESHOLD or data['successes'] > RECOVERY_THRESHOLD):
        raise ValueError('invalid state')
    return data


def lcd_message(kind, now):
    lines = ('MCP CHECK FAIL', 'CHECK STATUS') if kind == 'failed' else ('MCP CHECK OK', 'RECOVERED')
    expires = datetime.fromtimestamp(now, timezone.utc) + timedelta(seconds=60)
    return '\n'.join((*lines, expires.isoformat())) + '\n'


def test_notice(kind, *, state_dir=STATE_DIR, lcd_dir=LCD_DIR, sound=SOUND, runner=subprocess.run):
    """Exercise the actual display and sound without inventing monitor state."""
    _safe_directory(state_dir)
    lockfd = os.open(state_dir / '.mcp-health-alert.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(lockfd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('unsafe lock')
        fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if load_state(state_dir / STATE_FILE)['alerted']:
            raise ValueError('active alert')
        lines = ('MCP TEST FAIL', 'AUDIO DISPLAY') if kind == 'failure' else ('MCP TEST OK', 'AUDIO DISPLAY')
        expires = datetime.now(timezone.utc) + timedelta(seconds=30)
        _atomic_write(lcd_dir / LCD_FILE, '\n'.join((*lines, expires.isoformat())) + '\n')
        result = runner([str(sound), 'warning' if kind == 'failure' else 'ok'],
                        capture_output=True, timeout=12, check=False)
        if result.returncode:
            return 1
        print(json.dumps({'status': 'test_sent', 'kind': kind}))
        return 0
    finally:
        os.close(lockfd)


def run_once(*, state_dir=STATE_DIR, lcd_dir=LCD_DIR, sound=SOUND, sample=None, now=None,
             runner=subprocess.run):
    now = int(time.time()) if now is None else now
    _safe_directory(state_dir)
    lockfd = os.open(state_dir / '.mcp-health-alert.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(lockfd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('unsafe lock')
        fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = state_dir / STATE_FILE
        previous = load_state(state_path)
        updated, notice = advance(previous, observe() if sample is None else sample, now)
        if notice:
            _atomic_write(lcd_dir / LCD_FILE, lcd_message(notice, now))
        _atomic_write(state_path, json.dumps(updated, sort_keys=True) + '\n')
        if notice:
            try:
                completed = runner([str(sound), 'warning' if notice == 'failed' else 'ok'],
                                   capture_output=True, timeout=12, check=False)
                if completed.returncode:
                    print(json.dumps({'status': 'sound_unavailable', 'notice': notice}))
                    return 1
            except (OSError, subprocess.SubprocessError):
                print(json.dumps({'status': 'sound_unavailable', 'notice': notice}))
                return 1
        print(json.dumps({'status': 'ok', 'notice': notice or 'none'}))
        return 0
    finally:
        os.close(lockfd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', choices=('failure', 'recovery'), help='send an unmistakable local test notification')
    args = parser.parse_args()
    try:
        return test_notice(args.test) if args.test else run_once()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, json.JSONDecodeError):
        print(json.dumps({'status': 'alert_observer_unavailable'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
