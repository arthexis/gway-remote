"""Fixed private installer for the root-owned execution observer."""
import json
import subprocess
import stat
from pathlib import Path

HELPER=Path('/usr/local/libexec/gway-mcp-external-health')


def deliver(operation, credential=None, *, run=subprocess.run):
    for path in (HELPER,*HELPER.parents):
        st=path.lstat()
        if st.st_uid!=0 or st.st_mode&0o022 or (not stat.S_ISREG(st.st_mode) if path==HELPER else not stat.S_ISDIR(st.st_mode)):
            raise PermissionError('untrusted observer installer')
    if operation=='probe_provision_status' and credential is None:
        flag='--probe-provision-status';raw=b''
    elif operation=='probe_provision_install' and type(credential) is dict:
        flag='--probe-provision-install';raw=json.dumps(credential,separators=(',',':')).encode('ascii')
    else:raise ValueError('invalid provisioning operation')
    if len(raw)>4096:raise ValueError('oversized private payload')
    try:
        result=run(['/usr/bin/sudo','-n','/usr/bin/python3','-I',str(HELPER),flag],input=raw,capture_output=True,check=True,timeout=10)
        if len(result.stdout)>1024:raise ValueError('invalid provisioning receipt')
        return json.loads(result.stdout)
    except (OSError,ValueError,subprocess.SubprocessError):raise PermissionError('private observer delivery failed') from None
