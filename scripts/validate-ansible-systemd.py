#!/usr/bin/env python3
"""CI contract: Ansible must render templated systemd units before installation."""
from pathlib import Path
import re
import subprocess
import tempfile

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
tasks = yaml.safe_load((ROOT / "ansible/roles/gway_remote/tasks/main.yml").read_text())
units = ["gway-remote-health.service", "gway-remote-health.timer"]
install = next(t for t in tasks if t.get("name") == "Install GitHub Health collector systemd units")
assert "ansible.builtin.template" in install, "Systemd Jinja units must use ansible.builtin.template"
assert install.get("loop") == units, "Check all installed GitHub Health units"
for task in tasks:
    if "ansible.builtin.copy" not in task:
        continue
    src = task["ansible.builtin.copy"].get("src")
    if not isinstance(src, str):
        continue
    for unit in ROOT.glob("deploy/systemd/*"):
        if unit.name in src or "{{ item }}" in src and unit.name in task.get("loop", []):
            assert not re.search(r"{{|{%", unit.read_text()), f"{unit} copied without rendering"

with tempfile.TemporaryDirectory() as tmp:
    for unit in units:
        source = ROOT / "deploy/systemd" / unit
        rendered = Environment(undefined=StrictUndefined).from_string(source.read_text()).render(
            gway_remote_runner_user="arthe"
        )
        assert not re.search(r"{{|{%", rendered), f"Unrendered Jinja in {unit}"
        target = Path(tmp) / unit
        target.write_text(rendered)
        if unit.endswith(".service"):
            for expected in ("User=arthe", "Group=arthe", "EnvironmentFile=/home/arthe/"):
                assert expected in rendered, f"Missing {expected} in {unit}"
    subprocess.run(["systemd-analyze", "verify", *(str(Path(tmp) / u) for u in units)], check=True)
print("Ansible systemd template contracts verified")
