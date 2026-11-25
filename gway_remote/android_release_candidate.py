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
