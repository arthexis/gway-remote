"""Offline phase D drift doctor: evidence, non-mutating I/O and stable codes."""
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import stat
import subprocess
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


def release(sha=SHA, state="selected_partial_verified"):
    return {"state": state, "selected_sha": sha,
            "evidence": "root_owned_pointer_manifest_launcher"}


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

    def test_missing_required_service_and_invalid_manifest_fail_closed(self):
        service = services()
        service["current"]["gway-remote-mcp.service"] = unit(load="not-found")
        result = d.classify(source(), inventory(state="untrusted"),
                            release(state="invalid"), providers(state="unknown"), service)
        codes = {r["code"] for r in result["findings"]}
        self.assertTrue({"UNTRUSTED_INVENTORY", "INVALID_RELEASE_EVIDENCE",
                         "INVALID_PROVIDER_REGISTRY", "MISSING_REQUIRED_UNIT"} <= codes)

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
            self.assertEqual(d._read_inventory(path)["state"], "unknown")
            path.write_bytes(b"inventory")
            def own(path, *, maximum):
                return d._owned_bytes(path, maximum=maximum, owner=os.geteuid())
            result = d._read_inventory(path, reader=own)
            self.assertEqual(result["state"], "validated_local_file")
            self.assertEqual(result["digest"], DIGEST)
            self.assertNotIn(str(path), json.dumps(result))
            path.chmod(0o666)
            self.assertEqual(d._read_inventory(path, reader=own)["state"], "untrusted")

    def test_release_selected_sha_and_partial_manifest_digest_not_runtime_health(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "mcp"
            releases = root / "releases"
            sha_dir = releases / SHA
            sha_dir.mkdir(parents=True)
            code = sha_dir / "run.py"
            code.write_text("print('local fixture')\n")
            digest = hashlib.sha256(code.read_bytes()).hexdigest()
            (sha_dir / "manifest.json").write_text(json.dumps({
                "revision": SHA, "sha256": {"run.py": digest}}))
            (root / "current").symlink_to("releases/" + SHA)
            def own(path, *, maximum, owner=0):
                return d._owned_bytes(path, maximum=maximum, owner=os.geteuid())
            result = d._release_observation(root, reader=own, owner=os.geteuid())
            self.assertEqual(result["state"], "selected_partial_verified")
            self.assertEqual(result["selected_sha"], SHA)
            self.assertNotIn("healthy", json.dumps(result))
            code.write_text("tampered")
            broken = d._release_observation(root, reader=own, owner=os.geteuid())
            self.assertEqual(broken["state"], "invalid")
            self.assertEqual(broken["evidence"], "launcher_digest_mismatch")
            code.write_text("print('local fixture')\n")
            (root / "current").unlink()
            (root / "current").symlink_to("../../secrets")
            broken = d._release_observation(root, reader=own, owner=os.geteuid())
            self.assertEqual(broken["state"], "invalid")
            (root / "current").unlink()
            (root / "current").symlink_to("releases/" + SHA)
            sha_dir.chmod(0o777)
            broken = d._release_observation(root, reader=own, owner=os.geteuid())
            self.assertEqual(broken["state"], "invalid")

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
        self.assertEqual(d._retired_rules(sources), [])
        sources.append("""
- name: Re-enable removed legacy timer
  ansible.builtin.systemd:
    name: gway-remote-watch.timer
    state: started
    enabled: true
""")
        self.assertEqual(d._retired_rules(sources), ["gway-remote-watch.timer"])

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
