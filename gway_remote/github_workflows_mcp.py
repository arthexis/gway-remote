"""Bounded, read-only GitHub Actions API adapter for MCP."""
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .target_export import export_targets

MAX_BYTES = 256 * 1024
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class WorkflowError(RuntimeError):
    pass


def _allowed(repository):
    allowed = {row["repository"] for row in export_targets()["targets"]}
    if repository not in allowed or not _REPO.fullmatch(repository):
        raise ValueError("repository_not_allowed")
    return repository


def _positive(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("invalid_number")
    return value


def _request(repository, path, params=None, *, binary=False):
    _allowed(repository)
    token = os.environ.get("GWAY_MCP_GITHUB_TOKEN")
    if not token:
        raise WorkflowError("github_not_configured")
    url = "https://api.github.com/repos/" + repository + "/actions/" + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Authorization": "Bearer " + token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"}, method="GET")
    try:
        with urlopen(req, timeout=10) as response:
            data = response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        exc.close()
        if exc.code in (401, 403, 404, 429):
            raise WorkflowError("github_http_" + str(exc.code)) from None
        raise WorkflowError("github_unavailable") from None
    except (URLError, TimeoutError, OSError):
        raise WorkflowError("github_unavailable") from None
    if len(data) > MAX_BYTES:
        raise WorkflowError("github_response_too_large")
    if binary:
        return data
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError):
        raise WorkflowError("github_invalid_response") from None
    if not isinstance(result, dict):
        raise WorkflowError("github_invalid_response")
    return result


def _fields(item, fields):
    if not isinstance(item, dict):
        raise WorkflowError("github_invalid_response")
    return {field: item.get(field) for field in fields}


RUN = ("id", "name", "workflow_id", "head_branch", "head_sha", "event",
       "status", "conclusion", "created_at", "updated_at", "html_url")
JOB = ("id", "name", "status", "conclusion", "started_at", "completed_at", "html_url")
STEP = ("name", "number", "status", "conclusion", "started_at", "completed_at")


def runs(args):
    if type(args) is not dict or set(args) - {"repository", "branch", "status", "event", "limit"}:
        raise ValueError("invalid_arguments")
    limit = _positive(args.get("limit", 10), 20)
    repos = [args["repository"]] if "repository" in args else [
        row["repository"] for row in export_targets()["targets"]]
    for repo in repos:
        _allowed(repo)
    params = {"per_page": limit, "page": 1}
    for key in ("branch", "event"):
        if key in args:
            v = args[key]
            if type(v) is not str or not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", v):
                raise ValueError("invalid_filter")
            params[key] = v
    if "status" in args:
        if args["status"] not in ("queued", "in_progress", "completed", "success",
                                   "failure", "cancelled", "timed_out", "neutral"):
            raise ValueError("invalid_filter")
        params["status"] = args["status"]
    results = []
    for repo in repos:
        _allowed(repo)
        data = _request(repo, "runs", params)
        items = data.get("workflow_runs")
        if not isinstance(items, list):
            raise WorkflowError("github_invalid_response")
        results.extend({"repository": repo, **_fields(x, RUN)} for x in items[:limit])
    return {"source": "github_live", "runs": results}


def status(args):
    if type(args) is not dict or set(args) != {"repository", "run_id"}:
        raise ValueError("invalid_arguments")
    repo, run_id = args["repository"], _positive(args["run_id"], 10**18)
    run = _request(repo, "runs/" + str(run_id))
    jobs = _request(repo, "runs/" + str(run_id) + "/jobs", {"per_page": 100})
    items = jobs.get("jobs")
    if not isinstance(items, list) or jobs.get("total_count", 0) > len(items):
        raise WorkflowError("github_jobs_truncated")
    return {"source": "github_live", "repository": repo, "run": _fields(run, RUN),
            "jobs": [{**_fields(j, JOB), "steps": [_fields(s, STEP) for s in j.get("steps", [])]}
                     for j in items]}


def errors(args):
    if type(args) is not dict or set(args) - {"repository", "run_id", "job_id", "limit"} or not {"repository", "run_id"} <= set(args):
        raise ValueError("invalid_arguments")
    repo, run_id = args["repository"], _positive(args["run_id"], 10**18)
    limit = _positive(args.get("limit", 20), 30)
    record = status({"repository": repo, "run_id": run_id})
    jobs = [j for j in record["jobs"] if j["conclusion"] == "failure"][:5]
    if "job_id" in args:
        job_id = _positive(args["job_id"], 10**18)
        jobs = [j for j in jobs if j["id"] == job_id]
    # Logs can contain arbitrary secrets despite masking. Do not export raw lines.
    # Return bounded job/step failure metadata instead of unsafe excerpts.
    summaries = []
    for job in jobs:
        detail = _request(repo, "jobs/" + str(job["id"]))
        summaries.append({"job": _fields(detail, JOB),
                          "failed_steps": [_fields(s, STEP) for s in detail.get("steps", [])
                                           if s.get("conclusion") == "failure"][:limit],
                          "log_excerpt": "withheld_untrusted_build_output"})
    return {"source": "github_live", "repository": repo, "run_id": run_id,
            "failures": summaries, "logs_available": False}
