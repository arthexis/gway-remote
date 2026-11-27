import importlib.util
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

path=Path(__file__).resolve().parents[2]/'scripts/mcp-health-recovery.py'
spec=importlib.util.spec_from_file_location('mcp_health_recovery',path)
r=importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def scenario(verify):
    state={'LoadState':'loaded','UnitFileState':'enabled','ActiveState':'failed','InvocationID':'0'*32}
    calls=[]
    def run(argv,**kw):
        calls.append(argv)
        if 'start' in argv:
            state.update(ActiveState='active',InvocationID='1'*32)
        else:
            state.update(ActiveState='inactive',InvocationID='0'*32)
        return SimpleNamespace(returncode=0)
    def local():
        return ('protected' if verify else 'unexpected_access') if state['ActiveState']=='active' else 'absent'
    result=r.repair('a'*40,inspect=lambda:dict(state),local=local,pin=lambda _:True,run=run,sleep=lambda _:None,acquire=lambda _:os.open('/dev/null',os.O_RDONLY))
    return result,calls


class RecoveryRecipeTests(unittest.TestCase):
    def test_inactive_enabled_pinned_only(self):
        s={'LoadState':'loaded','UnitFileState':'enabled','ActiveState':'failed'}
        assert r.eligible('a'*40,pin=lambda _:True,inspect=lambda:s,local=lambda:'absent')
        assert not r.eligible('a'*40,pin=lambda _:True,inspect=lambda:s,local=lambda:'unknown')
        s['ActiveState']='active'
        assert not r.eligible('a'*40,pin=lambda _:True,inspect=lambda:s,local=lambda:'absent')
        s['ActiveState']='failed';s['UnitFileState']='disabled'
        assert not r.eligible('a'*40,pin=lambda _:True,inspect=lambda:s,local=lambda:'absent')


    def test_success_only_starts_fixed_service(self):
        result,calls=scenario(True)
        assert result=={'outcome':'applied'}
        assert calls==[['/usr/bin/systemctl','--user','start',r.UNIT]]


    def test_failed_verification_rolls_back_own_invocation(self):
        result,calls=scenario(False)
        assert result=={'outcome':'rolled_back'}
        assert calls==[['/usr/bin/systemctl','--user','start',r.UNIT],['/usr/bin/systemctl','--user','stop',r.UNIT]]
