"""Hosted synthetic module evidence for the exact main source; no physical credentials."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from gway_remote.android_release_candidate import SHA, require

PREFIX = "com.arthexis.gwayremote."
# These tests exercise real Compose panels using synthetic sources or callbacks.
# Never equate a successful hosted workflow alone with the named tests running.
GROUPS = {
    "opportunity_refresh_and_stale": (
        "AndroidRcOpportunityContractTest.refreshRetainsStaleRecordsAndRecovers",
        "AndroidRcOpportunityContractTest.paginationAndConsentValidation",
        "AndroidRcOpportunityContractTest.missingCredentialsNeverCallOpportunityBackend",
    ),
    "opportunity_consent_and_copy_contract": (
        "AndroidRcOpportunityContractTest.paginationAndConsentValidation",
        "OdooOpportunityCopyTest.copiesExactlyOneValuePerButton",
        "OdooOpportunityCopyTest.missingFieldsCannotBeCopied",
    ),
    "liturgia_reader_search_comparison": (
        "AndroidRcLiturgiaContractTest.dayFormAndRightsBoundary",
        "AndroidRcLiturgiaContractTest.readerComparisonBookmarkAndHistory",
        "AndroidRcLiturgiaContractTest.searchPaginationAndSanitizedError",
    ),
    "liturgia_local_library_and_errors": (
        "AndroidRcLiturgiaContractTest.readerComparisonBookmarkAndHistory",
        "AndroidRcLiturgiaContractTest.searchPaginationAndSanitizedError",
    ),
    "quotation_pdf_and_refresh": (
        "OdooQuotationRefreshTest.refreshKeepsFilterAndLastGoodResults",
        "OdooQuotationRefreshTest.pagingAndRecentResetKeepCorrectQuery",
        "OdooQuotationRefreshTest.emptyAndInitialErrorAreRecoverable",
        "OdooQuotationRefreshTest.missingCredentialsNeverCallBackend",
        "OdooQuotationRefreshTest.actualSaveContractUsesSuggestedNameAndLegacyFallback",
    ),
    "feed_read_and_failure": (
        "ActivityFeedComposeTest.filtersOfflineReadAndNavigation",
        "ModuleNavigationComposeTest.feedRemovesWholeReadCardOnlyAfterSuccess",
    ),
    "navigation_and_scope": (
        "ModuleNavigationComposeTest.drawerSelectsAnEntireModuleWithoutOpeningASecondPanel",
        "ModuleNavigationComposeTest.homeHasOnlyAppInformationAndUpdateEntry",
        "ModuleNavigationComposeTest.updatesCheckOncePerEntryNotRecomposition",
        "ModulePageComposeTest.canaryUpdatePageCannotDownloadOrInstallStableRelease",
        "ModulePageComposeTest.deploymentIsDisabledWithoutTokenEvenAfterExplicitConfirmation",
    ),
    "deployment_confirmation": (
        "DeploymentConfirmationTest.confirmationStartsUncheckedAndLabelIsClickable",
        "ModulePageComposeTest.deploymentIsDisabledWithoutTokenEvenAfterExplicitConfirmation",
    ),
}
CASES = frozenset(PREFIX + case for group in GROUPS.values() for case in group)
WORKFLOW = "android-compose-ui.yml"


def validate_ids(source_sha, source_tree, run_id):
    require(all(isinstance(x, str) and SHA.fullmatch(x) for x in (source_sha, source_tree)),
            "invalid_contract_source")
    require(type(run_id) is int and run_id > 0, "invalid_contract_run")


def receipt(source_sha, source_tree, run_id):
    validate_ids(source_sha, source_tree, run_id)
    return {"schema":1, "scope":"hosted_synthetic_module_contracts_v1",
            "source_sha":source_sha, "source_tree":source_tree, "run_id":run_id,
            "profile":"phone", "cases":sorted(CASES), "groups":dict.fromkeys(GROUPS,"pass")}


def from_junit(root, source_sha, source_tree, run_id):
    """Emit only fixed case identities, never logs or fixture/real user text."""
    require(root.is_dir() and not root.is_symlink(), "contract_reports_missing")
    paths = sorted(root.rglob("TEST-*.xml"))
    require(0 < len(paths) <= 100, "contract_reports_missing_or_excessive")
    seen = set()
    for path in paths:
        require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 4*1024*1024,
                "invalid_contract_report")
        data = path.read_bytes()
        require(b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(),
                "invalid_contract_report")
        tree = ET.fromstring(data)
        require(tree.tag in ("testsuite", "testsuites"), "invalid_contract_report")
        for case in tree.iter("testcase"):
            name = case.get("classname","")+"."+case.get("name","")
            require(case.find("failure") is None and case.find("error") is None,
                    "hosted_test_failed")
            if name in CASES:
                require(name not in seen and case.find("skipped") is None, "contract_case_duplicate_or_skipped")
                seen.add(name)
    require(seen == CASES, "required_contract_cases_missing")
    return receipt(source_sha, source_tree, run_id)


def successful_run(gate, workflow, run_id, source_sha, job):
    require(type(run_id) is int and run_id > 0, "invalid_evidence_run_id")
    run = gate.api(f"actions/runs/{run_id}")
    gate.verify_run_identity(run, workflow, run_id, "workflow_dispatch", source_sha)
    require(run.get("run_attempt") == 1 and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and (run.get("actor") or {}).get("login") == gate.OWNER
            and (run.get("triggering_actor") or {}).get("login") == gate.OWNER,
            "hosted_run_unverified")
    result = gate.api(f"actions/runs/{run_id}/jobs?per_page=100")
    jobs = result["jobs"]
    require(result.get("total_count") == len(jobs)
            and len([j for j in jobs if j.get("name") == job and j.get("conclusion") == "success"]) == 1
            and all(j.get("conclusion") == "success" for j in jobs), "hosted_jobs_unverified")


def reconcile(gate, candidate, *, ci_run, compose_run, build_run):
    """Independently fetch exact source CI, build and named hosted fixture evidence."""
    import tempfile
    require(len({ci_run, compose_run, build_run}) == 3, "evidence_run_conflict")
    successful_run(gate, "ci.yml", ci_run, candidate.source_sha, "CI")
    successful_run(gate, "android-release-candidate.yml", build_run, candidate.source_sha, "build")
    successful_run(gate, WORKFLOW, compose_run, candidate.source_sha, "compose-ui")
    name = f"android-rc-contract-{compose_run}"
    listing = gate.api(f"actions/runs/{compose_run}/artifacts?per_page=100")
    rows = listing["artifacts"]
    require(listing.get("total_count") == len(rows), "contract_listing_incomplete")
    found = [x for x in rows if x.get("name") == name and x.get("expired") is False]
    require(len(found) == 1 and type(found[0].get("id")) is int and found[0]["id"] > 0,
            "contract_artifact_missing")
    artifact_id = found[0]["id"]
    meta = gate.api(f"actions/artifacts/{artifact_id}")
    require(meta.get("name") == name and meta.get("expired") is False
            and (meta.get("workflow_run") or {}).get("id") == compose_run
            and (meta.get("workflow_run") or {}).get("head_sha") == candidate.source_sha,
            "contract_artifact_identity_mismatch")
    with tempfile.TemporaryDirectory() as tmp:
        gate.download(compose_run, name, tmp)
        path = Path(tmp)/"contracts.json"
        require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 16384,
                "contract_artifact_invalid")
        payload = json.loads(path.read_text())
    require(payload == receipt(candidate.source_sha, candidate.source_tree, compose_run),
            "contract_receipt_mismatch")
    return {"ci_run":ci_run, "compose_run":compose_run, "build_run":build_run,
            "contract_artifact_id":artifact_id, "hosted_groups":dict.fromkeys(GROUPS,"pass")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(from_junit(args.report_dir, args.sha, args.tree, args.run_id), sort_keys=True))


if __name__ == "__main__":
    main()
