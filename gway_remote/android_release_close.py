"""Close release-tracked issues only after the signed asset has been verified."""
import hashlib
import re
from pathlib import Path

from gway_remote.android_release_gate import OWNER, REPO, SHA, api, gh, release_issues, require


def verify_release(release, resolved_sha, tag, sha, digest):
    require(SHA.fullmatch(sha) and resolved_sha == sha
            and release["tag_name"] == tag and release["target_commitish"] == sha
            and not release["draft"] and not release["prerelease"], "release identity mismatch")
    notes = release.get("body") or ""
    require(re.findall(r"(?m)^Source-Commit: ([a-f0-9]{40})\s*$", notes) == [sha]
            and re.findall(r"(?m)^APK-SHA256: ([a-f0-9]{64})\s*$", notes) == [digest],
            "release metadata mismatch")
    assets = [a for a in release["assets"] if a["name"] == "gway-remote.apk"]
    require(len(assets) == 1 and assets[0]["state"] == "uploaded"
            and assets[0]["size"] > 10000 and assets[0].get("digest") == "sha256:" + digest,
            "published asset digest mismatch")


def close(tag, sha, apk):
    digest = hashlib.sha256(Path(apk).read_bytes()).hexdigest()
    require(re.fullmatch(r"android-v0\.2\.[0-9]+", tag), "unexpected release tag")
    release = api(f"releases/tags/{tag}")
    verify_release(release, api(f"commits/{tag}")["sha"], tag, sha, digest)
    prs = [p for p in api(f"commits/{sha}/pulls?per_page=100")
           if p.get("merge_commit_sha") == sha and p.get("merged_at")]
    if not prs:
        return
    require(len(prs) == 1, "ambiguous release PR")
    p = prs[0]
    body = p.get("body") or ""
    commit_message = api(f"commits/{sha}")["commit"]["message"]
    if not re.search(r"(?m)^Release-Issue: #", body + "\n" + commit_message):
        return
    require(p["base"]["ref"] == "main" and p["user"]["login"] == OWNER
            and p["head"]["repo"] and p["head"]["repo"]["full_name"] == REPO,
            "release PR not owner-authorized")
    issues = release_issues(commit_message)
    require(issues and issues == release_issues(body), "immutable release links differ from PR")
    rows = [api(f"issues/{n}") for n in issues]
    require(all("pull_request" not in row for row in rows), "release link is not an issue")
    for n, row in zip(issues, rows):
        if row["state"] == "open":
            gh("issue", "close", str(n), "-R", REPO, "--comment",
               f"Verified signed Android release {release['html_url']} at {sha}; APK SHA256 {digest}.")


if __name__ == "__main__":
    import sys
    close(*sys.argv[1:])
