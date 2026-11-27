"""Interactive Watchtower console only; no MCP issuance or unattended CLI."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import select
import signal
import time
import sys
import tempfile
import uuid

from .activity_feed_http import GRANT_PATH, load_feed_grants, validate_grants
from .mcp_bearer import BearerRegistry, _lookup

DATABASE = Path("/var/lib/gway-mcp-auth/credentials.sqlite3")
AUTH = "gway-mcp-auth"
GATEWAY = "gway-mcp-gateway"
TYPES = ["agentops.accepted","agentops.finished","agentops.codex_failed",
         "agentops.interrupted","agentops.released","feed.provisioned"]
ID = re.compile(r"[a-f0-9]{24}\Z")


def grant(node, repositories):
    if not isinstance(node,str) or not re.fullmatch(r"gway-[0-9]{3,}",node) or not 1 <= len(repositories) <= 32:
        raise ValueError("explicit enrolled node and repositories required")
    if any(not re.fullmatch(r"arthexis/[A-Za-z0-9_.-]{1,100}", x) for x in repositories):
        raise ValueError("invalid repository allowlist")
    return {"enabled":True,"source":"/nodes/"+node,"nodes":[node],
            "repositories":[None,*sorted(set(repositories))],"types":TYPES}


def _child(account, action, payload, *, handler=None):
    """Private root-console child, never an externally callable issuer CLI."""
    if os.geteuid() != 0 or account not in (AUTH,GATEWAY):
        raise PermissionError("root operator required")
    who = pwd.getpwnam(account)
    readfd, writefd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(readfd)
            os.setgroups(os.getgrouplist(account,who.pw_gid))
            os.setgid(who.pw_gid)
            os.setuid(who.pw_uid)
            os.environ.clear()
            os.environ.update({"PATH":"/usr/bin:/bin","HOME":who.pw_dir})
            result = json.dumps((handler or internal)(action,payload)).encode("ascii")
            if len(result)>4096:
                raise RuntimeError("private result too large")
            os.write(writefd,result)
            os._exit(0)
        except BaseException:
            os._exit(1)
    os.close(writefd)
    try:
        raw = bytearray()
        deadline = time.monotonic()+25
        while True:
            remaining = deadline-time.monotonic()
            if remaining<=0 or not select.select([readfd],[],[],remaining)[0]:
                raise TimeoutError("private operation timed out")
            chunk = os.read(readfd,4097-len(raw))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw)>4096:
                raise RuntimeError("private response exceeds bound")
        _, result = os.waitpid(pid,0)
        pid = None
        if result != 0:
            raise RuntimeError("private provisioning operation failed")
        return json.loads(raw)
    finally:
        os.close(readfd)
        if pid is not None:
            try:
                os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid,0)


def check_child(registry, principal, key, *, revoke=False):
    """A node-reported ID may never revoke a root or another producer."""
    if not ID.fullmatch(principal) or not ID.fullmatch(key) or key == principal:
        raise PermissionError("invalid delegated producer identity")
    with registry._db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT c.scope, d.parent_id, p.scope FROM credentials c "
            "JOIN delegations d ON d.key_id=c.key_id "
            "JOIN credentials p ON p.key_id=d.parent_id WHERE c.key_id=?",
            (key,)).fetchone()
        if row != ("gway:feed-publish", principal, "gway:feed-publish"):
            raise PermissionError("credential does not belong to this producer")
        if revoke:
            db.execute("UPDATE credentials SET revoked_at=? WHERE key_id=? AND revoked_at IS NULL",
                       (int(time.time()), key))
    return {"verified":True}


def internal(action, payload):
    account = AUTH if action in ("issue","revoke","check-child") else GATEWAY
    if os.geteuid() != pwd.getpwnam(account).pw_uid:
        raise PermissionError("incorrect service owner")
    if action == "issue":
        if set(payload) != {"principal","days"} or type(payload["days"]) is not int or not 1<=payload["days"]<=30:
            raise ValueError("invalid credential request")
        if not DATABASE.is_file() or DATABASE.is_symlink():
            raise PermissionError("existing issuer database required")
        registry = BearerRegistry(DATABASE)
        principal = payload["principal"]
        if principal is None:
            root = registry.issue(scope="gway:feed-publish",lifetime=90*86400,operator_approved=True)
            principal = root.split("_",2)[1]
            del root
        elif not ID.fullmatch(principal):
            raise ValueError("invalid publisher principal")
        row = _lookup(DATABASE, principal)
        if not row or row[1] != "gway:feed-publish" or row[3] is not None:
            raise PermissionError("publisher principal unavailable")
        try:
            token = registry.issue(scope="gway:feed-publish",lifetime=payload["days"]*86400,
                                   parent_id=principal)
        except BaseException:
            if payload["principal"] is None:
                registry.revoke(principal)
            raise
        return {"principal":principal,"credential":token}
    if action in ("revoke","check-child"):
        if set(payload) != {"id","principal"}:
            raise ValueError("invalid delegated credential request")
        return check_child(BearerRegistry(DATABASE),payload["principal"],payload["id"],
                           revoke=action=="revoke")
    from .watchtower_exec_service import load_service
    from .watchtower_exec_transport import pinned_transport
    if action == "status" and set(payload) == {"node"}:
        operation = "feed_provision_status"
    elif action == "install" and set(payload) == {"node","principal","credential"}:
        operation = "feed_provision_install"
    else:
        raise ValueError("invalid private delivery operation")
    rid = uuid.uuid4().hex
    transport = pinned_transport(load_service().relay.transport,payload["node"])
    if transport.node.remote_user == "gway-exec":
        raise PermissionError("installation-user transport required")
    response = transport.invoke({"operation":operation,"request_id":rid,**payload})
    return response["result"]


def save_grants(grants):
    validate_grants(grants)
    fd, name = tempfile.mkstemp(dir=GRANT_PATH.parent, prefix=".feed-grants-")
    try:
        with os.fdopen(fd,"w") as stream:
            os.fchmod(stream.fileno(),0o644)
            json.dump({"schema":1,"grants":grants},stream,sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name,GRANT_PATH)
        fd = os.open(GRANT_PATH.parent,os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(name).unlink(missing_ok=True)


def provision(node, repositories, days, *, child=_child, read=load_feed_grants, save=save_grants):
    policy = grant(node,repositories)
    old = child(GATEWAY,"status",{"node":node})
    grants = read()
    # An existing source may only rotate under the exact same policy.
    matching = [p for p,g in grants.items() if g["source"]==policy["source"]]
    if len(matching)>1:
        raise PermissionError("ambiguous producer grant")
    principal = matching[0] if matching else None
    if principal is not None and grants[principal] != policy:
        raise PermissionError("existing grant differs; review policy separately")
    if old.get("configured") and (old.get("principal")!=principal or not ID.fullmatch(old.get("credential_id",""))):
        raise PermissionError("existing node binding differs")
    if old.get("configured"):
        if child(AUTH,"check-child",{"id":old["credential_id"],"principal":principal}) != {"verified":True}:
            raise PermissionError("existing credential lineage unverified")
    issued = child(AUTH,"issue",{"principal":principal,"days":days})
    from .activity_feed_provision_node import TOKEN
    token = TOKEN.fullmatch(issued["credential"])
    if not token or not ID.fullmatch(issued["principal"]):
        raise RuntimeError("invalid private issuer receipt")
    key = token[1]
    root = issued["principal"]
    try:
        if principal is not None and root != principal:
            raise PermissionError("issuer changed producer identity")
        if principal is None:
            save({**grants,root:policy})
        receipt = child(GATEWAY,"install",{"node":node,"principal":root,"credential":issued["credential"]})
        if receipt != {"configured":True,"principal":root,"credential_id":key,"delivered":True}:
            raise RuntimeError("uncorrelated delivery")
    except BaseException:
        # The node may have committed the pointer before losing its ACK.
        # Keep the stable grant/root for retry; revoke only the uncertain child.
        child(AUTH,"revoke",{"id":key,"principal":root})
        raise
    if old.get("configured") and old["credential_id"] != key:
        child(AUTH,"revoke",{"id":old["credential_id"],"principal":root})
    return {"node":node,"configured":True,"scope":"gway:feed-publish",
            "delivery":"verified","rotation":bool(old.get("configured"))}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("node",nargs="?")
    p.add_argument("--repository",action="append",default=[])
    p.add_argument("--days",type=int,default=30)
    args = p.parse_args(argv)
    try:
        if os.geteuid()!=0 or not sys.stdin.isatty() or not sys.stdout.isatty():
            raise PermissionError("interactive Watchtower root console required")
        if not 1<=args.days<=30:
            raise ValueError("invalid credential lifetime")
        policy = grant(args.node,args.repository)
        print("Provision feed-only AgentOps publisher for",args.node,
              "repositories:",", ".join(x for x in policy["repositories"] if x))
        if input("Type the node name to confirm: ").strip()!=args.node:
            raise PermissionError("operator confirmation required")
        # No automatic privilege elevation, arbitrary target, or log output.
        lock = os.open(GRANT_PATH.parent/"activity-feed-provision.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            print(json.dumps(provision(args.node,args.repository,args.days),sort_keys=True))
        finally:
            os.close(lock)
        return 0
    except (Exception,KeyboardInterrupt):
        print("Feed provisioning unavailable; review operator receipt and retry only after reconciliation.",file=sys.stderr)
        return 1
