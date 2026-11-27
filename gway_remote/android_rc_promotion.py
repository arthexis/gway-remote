"""Exact-artifact promotion prerequisites; no rebuilding or signing."""
import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

from gway_remote.android_release_candidate import _private_artifact_dir, require
from gway_remote.android_rc_acceptance import WORKFLOW, SMOKE_CHECKS, identity, smoke_receipt, full_receipt

PUBLISH_WORKFLOW = "android-release-candidate-promote.yml"
CONFIRM = "PUBLISH_EXACT_ACCEPTED_APK"
HOLD_LINE = "# ANDROID_PUBLICATION_HOLD_718: preserve the staged CRM rollout."


def workflow_source(gate, revision):
    row = gate.api(f"contents/.github/workflows/android.yml?ref={revision}")
    require(row.get("encoding") == "base64", "publication_policy_unknown")
    return base64.b64decode(row["content"]).decode("utf-8")


def validate_revision(candidate, revision, gate, *, accepted_revision=None):
    """Permit exact reviewed source or one literal hold-marker removal."""
    require(gate.api("branches/main")["commit"]["sha"] == revision, "publication_revision_moved")
    require(gate.api(f"git/commits/{candidate.source_sha}")["tree"]["sha"] == candidate.source_tree,
            "source_tree_mismatch")
    current = workflow_source(gate, revision)
    require("ANDROID_PUBLICATION_HOLD_718" not in current, "publication_held")
    require("LEGACY_ANDROID_PUBLISHER_RETIRED" in current and "\n  publish:" not in current,
            "legacy_publication_not_retired")
    accepted_revision = accepted_revision or candidate.source_sha
    if revision == accepted_revision:
        return
    comparison = gate.api(f"compare/{accepted_revision}...{revision}")
    rows = comparison.get("files", [])
    require(comparison.get("status") == "ahead" and comparison.get("total_commits") == 1
            and comparison.get("merge_base_commit",{}).get("sha") == accepted_revision
            and len(rows) == 1 and rows[0].get("filename") == ".github/workflows/android.yml"
            and rows[0].get("status") == "modified", "candidate_superseded")
    original = workflow_source(gate, accepted_revision)
    require(original.splitlines().count(HOLD_LINE) == 1
            and original.replace(HOLD_LINE+"\n","",1) == current,
            "publication_policy_transition_unverified")


def validate_full_receipt(receipt, artifact, run_id, hosted, *, compatibility=None):
    expected = full_receipt(artifact, run_id,
        smoke_receipt(artifact, run_id, dict.fromkeys(SMOKE_CHECKS,"pass")), hosted)
    if compatibility is not None:
        expected["compatibility"] = compatibility
    require(receipt == expected, "full_acceptance_missing_or_mismatched")
    return expected


def read_full_receipt(artifact, run_id, gate, *, build_run):
    from gway_remote.android_rc_contracts import reconcile, successful_run
    c = artifact.candidate
    require(type(run_id) is int and run_id > 0, "invalid_acceptance_run_id")
    run = gate.api(f"actions/runs/{run_id}")
    revision = run.get("head_sha")
    successful_run(gate, WORKFLOW, run_id, revision, "physical")
    gate.verify_run_identity(run, WORKFLOW, run_id, "workflow_dispatch", revision)
    require(run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("run_attempt") == 1 and (run.get("actor") or {}).get("login") == gate.OWNER
            and (run.get("triggering_actor") or {}).get("login") == gate.OWNER, "acceptance_run_unverified")
    name = f"android-rc-full-{run_id}"
    listing = gate.api(f"actions/runs/{run_id}/artifacts?per_page=100")
    rows = listing["artifacts"]
    require(listing.get("total_count") == len(rows), "incomplete_artifact_listing")
    matches = [a for a in rows if a.get("name") == name and a.get("expired") is False]
    require(len(matches) == 1, "full_acceptance_artifact_missing")
    meta = gate.api(f"actions/artifacts/{matches[0]['id']}")
    require(meta.get("name") == name and meta.get("expired") is False
            and (meta.get("workflow_run") or {}).get("id") == run_id
            and (meta.get("workflow_run") or {}).get("head_sha") == revision,
            "receipt_artifact_identity_mismatch")
    with tempfile.TemporaryDirectory() as tmp:
        gate.download(run_id, name, tmp)
        path = Path(tmp)/"receipt.json"
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 16384,
                "invalid_receipt_file")
        payload = json.loads(path.read_text())
    require(isinstance(payload, dict) and isinstance(payload.get("hosted_evidence"),dict),
            "full_acceptance_missing_or_mismatched")
    evidence = payload["hosted_evidence"]
    hosted = reconcile(gate, c, ci_run=evidence.get("ci_run"),
                       compose_run=evidence.get("compose_run"), build_run=build_run)
    compatibility = None
    if revision != c.source_sha or "compatibility" in payload:
        from gway_remote.android_release_candidate import compatible_revision
        info = payload.get("compatibility")
        require(isinstance(info, dict), "compatible_evidence_missing")
        compatibility = compatible_revision(c, revision, gate, revision_ci_run=info.get("revision_ci_run"),
                                            backend_run=info.get("backend_run"), current=False)
    return validate_full_receipt(payload, artifact, run_id, hosted, compatibility=compatibility)


def preflight(ledger, candidate, *, revision, acceptance_run, artifact_dir, gate):
    """All read-only. A smoke receipt or an expired full receipt cannot authorize release."""
    # Keep hold check before fetching receipts; validate exact transition after receipt read.
    require("ANDROID_PUBLICATION_HOLD_718" not in workflow_source(gate, revision), "publication_held")
    artifact = identity(ledger, candidate)
    receipt = read_full_receipt(artifact, acceptance_run, gate,
                                build_run=ledger.read(candidate.candidate_id)["built"]["run_id"])
    from gway_remote.android_canary_certificate import certificate_sha256
    apk = _private_artifact_dir(artifact_dir)/f"{candidate.candidate_id}.apk"
    require(apk.is_file() and not apk.is_symlink() and apk.stat().st_uid == os.getuid()
            and apk.stat().st_mode & 0o077 == 0 and 10000 < apk.stat().st_size < 104857600,
            "local_candidate_unverified")
    require(hashlib.sha256(apk.read_bytes()).hexdigest() == artifact.apk_sha256
            and certificate_sha256(apk) == artifact.certificate_sha256, "local_candidate_mismatch")
    validate_revision(candidate, revision, gate, accepted_revision=receipt.get("compatibility", {}).get("revision"))
    return artifact, receipt, apk


def verify_release_asset(artifact, release, *, draft, acceptance_run):
    c = artifact.candidate
    tag = f"android-v{c.version_name}"
    require(release.get("tag_name") == tag and release.get("target_commitish") == c.source_sha
            and release.get("draft") is draft and release.get("prerelease") is False,
            "existing_release_conflict")
    assets = release.get("assets", [])
    require(len(assets) == 1 and assets[0].get("name") == "gway-remote.apk"
            and assets[0].get("state") == "uploaded"
            and assets[0].get("digest") == "sha256:"+artifact.apk_sha256,
            "release_asset_mismatch")
    notes = release.get("body") or ""
    require(notes.splitlines().count("Android-Version-Code: "+str(c.version_code)) == 1
            and notes.splitlines().count("Source-Commit: "+c.source_sha) == 1
            and notes.splitlines().count("APK-SHA256: "+artifact.apk_sha256) == 1
            and notes.splitlines().count("Acceptance-Run: "+str(acceptance_run)) == 1,
            "release_metadata_mismatch")


def promotion_plan(ledger, candidate, *, revision, acceptance_run, artifact_dir, gate):
    """Read-only admission preview, even after complete acceptance.

    Publication mutation requires a separate owner-authorized workflow;
    this preview deliberately never grants that authority.
    """
    artifact, receipt, apk = preflight(ledger, candidate, revision=revision,
                                    acceptance_run=acceptance_run, artifact_dir=artifact_dir, gate=gate)
    return {"candidate_id":candidate.candidate_id, "source_sha":candidate.source_sha,
            "publication_revision":revision, "version_code":candidate.version_code,
            "apk_sha256":artifact.apk_sha256, "certificate_sha256":artifact.certificate_sha256,
            "artifact_id":artifact.artifact_id, "acceptance_run":receipt["run_id"],
            "tag":f"android-v{candidate.version_name}", "asset_name":"gway-remote.apk",
            "publication_admission":False, "status":"ready_for_explicit_authorization"}


def publish_exact(ledger, candidate, *, revision, acceptance_run, artifact_dir, gate,
                  publish_run, confirm, expected_digest):
    """Owner-only workflow; draft first, verify download, then publish exact bytes."""
    require(confirm == CONFIRM, "explicit_publication_authorization_required")
    require(type(publish_run) is int and publish_run > 0, "invalid_publication_run")
    artifact, receipt, apk = preflight(ledger, candidate, revision=revision,
                                    acceptance_run=acceptance_run, artifact_dir=artifact_dir, gate=gate)
    require(expected_digest == artifact.apk_sha256, "approved_digest_mismatch")
    run = gate.api(f"actions/runs/{publish_run}")
    gate.verify_run_identity(run, PUBLISH_WORKFLOW, publish_run, "workflow_dispatch", revision)
    require(run.get("status") == "in_progress" and run.get("run_attempt") == 1
            and (run.get("actor") or {}).get("login") == gate.OWNER
            and (run.get("triggering_actor") or {}).get("login") == gate.OWNER
            and run.get("display_title") == f"Promote RC {candidate.version_code} {expected_digest} acceptance {acceptance_run}",
            "publication_run_unverified")
    tag = f"android-v{candidate.version_name}"
    import re
    releases = gate.pages("releases?per_page=100")
    matches = [r for r in releases if r.get("tag_name") == tag]
    require(len(matches) <= 1, "ambiguous_release")
    for r in releases:
        m = re.fullmatch(r"android-v0[.]2[.]([0-9]+)", r.get("tag_name",""))
        require(not m or int(m[1]) <= candidate.version_code, "release_version_superseded")
    state = ledger.read(candidate.candidate_id)
    prior = state.get("approved")
    approval = {"candidate_id":candidate.candidate_id,"apk_sha256":artifact.apk_sha256,
                "acceptance_run":acceptance_run,"publication_revision":revision}
    require(prior is None or {k:v for k,v in prior.items() if k != "approval_run"} == approval,
            "publication_approval_conflict")
    if prior is None:
        approval["approval_run"] = publish_run
    else:
        original_run = prior.get("approval_run")
        require(type(original_run) is int and original_run > 0, "publication_approval_run_missing")
        original = gate.api(f"actions/runs/{original_run}")
        gate.verify_run_identity(original, PUBLISH_WORKFLOW, original_run, "workflow_dispatch", revision)
        require(original.get("run_attempt") == 1
                and (original.get("actor") or {}).get("login") == gate.OWNER
                and (original.get("triggering_actor") or {}).get("login") == gate.OWNER
                and original.get("display_title") == run.get("display_title"),
                "original_publication_authorization_unverified")
        approval = prior
    require(not matches or prior is not None, "unowned_release_conflict")
    require(matches or prior is None, "publication_intent_uncertain")
    ledger.record(candidate.candidate_id,"accepted",receipt)
    ledger.record(candidate.candidate_id,"approved",approval)
    notes = f"Android-Version-Code: {candidate.version_code}\nSource-Commit: {candidate.source_sha}\nAPK-SHA256: {artifact.apk_sha256}\nAcceptance-Run: {acceptance_run}\n"
    def exact_release():
        rows = [r for r in gate.pages("releases?per_page=100") if r.get("tag_name") == tag]
        require(len(rows) == 1, "release_identity_unverified")
        return rows[0]
    def verify_download(release, draft):
        verify_release_asset(artifact, release, draft=draft, acceptance_run=acceptance_run)
        with tempfile.TemporaryDirectory() as tmp:
            gate.gh("release","download",tag,"-R",gate.REPO,"--pattern","gway-remote.apk","--dir",tmp)
            downloaded = Path(tmp)/"gway-remote.apk"
            require(downloaded.is_file() and not downloaded.is_symlink()
                    and hashlib.sha256(downloaded.read_bytes()).hexdigest() == artifact.apk_sha256,
                    "published_bytes_mismatch")
    def check_tag(required=False):
        refs = gate.api(f"git/matching-refs/tags/{tag}")
        exact = [r for r in refs if r.get("ref") == "refs/tags/"+tag]
        require(len(exact) <= 1 and (exact or not required), "release_tag_missing")
        if exact:
            require(gate.api(f"commits/{tag}")["sha"] == candidate.source_sha,"release_tag_conflict")
    validate_revision(candidate, revision, gate, accepted_revision=receipt.get("compatibility", {}).get("revision"))
    check_tag()
    if not matches:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp)/"gway-remote.apk"
            local.write_bytes(apk.read_bytes())
            require(hashlib.sha256(local.read_bytes()).hexdigest() == artifact.apk_sha256,
                    "local_candidate_mismatch")
            gate.gh("release","create",tag,str(local),"-R",gate.REPO,"--draft",
                    "--target",candidate.source_sha,"--title","GWay Remote "+tag,"--notes",notes)
    release = exact_release()
    if release.get("draft") is True:
        verify_download(release, True)
        validate_revision(candidate, revision, gate, accepted_revision=receipt.get("compatibility", {}).get("revision"))
        check_tag()
        gate.gh("release","edit",tag,"-R",gate.REPO,"--draft=false","--latest")
    release = exact_release()
    check_tag(required=True)
    verify_download(release, False)
    latest = gate.api("releases/latest")
    verify_release_asset(artifact, latest, draft=False, acceptance_run=acceptance_run)
    require(latest.get("id") == release.get("id"), "latest_release_identity_mismatch")
    result = {"tag":tag,"source_sha":candidate.source_sha,"apk_sha256":artifact.apk_sha256,
              "certificate_sha256":artifact.certificate_sha256,"acceptance_run":acceptance_run,
              "approval_run":approval["approval_run"],"release_id":release["id"]}
    ledger.record(candidate.candidate_id,"published",result)
    return result

def main():
    import argparse
    from gway_remote.android_release_candidate import Candidate, CandidateLedger
    from gway_remote import android_release_gate as gate
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--artifact-dir", type=Path, required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--tree", required=True)
    p.add_argument("--version", type=int, required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--acceptance-run", type=int, required=True)
    p.add_argument("--publish-run", type=int)
    p.add_argument("--confirm")
    p.add_argument("--digest")
    a = p.parse_args()
    require(a.ledger.is_absolute() and a.ledger.is_file() and not a.ledger.is_symlink()
            and a.ledger.stat().st_uid == os.getuid() and a.ledger.stat().st_mode & 0o077 == 0,
            "insecure_ledger_path")
    candidate = Candidate(a.sha, a.tree, a.version, f"0.2.{a.version}")
    ledger = CandidateLedger(a.ledger, read_only=a.publish_run is None)
    try:
        kw = dict(revision=a.revision, acceptance_run=a.acceptance_run,
                  artifact_dir=a.artifact_dir, gate=gate)
        if a.publish_run is not None:
            result = publish_exact(ledger, candidate, **kw, publish_run=a.publish_run,
                                   confirm=a.confirm, expected_digest=a.digest)
        else:
            require(a.confirm is None and a.digest is None, "unexpected_publication_options")
            result = promotion_plan(ledger, candidate, **kw)
        print(json.dumps(result, sort_keys=True))
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
