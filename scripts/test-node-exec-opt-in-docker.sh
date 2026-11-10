#!/bin/sh
# CI-only disposable fixture. Never run the opt-in recipe on the host.
set -eu
if [ "$#" -eq 0 ]; then
  command -v docker >/dev/null 2>&1 || { echo "Docker required for isolated opt-in test" >&2; exit 1; }
  exec docker run --rm --network=bridge \
    --mount "type=bind,src=$(pwd),dst=/repo,readonly" \
    --workdir /repo debian:bookworm \
    /bin/sh /repo/scripts/test-node-exec-opt-in-docker.sh --inside
fi
[ "$#" -eq 1 ] && [ "$1" = "--inside" ] && [ -f /.dockerenv ] || {
  echo "Refusing non-container opt-in test" >&2; exit 1;
}
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends ansible sudo openssh-client openssh-server passwd >/dev/null

# All account, key, root-policy, sshd and file changes happen INSIDE this
# throwaway container. /repo is mounted read-only; no host credentials used.
useradd -m -s /bin/sh installer
# Unlock the fixture account for public-key SSH (password auth stays disabled).
passwd -d installer >/dev/null
printf 'installer ALL=(ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/test-installer
chmod 0440 /etc/sudoers.d/test-installer
work=$(mktemp -d /tmp/gway-optin.XXXXXX)
chmod 0755 "$work"
mkdir -p "$work/ansible/roles/gway_remote/tasks" "$work/scripts"
cp /repo/ansible/roles/gway_remote/tasks/node-exec-opt-in.yml "$work/ansible/roles/gway_remote/tasks/"
cp /repo/scripts/node-exec-forced-command.py "$work/scripts/"
cat >"$work/ansible/fixture.yml" <<'YAML'
- name: Exercise only the SSH opt-in recipe in the disposable container
  hosts: localhost
  gather_facts: false
  connection: local
  become: true
  tasks:
    - ansible.builtin.import_tasks: roles/gway_remote/tasks/node-exec-opt-in.yml
YAML
ssh-keygen -q -t ed25519 -N '' -f "$work/admin"
ssh-keygen -q -t ed25519 -N '' -f "$work/executor"
install -d -m 0700 -o installer -g installer /home/installer/.ssh
install -m 0600 -o installer -g installer "$work/admin.pub" /home/installer/.ssh/authorized_keys
install -d -m 0755 -o root -g root /etc/gway-remote
printf '{"user":"installer"}\n' >/etc/gway-remote/executor-identity.json
chmod 0644 /etc/gway-remote/executor-identity.json
uid=$(id -u installer)
pub=$(awk '{print $1 " " $2}' "$work/executor.pub")
printf '{"gway_remote_executor_opt_in":true,"gway_remote_runner_user":"installer","gway_remote_runner_uid":%s,"gway_remote_exec_public_key":"%s"}\n' "$uid" "$pub" >"$work/vars.json"
chmod 0644 "$work/vars.json"

run_playbook() {
  runuser -u installer -- ansible-playbook -i 'localhost,' -c local \
    "$work/ansible/fixture.yml" -e "@$work/vars.json" "$@"
}
assert_rejected() {
  label=$1
  shift
  if run_playbook "$@" >"$work/negative.log" 2>&1; then
    echo "Unexpected acceptance of negative scenario: $label" >&2
    cat "$work/negative.log" >&2
    exit 1
  fi
}

# Refuse invalid inputs before modifying a dedicated key or admin key.
assert_rejected opt_out -e gway_remote_executor_opt_in=false
assert_rejected wrong_uid -e gway_remote_runner_uid=99999
assert_rejected wrong_user -e gway_remote_runner_user=other
printf '{"user":"other"}\n' >/etc/gway-remote/executor-identity.json
assert_rejected conflicting_policy
printf '{"user":"installer"}\n' >/etc/gway-remote/executor-identity.json
chmod 0666 /etc/gway-remote/executor-identity.json
assert_rejected writable_policy
chmod 0644 /etc/gway-remote/executor-identity.json
chmod 0777 /home/installer/.ssh
assert_rejected unsafe_ssh_dir
chmod 0700 /home/installer/.ssh
cmp "$work/admin.pub" /home/installer/.ssh/authorized_keys

# Genuine Ansible modules install the fake key and the fixed entrypoint,
# then the second pass must be strictly idempotent.
run_playbook >"$work/first.log" 2>&1 || { cat "$work/first.log"; exit 1; }
run_playbook >"$work/second.log" 2>&1 || { cat "$work/second.log"; exit 1; }
grep -Eq 'changed=0' "$work/second.log"
grep -Fx "$(cat "$work/admin.pub")" /home/installer/.ssh/authorized_keys >/dev/null
grep -F 'restrict,command="/usr/local/libexec/gway-remote-exec-protocol-v1"' \
  /home/installer/.ssh/authorized_keys >/dev/null
[ "$(wc -l </home/installer/.ssh/authorized_keys)" -eq 2 ]
[ "$(stat -c '%U %a' /usr/local/libexec/gway-remote-exec-protocol-v1)" = 'root 755' ]

# OpenSSH server-side negative checks using the fake executor key.
# Valid protocol marker is NEVER sent; no node_exec operation is dispatched.
ssh-keygen -q -t ed25519 -N '' -f "$work/host"
mkdir -p /run/sshd
cat >"$work/sshd_config" <<EOF
Port 22228
ListenAddress 127.0.0.1
PidFile $work/sshd.pid
HostKey $work/host
AuthorizedKeysFile .ssh/authorized_keys
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
UsePAM no
AllowUsers installer
LogLevel VERBOSE
EOF
/usr/sbin/sshd -f "$work/sshd_config" -t
/usr/sbin/sshd -f "$work/sshd_config"
ssh_opts="-p 22228 -i $work/executor -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -o ConnectTimeout=3"
# shellcheck disable=SC2086
if ssh $ssh_opts installer@127.0.0.1 id >"$work/shell.log" 2>&1; then
  echo "Restricted key allowed an arbitrary shell command" >&2; exit 1
fi
# -tt must be refused by the key's restrict option.
# shellcheck disable=SC2086
if ssh $ssh_opts -tt installer@127.0.0.1 id >"$work/pty.log" 2>&1; then
  echo "Restricted key allowed PTY" >&2; exit 1
fi
grep -qi 'pty allocation request failed' "$work/pty.log"
# -W requests a direct-tcpip forwarding channel, prohibited by restrict.
# shellcheck disable=SC2086
if timeout 6 ssh $ssh_opts -W 127.0.0.1:22228 installer@127.0.0.1 \
    >"$work/forward.log" 2>&1; then
  echo "Restricted key allowed TCP forwarding" >&2; exit 1
fi
grep -Eiq 'administratively prohibited|open failed' "$work/forward.log"
# Execute only the bounded limits/read-only path and local SQLite state under
# the same fake installer UID. Never submit a job or start systemd.
runuser -u installer -- env PYTHONPATH=/repo /usr/bin/python3 - <<'PY'
import json
from pathlib import Path
import tempfile
from gway_remote import node_exec_protocol, node_exec_worker

request = {"operation": "limits", "node": "gway-001", "request_id": "a" * 32}
result = node_exec_protocol.serve_one(json.dumps(request).encode(), hostname="gway-001")
assert result["node"] == "gway-001"
assert 1 <= result["concurrent_jobs_per_node"] <= 8

with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary) / "private"
    directory.mkdir(mode=0o700)
    database = directory / "jobs.sqlite3"
    first = node_exec_worker.Jobs(database, max_active=1)
    with first.connection() as connection:
        connection.execute(
            "INSERT INTO jobs (id,node,command,status,created_at) VALUES (?,?,?,?,?)",
            ("b" * 32, "gway-001", "true", "queued", "2026-01-01T00:00:00+00:00"),
        )
    restarted = node_exec_worker.Jobs(database, max_active=1)
    assert restarted.row("b" * 32)["status"] == "queued"
    assert database.stat().st_mode & 0o077 == 0

try:
    node_exec_worker.user_manager_env()
except RuntimeError as error:
    assert "user manager unavailable" in str(error)
else:
    raise AssertionError("systemd user-bus absence must fail closed")
PY
echo "PASS: disposable Ansible, OpenSSH negatives, UID-bound limits, SQLite restart and absent systemd user bus"
