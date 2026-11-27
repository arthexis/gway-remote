"""Pure release candidate evidence validation. No signing or publication side effects."""
from dataclasses import dataclass, asdict
import hashlib
import json
import re

PACKAGE = "com.arthexis.gwayremote"
STAGES = ("allocated", "built", "signed", "installed", "accepted", "approved", "published")
HEX = re.compile(r"[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


@dataclass(frozen=True)
class Candidate:
    source_sha: str
    source_tree: str
    version_code: int
    version_name: str
    package: str = PACKAGE

    def __post_init__(self):
        require(all(isinstance(v, str) and SHA.fullmatch(v) for v in
                    (self.source_sha, self.source_tree)), "invalid_source")
        require(type(self.version_code) is int and 0 < self.version_code <= 2100000000,
                "invalid_version_code")
        require(isinstance(self.version_name, str) and
                self.version_name == f"0.2.{self.version_code}", "invalid_version_name")
        require(self.package == PACKAGE, "invalid_package")

    @property
    def candidate_id(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    def require_newer_than(self, published_version, installed_version):
        require(all(type(v) is int and v >= 0 for v in
                    (published_version, installed_version)), "unknown_version_floor")
        require(self.version_code > max(published_version, installed_version), "version_not_increasing")


@dataclass(frozen=True)
class SignedArtifact:
    candidate: Candidate
    apk_sha256: str
    certificate_sha256: str
    artifact_id: int
    signing_run_id: int

    def __post_init__(self):
        require(all(isinstance(v, str) and HEX.fullmatch(v) for v in
                    (self.apk_sha256, self.certificate_sha256)), "invalid_digest")
        require(all(type(v) is int and v > 0 for v in
                    (self.artifact_id, self.signing_run_id)), "invalid_artifact_identity")

    def validate_install(self, *, installed_digest, installed_certificate, installed_version,
                         device, credential_before, credential_after, expected_certificate):
        require(device == "gway-001", "wrong_device")
        require(expected_certificate == self.certificate_sha256 == installed_certificate,
                "certificate_mismatch")
        require(installed_digest == self.apk_sha256, "installed_digest_mismatch")
        require(type(installed_version) is int and installed_version == self.candidate.version_code,
                "installed_version_mismatch")
        require(credential_before is True and credential_after is True, "credential_not_preserved")

    def validate_promotion(self, *, accepted_digest, accepted_candidate_id, accepted_device,
                           approved, publication_hold, current_main, downloaded_digest):
        require(publication_hold is False, "publication_held")
        require(approved is True, "approval_required")
        require(accepted_device == "gway-001", "wrong_device")
        require(accepted_candidate_id == self.candidate.candidate_id, "candidate_mismatch")
        require(accepted_digest == self.apk_sha256 == downloaded_digest, "artifact_digest_mismatch")
        require(current_main == self.candidate.source_sha, "candidate_superseded")


class CandidateLedger:
    """Durable local storage primitive; evidence admission belongs to the coordinator.

    Each stage has immutable evidence. A replay with identical evidence is a no-op.
    No stage record alone confers signing, installation or publication authority.
    """
    def __init__(self, path, *, read_only=False):
        import sqlite3
        if read_only:
            from pathlib import Path
            self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro",
                                      uri=True, timeout=10, isolation_level=None)
            self.db.execute("PRAGMA query_only=ON")
            return
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS candidate (
                id TEXT PRIMARY KEY, version INTEGER NOT NULL UNIQUE, manifest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence (
                candidate_id TEXT NOT NULL REFERENCES candidate(id),
                stage TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(candidate_id,stage)
            );
            CREATE TABLE IF NOT EXISTS upgrade_health (
                candidate_id TEXT PRIMARY KEY REFERENCES candidate(id), payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dispatch_intent (
                candidate_id TEXT NOT NULL REFERENCES candidate(id),
                stage TEXT NOT NULL, inputs TEXT NOT NULL,
                run_id INTEGER UNIQUE,
                PRIMARY KEY(candidate_id,stage)
            );
        """)

    @staticmethod
    def encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def close(self):
        self.db.close()

    def allocate(self, candidate, *, published_version, installed_version):
        identifier = candidate.candidate_id
        manifest = self.encode(asdict(candidate))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute("SELECT manifest FROM candidate WHERE id=?", (identifier,)).fetchone()
            if prior:
                require(prior[0] == manifest, "allocation_conflict")
                self.db.commit()
                return False
            candidate.require_newer_than(published_version, installed_version)
            floor = self.db.execute("SELECT MAX(version) FROM candidate").fetchone()[0]
            require(floor is None or candidate.version_code > floor, "version_already_reserved")
            self.db.execute("INSERT INTO candidate VALUES (?,?,?)",
                            (identifier, candidate.version_code, manifest))
            self.db.execute("INSERT INTO evidence VALUES (?,?,?)",
                            (identifier, "allocated", manifest))
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def record(self, candidate_id, stage, evidence):
        require(stage in STAGES[1:] and isinstance(evidence, dict) and bool(evidence),
                "invalid_stage_evidence")
        payload = self.encode(evidence)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute("SELECT payload FROM evidence WHERE candidate_id=? AND stage=?",
                                    (candidate_id, stage)).fetchone()
            if prior:
                require(prior[0] == payload, "immutable_evidence_conflict")
                self.db.commit()
                return False
            predecessor = STAGES[STAGES.index(stage)-1]
            require(self.db.execute("SELECT 1 FROM evidence WHERE candidate_id=? AND stage=?",
                                    (candidate_id, predecessor)).fetchone() is not None,
                    "previous_stage_missing")
            self.db.execute("INSERT INTO evidence VALUES (?,?,?)", (candidate_id, stage, payload))
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def read(self, candidate_id):
        return {stage: json.loads(payload) for stage, payload in self.db.execute(
            "SELECT stage,payload FROM evidence WHERE candidate_id=?", (candidate_id,))}


    def read_upgrade_health(self, candidate_id):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='upgrade_health'").fetchone():
            return None
        row = self.db.execute("SELECT payload FROM upgrade_health WHERE candidate_id=?", (candidate_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def record_upgrade_health(self, candidate, *, run_id, post_authenticated):
        """Record credential preservation, NOT full module acceptance."""
        require(type(run_id) is int and run_id > 0 and post_authenticated is True,
                "post_install_authentication_failed")
        state = self.read(candidate.candidate_id)
        installed, signed = state.get("installed", {}), state.get("signed", {})
        require(state.get("allocated") == asdict(candidate)
                and installed.get("candidate_id") == candidate.candidate_id
                and installed.get("artifact_id") == signed.get("artifact_id")
                and installed.get("apk_sha256") == signed.get("apk_sha256")
                and installed.get("certificate_sha256") == signed.get("certificate_sha256")
                and installed.get("operation") == "incremental_update"
                and installed.get("credential_before") is True
                and installed.get("canary_path_unchanged") is True
                and installed.get("device") == "gway-001"
                and installed.get("install_run_id") == run_id, "upgrade_baseline_unverified")
        before, after = installed.get("installed_before", {}), installed.get("installed_after", {})
        artifact = SignedArtifact(candidate, signed["apk_sha256"], signed["certificate_sha256"],
                                  signed["artifact_id"], signed["run_id"])
        artifact.validate_install(installed_digest=after.get("apk_sha256"),
                                  installed_certificate=after.get("certificate_sha256"),
                                  installed_version=after.get("version_code"), device="gway-001",
                                  credential_before=True, credential_after=True,
                                  expected_certificate=before.get("certificate_sha256"))
        require(before.get("package") == after.get("package") == PACKAGE
                and type(before.get("version_code")) is int
                and before["version_code"] < candidate.version_code
                and isinstance(before.get("apk_sha256"), str)
                and HEX.fullmatch(before["apk_sha256"]), "upgrade_baseline_unverified")
        evidence = {"candidate_id": candidate.candidate_id, "run_id": run_id,
                    "from_version": before["version_code"], "to_version": candidate.version_code,
                    "from_sha256": before["apk_sha256"], "to_sha256": artifact.apk_sha256,
                    "certificate_sha256": artifact.certificate_sha256,
                    "device": "gway-001", "authenticated_before": True, "authenticated_after": True}
        payload = self.encode(evidence)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.read_upgrade_health(candidate.candidate_id)
            if previous is not None:
                require(previous == evidence, "immutable_upgrade_health_conflict")
            else:
                self.db.execute("INSERT INTO upgrade_health VALUES (?,?)", (candidate.candidate_id, payload))
            self.db.commit()
            return evidence
        except BaseException:
            self.db.rollback()
            raise

    def claim_dispatch(self, candidate_id, stage, inputs):
        """Reserve before network mutation; an uncertain intent is never replayed."""
        require(stage in ("built", "signed", "installed"), "unsupported_dispatch_stage")
        payload = self.encode(inputs)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute("SELECT inputs,run_id FROM dispatch_intent WHERE candidate_id=? AND stage=?",
                                    (candidate_id, stage)).fetchone()
            if prior:
                require(prior[0] == payload, "dispatch_input_conflict")
                self.db.commit()
                return False, prior[1]
            predecessor = STAGES[STAGES.index(stage)-1]
            require(self.db.execute("SELECT 1 FROM evidence WHERE candidate_id=? AND stage=?",
                                    (candidate_id, predecessor)).fetchone() is not None,
                    "previous_stage_missing")
            self.db.execute("INSERT INTO dispatch_intent VALUES (?,?,?,NULL)",
                            (candidate_id,stage,payload))
            self.db.commit()
            return True, None
        except BaseException:
            self.db.rollback()
            raise

    def bind_dispatch(self, candidate_id, stage, run_id):
        require(type(run_id) is int and run_id > 0, "invalid_run_id")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT run_id FROM dispatch_intent WHERE candidate_id=? AND stage=?",
                                  (candidate_id,stage)).fetchone()
            require(row is not None, "dispatch_intent_missing")
            require(row[0] is None or row[0] == run_id, "dispatch_run_conflict")
            self.db.execute("UPDATE dispatch_intent SET run_id=? WHERE candidate_id=? AND stage=?",
                            (run_id,candidate_id,stage))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise


DELIVERY_FIX_PATHS = frozenset({
    ".github/workflows/android-release-candidate-sign.yml",
    "gway_remote/android_release_candidate.py",
    "gway_remote/android_release_gate.py",
    "tests/infrastructure/test_android_release_candidate.py",
    "tests/mobile/test_android_release_gate.py",
    "docs/android-single-release-candidate.md",
})


def validate_signing_revision(candidate, workflow_sha, gate):
    """Keep immutable build identity; permit only explicitly reviewed delivery fixes."""
    require(isinstance(workflow_sha, str) and SHA.fullmatch(workflow_sha), "invalid_workflow_revision")
    if workflow_sha == candidate.source_sha:
        return
    comparison = gate.api(f"compare/{candidate.source_sha}...{workflow_sha}")
    files = comparison.get("files", [])
    require(comparison.get("status") == "ahead"
            and (comparison.get("merge_base_commit") or {}).get("sha") == candidate.source_sha
            and type(comparison.get("total_commits")) is int
            and 0 < comparison["total_commits"] <= 30 and 0 < len(files) < 300
            and all(f.get("status") in ("added", "modified")
                    and f.get("filename") in DELIVERY_FIX_PATHS for f in files),
            "candidate_superseded")
    def android_tree(sha):
        rows = gate.api(f"git/trees/{sha}").get("tree", [])
        matches = [r["sha"] for r in rows if r.get("path") == "android" and r.get("type") == "tree"]
        require(len(matches) == 1 and SHA.fullmatch(matches[0]), "android_tree_unverified")
        return matches[0]
    require(android_tree(candidate.source_sha) == android_tree(workflow_sha), "android_tree_changed")


def dispatch_candidate(ledger, candidate, stage, *, artifact_id=None, build_run_id=None,
                       workflow_sha=None, gate=None):
    """Owner-side coordinator adapter. Resume only the exact recorded run.

    This is not a publication or device operation. Signing remains subject to
    the independently configured protected environment and artifact approvals.
    """
    if gate is None:
        from gway_remote import android_release_gate as gate
    state = ledger.read(candidate.candidate_id)
    require(state.get("allocated") == asdict(candidate), "candidate_not_allocated")
    workflow_sha = candidate.source_sha if workflow_sha is None else workflow_sha
    require(gate.api("branches/main")["commit"]["sha"] == workflow_sha, "candidate_superseded")
    if stage == "built":
        require(workflow_sha == candidate.source_sha, "build_revision_mismatch")
        workflow = "android-release-candidate.yml"
        inputs = {"expected_sha": candidate.source_sha, "version_code": str(candidate.version_code)}
    elif stage == "signed":
        require(all(type(v) is int and v > 0 for v in (artifact_id, build_run_id)),
                "invalid_build_artifact")
        built = state.get("built", {})
        require(built.get("artifact_id") == artifact_id and built.get("run_id") == build_run_id,
                "build_evidence_mismatch")
        validate_signing_revision(candidate, workflow_sha, gate)
        workflow = "android-release-candidate-sign.yml"
        inputs = {"expected_sha": candidate.source_sha, "build_run_id": str(build_run_id),
                  "artifact_id": str(artifact_id), "workflow_sha": workflow_sha}
    else:
        raise ValueError("unsupported_dispatch_stage")
    new, run_id = ledger.claim_dispatch(candidate.candidate_id, stage, inputs)
    if new:
        run_id = gate.create_run(workflow, **inputs)
        ledger.bind_dispatch(candidate.candidate_id, stage, run_id)
    require(run_id is not None, "dispatch_uncertain_reconcile_before_retry")
    gate.await_dispatch_visibility(workflow, run_id, workflow_sha)
    return run_id


def plan_lab_install(artifact, *, installed, pinned_certificate, device, lab_authorized,
                     credential_present, screen_unlocked, allow_unverified_auth=False):
    """Pure fail-closed decision. Never authorizes reset, first install or downgrade."""
    require(device == "gway-001" and lab_authorized is True, "lab_not_authorized")
    require(screen_unlocked is True, "device_locked_or_unknown")
    require(credential_present is True or allow_unverified_auth is True, "credential_missing_or_unverified")
    require(isinstance(installed, dict) and installed.get("package") == PACKAGE,
            "stable_package_missing")
    require(isinstance(pinned_certificate, str) and HEX.fullmatch(pinned_certificate)
            and installed.get("certificate_sha256") == pinned_certificate == artifact.certificate_sha256,
            "certificate_mismatch")
    digest = installed.get("apk_sha256")
    version = installed.get("version_code")
    require(isinstance(digest, str) and HEX.fullmatch(digest) and type(version) is int and version > 0,
            "installed_identity_unknown")
    if digest == artifact.apk_sha256:
        require(version == artifact.candidate.version_code, "installed_version_mismatch")
        return "verify_noop"
    require(version < artifact.candidate.version_code, "version_not_increasing")
    return "incremental_update"


def plan_promotion(artifact, *, existing_release, **acceptance):
    """No network side effects. Existing exact release is a verification-only replay."""
    artifact.validate_promotion(**acceptance)
    if existing_release is None:
        return "create_exact_release"
    require(isinstance(existing_release, dict)
            and existing_release.get("source_sha") == artifact.candidate.source_sha
            and existing_release.get("tag") == f"android-v{artifact.candidate.version_name}"
            and existing_release.get("apk_sha256") == artifact.apk_sha256
            and existing_release.get("certificate_sha256") == artifact.certificate_sha256,
            "existing_release_conflict")
    return "verify_noop"


def reconcile_artifact(ledger, candidate, stage, *, pinned_certificate=None, artifact_dir=None, gate=None):
    """Accept only the exact successful, owner-dispatched workflow and its artifact."""
    import tempfile
    from pathlib import Path
    if gate is None:
        from gway_remote import android_release_gate as gate
    require(stage in ("built", "signed"), "unsupported_reconciliation_stage")
    state = ledger.read(candidate.candidate_id)
    require(state.get("allocated") == asdict(candidate), "candidate_not_allocated")
    row = ledger.db.execute("SELECT run_id, inputs FROM dispatch_intent WHERE candidate_id=? AND stage=?",
                            (candidate.candidate_id, stage)).fetchone()
    require(row is not None and type(row[0]) is int and row[0] > 0,
            "dispatch_uncertain_reconcile_before_retry")
    run_id = row[0]
    workflow = ("android-release-candidate.yml" if stage == "built"
                else "android-release-candidate-sign.yml")
    intent = json.loads(row[1])
    workflow_sha = candidate.source_sha if stage == "built" else intent.get("workflow_sha")
    require(isinstance(workflow_sha,str) and SHA.fullmatch(workflow_sha), "missing_signing_workflow_revision")
    if stage == "signed":
        validate_signing_revision(candidate, workflow_sha, gate)
    run = gate.wait_run(workflow, run_id, "workflow_dispatch", workflow_sha)
    require((run.get("actor") or {}).get("login") == gate.OWNER
            and (run.get("triggering_actor") or {}).get("login") == gate.OWNER,
            "unexpected_run_actor")
    name = ("unsigned" if stage == "built" else "signed") + f"-release-candidate-{run_id}"
    listing = gate.api(f"actions/runs/{run_id}/artifacts?per_page=100")
    matches = [a for a in listing["artifacts"] if a.get("name") == name]
    require(len(matches) == 1 and matches[0].get("expired") is False
            and type(matches[0].get("id")) is int and matches[0]["id"] > 0,
            "artifact_missing_or_expired")
    require(listing.get("total_count") == len(listing["artifacts"]), "incomplete_artifact_listing")
    artifact_id = matches[0]["id"]
    with tempfile.TemporaryDirectory() as directory:
        gate.download(run_id, name, directory)
        root = Path(directory)
        file = root / ("gway-remote-unsigned.apk" if stage == "built" else "gway-remote.apk")
        manifest_path = root / "manifest.json"
        require(file.is_file() and not file.is_symlink() and 0 < file.stat().st_size < 104857600
                and manifest_path.is_file() and not manifest_path.is_symlink()
                and manifest_path.stat().st_size < 65536, "invalid_artifact_files")
        manifest = json.loads(manifest_path.read_text())
        require(all(manifest.get(k) == v for k,v in asdict(candidate).items())
                and manifest.get("repository") == gate.REPO, "candidate_manifest_mismatch")
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if stage == "signed":
            require(manifest.get("signing_workflow_sha") == workflow_sha, "signing_workflow_mismatch")
            require(not (root / "gway-remote.apk.cms").exists(), "unexpected_encrypted_artifact")
        if stage == "built":
            require(manifest.get("build_run_id") == run_id
                    and manifest.get("unsigned_sha256") == digest, "unsigned_evidence_mismatch")
            evidence = {"run_id":run_id, "artifact_id":artifact_id, "unsigned_sha256":digest}
        else:
            from gway_remote.android_canary_certificate import certificate_sha256
            built = state.get("built", {})
            require(manifest.get("build_run_id") == built.get("run_id")
                    and manifest.get("unsigned_artifact_id") == built.get("artifact_id")
                    and manifest.get("unsigned_sha256") == built.get("unsigned_sha256")
                    and manifest.get("signing_run_id") == run_id
                    and manifest.get("apk_sha256") == digest, "signed_evidence_mismatch")
            require(isinstance(pinned_certificate,str) and HEX.fullmatch(pinned_certificate)
                    and manifest.get("certificate_sha256") == pinned_certificate
                    and certificate_sha256(file) == pinned_certificate, "certificate_mismatch")
            persist_private_apk(file, artifact_dir, candidate.candidate_id, digest)
            evidence = {"run_id":run_id, "artifact_id":artifact_id, "apk_sha256":digest,
                        "certificate_sha256":pinned_certificate, "workflow_sha":workflow_sha}
    ledger.record(candidate.candidate_id, stage, evidence)
    return evidence


def _private_artifact_dir(path):
    import os
    from pathlib import Path
    require(path is not None, "artifact_directory_required")
    path = Path(path)
    require(path.is_absolute() and path.is_dir() and not path.is_symlink()
            and path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o077 == 0,
            "insecure_artifact_directory")
    return path


def persist_private_apk(file, artifact_dir, candidate_id, digest):
    import os
    import tempfile
    directory = _private_artifact_dir(artifact_dir)
    require(isinstance(candidate_id,str) and HEX.fullmatch(candidate_id), "invalid_candidate_id")
    path = directory / f"{candidate_id}.apk"
    require(hashlib.sha256(file.read_bytes()).hexdigest() == digest, "private_artifact_digest_mismatch")
    fd, name = tempfile.mkstemp(prefix=".rc-", dir=directory)
    try:
        with os.fdopen(fd,"wb") as output:
            output.write(file.read_bytes())
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(name,path,follow_symlinks=False)
        except FileExistsError:
            require(path.is_file() and not path.is_symlink() and path.stat().st_uid == os.getuid()
                    and path.stat().st_mode & 0o077 == 0 and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                    "private_artifact_conflict")
        dirfd = os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        os.unlink(name)


INSTALL_WORKFLOW = "android-release-candidate-install.yml"
INSTALL_FIX_PATHS = DELIVERY_FIX_PATHS | frozenset({
    ".github/workflows/" + INSTALL_WORKFLOW,
    "gway_remote/deploy_impact.py",
    "tests/deployment/test_deploy_impact.py",
})


def validate_install_revision(candidate, revision, gate):
    """Verify the reviewed delivery-only revision, not arbitrary new app code."""
    require(isinstance(revision,str) and SHA.fullmatch(revision), "invalid_workflow_revision")
    require(gate.api("branches/main")["commit"]["sha"] == revision, "candidate_superseded")
    if revision == candidate.source_sha:
        require(gate.api(f"git/commits/{revision}")["tree"]["sha"] == candidate.source_tree,
                "source_tree_mismatch")
        return
    comparison = gate.api(f"compare/{candidate.source_sha}...{revision}")
    files = comparison.get("files", [])
    require(comparison.get("status") == "ahead"
            and (comparison.get("merge_base_commit") or {}).get("sha") == candidate.source_sha
            and type(comparison.get("total_commits")) is int
            and 0 < comparison["total_commits"] <= 60 and 0 < len(files) < 300
            and all(f.get("status") in ("added","modified") and f.get("filename") in INSTALL_FIX_PATHS for f in files),
            "candidate_superseded")
    for pair in (("android","tree"),):
        def subtree(sha):
            matches = [r.get("sha") for r in gate.api(f"git/trees/{sha}")["tree"]
                       if (r.get("path"),r.get("type")) == pair]
            require(len(matches) == 1 and isinstance(matches[0],str) and SHA.fullmatch(matches[0]),
                    "android_tree_unverified")
            return matches[0]
        require(subtree(candidate.source_sha) == subtree(revision), "android_tree_changed")


def health_is_authenticated(tree):
    """Only a visible exact health response counts, never a stored token or UI label."""
    if not isinstance(tree,dict) or tree.get("truncated") is not False:
        return False
    elements = tree.get("elements", [])
    if not any(e.get("text") == "API health" for e in elements):
        return False
    texts = [e.get("text","") for e in elements if isinstance(e.get("text"),str)]
    if any(t in ("Token is required","Unauthorized: check your token","Access denied","Connection failed")
           for t in texts):
        return False
    # The stable Compose GenericResultRenderer displays separate key/value
    # rows, not the JSON string used by older fixtures. Reject conflicting
    # result rows; do not mistake the API Health tab label for a response.
    statuses = [t for t in texts if t.startswith("status:")]
    apis = [t for t in texts if t.startswith("api:")]
    if statuses or apis:
        return statuses == ["status: ok"] and apis == ["api: gway-remote/v1"]
    for text in texts:
        try:
            value = json.loads(text)
        except (ValueError,TypeError):
            continue
        if value == {"status":"ok","api":"gway-remote/v1"}:
            return True
    return False


def install_stable_candidate(ledger, candidate, *, artifact_dir, workflow_sha, install_run_id,
                             expected_digest, expected_certificate, expected_artifact_id,
                             preflight_only=False, allow_unverified_auth=False, gate=None, call=None, device=None,
                             inspect=None, hostname=None, fresh_check=None):
    """Reviewed hardware workflow only. No credential reads, reset or publication."""
    import socket
    from gway_remote import android_canary_install as usb
    from gway_remote.android_canary_certificate import installed_evidence, certificate_sha256
    from gway_remote.mcp_android import Device
    if gate is None:
        from gway_remote import android_release_gate as gate
    call = call or usb.run_command
    inspect = inspect or installed_evidence
    device = device or Device()
    require((hostname or socket.gethostname()).split(".")[0] == "gway-001", "wrong_device")
    validate_install_revision(candidate, workflow_sha, gate)
    run = gate.api(f"actions/runs/{install_run_id}")
    require(run.get("id") == install_run_id and run.get("path") == ".github/workflows/"+INSTALL_WORKFLOW
            and run.get("event") == "workflow_dispatch" and run.get("head_sha") == workflow_sha
            and run.get("head_branch") == "main" and run.get("status") == "in_progress"
            and run.get("run_attempt") == 1 and (run.get("actor") or {}).get("login") == gate.OWNER
            and (run.get("triggering_actor") or {}).get("login") == gate.OWNER,
            "install_run_identity_mismatch")
    if allow_unverified_auth is True:
        require(not preflight_only and run.get("display_title") ==
                f"Android RC install-lab-only version {candidate.version_code} artifact {expected_artifact_id}",
                "lab_only_authorization_mismatch")
    state = ledger.read(candidate.candidate_id)
    require(state.get("allocated") == asdict(candidate), "candidate_not_allocated")
    signed = state.get("signed", {})
    require(signed.get("artifact_id") == expected_artifact_id
            and signed.get("apk_sha256") == expected_digest
            and signed.get("certificate_sha256") == expected_certificate, "signed_evidence_mismatch")
    artifact = SignedArtifact(candidate,expected_digest,expected_certificate,
                              expected_artifact_id,signed.get("run_id"))
    validate_signing_revision(candidate,signed.get("workflow_sha"),gate)
    sign_run = gate.api(f"actions/runs/{artifact.signing_run_id}")
    require(sign_run.get("conclusion") == "success" and sign_run.get("run_attempt") == 1
            and sign_run.get("path") == ".github/workflows/android-release-candidate-sign.yml"
            and sign_run.get("head_sha") == signed["workflow_sha"]
            and sign_run.get("event") == "workflow_dispatch" and sign_run.get("head_branch") == "main"
            and (sign_run.get("actor") or {}).get("login") == gate.OWNER
            and (sign_run.get("triggering_actor") or {}).get("login") == gate.OWNER,
            "signing_run_mismatch")
    meta = gate.api(f"actions/artifacts/{artifact.artifact_id}")
    require(meta.get("expired") is False and meta.get("name") == f"signed-release-candidate-{artifact.signing_run_id}"
            and (meta.get("workflow_run") or {}).get("id") == artifact.signing_run_id
            and (meta.get("workflow_run") or {}).get("head_sha") == signed["workflow_sha"],
            "signed_artifact_unavailable")
    apk = _private_artifact_dir(artifact_dir) / f"{candidate.candidate_id}.apk"
    import os
    require(apk.is_file() and not apk.is_symlink() and apk.stat().st_uid == os.getuid()
            and apk.stat().st_mode & 0o077 == 0 and 10000 < apk.stat().st_size < 104857600,
            "invalid_local_candidate")
    require(hashlib.sha256(apk.read_bytes()).hexdigest() == artifact.apk_sha256
            and certificate_sha256(apk) == artifact.certificate_sha256, "local_candidate_mismatch")
    serial = usb.authorized_usb(call)
    if fresh_check is not None:
        device.wake_if_needed(serial=serial)
    screen = device.screen_state(serial)
    require(screen.get("screen_on") is True and screen.get("locked") is False, "device_locked_or_unknown")
    before = inspect(usb.PRODUCTION,call=call)
    require(before.get("package") == PACKAGE and before.get("certificate_sha256") == expected_certificate,
            "installed_signer_mismatch")
    require(type(before.get("version_code")) is int and before["version_code"] <= candidate.version_code,
            "version_not_increasing")
    # Authentication is observed independently; never infer success from authorization to install.
    authenticated = fresh_check(device, serial) if fresh_check else health_is_authenticated(device.ui_tree(serial))
    require(isinstance(before.get("apk_sha256"),str) and HEX.fullmatch(before["apk_sha256"]),
            "installed_identity_unknown")
    require(before["version_code"] < candidate.version_code or before["apk_sha256"] == artifact.apk_sha256,
            "version_not_increasing")
    receipt = {"candidate_id":candidate.candidate_id,"device":"gway-001",
               "artifact_id":artifact.artifact_id,"apk_sha256":artifact.apk_sha256,
               "certificate_sha256":artifact.certificate_sha256,"installed_before":before,
               "credential_before":authenticated,
               "authenticated_acceptance":"pending",
               "installation_without_verified_auth":not authenticated and allow_unverified_auth is True}
    if preflight_only:
        return {**receipt,"status":"ready" if authenticated or allow_unverified_auth is True else "blocked",
                "reason":None if authenticated or allow_unverified_auth is True else "credential_missing_or_unverified"}
    action = plan_lab_install(artifact,installed=before,pinned_certificate=expected_certificate,
                              device="gway-001",lab_authorized=True,
                              credential_present=authenticated,screen_unlocked=True,
                              allow_unverified_auth=allow_unverified_auth)
    prior = state.get("installed")
    if prior is not None:
        require(action == "verify_noop" and prior.get("installed_after") == before,
                "installed_evidence_conflict")
        if fresh_check is not None and not allow_unverified_auth:
            health = ledger.read_upgrade_health(candidate.candidate_id)
            require(health is not None and authenticated, "upgrade_health_unverified_reconcile")
            return {**prior, "upgrade_health": health}
        return prior
    require(action == "incremental_update", "install_uncertain_reconcile_before_retry")
    canary_before = usb.require_success(call(["/usr/bin/adb","-s",serial,"shell","pm","path",usb.CANARY],30),
                                         "canary_path_unverified")
    require(canary_before.startswith("package:"), "canary_path_unverified")
    # Persist the install intent BEFORE ADB. Unknown outcomes are never replayed.
    inputs = {"workflow_sha":workflow_sha,"artifact_id":artifact.artifact_id,
              "apk_sha256":artifact.apk_sha256}
    new, recorded_run = ledger.claim_dispatch(candidate.candidate_id,"installed",inputs)
    require(new and recorded_run is None, "install_uncertain_reconcile_before_retry")
    ledger.bind_dispatch(candidate.candidate_id,"installed",install_run_id)
    require(gate.api("branches/main")["commit"]["sha"] == workflow_sha, "candidate_superseded")
    require(usb.authorized_usb(call) == serial, "usb_identity_changed")
    result = call(["/usr/bin/adb","-s",serial,"install","-r",str(apk)],100)
    require(usb.adb_install_succeeded(result), "stable_install_unconfirmed_no_reset")
    require(usb.authorized_usb(call) == serial, "usb_identity_changed")
    after = inspect(usb.PRODUCTION,call=call)
    require(after.get("package") == PACKAGE and after.get("apk_sha256") == artifact.apk_sha256
            and after.get("certificate_sha256") == artifact.certificate_sha256
            and after.get("version_code") == candidate.version_code, "post_install_identity_mismatch")
    canary_after = usb.require_success(call(["/usr/bin/adb","-s",serial,"shell","pm","path",usb.CANARY],30),
                                        "canary_path_unverified")
    require(canary_before == canary_after, "canary_path_changed")
    # This is physical installation evidence, not authenticated module acceptance.
    receipt = {**receipt,"status":"installed","installed_after":after,
               "install_run_id":recorded_run or install_run_id,"operation":action,"canary_path_unchanged":True}
    ledger.record(candidate.candidate_id,"installed",receipt)
    if fresh_check is not None and authenticated:
        try:
            require(usb.authorized_usb(call) == serial, "usb_identity_changed")
            post = fresh_check(device, serial)
            require(usb.authorized_usb(call) == serial, "usb_identity_changed")
            health = ledger.record_upgrade_health(candidate, run_id=install_run_id, post_authenticated=post)
        except (ValueError, RuntimeError, OSError):
            return {**receipt, "status": "blocked", "reason": "post_install_authentication_unverified"}
        return {**receipt, "upgrade_health": health}
    return receipt


def reconciliation_status(ledger, candidate, *, artifact_dir, gate):
    """Read-only checkpoint, not admission for installation or publication."""
    import base64
    import os
    state = ledger.read(candidate.candidate_id)
    require(state.get("allocated") == asdict(candidate), "candidate_not_allocated")
    main_sha = gate.api("branches/main")["commit"]["sha"]
    require(isinstance(main_sha, str) and SHA.fullmatch(main_sha), "invalid_main_revision")
    workflow = gate.api(f"contents/.github/workflows/android.yml?ref={main_sha}")
    require(workflow.get("encoding") == "base64", "publication_policy_unknown")
    source = base64.b64decode(workflow["content"], validate=False).decode("utf-8")
    held = "ANDROID_PUBLICATION_HOLD_718" in source
    signed = state.get("signed")
    verified = False
    blockers = []
    if signed:
        artifact = SignedArtifact(candidate, signed["apk_sha256"], signed["certificate_sha256"],
                                  signed["artifact_id"], signed["run_id"])
        apk = _private_artifact_dir(artifact_dir) / f"{candidate.candidate_id}.apk"
        if (apk.is_file() and not apk.is_symlink() and apk.stat().st_uid == os.getuid()
                and apk.stat().st_mode & 0o077 == 0 and 10000 < apk.stat().st_size < 104857600):
            from gway_remote.android_canary_certificate import certificate_sha256
            verified = (hashlib.sha256(apk.read_bytes()).hexdigest() == artifact.apk_sha256
                        and certificate_sha256(apk) == artifact.certificate_sha256)
    if not verified:
        blockers.append("signed_artifact_unverified")
    if main_sha != candidate.source_sha:
        blockers.append("candidate_superseded")
    if "installed" not in state:
        blockers.append("installation_missing")
    elif state["installed"].get("credential_before") is not True:
        blockers.append("authenticated_upgrade_baseline_missing")
    if "accepted" not in state:
        blockers.append("authenticated_acceptance_missing")
    if "approved" not in state:
        blockers.append("publication_approval_missing")
    if held:
        blockers.append("publication_held")
    return {"candidate_id": candidate.candidate_id, "version_code": candidate.version_code,
            "source_sha": candidate.source_sha, "current_main": main_sha,
            "recorded_stages": [stage for stage in STAGES if stage in state],
            "upgrade_health": ledger.read_upgrade_health(candidate.candidate_id),
            "local_signed_artifact_verified": verified, "publication_hold": held,
            "blockers": blockers, "admission": False}


def main(argv=None):
    """Owner-side entrypoint for the pre-install candidate stages only."""
    import argparse
    from pathlib import Path
    import os
    from gway_remote import android_release_gate as gate
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--version", type=int, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    allocate = sub.add_parser("allocate")
    allocate.add_argument("--published-version", type=int, required=True)
    allocate.add_argument("--installed-version", type=int, required=True)
    for action in ("dispatch", "reconcile"):
        command = sub.add_parser(action)
        command.add_argument("stage", choices=("built", "signed"))
        if action == "reconcile":
            command.add_argument("--certificate")
            command.add_argument("--artifact-dir", type=Path)
        else:
            command.add_argument("--workflow-sha")
    sub.add_parser("status")
    checkpoint = sub.add_parser("reconciliation-status")
    checkpoint.add_argument("--artifact-dir", type=Path, required=True)
    lab = sub.add_parser("lab-install")
    lab.add_argument("--artifact-dir", type=Path, required=True)
    lab.add_argument("--workflow-sha", required=True)
    lab.add_argument("--run-id", type=int, required=True)
    lab.add_argument("--artifact-id", type=int, required=True)
    lab.add_argument("--digest", required=True)
    lab.add_argument("--certificate", required=True)
    lab.add_argument("--preflight-only", action="store_true")
    lab.add_argument("--allow-unverified-auth", action="store_true")
    args = parser.parse_args(argv)
    candidate = Candidate(args.sha, args.tree, args.version, f"0.2.{args.version}")
    os.umask(0o077)
    path = args.ledger
    require(path.is_absolute() and path.parent.is_dir() and not path.is_symlink(),
            "invalid_ledger_path")
    require(not path.exists() or (path.is_file() and path.stat().st_mode & 0o077 == 0
                                  and path.stat().st_uid == os.getuid()), "insecure_ledger_path")
    if args.action == "reconciliation-status":
        require(path.is_file(), "candidate_ledger_missing")
    ledger = CandidateLedger(path, read_only=args.action == "reconciliation-status")
    try:
        if args.action == "allocate":
            require(gate.api("branches/main")["commit"]["sha"] == candidate.source_sha,
                    "candidate_superseded")
            require(gate.api(f"git/commits/{candidate.source_sha}")["tree"]["sha"] == candidate.source_tree,
                    "source_tree_mismatch")
            result = {"candidate_id":candidate.candidate_id,
                      "allocated":ledger.allocate(candidate,published_version=args.published_version,
                                                   installed_version=args.installed_version)}
        elif args.action == "dispatch":
            # Only an existing local reservation can request a run.
            built = ledger.read(candidate.candidate_id).get("built", {})
            result = {"run_id":dispatch_candidate(ledger,candidate,args.stage,
                       artifact_id=built.get("artifact_id"),build_run_id=built.get("run_id"),workflow_sha=args.workflow_sha)}
        elif args.action == "reconcile":
            result = reconcile_artifact(ledger,candidate,args.stage,pinned_certificate=args.certificate,artifact_dir=args.artifact_dir)
        elif args.action == "lab-install":
            from gway_remote.mcp_android import Device, _device_session
            from gway_remote.android_rc_health import fresh_health
            from gway_remote.android_execution_contract import budget
            with _device_session():
                device = Device()
                serial = device.serial()
                initial = device.screen_state(serial)
                automatic = not args.preflight_only and not args.allow_unverified_auth
                try:
                    with budget(seconds=390):
                        result = install_stable_candidate(ledger,candidate,artifact_dir=args.artifact_dir,
                                   workflow_sha=args.workflow_sha,install_run_id=args.run_id,
                                   expected_artifact_id=args.artifact_id,expected_digest=args.digest,
                                   expected_certificate=args.certificate,preflight_only=args.preflight_only,
                                   allow_unverified_auth=args.allow_unverified_auth,device=device,
                                   fresh_check=fresh_health if automatic else None)
                finally:
                    if automatic and initial.get("screen_on") is False:
                        require(device.serial() == serial, "usb_identity_changed")
                        final = device.screen_state(serial)
                        if final.get("screen_on") is True and final.get("locked") is False:
                            device.invoke("key", {"key":"SLEEP"})
                        require(device.screen_state(serial).get("screen_on") is False,
                                "sleep_restore_unverified")
        elif args.action == "reconciliation-status":
            result = reconciliation_status(ledger, candidate, artifact_dir=args.artifact_dir, gate=gate)
        else:
            result = {"candidate_id":candidate.candidate_id,"evidence":ledger.read(candidate.candidate_id)}
        print(json.dumps(result,sort_keys=True))
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
