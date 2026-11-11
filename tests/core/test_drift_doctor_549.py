"""Offline phase D drift doctor: evidence, non-mutating I/O and stable codes."""
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from gway_remote import drift_doctor as d
from gway_remote.cli.registry import build_parser
from gway_remote.reconcile import TARGETS

SHA = "a" * 40
OTHER = "b" * 40
DIGEST = hashlib.sha256(b"inventory").hexdigest()


def source(rev=SHA, digest=DIGEST, rules=()):
    return {"state": "local_checkout", "revision": rev,
            "inventory_digest": digest, "rules": list(rules),
            "evidence": "local_checkout_not_remote_verified"}


def inventory(state="validated_local_file", digest=DIGEST):
    return {"state": state, "digest": digest}


def release(sha=SHA, state="selected_manifest_verified"):
    return {"state": state, "selected_sha": sha,
            "evidence": "root_owned_manifest_file_digests"}


def providers(state="manifest_validated"):
    return {"state": state, "providers": []}


def unit(load="loaded", active="inactive", enablement="disabled"):
    return {"state": "observed", "load": load, "active": active,
            "enablement": enablement}


def services(*, active=False):
    retired = {name: unit() for name in d._RETIRED}
    if active:
        retired[d._RETIRED[0]] = unit(active="active", enablement="enabled")
    return {"state": "observed", "role": "controller", "retired": retired,
            "current": {"gway-remote-mcp.service": unit(active="active",
                                                        enablement="enabled")}}


class DriftDoctorTests(unittest.TestCase):
    def test_parser_and_cli_read_only_disposition(self):
        from gway_remote.cli import operations
        parser = build_parser(("system-health",), TARGETS)
        args = parser.parse_args(["doctor", "--checkout", "/tmp/example", "--json"])
        self.assertEqual((args.command, args.checkout, args.json),
                         ("doctor", "/tmp/example", True))
        base = d.doctor(source_reader=lambda path: source(),
                        inventory_reader=inventory, release_reader=release,
                        providers_reader=providers, services_reader=services)
        self.assertEqual(base["result"]["state"], "no_observed_drift_not_health_verified")
        for altered, code in ((base, None),
                              (dict(base, result={"state": "drift_detected"}), 1),
                              (dict(base, result={"state": "incomplete"}), 2)):
            with self.subTest(code=code), patch("gway_remote.drift_doctor.doctor",
                                                return_value=altered):
                out = StringIO()
                with patch("sys.stdout", out):
                    if code is None:
                        self.assertTrue(operations.dispatch(args, parser))
                    else:
                        with self.assertRaises(SystemExit) as error:
                            operations.dispatch(args, parser)
                        self.assertEqual(error.exception.code, code)
                self.assertNotIn("/tmp/example", out.getvalue())

    def test_cli_error_is_sanitized_and_newline_terminated(self):
        from gway_remote.cli import operations
        parser = build_parser(("system-health",), TARGETS)
        args = parser.parse_args(["doctor", "--json"])
        output = StringIO()
        with patch("gway_remote.drift_doctor.doctor",
                   side_effect=ValueError("TOP_SECRET=/etc/credentials")), \
             patch("sys.stderr", output), self.assertRaises(SystemExit) as failure:
            operations.dispatch(args, parser)
        self.assertEqual(failure.exception.code, 2)
        self.assertEqual(output.getvalue(), "gway-remote: drift evidence unavailable\n")
        self.assertNotIn("TOP_SECRET", output.getvalue())

    def test_pure_classifier_missing_source_never_reports_healthy(self):
        missing = source()
        missing.update(state="unknown", revision=None, inventory_digest=None,
                       rules="unknown")
        result = d.classify(missing, inventory(), release(), providers(), services())
        self.assertEqual(result["state"], "incomplete")
        self.assertEqual([x["code"] for x in result["findings"]],
                         ["GIT_SOURCE_UNKNOWN", "SOURCE_RULES_UNKNOWN"])
        self.assertNotIn("healthy", json.dumps(result))

    def test_pure_classifier_detects_inventory_release_unit_and_rule_drift(self):
        result = d.classify(source(rev=OTHER, digest="c"*64, rules=["gway-remote-watch.timer"]),
                            inventory(), release(), providers(), services(active=True))
        self.assertEqual(result["state"], "drift_detected")
        codes = {x["code"] for x in result["findings"]}
        self.assertTrue({"DRIFT_REACTIVATION_RULE", "DRIFT_INVENTORY",
                         "DRIFT_RELEASE", "DRIFT_RETIRED_UNIT"} <= codes)
        self.assertEqual({x["proposed_action"] for x in result["findings"]},
                         {d._PROPOSALS[x["code"]] for x in result["findings"]})
        self.assertNotIn("rm -", json.dumps(result))
        self.assertNotIn("systemctl disable", json.dumps(result))

    def test_specific_retired_and_required_units_emit_stable_targets(self):
        data = services(active=True)
        data["current"]["gway-remote-mcp.service"] = unit(active="failed",
                                                           enablement="enabled")
        result = d.classify(source(), inventory(), release(), providers(), data)
        self.assertEqual(result["state"], "drift_detected")
        pairs = {(r["code"], r.get("target")) for r in result["findings"]}
        self.assertIn(("DRIFT_RETIRED_UNIT", "gway-remote-watch.timer"), pairs)
        self.assertIn(("DRIFT_REQUIRED_UNIT_INACTIVE", "gway-remote-mcp.service"), pairs)
        self.assertIn("gway-remote-watch.timer", d.format_report(
            {"source": source(), "inventory": inventory(), "release": release(),
             "providers": providers(), "result": result}))
        data["role"] = "watchtower_candidate"
        data["current"] = {"gway-mcp-gateway.service": unit(active="active"),
                           "gway-mcp-link.service": unit(active="active",
                                                         enablement="enabled")}
        result = d.classify(source(), inventory(), release(), providers(), data)
        self.assertIn(("DRIFT_REQUIRED_UNIT_DISABLED", "gway-mcp-gateway.service"),
                      {(r["code"], r.get("target")) for r in result["findings"]})
        data["role"] = "unknown"
        data["current"] = {}
        result = d.classify(source(), inventory(), release(), providers(), data)
        self.assertIn("SERVICE_UNKNOWN", {r["code"] for r in result["findings"]})
        self.assertEqual(result["state"], "drift_detected")  # retired unit still active
        data["retired"] = {k: unit() for k in d._RETIRED}
        result = d.classify(source(), inventory(), release(), providers(), data)
        self.assertEqual(result["state"], "incomplete")

    def test_missing_required_service_and_invalid_manifest_fail_closed(self):
        service = services()
        service["current"]["gway-remote-mcp.service"] = unit(load="not-found")
        result = d.classify(source(), inventory(state="untrusted"),
                            release(state="invalid"), providers(state="unknown"), service)
        codes = {r["code"] for r in result["findings"]}
        self.assertTrue({"UNTRUSTED_INVENTORY", "INVALID_RELEASE_EVIDENCE",
                         "INVALID_PROVIDER_REGISTRY", "MISSING_REQUIRED_UNIT"} <= codes)

    def test_masked_and_error_units_fail_closed(self):
        data = services()
        data["current"]["gway-remote-mcp.service"] = unit(load="masked")
        result = d.classify(source(), inventory(), release(), providers(), data)
        self.assertEqual(result["state"], "drift_detected")
        self.assertIn(("MISSING_REQUIRED_UNIT", "gway-remote-mcp.service"),
                      {(r["code"], r.get("target")) for r in result["findings"]})
        data["current"]["gway-remote-mcp.service"] = unit(load="error")
        result = d.classify(source(), inventory(), release(), providers(), data)
        self.assertEqual(result["state"], "incomplete")
        self.assertIn("SERVICE_UNKNOWN", {r["code"] for r in result["findings"]})
        data = services()
        data["retired"][d._RETIRED[0]] = unit(load="error")
        self.assertEqual(d.classify(source(), inventory(), release(),
                                    providers(), data)["state"], "incomplete")
        data["retired"][d._RETIRED[0]] = unit(enablement="bad")
        self.assertEqual(d.classify(source(), inventory(), release(),
                                    providers(), data)["state"], "incomplete")

    def test_inaccessible_inventory_is_unknown_but_unsafe_metadata_is_drift(self):
        def inaccessible(path, *, maximum):
            raise PermissionError("EACCES: secret path")
        evidence = d._read_inventory(Path("/not-opened"), reader=inaccessible)
        self.assertEqual(evidence["state"], "unknown")
        self.assertNotIn("secret", json.dumps(evidence))
        def unsafe(path, *, maximum):
            raise d._UntrustedFileError("untrusted_file")
        self.assertEqual(d._read_inventory(Path("/not-opened"),
                                           reader=unsafe)["state"], "untrusted")

    def test_missing_required_ansible_recipes_are_specific_and_read_only(self):
        files = [
            """- name: Install health units
  ansible.builtin.template:
    src: health
  loop:
    - gway-remote-health.timer
    - gway-remote-health.service
- name: Enable with credential
  ansible.builtin.systemd:
    name: gway-remote-health.timer
    enabled: true
    state: started
- name: Disable without credential
  ansible.builtin.systemd:
    name: gway-remote-health.timer
    enabled: false
    state: stopped
""",
            """- name: Disable obsolete service
  ansible.builtin.systemd:
    name: gway-remote-deploy.service
    enabled: false
    state: stopped
- name: Remove dedicated service files
  ansible.builtin.file:
    path: "{{ item }}"
    state: absent
  loop:
    - /etc/systemd/system/gway-remote-deploy.service
""",
            """- name: Install Watchtower link
  ansible.builtin.copy:
    dest: /etc/systemd/system/gway-mcp-link.service
- name: Install Watchtower gateway
  ansible.builtin.copy:
    dest: /etc/systemd/system/gway-mcp-gateway.service
""",
            "other enrollment recipe"
        ]
        self.assertEqual(d._missing_required_rules(files), [])
        corrupted = files.copy()
        corrupted[0] = corrupted[0].replace("enabled: false", "enabled: true")
        corrupted[1] = corrupted[1].replace("state: absent", "state: present")
        corrupted[2] = corrupted[2].replace("gway-mcp-link.service", "not-gateway.service")
        absent = d._missing_required_rules(corrupted)
        targets = {r["target"] for r in absent}
        self.assertEqual(targets, {
            "gway-remote-health.timer", "gway-remote-deploy.service",
            "gway-mcp-link.service"})
        declared = source()
        declared["missing_rules"] = absent
        report = d.classify(declared, inventory(), release(), providers(), services())
        self.assertEqual(report["state"], "drift_detected")
        self.assertEqual({r["target"] for r in report["findings"]
                          if r["code"] == "MISSING_DECLARED_RULE"}, targets)
        self.assertNotIn("not-gateway", json.dumps(report))
        with self.assertRaises(ValueError):
            d._missing_required_rules(files[:2])

    def test_owned_reader_does_not_follow_symlink_or_fifo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = root / "data"
            p.write_bytes(b"inventory")
            self.assertEqual(d._owned_bytes(p, maximum=30, owner=os.geteuid()), b"inventory")
            link = root / "link"
            link.symlink_to(p)
            with self.assertRaises(OSError):
                d._owned_bytes(link, maximum=30, owner=os.geteuid())
            unsafe = root / "untrusted"
            unsafe.mkdir()
            unsafe.chmod(0o777)
            with self.assertRaises(PermissionError):
                d._owned_bytes(unsafe / "data", maximum=30, owner=os.geteuid())
            p.write_bytes(b"x" * 31)
            with self.assertRaises(PermissionError):
                d._owned_bytes(p, maximum=30, owner=os.geteuid())
            p.chmod(0o666)
            with self.assertRaises(PermissionError):
                d._owned_bytes(p, maximum=40, owner=os.geteuid())

    def test_local_inventory_reports_unknown_or_valid_digest_without_leaking_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inventory.yml"
            def own(path, *, maximum):
                return d._owned_bytes(path, maximum=maximum, owner=os.geteuid())
            self.assertEqual(d._read_inventory(path, reader=own)["state"], "unknown")
            path.write_bytes(b"inventory")
            result = d._read_inventory(path, reader=own)
            self.assertEqual(result["state"], "validated_local_file")
            self.assertEqual(result["digest"], DIGEST)
            self.assertNotIn(str(path), json.dumps(result))
            path.chmod(0o666)
            self.assertEqual(d._read_inventory(path, reader=own)["state"], "untrusted")

    def test_release_manifest_digests_are_not_runtime_health(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "mcp"
            releases = root / "releases"
            sha_dir = releases / SHA
            sha_dir.mkdir(parents=True)
            code = sha_dir / "run.py"
            code.write_text("print('local fixture')\n")
            digest = hashlib.sha256(code.read_bytes()).hexdigest()
            module = sha_dir / "gway_remote" / "node.py"
            module.parent.mkdir()
            module.write_text("# signed fixture module\n")
            module_digest = hashlib.sha256(module.read_bytes()).hexdigest()
            (sha_dir / "manifest.json").write_text(json.dumps({
                "revision": SHA,
                "sha256": {"run.py": digest, "gway_remote/node.py": module_digest}}))
            (root / "current").symlink_to("releases/" + SHA)
            def own(path, *, maximum, owner=0):
                return d._owned_bytes(path, maximum=maximum, owner=os.geteuid())
            result = d._release_observation(root, reader=own, owner=os.geteuid())
            self.assertEqual(result["state"], "selected_manifest_verified")
            self.assertEqual(result["selected_sha"], SHA)
            self.assertNotIn("healthy", json.dumps(result))
            code.write_text("tampered")
            broken = d._release_observation(root, reader=own, owner=os.geteuid())
            self.assertEqual(broken["state"], "invalid")
            self.assertEqual(broken["evidence"], "launcher_digest_mismatch")
            code.write_text("print('local fixture')\n")
            module.write_text("# unexpected module change\n")
            broken = d._release_observation(root, reader=own, owner=os.geteuid())
            self.assertEqual(broken["state"], "invalid")
            self.assertEqual(broken["evidence"], "manifest_content_mismatch")
            module.write_text("# signed fixture module\n")
            (root / "current").unlink()
            (root / "current").symlink_to("../../secrets")
            broken = d._release_observation(root, reader=own, owner=os.geteuid())
            self.assertEqual(broken["state"], "invalid")
            (root / "current").unlink()
            (root / "current").symlink_to("releases/" + SHA)
            sha_dir.chmod(0o777)
            broken = d._release_observation(root, reader=own, owner=os.geteuid())
            self.assertEqual(broken["state"], "invalid")

    def test_bounded_git_read_rejects_large_output_and_timeout(self):
        # The production Git adapter must cap output while reading, not only
        # after subprocess.run has buffered an arbitrarily large blob.
        good = d._bounded_command_output(
            [sys.executable, "-I", "-B", "-c", "print('ok')"],
            maximum=4, env={})
        self.assertEqual(good, b"ok\\n")
        with self.assertRaises(ValueError):
            d._bounded_command_output(
                [sys.executable, "-I", "-B", "-c",
                 "import sys;sys.stdout.write('x'*1000000)"],
                maximum=64, env={})
        with self.assertRaises(subprocess.TimeoutExpired):
            d._bounded_command_output(
                [sys.executable, "-I", "-B", "-c",
                 "import time;time.sleep(1)"],
                maximum=64, env={}, timeout=0.08)

    def test_git_checkout_is_local_only_and_never_fetches(self):
        with tempfile.TemporaryDirectory() as temp:
            args = []
            def runner(argv, **kwargs):
                args.append(argv)
                if "symbolic-ref" in argv:
                    answer = "main\n"
                elif "rev-parse" in argv:
                    answer = SHA + "\n"
                elif argv[-1] == "origin":
                    answer = "https://github.com/arthexis/gway-remote.git\n"
                elif argv[-1] == "HEAD:ansible/inventory/deployment.yml":
                    answer = "inventory"
                else:
                    answer = "# A comment about gway-remote-watch.timer\n"
                return subprocess.CompletedProcess(argv, 0, answer.encode(), b"")
            result = d._git_source(temp, run=runner)
            self.assertEqual(result["state"], "local_checkout")
            self.assertEqual(result["revision"], SHA)
            self.assertEqual(result["inventory_digest"], DIGEST)
            self.assertEqual(result["rules"], [])
            self.assertEqual(len(args), 8)
            self.assertFalse(any("fetch" in a or "pull" in a for arg in args for a in arg))
            self.assertEqual(result["evidence"], "local_checkout_not_remote_verified")
            self.assertNotIn(str(temp), json.dumps(result))

    def test_git_untrusted_origin_or_detached_head_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            def run(argv, **kwargs):
                if "rev-parse" in argv:
                    answer = SHA
                elif "symbolic-ref" in argv:
                    answer = "main"
                else:
                    answer = "https://example.com/secret-token.git"
                return subprocess.CompletedProcess(argv, 0, answer.encode(), b"")
            result = d._git_source(temp, run=run)
            self.assertEqual(result["state"], "unknown")
            self.assertNotIn("example.com", json.dumps(result))

    def test_retired_reactivation_scan_ignores_comments_and_removal(self):
        sources = ["""
# systemd:
# name: gway-remote-watch.timer
- name: Remove old timer
  ansible.builtin.systemd:
    name: gway-remote-watch.timer
    state: stopped
    enabled: false
- name: Activate expected health timer
  ansible.builtin.systemd:
    name: gway-remote-health.timer
    state: started
    enabled: true
"""]
        self.assertEqual(d._retired_rules(sources)["matches"], [])
        sources.append("""
- name: Re-enable removed legacy timer
  ansible.builtin.systemd:
    name: gway-remote-watch.timer
    state: started
    enabled: true
""")
        self.assertEqual(d._retired_rules(sources)["matches"], ["gway-remote-watch.timer"])

    def test_retired_rule_only_matches_real_systemd_target(self):
        mention = """- name: Replace old gway-remote-watch.timer with health timer
  ansible.builtin.systemd:
    name: gway-remote-health.timer
    state: started
    enabled: true
"""
        scan = d._retired_rules([mention])
        self.assertEqual(scan, {"matches": [], "ambiguous": False})
        dynamic = """- name: Install optionally active timer
  ansible.builtin.systemd:
    name: "{{ item }}"
    state: started
  loop:
    - gway-remote-watch.timer
"""
        scan = d._retired_rules([dynamic])
        self.assertEqual(scan, {"matches": [], "ambiguous": True})
        declared = source()
        declared["rules_dynamic"] = True
        report = d.classify(declared, inventory(), release(), providers(), services())
        self.assertEqual(report["state"], "incomplete")
        self.assertIn("SOURCE_RULES_UNKNOWN",
                      [finding["code"] for finding in report["findings"]])

    def test_systemd_reads_only_fixed_fields_and_no_mutation(self):
        runs = []
        def run(argv, **kwargs):
            runs.append(argv)
            return subprocess.CompletedProcess(
                argv, 0, "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n", "")
        state = d._unit("gway-mcp-gateway.service", run=run)
        self.assertEqual(state["state"], "observed")
        self.assertEqual(runs[0][:2], ["systemctl", "show"])
        self.assertNotIn("restart", runs[0])
        self.assertNotIn("enable", runs[0])
        result = d._services(node="gway-005", unit_reader=lambda unit, **kwargs: unit and state)
        self.assertEqual(result["role"], "unknown")
        self.assertEqual(result["current"], {})
        self.assertEqual(set(result["retired"]), set(d._RETIRED))

    def test_provider_receipts_are_historical_and_never_installed(self):
        from types import SimpleNamespace
        item = SimpleNamespace(source_id="odoo", revision=SHA,
                               deployment={"schema":1, "revision":SHA,
                                           "checkout":"/opt/app", "runner":"/opt/app/deploy.sh"})
        result = d._providers(discover=lambda directory:(item,),
                              receipt=lambda source, **kw: {"state":"succeeded"})
        self.assertEqual(result["providers"][0]["receipt"], "succeeded")
        self.assertEqual(result["providers"][0]["installed_release"], "unverified")
        self.assertNotIn("/opt/app", json.dumps(result))
        denied = d._providers(discover=lambda directory: (_ for _ in ()).throw(
            PermissionError("TOP_SECRET")))
        self.assertEqual(denied["state"], "unknown")
        self.assertNotIn("TOP_SECRET", json.dumps(denied))

    def test_determinism_and_no_side_effects_for_same_evidence(self):
        def inject():
            return d.doctor(checkout=None, source_reader=lambda _: source(),
                            inventory_reader=inventory, release_reader=release,
                            providers_reader=providers, services_reader=services)
        a, b = inject(), inject()
        a.pop("checked_at")
        b.pop("checked_at")
        self.assertEqual(a, b)
        self.assertIn("no_observed_drift_not_health_verified", json.dumps(a))


if __name__ == "__main__":
    unittest.main()
