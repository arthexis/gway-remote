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
