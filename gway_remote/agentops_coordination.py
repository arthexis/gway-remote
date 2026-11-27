"""Durable internal AgentOps reservation authority; no MCP/public HTTP surface.

A node identity is derived exclusively from the existing pinned SSH route.
The database is initialized explicitly after all-node quiescence and a
reviewed historical seed; normal operations never create/reset it.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess

HEX = re.compile(r"[a-f0-9]{64}\Z")
TOKEN = re.compile(r"[a-f0-9]{32}\Z")
NODE = re.compile(r"gway-[0-9]{3}\Z")
MAX_HISTORY = 100000
MAX_BATCH = 32
OPS = {"agentops_coordination_snapshot": frozenset({"operation","node","request_id","epoch"}),
       "agentops_coordination_apply": frozenset({"operation","node","request_id","epoch","decisions"})}
CONFIG = Path("/etc/gway-mcp/agentops-coordination.json")
DATABASE = Path("/var/lib/gway-mcp-exec/agentops-coordination.sqlite3")


def require(ok):
    if not ok:
        raise ValueError("agentops_coordination_unavailable")


def now():
    return datetime.now(timezone.utc).isoformat()


def matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def membership(epoch, members):
    require(matches(TOKEN, epoch) and type(members) is list
            and 1 <= len(members) <= 32 and len(set(members)) == len(members)
            and all(matches(NODE, node) for node in members))


def entry(row, *, decision=False):
    keys = {"repo","identity","token","state"}
    require(type(row) is dict and set(row) == keys
            and matches(HEX,row["repo"]) and matches(HEX,row["identity"])
            and matches(TOKEN,row["token"])
            and row["state"] in (("reserved","busy","replayed","released") if decision
                                 else ("pending","terminal")))
    return row


def batch(rows, *, decision=False):
    require(type(rows) is list and len(rows) <= MAX_BATCH)
    for row in rows:
        entry(row, decision=decision)
    require(len({r["identity"] for r in rows}) == len(rows))
    return rows


class Ledger:
    def __init__(self, path, *, epoch, members):
        membership(epoch,members)
        self.path = Path(path)
        self.epoch = epoch
        self.members = sorted(members)

    def _check(self, *, exists=True):
        info = self.path.parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and not info.st_mode & 0o077)
        if exists:
            info = self.path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and not info.st_mode & 0o077 and info.st_nlink == 1)

    def initialize(self, history):
        """Explicit, one-time seed. Never silently replace an old ledger."""
        require(type(history) is list and len(history) <= MAX_HISTORY
                and all(matches(HEX,x) for x in history) and len(set(history)) == len(history))
        self._check(exists=False)
        fd = os.open(self.path, os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        os.close(fd)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                db.execute("CREATE TABLE meta (epoch TEXT NOT NULL, members TEXT NOT NULL)")
                db.execute("""CREATE TABLE reservations (
                    identity TEXT PRIMARY KEY, repo TEXT, node TEXT, token TEXT,
                    state TEXT NOT NULL CHECK(state IN ('historical','reserved','released')),
                    created_at TEXT NOT NULL, released_at TEXT)""")
                db.execute("CREATE UNIQUE INDEX active_repo ON reservations(repo) WHERE state='reserved'")
                db.execute("INSERT INTO meta VALUES (?,?)",(self.epoch,json.dumps(self.members)))
                db.executemany("INSERT INTO reservations(identity,state,created_at) VALUES (?,'historical',?)",
                               [(identity,now()) for identity in history])
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        self._check()
        db = sqlite3.connect(self.path.resolve().as_uri()+"?mode=rw",uri=True,timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            require([tuple(r) for r in db.execute("SELECT epoch,members FROM meta")]
                    == [(self.epoch,json.dumps(self.members))])
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def resolve(self,node,row):
        require(node in self.members)
        entry(row)
        repo,identity,token = row["repo"],row["identity"],row["token"]
        with self.transaction() as db:
            old=db.execute("SELECT * FROM reservations WHERE identity=?",(identity,)).fetchone()
            same=bool(old and (old["repo"],old["node"],old["token"])==(repo,node,token))
            if row["state"]=="terminal":
                # Never release another owner or infer termination from age.
                require(same and old["state"] in ("reserved","released"))
                if old["state"]=="reserved":
                    db.execute("UPDATE reservations SET state='released',released_at=? WHERE identity=?",
                               (now(),identity))
                state="released"
            elif old:
                state="reserved" if same and old["state"]=="reserved" else "replayed"
            elif db.execute("SELECT 1 FROM reservations WHERE repo=? AND state='reserved'",(repo,)).fetchone():
                state="busy"
            else:
                require(db.execute("SELECT count(*) FROM reservations").fetchone()[0]<MAX_HISTORY)
                db.execute("INSERT INTO reservations VALUES (?,?,?,?,'reserved',?,NULL)",
                           (identity,repo,node,token,now()))
                state="reserved"
        return {**row,"state":state}

    def counts(self):
        with self.transaction() as db:
            return {r[0]:r[1] for r in db.execute("SELECT state,count(*) FROM reservations GROUP BY state")}


def exchange(transport,node,epoch,operation,decisions=None):
    require(matches(NODE,node) and matches(TOKEN,epoch) and operation in OPS)
    rid=secrets.token_hex(16)
    payload={"node":node,"epoch":epoch,"operation":operation,"request_id":rid}
    if operation=="agentops_coordination_apply":
        payload["decisions"]=batch(decisions,decision=True)
    result=transport.invoke(payload)
    require(type(result) is dict and set(result)=={"node","request_id","result"}
            and result["node"]==node and result["request_id"]==rid)
    data=result["result"]
    require(type(data) is dict and data.get("epoch")==epoch and data.get("node")==node)
    if operation=="agentops_coordination_snapshot":
        require(set(data)=={"epoch","node","intents"})
        return batch(data["intents"])
    require(set(data)=={"epoch","node","applied"} and data["applied"]==len(decisions))
    return data["applied"]


def tick(ledger,transport):
    """One bounded internal poll; no retries of worker launches, no public RPC.
    A committed grant survives an uncertain response. Re-reading the identical
    pending intent returns exactly that grant; terminal proof is idempotent.
    """
    outcomes={}
    for node in ledger.members:
        try:
            rows=exchange(transport,node,ledger.epoch,"agentops_coordination_snapshot")
            results=[ledger.resolve(node,row) for row in rows]
            if results:
                exchange(transport,node,ledger.epoch,"agentops_coordination_apply",results)
            outcomes[node]={"state":"ok","intents":len(rows)}
        except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error,subprocess.SubprocessError):
            outcomes[node]={"state":"unavailable"}
    return outcomes


def node_exchange(host,req,*,registrations=None,runner=subprocess.run):
    """Only called from the fixed trusted SSH receiver, never public federation."""
    require(matches(NODE,host) and req.get("node")==host and matches(TOKEN,req.get("epoch")))
    op=req.get("operation")
    require(op in OPS and set(req)==OPS[op])
    if op=="agentops_coordination_apply":
        batch(req["decisions"],decision=True)
    from .mcp_installed_providers import discover_installed_providers
    from .mcp_node_providers import _registration
    reg=_registration(discover_installed_providers() if registrations is None else registrations,"agentops")
    expected=Path.home()/".local/share/gway-agent-ops/releases"/reg.revision/"bin"/"agent-mcp"
    require(Path(reg.executable)==expected)
    exe=expected.with_name("agent")
    require(exe.is_file() and not exe.is_symlink() and os.access(exe,os.X_OK))
    data={"operation":"snapshot" if op.endswith("snapshot") else "apply","epoch":req["epoch"]}
    if op.endswith("apply"):
        data["decisions"]=req["decisions"]
    result=runner([str(exe),"coordination-exchange"],input=json.dumps(data),
                  text=True,capture_output=True,check=False,timeout=8,cwd="/",
                  env={"HOME":str(Path.home()),"PATH":"/usr/bin:/bin","LANG":"C.UTF-8"})
    require(result.returncode==0 and len(result.stdout)<=32768)
    result=json.loads(result.stdout)
    require(type(result) is dict and result.get("epoch")==req["epoch"] and result.get("node")==host)
    return result


def load_config(path=CONFIG):
    info=Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022
            and info.st_nlink==1 and info.st_size<=4096)
    data=json.loads(Path(path).read_text())
    require(type(data) is dict and set(data)=={"schema","epoch","members"} and data["schema"]==1)
    membership(data["epoch"],data["members"])
    return data


def main():
    # Private operator/systemd one-shot entrypoint. No server/listener.
    cfg=load_config()
    from .watchtower_exec_service import load_service
    ledger=Ledger(DATABASE,epoch=cfg["epoch"],members=cfg["members"])
    service=load_service()
    print(json.dumps(tick(ledger,service.relay.transport),sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
