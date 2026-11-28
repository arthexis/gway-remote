"""Candidate-bound physical evidence. No secrets, customer text or raw trees in receipts."""
import time
from gway_remote.android_release_candidate import PACKAGE, SignedArtifact, require
from gway_remote.android_rc_health import MENU, _snapshot, _point, fresh_health

WORKFLOW = "android-release-candidate-accept.yml"
SMOKE_CHECKS = ("health", "home", "updates", "opportunities", "liturgia_today",
                "quotation_list", "deployment_controls_visible", "feed_view")
FULL_CHECKS = frozenset(SMOKE_CHECKS + (
    "opportunity_refresh_and_stale", "opportunity_consent_and_copy_contract",
    "liturgia_reader_search_comparison", "liturgia_local_library_and_errors",
    "quotation_pdf_and_refresh", "feed_read_and_failure", "navigation_and_scope", "deployment_confirmation",
    "exact_source_ci_and_compose",
))


def tagged_rows(rows, tag):
    return [row for row in rows if row.get("resource_id") == tag]


def tagged_control_ready(rows, tag):
    matches = tagged_rows(rows, tag)
    return len(matches) == 1 and matches[0].get("enabled") is True


def verify_deployment_guard(tree):
    # UiAutomator's child text labels remain enabled even on a disabled
    # Compose button. Only the explicit parent semantics prove the guard.
    submits = tagged_rows(tree["elements"], "rc-deploy-submit")
    confirms = tagged_rows(tree["elements"], "rc-deploy-confirm")
    require(len(submits) == len(confirms) == 1
            and submits[0].get("enabled") is False
            and confirms[0].get("checkable") is True
            and confirms[0].get("checked") is False,
            "deployment_guard_unverified")


class PhysicalSmoke:
    """Fixed read-only actions inside the reviewed hardware workflow/device lease."""
    def __init__(self, device, serial, *, pause=time.sleep):
        self.device, self.serial, self.pause = device, serial, pause
        self.rotation = device.screen_state(serial).get("rotation")
        self.dimensions = device.size(serial)
        require(type(self.rotation) is int, "screen_rotation_unknown")

    def observe(self):
        return _snapshot(self.device, self.serial, self.rotation, self.dimensions)

    def wait(self, predicate):
        for _ in range(8):
            tree = self.observe()
            if predicate(tree):
                return tree
            self.pause(1)
        raise ValueError("physical_observation_unconfirmed")

    @staticmethod
    def has(tree, text):
        return any(r.get("text") == text for r in tree["elements"])

    def tap(self, field, value, *, first=False):
        def target(tree):
            rows = [r for r in tree["elements"] if r.get(field) == value and r.get("enabled") is True]
            require(bool(rows) and (first or len(rows) == 1), "physical_target_ambiguous")
            points = [_point(r, self.dimensions) for r in rows]
            require(len({(p["x"], p["y"]) for p in points}) == len(points), "physical_target_ambiguous")
            return min(points, key=lambda p: (p["y"], p["x"])) if first else points[0]
        point = target(self.observe())
        require(point == target(self.observe()), "physical_target_moved")
        require(self.device.serial() == self.serial, "usb_identity_changed")
        self.device.adb(self.serial, "shell", "input", "tap", point["x"], point["y"])
        self.pause(0.4)

    def drawer_scroll(self, down):
        tree = self.observe()
        require(sum(self.has(tree, n) for n in ("System", "Cotizaciones", "Deployments",
                    "MCP Access", "Liturgia", "GitHub Health")) >= 2, "drawer_unconfirmed")
        w, h = self.dimensions
        x, top, bottom = w*2//5, h*3//10, h*8//10
        require(self.device.serial() == self.serial, "usb_identity_changed")
        self.device.adb(self.serial, "shell", "input", "swipe", x,
                        bottom if down else top, x, top if down else bottom, 450)
        self.pause(0.4)

    def navigate(self, label, header):
        self.tap("description", MENU)
        for direction in (None, False, True, True):
            if direction is not None:
                self.drawer_scroll(direction)
            tree = self.observe()
            if self.has(tree, label):
                self.tap("text", label)
                return self.wait(lambda t: self.has(t, header) and
                                 any(r.get("description") == MENU for r in t["elements"]))
        raise ValueError("physical_module_not_visible")

    def home_feed(self):
        def ready(tree):
            rows = tree["elements"]
            unavailable = {"Acceso al feed no autorizado", "Activity Feed aún no habilitado",
                           "Historial offline", "Feed no disponible",
                           "Configura la API Key y el endpoint HTTPS desde el menú lateral."}
            if any(row.get("text") in unavailable for row in rows):
                return False  # transient offline cache is not a successful live observation
            return (self.has(tree, "Activity Feed")
                    and tagged_control_ready(rows, "rc-feed-refresh"))
        # This probe only views the Home feed; never mark a real item read.
        tree = self.observe()
        if not self.has(tree, "Activity Feed"):
            self.scroll_home(down=True)
            self.wait(ready)
            self.scroll_home(down=False)
        else:
            self.wait(ready)
        self.wait(lambda t: self.has(t, "Actualizaciones"))

    def scroll_home(self, *, down):
        tree = self.observe()
        require(self.has(tree, "Inicio") and any(r.get("description") == MENU for r in tree["elements"]),
                "home_screen_unconfirmed")
        w, h = self.dimensions
        x, top, bottom = w*2//3, h*3//10, h*8//10
        require(self.device.serial() == self.serial, "usb_identity_changed")
        self.device.adb(self.serial, "shell", "input", "swipe", x,
                        bottom if down else top, x, top if down else bottom, 450)
        self.pause(0.4)

    def run(self, candidate):
        checks = {}
        require(fresh_health(self.device, self.serial, pause=self.pause), "health_unverified")
        checks["health"] = "pass"
        home = self.navigate("Inicio", "Inicio")
        require(self.has(home, "Versión instalada: " + candidate.version_name), "home_version_unverified")
        checks["home"] = "pass"
        self.home_feed()
        checks["feed_view"] = "pass"
        self.tap("text", "Actualizaciones")
        updates = self.wait(lambda t: self.has(t, "Actualizaciones de la aplicación"))
        require(not self.has(updates, "Comprobar actualizaciones"), "legacy_update_control")
        checks["updates"] = "pass"
        self.navigate("Oportunidades", "Oportunidades · Odoo")
        self.wait(lambda t: self.has(t, "Copiar datos"))
        self.tap("text", "Copiar datos", first=True)
        dialog = self.wait(lambda t: self.has(t, "Cerrar"))
        copies = [r.get("description") for r in dialog["elements"]
                  if (r.get("description") or "").startswith("Copiar línea ")]
        require(sorted(copies) == ["Copiar línea "+str(i) for i in range(1,6)], "copy_controls_unverified")
        self.tap("text", "Cerrar")
        self.wait(lambda t: not self.has(t, "Cerrar") and self.has(t, "Oportunidades · Odoo"))
        checks["opportunities"] = "pass"
        self.navigate("Cotizaciones", "Cotizaciones · Odoo")
        import re
        self.wait(lambda t: any(re.fullmatch(r"S[0-9]{4,}", r.get("text") or "") for r in t["elements"]))
        checks["quotation_list"] = "pass"
        self.navigate("Deployments", "Deployments")
        controls = self.wait(lambda t: self.has(t, "Confirm deployment of all repositories") and self.has(t, "Deploy all"))
        verify_deployment_guard(controls)
        checks["deployment_controls_visible"] = "pass"
        self.navigate("Liturgia", "Lecturas, Biblia y búsqueda")
        self.wait(lambda t: self.has(t, "Esta edición solo tiene referencias disponibles para consulta remota.")
                  and any((r.get("text") or "").startswith("Cobertura: ") for r in t["elements"]))
        checks["liturgia_today"] = "pass"
        return checks


def identity(ledger, candidate):
    state = ledger.read(candidate.candidate_id)
    signed = state.get("signed", {})
    artifact = SignedArtifact(candidate, signed["apk_sha256"], signed["certificate_sha256"],
                              signed["artifact_id"], signed["run_id"])
    chain = ledger.consecutive_upgrade_health(candidate)
    require(chain is not None, "consecutive_upgrade_health_missing")
    return artifact


def validate_run(candidate, run_id, gate, *, completed, revision=None):
    require(type(run_id) is int and run_id > 0, "invalid_run_id")
    revision = revision or candidate.source_sha
    require(gate.api("branches/main")["commit"]["sha"] == revision, "candidate_superseded")
    require(gate.api(f"git/commits/{candidate.source_sha}")["tree"]["sha"] == candidate.source_tree,
            "source_tree_mismatch")
    run = gate.api(f"actions/runs/{run_id}")
    gate.verify_run_identity(run, WORKFLOW, run_id, "workflow_dispatch", revision)
    require(run.get("run_attempt") == 1 and (run.get("actor") or {}).get("login") == gate.OWNER
            and (run.get("triggering_actor") or {}).get("login") == gate.OWNER
            and run.get("status") == ("completed" if completed else "in_progress")
            and (not completed or run.get("conclusion") == "success"), "acceptance_run_unverified")


def verify_installed(artifact, evidence):
    require(evidence.get("package") == PACKAGE and evidence.get("version_code") == artifact.candidate.version_code
            and evidence.get("apk_sha256") == artifact.apk_sha256
            and evidence.get("certificate_sha256") == artifact.certificate_sha256, "installed_identity_mismatch")


def validate_smoke_receipt(receipt, artifact, run_id):
    expected = {"schema":1, "scope":"authenticated_smoke_v1", "status":"smoke_passed",
                "candidate_id":artifact.candidate.candidate_id, "source_sha":artifact.candidate.source_sha,
                "source_tree":artifact.candidate.source_tree, "version_code":artifact.candidate.version_code,
                "apk_sha256":artifact.apk_sha256, "certificate_sha256":artifact.certificate_sha256,
                "artifact_id":artifact.artifact_id, "run_id":run_id, "device":"gway-001",
                "checks":dict.fromkeys(SMOKE_CHECKS,"pass"), "installed_unchanged":True,
                "canary_unchanged":True, "screen_restored":True, "publication_admission":False}
    require(receipt == expected, "smoke_receipt_mismatch")
    return expected


def smoke_receipt(artifact, run_id, checks):
    return {"schema":1, "scope":"authenticated_smoke_v1", "status":"smoke_passed",
            "candidate_id":artifact.candidate.candidate_id, "source_sha":artifact.candidate.source_sha,
            "source_tree":artifact.candidate.source_tree, "version_code":artifact.candidate.version_code,
            "apk_sha256":artifact.apk_sha256, "certificate_sha256":artifact.certificate_sha256,
            "artifact_id":artifact.artifact_id, "run_id":run_id, "device":"gway-001",
            "checks":checks, "installed_unchanged":True, "canary_unchanged":True,
            "screen_restored":True, "publication_admission":False}


def execute_smoke(ledger, candidate, run_id, gate, *, revision=None):
    import socket
    from gway_remote.android_canary_certificate import installed_evidence
    from gway_remote.android_canary_install import CANARY
    from gway_remote.mcp_android import Device, _device_session
    from gway_remote.android_execution_contract import budget
    from gway_remote.android_rc_health import restore_sleep
    require(socket.gethostname().split(".")[0] == "gway-001", "wrong_device")
    validate_run(candidate, run_id, gate, completed=False, revision=revision)
    artifact = identity(ledger, candidate)
    with _device_session():
        device = Device()
        serial = device.serial()
        initial = device.screen_state(serial)
        require(initial.get("locked") is False and type(initial.get("screen_on")) is bool,
                "screen_not_safe")
        before = installed_evidence(PACKAGE)
        verify_installed(artifact, before)
        canary = installed_evidence(CANARY)
        try:
            with budget(seconds=570):
                device.wake_if_needed(serial=serial)
                checks = PhysicalSmoke(device, serial).run(candidate)
        finally:
            if initial["screen_on"] is False:
                require(restore_sleep(device, serial), "sleep_restore_unverified")
        require(device.serial() == serial and device.screen_state(serial).get("screen_on") == initial["screen_on"],
                "screen_restore_unverified")
        require(installed_evidence(PACKAGE) == before and installed_evidence(CANARY) == canary,
                "installed_identity_changed")
        validate_run(candidate, run_id, gate, completed=False, revision=revision)
        return validate_smoke_receipt(smoke_receipt(artifact, run_id, checks), artifact, run_id)



def full_receipt(artifact, run_id, smoke, hosted):
    """Combine verified physical observations and exact-source synthetic contracts.

    The receipt identifies both scopes; fixture failures cannot be waived by a
    successful physical smoke test, and hosted tests do not imply live writes.
    """
    from gway_remote.android_rc_contracts import GROUPS
    validate_smoke_receipt(smoke, artifact, run_id)
    require(set(hosted) == {"ci_run", "compose_run", "build_run",
                           "contract_artifact_id", "hosted_groups"}
            and all(type(hosted[k]) is int and hosted[k] > 0 for k in
                    ("ci_run", "compose_run", "build_run", "contract_artifact_id"))
            and len({hosted["ci_run"], hosted["compose_run"], hosted["build_run"], run_id}) == 4
            and hosted["hosted_groups"] == dict.fromkeys(GROUPS, "pass"),
            "hosted_contract_evidence_mismatch")
    checks = {**smoke["checks"], **hosted["hosted_groups"], "exact_source_ci_and_compose": "pass"}
    require(checks == dict.fromkeys(FULL_CHECKS, "pass"), "full_acceptance_checks_missing")
    return {**smoke, "scope":"authenticated_full_v1", "status":"passed", "checks":checks,
            "physical_checks":smoke["checks"], "hosted_evidence":hosted}


def execute_full(ledger, candidate, run_id, gate, *, ci_run, compose_run,
                 revision=None, revision_ci_run=None, backend_run=None):
    from gway_remote.android_rc_contracts import reconcile
    from gway_remote.android_release_candidate import compatible_revision
    compatibility = None
    if revision_ci_run is not None or backend_run is not None:
        compatibility = compatible_revision(candidate, revision, gate,
            revision_ci_run=revision_ci_run, backend_run=backend_run)
    else:
        require(revision in (None, candidate.source_sha), "compatible_evidence_missing")
    validate_run(candidate, run_id, gate, completed=False, revision=revision)
    artifact = identity(ledger, candidate)
    build_run = ledger.read(candidate.candidate_id)["built"]["run_id"]
    hosted = reconcile(gate, candidate, ci_run=ci_run, compose_run=compose_run, build_run=build_run)
    smoke = execute_smoke(ledger, candidate, run_id, gate, revision=revision)
    validate_run(candidate, run_id, gate, completed=False, revision=revision)
    result = full_receipt(artifact, run_id, smoke, hosted)
    if compatibility is not None:
        require(compatible_revision(candidate, revision, gate, revision_ci_run=revision_ci_run,
                    backend_run=backend_run) == compatibility, "backend_revision_moved")
        result["compatibility"] = compatibility
    return result


def reconcile_smoke(ledger, candidate, run_id, gate):
    import json
    import tempfile
    from pathlib import Path
    validate_run(candidate, run_id, gate, completed=True)
    artifact = identity(ledger, candidate)
    name = f"android-rc-smoke-{run_id}"
    listing = gate.api(f"actions/runs/{run_id}/artifacts?per_page=100")
    rows = listing["artifacts"]
    require(listing.get("total_count") == len(rows), "incomplete_artifact_listing")
    matches = [a for a in rows if a.get("name") == name]
    require(len(matches) == 1 and matches[0].get("expired") is False, "receipt_artifact_unavailable")
    meta = gate.api(f"actions/artifacts/{matches[0]['id']}")
    require(meta.get("name") == name and meta.get("expired") is False
            and (meta.get("workflow_run") or {}).get("id") == run_id
            and (meta.get("workflow_run") or {}).get("head_sha") == candidate.source_sha,
            "receipt_artifact_identity_mismatch")
    with tempfile.TemporaryDirectory() as tmp:
        gate.download(run_id, name, tmp)
        path = Path(tmp)/"receipt.json"
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 16384,
                "invalid_receipt_file")
        receipt = validate_smoke_receipt(json.loads(path.read_text()), artifact, run_id)
    validate_run(candidate, run_id, gate, completed=True)
    return receipt


def main():
    import argparse
    import json
    import os
    from pathlib import Path
    from gway_remote.android_release_candidate import Candidate, CandidateLedger
    from gway_remote import android_release_gate as gate
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--tree", required=True)
    p.add_argument("--version", type=int, required=True)
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--ci-run", type=int)
    p.add_argument("--compose-run", type=int)
    p.add_argument("--revision")
    p.add_argument("--revision-ci-run", type=int)
    p.add_argument("--backend-run", type=int)
    p.add_argument("mode", choices=("execute", "reconcile", "execute-full"))
    a = p.parse_args()
    require(a.ledger.is_absolute() and a.ledger.is_file() and not a.ledger.is_symlink()
            and a.ledger.stat().st_uid == os.getuid() and a.ledger.stat().st_mode & 0o077 == 0,
            "insecure_ledger_path")
    candidate = Candidate(a.sha, a.tree, a.version, f"0.2.{a.version}")
    ledger = CandidateLedger(a.ledger, read_only=True)
    try:
        if a.mode == "execute-full":
            result = execute_full(ledger, candidate, a.run_id, gate, ci_run=a.ci_run, compose_run=a.compose_run,
                                  revision=a.revision, revision_ci_run=a.revision_ci_run, backend_run=a.backend_run)
        else:
            require(all(v is None for v in (a.ci_run, a.compose_run, a.revision, a.revision_ci_run, a.backend_run)),
                    "unexpected_hosted_evidence")
            fn = execute_smoke if a.mode == "execute" else reconcile_smoke
            result = fn(ledger, candidate, a.run_id, gate)
        print(json.dumps(result, sort_keys=True))
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
