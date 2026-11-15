"""Bounded, GET-only GitHub branch rules and commit checks for MCP."""
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .github_workflows_mcp import _allowed, WorkflowError

_SHA = re.compile(r"^[0-9a-f]{40}$")
_BRANCH = re.compile(r"^[A-Za-z0-9_.\/-]{1,200}$")
PAGE_SIZE = 100
MAX_PAGES = 10
MAX_BYTES = 256 * 1024


def _get(repository, path, params=None):
    """Only a caller-selected, allowlisted repository; paths built internally."""
    _allowed(repository)
    token = os.environ.get("GWAY_MCP_GITHUB_TOKEN")
    if not token:
        raise WorkflowError("github_not_configured")
    url = "https://api.github.com/repos/" + repository + "/" + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }, method="GET")
    try:
        with urlopen(req, timeout=10) as response:
            body = response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        if code in (401, 403, 404, 429):
            raise WorkflowError("github_http_" + str(code)) from None
        raise WorkflowError("github_unavailable") from None
    except (URLError, TimeoutError, OSError):
        raise WorkflowError("github_unavailable") from None
    if len(body) > MAX_BYTES:
        raise WorkflowError("github_response_too_large")
    try:
        return json.loads(body)
    except (UnicodeError, ValueError):
        raise WorkflowError("github_invalid_response") from None


def _pages(repository, path, key):
    """Fail closed on missing counts, truncated pages, duplicates and page cap."""
    result = []
    seen = set()
    total = None
    for page in range(1, MAX_PAGES + 1):
        data = _get(repository, path, {"per_page": PAGE_SIZE, "page": page})
        if not isinstance(data, dict) or type(data.get("total_count")) is not int:
            raise WorkflowError("github_invalid_response")
        entries = data.get(key)
        if not isinstance(entries, list) or data["total_count"] < 0:
            raise WorkflowError("github_invalid_response")
        if total is None:
            total = data["total_count"]
        elif total != data["total_count"]:
            raise WorkflowError("github_inconsistent_pagination")
        for item in entries:
            if not isinstance(item, dict) or type(item.get("id")) is not int:
                raise WorkflowError("github_invalid_response")
            if item["id"] in seen:
                raise WorkflowError("github_inconsistent_pagination")
            seen.add(item["id"])
            result.append(item)
        if len(result) == total:
            return result
        if len(result) > total or len(entries) != PAGE_SIZE:
            raise WorkflowError("github_incomplete_pagination")
    raise WorkflowError("github_incomplete_pagination")


def branch_effective_rules(args):
    if type(args) is not dict or set(args) != {"repository", "branch"}:
        raise ValueError("invalid_arguments")
    repository = _allowed(args["repository"])
    branch = args["branch"]
    if type(branch) is not str or not _BRANCH.fullmatch(branch) or ".." in branch or branch.startswith(("/", ".")):
        raise ValueError("invalid_branch")
    # GitHub's effective-rules endpoint returns an array, not a ruleset object.
    data = _get(repository, "rules/branches/" + quote(branch, safe=""))
    if not isinstance(data, list) or len(data) > 100:
        raise WorkflowError("github_invalid_response")
    rules = []
    for rule in data:
        if not isinstance(rule, dict) or type(rule.get("type")) is not str:
            raise WorkflowError("github_invalid_response")
        rules.append({
            "type": rule["type"],
            "ruleset_id": rule.get("ruleset_id"),
            "ruleset_source_type": rule.get("ruleset_source_type"),
            "ruleset_source": rule.get("ruleset_source"),
            "parameters": rule.get("parameters"),
        })
    return {"schema": "github/rules/v1", "source": "github_live",
            "repository": repository, "branch": branch,
            "complete": True, "rules": rules}


def commit_checks(args):
    if type(args) is not dict or set(args) != {"repository", "sha"}:
        raise ValueError("invalid_arguments")
    repository = _allowed(args["repository"])
    sha = args["sha"]
    if type(sha) is not str or not _SHA.fullmatch(sha):
        raise ValueError("invalid_sha")
    checks = _pages(repository, "commits/" + sha + "/check-runs", "check_runs")
    statuses = _pages(repository, "commits/" + sha + "/statuses", "statuses") if False else None
    # Classic commit statuses are an array endpoint, paginated without total_count.
    classic = []
    for page in range(1, MAX_PAGES + 1):
        chunk = _get(repository, "commits/" + sha + "/statuses",
                     {"per_page": PAGE_SIZE, "page": page})
        if not isinstance(chunk, list) or any(not isinstance(x, dict) for x in chunk):
            raise WorkflowError("github_invalid_response")
        classic.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            break
    else:
        raise WorkflowError("github_incomplete_pagination")
    normalized = []
    for item in checks:
        app = item.get("app")
        if item.get("head_sha") != sha or not isinstance(app, (dict, type(None))):
            raise WorkflowError("github_invalid_response")
        normalized.append({"id": item["id"], "name": item.get("name"),
                           "status": item.get("status"), "conclusion": item.get("conclusion"),
                           "app_id": app.get("id") if app else None,
                           "details_url": item.get("details_url")})
    states = []
    for item in classic:
        if item.get("sha") not in (None, sha):
            raise WorkflowError("github_invalid_response")
        states.append({"id": item.get("id"), "context": item.get("context"),
                       "state": item.get("state"), "creator_id": (item.get("creator") or {}).get("id")})
    return {"schema": "github/checks/v1", "source": "github_live",
            "repository": repository, "sha": sha, "complete": True,
            "check_runs": normalized, "statuses": states}
