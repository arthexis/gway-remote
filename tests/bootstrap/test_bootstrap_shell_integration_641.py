"""Hermetic end-to-end execution of the generated one-URL shell.

All binary commands that could mutate a host or reach the network are replaced
by executable stubs in a private PATH. No root, systemd, SSH, WireGuard, APT,
Watchtower or external host is ever contacted by these tests.
"""
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from gway_remote.bootstrap_script import render_bootstrap_script

REV = "a" * 40
HOST_KEY = "b" * 44
KEY = "ssh-ed25519 " + "A" * 43 + "="
CLIENT = b"# dummy reviewed standalone client\n"


def _stub(path, source):
    path.write_text("#!/bin/sh\nset -eu\n" + source)
    path.chmod(0o700)


@pytest.fixture
def fake_host(tmp_path):
    bins = tmp_path / "bin"
    bins.mkdir()
    log = tmp_path / "events"
    _stub(bins / "id", "if [ \"$1\" = '-u' ]; then echo 0; else exit 1; fi\n")
    _stub(bins / "hostname", "echo gway-007\n")
    _stub(bins / "apt-get", 'echo "apt $*" >> "$EVENTS"\n')
    _stub(bins / "git", '''
echo "git $*" >> "$EVENTS"
case " $* " in
  *" rev-parse HEAD "*) echo "$RELEASE";;
  *" status --porcelain "*) :;;
  *" fetch "*) [ "${FAIL_STAGE:-}" != git ] || exit 20;;
esac
''')
    _stub(bins / "wg", 'echo "' + "A" * 43 + '="\n')
    _stub(bins / "ansible-playbook", '''
echo "ansible $*" >> "$EVENTS"
[ "${FAIL_STAGE:-}" != ansible ] || exit 21
''')
    _stub(bins / "python3", '''
if [ "$1" = "-c" ]; then exec /usr/bin/python3 "$@"; fi
case "$1" in
  */build-bootstrap-vars.py)
    echo "vars $*" >> "$EVENTS"
    printf '{"gway_bootstrap_node":"gway-007"}\\n'
    ;;
  */client.py)
    echo "client $*" >> "$EVENTS"
    [ "${FAIL_STAGE:-}" != client ] || exit 22
    ;;
  *) exit 24;;
esac
''')
    _stub(bins / "curl", '''
echo "curl $*" >> "$EVENTS"
output=""
next=0
for word in "$@"; do
  if [ "$next" = 1 ]; then output="$word"; next=0; continue; fi
  if [ "$word" = "-o" ]; then next=1; fi
done
case " $* " in
  *"/client.py "*) printf '%s' "$CLIENT_CONTENT" > "$output";;
  *"/complete "*)
    if [ -n "$output" ]; then
      printf '{"complete":true,"local_setup_reported":true,"local_ready_verified":false}\\n' > "$output"
    else
      printf '{"complete":true,"local_setup_reported":false,"local_ready_verified":false}\\n'
    fi
    ;;
  *) exit 25;;
esac
''')
    env = {**os.environ, "PATH": str(bins) + ":" + os.environ["PATH"],
           "EVENTS": str(log), "RELEASE": REV,
           "CLIENT_CONTENT": CLIENT.decode(), "SUDO_USER": "arthe"}
    return env, log


def _render(*, repair=False, bad_hash=False):
    digest = hashlib.sha256(CLIENT).hexdigest()
    return render_bootstrap_script("c" * 40, "gway-007", HOST_KEY,
                                   repair_host_identity=repair,
                                   release_revision=REV,
                                   relay_public_key=KEY,
                                   client_sha256=("f" * 64 if bad_hash else digest))


def _execute(script, env):
    return subprocess.run(["sh", "-s"], input=script,
                          env=env, capture_output=True, timeout=10, check=False)


def test_success_does_not_claim_remote_execution(fake_host):
    env, events = fake_host
    result = _execute(_render(), env)
    assert result.returncode == 0, result.stderr.decode()
    lines = events.read_text().splitlines()
    def event(prefix):
        return next(i for i, line in enumerate(lines) if line.startswith(prefix))
    client_fetch = next(i for i, line in enumerate(lines) if
                        line.startswith("curl ") and "/client.py" in line)
    complete = next(i for i, line in enumerate(lines) if
                    line.startswith("curl ") and "/complete" in line)
    assert client_fetch < event("git -C")
    assert event("git -C") < event("vars ")
    assert event("vars ") < event("client ")
    assert event("client ") < event("ansible ")
    assert event("ansible ") < complete
    assert b"REMOTE_EXECUTION_UNVERIFIED" in result.stdout
    assert b"LOCAL_BOOTSTRAP_READY" not in result.stdout


@pytest.mark.parametrize("failed", ["client", "ansible", "git"])
def test_stage_failure_never_sends_completion(fake_host, failed):
    env, events = fake_host
    env["FAIL_STAGE"] = failed
    result = _execute(_render(), env)
    assert result.returncode != 0
    assert "/complete" not in events.read_text()


def test_bad_client_digest_blocks_any_provisioning(fake_host):
    env, events = fake_host
    result = _execute(_render(bad_hash=True), env)
    assert result.returncode != 0
    text = events.read_text()
    assert "/client.py" in text
    assert "git -C" not in text
    assert not any(line.startswith("ansible ") for line in text.splitlines())
    assert "/complete" not in text


def test_root_only_repair_keeps_existing_identity_path(fake_host):
    env, events = fake_host
    env.pop("SUDO_USER")
    result = _execute(_render(repair=True), env)
    assert result.returncode == 0, result.stderr.decode()
    content = events.read_text()
    assert "--repair" in content
    assert "/complete" in content
    # Regression: repair-first must not attempt full package/relay convergence.
    assert "git -C" not in content
    assert not any(line.startswith("vars ") for line in content.splitlines())
    assert not any(line.startswith("ansible ") for line in content.splitlines())
