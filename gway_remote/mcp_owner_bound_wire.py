"""Owner-bound RPC v1 over the existing authenticated forced-command channel.

The SSH peer is the attester. The digest is only an argument binding, not a
signature. Local shell operators are inside the existing trust boundary.
"""
import os
import re
import sqlite3
import time
from pathlib import Path
from .mcp_federated_auth_context import arguments_sha256
from .mcp_principal_admission import owner_bound,validate_principal,validate_owner_arguments

OPS={"provider_owner_read":"read","provider_owner_execute":"execute"}
FIELDS={"operation","node","request_id","provider","tool","arguments","principal","issued_at","arguments_sha256"}
TTL=90
CAP=4096

def make_payload(node,request,scope,principal,rid,now=None):
    if scope not in OPS.values() or set(request)!={"provider","tool","arguments"}:
        raise ValueError("invalid_owner_request")
    out={**request,"operation":"provider_owner_"+scope,"node":node,
         "request_id":rid,"principal":principal,"issued_at":int(time.time() if now is None else now),
         "arguments_sha256":arguments_sha256(request["arguments"])}
    validate(out,node,now=now)
    return out

def validate(req,node,*,now=None):
    if type(req) is not dict or set(req)!=FIELDS or type(req["operation"]) is not str or req["operation"] not in OPS:
        raise PermissionError("invalid_owner_envelope")
    if req["node"]!=node or not owner_bound(req["provider"]):
        raise PermissionError("owner_route_denied")
    if type(req["tool"]) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}",req["tool"]):
        raise PermissionError("owner_tool_denied")
    if type(req["request_id"]) is not str or not re.fullmatch(r"[0-9a-f]{32}",req["request_id"]):
        raise PermissionError("owner_request_id_denied")
    validate_principal(req["principal"])
    validate_owner_arguments(req["arguments"])
    current=int(time.time() if now is None else now)
    if type(req["issued_at"]) is not int or not current-TTL<=req["issued_at"]<=current+5:
        raise PermissionError("owner_request_expired")
    if req["arguments_sha256"]!=arguments_sha256(req["arguments"]):
        raise PermissionError("owner_arguments_mismatch")
    return OPS[req["operation"]]

def reserve(req,*,directory=None,now=None):
    """Durably reserve before dispatch; expired IDs cannot pass the time gate."""
    current=int(time.time() if now is None else now)
    validate(req,req["node"],now=current)
    root=Path(directory) if directory is not None else Path.home()/".local/state/gway-owner-rpc"
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    info=root.stat()
    if root.resolve()!=root.absolute() or info.st_uid!=os.geteuid() or info.st_mode&0o077:
        raise PermissionError("unsafe_owner_replay_store")
    dbpath=root/"replay.sqlite3"
    if dbpath.is_symlink() or (dbpath.exists() and (dbpath.stat().st_uid!=os.geteuid() or dbpath.stat().st_mode&0o077)):
        raise PermissionError("unsafe_owner_replay_db")
    fd=os.open(dbpath,os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
    os.close(fd)
    with sqlite3.connect(dbpath,timeout=2) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS seen (rid TEXT PRIMARY KEY, expires INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS clock (id INTEGER PRIMARY KEY CHECK(id=1), highwater INTEGER NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        highwater=db.execute("SELECT highwater FROM clock WHERE id=1").fetchone()
        if highwater and current<highwater[0]:
            raise PermissionError("owner_replay_clock_regressed")
        db.execute("INSERT OR REPLACE INTO clock VALUES (1,?)",(current,))
        db.execute("DELETE FROM seen WHERE expires < ?",(current,))
        if db.execute("SELECT COUNT(*) FROM seen").fetchone()[0]>=CAP:
            raise PermissionError("owner_replay_capacity")
        try:
            db.execute("INSERT INTO seen VALUES (?,?)",(req["request_id"],req["issued_at"]+TTL))
        except sqlite3.IntegrityError:
            raise PermissionError("owner_request_replayed") from None
