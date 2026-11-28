"""Owner-run, resumable orchestration of the existing single-candidate pipeline.

No allocation, signing authorization, environment approval, publication, PR merge,
device actions or credential issuance. Existing protected workflows own those actions.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

from gway_remote.android_release_candidate import (
    Candidate, CandidateLedger, SHA, SignedArtifact, require, _private_artifact_dir,
    dispatch_candidate, reconcile_artifact, compatible_revision, validate_signing_revision,
)
from gway_remote.android_rc_contracts import successful_run, reconcile
from gway_remote.android_rc_acceptance import identity, WORKFLOW as ACCEPT
from gway_remote.android_rc_promotion import read_full_receipt, verify_release_asset

BUILD = "android-release-candidate.yml"
SIGN = "android-release-candidate-sign.yml"
INSTALL = "android-release-candidate-install.yml"
CI = "ci.yml"
COMPOSE = "android-compose-ui.yml"
JOBS = {BUILD:"build", SIGN:"sign", INSTALL:"physical", ACCEPT:"physical",
        CI:"CI", COMPOSE:"compose-ui"}
ENV = "android-release-signing"
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}

def outcome(status, **kw):
    return {"status":status, "publication_admission":False, **kw}

def read_intent(ledger, candidate, stage):
    row = ledger.db.execute("SELECT run_id,inputs FROM dispatch_intent WHERE candidate_id=? AND stage=?",
                            (candidate.candidate_id,stage)).fetchone()
    return (row[0],json.loads(row[1])) if row else None

def setup(ledger):
    # Outer workflow requests live in the SAME ledger as the inner install intent.
    # Separate keys avoid claiming the install's physical mutation before it starts.
    ledger.db.execute("""CREATE TABLE IF NOT EXISTS coordinator_run (
        candidate_id TEXT NOT NULL REFERENCES candidate(id),
        stage TEXT NOT NULL, spec TEXT NOT NULL, run_id INTEGER,
        PRIMARY KEY(candidate_id,stage))""")

def tracked(ledger, candidate, stage):
    row = ledger.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coordinator_run'").fetchone()
    if not row:
        return None
    row = ledger.db.execute("SELECT spec,run_id FROM coordinator_run WHERE candidate_id=? AND stage=?",
                           (candidate.candidate_id,stage)).fetchone()
    return (json.loads(row[0]),row[1]) if row else None

def verified_run(gate, workflow, run_id, revision):
    require(type(run_id) is int and run_id > 0, "invalid_run_id")
    run = gate.api(f"actions/runs/{run_id}")
    gate.verify_run_identity(run, workflow, run_id, "workflow_dispatch", revision)
    require(run.get("run_attempt")==1 and (run.get("actor") or {}).get("login")==gate.OWNER
            and (run.get("triggering_actor") or {}).get("login")==gate.OWNER,
            "workflow_owner_or_attempt_unverified")
    require(run.get("status") in ACTIVE | {"completed"}, "unknown_workflow_state")
    return run

def list_runs(gate, workflow, revision):
    data = gate.api(f"actions/workflows/{workflow}/runs?event=workflow_dispatch&head_sha={revision}&per_page=100")
    rows = data["workflow_runs"]
    require(data.get("total_count")==len(rows) and len(rows)<100, "workflow_listing_incomplete")
    return rows

def reserve(ledger, candidate, stage, spec, existing=None):
    # The reservation precedes dispatch. A lost response stays NULL and blocks replay.
    ledger.db.execute("BEGIN IMMEDIATE")
    try:
        old = tracked(ledger,candidate,stage)
        if old:
            require(old[0]==spec and (existing is None or old[1]==existing), "coordinator_intent_conflict")
            ledger.db.commit()
            return False,old[1]
        ledger.db.execute("INSERT INTO coordinator_run VALUES (?,?,?,?)",
                          (candidate.candidate_id,stage,ledger.encode(spec),existing))
        ledger.db.commit()
        return True,existing
    except BaseException:
        ledger.db.rollback()
        raise

def bind(ledger,candidate,stage,spec,run_id):
    require(type(run_id) is int and run_id>0,"invalid_run_id")
    ledger.db.execute("BEGIN IMMEDIATE")
    try:
        row=tracked(ledger,candidate,stage)
        require(row is not None and row[0]==spec and row[1] in (None,run_id),"coordinator_run_conflict")
        ledger.db.execute("UPDATE coordinator_run SET run_id=? WHERE candidate_id=? AND stage=?",
                          (run_id,candidate.candidate_id,stage))
        ledger.db.commit()
    except BaseException:
        ledger.db.rollback()
        raise

def pick_run(gate,workflow,revision,*,title=None,adopt=None):
    if adopt is not None:
        r=verified_run(gate,workflow,adopt,revision)
        require(title is None or r.get("display_title")==title,"adopted_run_title_mismatch")
        return adopt
    rows=list_runs(gate,workflow,revision)
    if title is not None:
        rows=[r for r in rows if r.get("display_title")==title]
    # Generic legacy acceptance names cannot identify a candidate. Never guess.
    if workflow==ACCEPT and rows:
        raise ValueError("existing_acceptance_run_requires_explicit_adoption")
    if workflow==INSTALL and rows:
        raise ValueError("existing_install_run_requires_explicit_adoption")
    eligible=[r for r in rows if r.get("run_attempt")==1
              and (r.get("actor") or {}).get("login")==gate.OWNER
              and (r.get("triggering_actor") or {}).get("login")==gate.OWNER]
    require(len(eligible)==len(rows),"foreign_or_retried_workflow_requires_review")
    active=[r for r in eligible if r.get("status") in ACTIVE]
    require(len(active)<=1,"multiple_active_workflows")
    if active:
        return active[0]["id"]
    if eligible:
        # Reuse the newest exact owner run; a failed result is not silently replayed.
        return max(eligible,key=lambda r:r["id"])["id"]
    return None

def workflow_step(ledger,candidate,gate,stage,workflow,revision,inputs,*,adopt=None,title=None):
    spec={"workflow":workflow,"revision":revision,"inputs":inputs}
    old=tracked(ledger,candidate,stage)
    if old:
        require(old[0]==spec and (adopt is None or old[1] in (None,adopt)),"coordinator_intent_conflict")
        run_id=old[1]
        if run_id is None and adopt is not None:
            # Explicitly reconcile a lost response by identity; never redispatch.
            r=verified_run(gate,workflow,adopt,revision)
            require(title is None or r.get("display_title")==title,"adopted_run_title_mismatch")
            bind(ledger,candidate,stage,spec,adopt)
            run_id=adopt
    else:
        run_id=pick_run(gate,workflow,revision,title=title,adopt=adopt)
        require(run_id is not None or gate.api("branches/main")["commit"]["sha"]==revision,
                "historical_evidence_missing_or_main_moved")
        new,run_id=reserve(ledger,candidate,stage,spec,run_id)
        if new and run_id is None:
            require(gate.api("branches/main")["commit"]["sha"]==revision,"candidate_superseded")
            run_id=gate.create_run(workflow,**inputs)
            bind(ledger,candidate,stage,spec,run_id)
            gate.await_dispatch_visibility(workflow,run_id,revision)
    require(run_id is not None,"dispatch_uncertain_reconcile_before_retry")
    run=verified_run(gate,workflow,run_id,revision)
    require(title is None or run.get("display_title")==title,"workflow_title_mismatch")
    if run["status"]!="completed":
        return run_id,outcome("waiting",stage=stage,run_id=run_id)
    require(run.get("conclusion")=="success",f"{stage}_failed_review_before_retry")
    successful_run(gate,workflow,run_id,revision,JOBS[workflow])
    return run_id,None

def pin(gate,name):
    row=gate.api(f"environments/{ENV}/variables/{name}")
    require(row.get("name")==name and isinstance(row.get("value"),str),"signing_pin_unverified")
    return row["value"]

def signing_pins(candidate,built,revision):
    return {"RC_APPROVED_SOURCE_SHA":candidate.source_sha,"RC_APPROVED_WORKFLOW_SHA":revision,
            "RC_APPROVED_UNSIGNED_SHA256":built["unsigned_sha256"],
            "RC_APPROVED_BUILD_RUN":str(built["run_id"]),"RC_APPROVED_ARTIFACT_ID":str(built["artifact_id"]),
            "RC_APPROVED_VERSION_CODE":str(candidate.version_code)}

def artifact_step(ledger,candidate,gate,stage,revision,artifact_dir):
    state=ledger.read(candidate.candidate_id)
    if stage in state:
        return None
    intent=read_intent(ledger,candidate,stage)
    workflow=BUILD if stage=="built" else SIGN
    expected=candidate.source_sha if stage=="built" else revision
    if intent:
        run_id,inputs=intent
        expected=candidate.source_sha if stage=="built" else inputs.get("workflow_sha")
        require(run_id is not None,"dispatch_uncertain_reconcile_before_retry")
    else:
        if stage=="signed":
            validate_signing_revision(candidate,revision,gate)
            pins=signing_pins(candidate,state["built"],revision)
            # No automatic signing grant or environment approval.
            if pin(gate,"ANDROID_RC_SIGNING_ENABLED")!="true" or any(pin(gate,k)!=v for k,v in pins.items()):
                return outcome("operator_signing_authorization_required",stage=stage,required_pins=pins)
        require(not list_runs(gate,workflow,expected),"existing_build_or_sign_run_requires_reconciliation")
        b=state.get("built",{})
        run_id=dispatch_candidate(ledger,candidate,stage,artifact_id=b.get("artifact_id"),
                                  build_run_id=b.get("run_id"),workflow_sha=expected,gate=gate)
    run=verified_run(gate,workflow,run_id,expected)
    if run["status"]!="completed":
        if stage=="signed" and run["status"] in {"waiting","pending"}:
            return outcome("operator_signing_approval_required",stage=stage,run_id=run_id)
        return outcome("waiting",stage=stage,run_id=run_id)
    if stage=="signed":
        # Restore only the exact authorization belonging to this candidate.
        enabled=pin(gate,"ANDROID_RC_SIGNING_ENABLED")
        require(enabled in {"true","false"},"signing_switch_unknown")
        if enabled=="true":
            pins=signing_pins(candidate,state["built"],expected)
            require(all(pin(gate,k)==v for k,v in pins.items()),"signing_authorization_changed")
            gate.gh("variable","set","ANDROID_RC_SIGNING_ENABLED","--repo",gate.REPO,
                    "--env",ENV,"--body","false")
            require(pin(gate,"ANDROID_RC_SIGNING_ENABLED")=="false","signing_switch_restore_unverified")
    require(run.get("conclusion")=="success",f"{stage}_failed_review_before_retry")
    successful_run(gate,workflow,run_id,expected,JOBS[workflow])
    reconcile_artifact(ledger,candidate,stage,pinned_certificate=pin(gate,"RC_PRODUCTION_CERT_SHA256") if stage=="signed" else None,
                       artifact_dir=artifact_dir,gate=gate)
    return None

def local_artifact(ledger,candidate,artifact_dir):
    from gway_remote.android_canary_certificate import certificate_sha256
    state=ledger.read(candidate.candidate_id)
    signed=state["signed"]
    a=SignedArtifact(candidate,signed["apk_sha256"],signed["certificate_sha256"],
                     signed["artifact_id"],signed["run_id"])
    apk=_private_artifact_dir(artifact_dir)/f"{candidate.candidate_id}.apk"
    require(apk.is_file() and not apk.is_symlink() and apk.stat().st_uid==os.getuid()
            and apk.stat().st_mode & 0o077==0 and 10000<apk.stat().st_size<104857600,
            "local_candidate_unverified")
    require(hashlib.sha256(apk.read_bytes()).hexdigest()==a.apk_sha256
            and certificate_sha256(apk)==a.certificate_sha256,"local_candidate_mismatch")
    return a

def historical(ledger,candidate,gate,artifact_dir):
    state=ledger.read(candidate.candidate_id)
    if "accepted" not in state:
        return None
    a=local_artifact(ledger,candidate,artifact_dir)
    require(identity(ledger,candidate)==a,"upgrade_chain_mismatch")
    receipt=read_full_receipt(a,state["accepted"]["run_id"],gate,build_run=state["built"]["run_id"])
    require(receipt==state["accepted"],"historical_acceptance_mismatch")
    if "published" not in state:
        return outcome("accepted",acceptance_run=receipt["run_id"],artifact_id=a.artifact_id,
                       compatibility=receipt.get("compatibility"),replayed=False)
    published=state["published"]; tag=f"android-v{candidate.version_name}"
    release=gate.api("releases/tags/"+tag)
    verify_release_asset(a,release,draft=False,acceptance_run=receipt["run_id"])
    require(gate.api("commits/"+tag)["sha"]==candidate.source_sha,"published_tag_mismatch")
    require(published=={"tag":tag,"source_sha":candidate.source_sha,"apk_sha256":a.apk_sha256,
                       "certificate_sha256":a.certificate_sha256,"acceptance_run":receipt["run_id"],
                       "approval_run":state["approved"]["approval_run"],"release_id":release["id"]},
            "published_ledger_mismatch")
    import tempfile
    from gway_remote.android_canary_certificate import certificate_sha256
    with tempfile.TemporaryDirectory() as tmp:
        gate.gh("release","download",tag,"-R",gate.REPO,"--pattern","gway-remote.apk","--dir",tmp)
        downloaded=Path(tmp)/"gway-remote.apk"
        require(downloaded.is_file() and not downloaded.is_symlink()
                and hashlib.sha256(downloaded.read_bytes()).hexdigest()==a.apk_sha256
                and certificate_sha256(downloaded)==a.certificate_sha256,"published_artifact_mismatch")
    return outcome("published_verified",acceptance_run=receipt["run_id"],artifact_id=a.artifact_id,
                   release_id=release["id"],tag=tag,compatibility=receipt.get("compatibility"),
                   replayed=False)

def advance(ledger,candidate,gate,artifact_dir,*,revision,backend_run=None,ci_run=None,
            compose_run=None,revision_ci_run=None,install_run=None,acceptance_run=None):
    state=ledger.read(candidate.candidate_id)
    require(state.get("allocated")==asdict(candidate),"candidate_not_allocated")
    prior=historical(ledger,candidate,gate,artifact_dir)
    if prior:
        return prior
    require(gate.api("branches/main")["commit"]["sha"]==revision,"candidate_superseded")
    require(gate.api(f"git/commits/{candidate.source_sha}")["tree"]["sha"]==candidate.source_tree,
            "source_tree_mismatch")
    require(revision==candidate.source_sha or "signed" in state,"unsigned_candidate_superseded")
    # CI/Compose original source must already exist if main advanced.
    original=candidate.source_sha
    ci,wait=workflow_step(ledger,candidate,gate,"ci",CI,original,{},adopt=ci_run)
    if wait: return wait
    compose,wait=workflow_step(ledger,candidate,gate,"compose",COMPOSE,original,{"profile":"phone"},adopt=compose_run)
    if wait: return wait
    for stage in ("built","signed"):
        wait=artifact_step(ledger,candidate,gate,stage,revision,artifact_dir)
        if wait: return wait
    state=ledger.read(candidate.candidate_id)
    a=local_artifact(ledger,candidate,artifact_dir)
    # Verify actual named tests before hardware dispatch, not merely workflow success.
    reconcile(gate,candidate,ci_run=ci,compose_run=compose,build_run=state["built"]["run_id"])
    extra={}
    if revision!=original:
        require(type(backend_run) is int and backend_run>0,"compatible_backend_evidence_required")
        rci,wait=workflow_step(ledger,candidate,gate,"revision-ci:"+revision,CI,revision,{},adopt=revision_ci_run)
        if wait: return wait
        compatible_revision(candidate,revision,gate,revision_ci_run=rci,backend_run=backend_run)
        extra={"revision_ci_run":str(rci),"backend_run":str(backend_run)}
    else:
        require(backend_run is None and revision_ci_run is None,"unexpected_compatibility_evidence")
    inputs={"source_sha":original,"source_tree":candidate.source_tree,"version_code":str(candidate.version_code)}
    if "installed" not in state:
        inner=read_intent(ledger,candidate,"installed")
        outer=tracked(ledger,candidate,"install")
        if inner:
            require(inner[0] is not None and (outer is None or outer[1]==inner[0]),
                    "installation_uncertain_reconcile_before_retry")
            if install_run is not None: require(install_run==inner[0],"install_run_conflict")
            install_run=inner[0]
        title=f"Android RC install version {candidate.version_code} artifact {a.artifact_id}"
        run,wait=workflow_step(ledger,candidate,gate,"install",INSTALL,revision,
            {**inputs,"mode":"install","workflow_sha":revision,"artifact_id":str(a.artifact_id),
             "apk_sha256":a.apk_sha256,"certificate_sha256":a.certificate_sha256,**extra},adopt=install_run,title=title)
        if wait: return wait
        state=ledger.read(candidate.candidate_id)
        require(state.get("installed",{}).get("install_run_id")==run,"install_receipt_missing")
    else:
        run=state["installed"]["install_run_id"]
        require(install_run in (None,run),"install_run_conflict")
        row=read_intent(ledger,candidate,"installed")
        require(row and row[0]==run,"install_intent_missing")
        successful_run(gate,INSTALL,run,row[1]["workflow_sha"],"physical")
    require(identity(ledger,candidate)==a,"authenticated_upgrade_missing")
    # Existing acceptance workflow performs all physical checks and issues the receipt.
    run,wait=workflow_step(ledger,candidate,gate,"acceptance",ACCEPT,revision,
        {**inputs,"scope":"full","ci_run":str(ci),"compose_run":str(compose),**extra},adopt=acceptance_run)
    if wait: return wait
    receipt=read_full_receipt(a,run,gate,build_run=state["built"]["run_id"])
    require(receipt["hosted_evidence"]["ci_run"]==ci and receipt["hosted_evidence"]["compose_run"]==compose
            and (receipt.get("compatibility") or {}).get("revision",original)==revision,
            "coordinator_acceptance_evidence_mismatch")
    require(gate.api("branches/main")["commit"]["sha"]==revision,"candidate_superseded")
    ledger.record(candidate.candidate_id,"accepted",receipt)
    return outcome("accepted",acceptance_run=run,artifact_id=a.artifact_id,compatibility=receipt.get("compatibility"))

def wait_current(gate,result,deadline,*,clock=time.monotonic,pause=time.sleep):
    """Poll only the active run; full reconciliation happens on its terminal result."""
    while clock()<deadline:
        pause(min(15,max(0,deadline-clock())))
        r=gate.api(f"actions/runs/{result[\"run_id\"]}")
        require(r.get("id")==result["run_id"] and r.get("status") in ACTIVE | {"completed"},
                "workflow_poll_identity_unverified")
        if r["status"]=="completed" or (result["stage"]=="signed" and r["status"] in {"waiting","pending"}):
            return True
    return False


def main():
    import fcntl
    import socket
    from gway_remote import android_release_gate as gate
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger",type=Path,required=True); p.add_argument("--artifact-dir",type=Path,required=True)
    p.add_argument("--sha",required=True); p.add_argument("--tree",required=True); p.add_argument("--version",type=int,required=True)
    p.add_argument("--revision")
    for name in ("backend-run","ci-run","compose-run","revision-ci-run","install-run","acceptance-run"):
        p.add_argument("--"+name,type=int)
    p.add_argument("--execute",action="store_true",help="Owner authorization to advance this allocated candidate through acceptance only")
    p.add_argument("--wait-seconds",type=int,default=3600)
    args=p.parse_args()
    c=Candidate(args.sha,args.tree,args.version,f"0.2.{args.version}")
    require(0<=args.wait_seconds<=5400,"invalid_wait_budget")
    require(args.ledger.is_absolute() and args.ledger.is_file() and not args.ledger.is_symlink()
            and args.ledger.stat().st_uid==os.getuid() and args.ledger.stat().st_mode & 0o077==0
            and args.ledger.parent.stat().st_uid==os.getuid() and args.ledger.parent.stat().st_mode & 0o077==0,
            "insecure_ledger_path")
    os.umask(0o077)
    if not args.execute:
        ledger=CandidateLedger(args.ledger,read_only=True)
        try:
            require(ledger.read(c.candidate_id).get("allocated")==asdict(c),"candidate_not_allocated")
            result=historical(ledger,c,gate,args.artifact_dir)
            print(json.dumps(result or outcome("execution_not_authorized",recorded_stages=sorted(ledger.read(c.candidate_id))),sort_keys=True))
        finally: ledger.close()
        return
    require(socket.gethostname().split(".")[0]=="gway-001","wrong_coordinator_host")
    require(gate.gh("api","user","--jq",".login")==gate.OWNER,"coordinator_owner_unverified")
    require(isinstance(args.revision,str) and SHA.fullmatch(args.revision),"reviewed_revision_required")
    lock=args.ledger.parent/"coordinator.lock"
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        st=os.fstat(fd); require(st.st_uid==os.getuid() and st.st_mode & 0o077==0,"insecure_coordinator_lock")
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        ledger=CandidateLedger(args.ledger)
        try:
            setup(ledger); deadline=time.monotonic()+args.wait_seconds
            while True:
                result=advance(ledger,c,gate,args.artifact_dir,revision=args.revision,backend_run=args.backend_run,
                    ci_run=args.ci_run,compose_run=args.compose_run,revision_ci_run=args.revision_ci_run,
                    install_run=args.install_run,acceptance_run=args.acceptance_run)
                print(json.dumps(result,sort_keys=True),flush=True)
                if result["status"]!="waiting" or time.monotonic()>=deadline: break
                if not wait_current(gate,result,deadline): break
        finally: ledger.close()
    finally: os.close(fd)

if __name__=="__main__":
    main()
