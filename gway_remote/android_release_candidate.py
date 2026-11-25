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
    def __init__(self, path):
        import sqlite3
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


    def claim_dispatch(self, candidate_id, stage, inputs):
        """Reserve before network mutation; an uncertain intent is never replayed."""
        require(stage in ("built", "signed"), "unsupported_dispatch_stage")
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


def dispatch_candidate(ledger, candidate, stage, *, artifact_id=None, build_run_id=None,
                       gate=None):
    """Owner-side coordinator adapter. Resume only the exact recorded run.

    This is not a publication or device operation. Signing remains subject to
    the independently configured protected environment and artifact approvals.
    """
    if gate is None:
        from gway_remote import android_release_gate as gate
    state = ledger.read(candidate.candidate_id)
    require(state.get("allocated") == asdict(candidate), "candidate_not_allocated")
    require(gate.api("branches/main")["commit"]["sha"] == candidate.source_sha,
            "candidate_superseded")
    if stage == "built":
        workflow = "android-release-candidate.yml"
        inputs = {"expected_sha": candidate.source_sha, "version_code": str(candidate.version_code)}
    elif stage == "signed":
        require(all(type(v) is int and v > 0 for v in (artifact_id, build_run_id)),
                "invalid_build_artifact")
        built = state.get("built", {})
        require(built.get("artifact_id") == artifact_id and built.get("run_id") == build_run_id,
                "build_evidence_mismatch")
        workflow = "android-release-candidate-sign.yml"
        inputs = {"expected_sha": candidate.source_sha, "build_run_id": str(build_run_id),
                  "artifact_id": str(artifact_id)}
    else:
        raise ValueError("unsupported_dispatch_stage")
    new, run_id = ledger.claim_dispatch(candidate.candidate_id, stage, inputs)
    if new:
        run_id = gate.create_run(workflow, **inputs)
        ledger.bind_dispatch(candidate.candidate_id, stage, run_id)
    require(run_id is not None, "dispatch_uncertain_reconcile_before_retry")
    gate.await_dispatch_visibility(workflow, run_id, candidate.source_sha)
    return run_id


def plan_lab_install(artifact, *, installed, pinned_certificate, device, lab_authorized,
                     credential_present, screen_unlocked):
    """Pure fail-closed decision. Never authorizes reset, first install or downgrade."""
    require(device == "gway-001" and lab_authorized is True, "lab_not_authorized")
    require(screen_unlocked is True, "device_locked_or_unknown")
    require(credential_present is True, "credential_missing_or_unverified")
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


def reconcile_artifact(ledger, candidate, stage, *, pinned_certificate=None, gate=None):
    """Accept only the exact successful, owner-dispatched workflow and its artifact."""
    import tempfile
    from pathlib import Path
    if gate is None:
        from gway_remote import android_release_gate as gate
    require(stage in ("built", "signed"), "unsupported_reconciliation_stage")
    state = ledger.read(candidate.candidate_id)
    require(state.get("allocated") == asdict(candidate), "candidate_not_allocated")
    row = ledger.db.execute("SELECT run_id FROM dispatch_intent WHERE candidate_id=? AND stage=?",
                            (candidate.candidate_id, stage)).fetchone()
    require(row is not None and type(row[0]) is int and row[0] > 0,
            "dispatch_uncertain_reconcile_before_retry")
    run_id = row[0]
    workflow = ("android-release-candidate.yml" if stage == "built"
                else "android-release-candidate-sign.yml")
    run = gate.wait_run(workflow, run_id, "workflow_dispatch", candidate.source_sha)
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
            evidence = {"run_id":run_id, "artifact_id":artifact_id, "apk_sha256":digest,
                        "certificate_sha256":pinned_certificate}
    ledger.record(candidate.candidate_id, stage, evidence)
    return evidence


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
    sub.add_parser("status")
    args = parser.parse_args(argv)
    candidate = Candidate(args.sha, args.tree, args.version, f"0.2.{args.version}")
    os.umask(0o077)
    path = args.ledger
    require(path.is_absolute() and path.parent.is_dir() and not path.is_symlink(),
            "invalid_ledger_path")
    require(not path.exists() or (path.is_file() and path.stat().st_mode & 0o077 == 0
                                  and path.stat().st_uid == os.getuid()), "insecure_ledger_path")
    ledger = CandidateLedger(path)
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
                       artifact_id=built.get("artifact_id"),build_run_id=built.get("run_id"))}
        elif args.action == "reconcile":
            result = reconcile_artifact(ledger,candidate,args.stage,pinned_certificate=args.certificate)
        else:
            result = {"candidate_id":candidate.candidate_id,"evidence":ledger.read(candidate.candidate_id)}
        print(json.dumps(result,sort_keys=True))
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
