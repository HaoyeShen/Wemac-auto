"""Verify task completion after its submitting Frida script has been unloaded."""
from pathlib import Path
import json
import secrets
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wechat_aumac.native import NativeSession
from wechat_aumac.native.wire import text_request

profile='research/native-profile-4.2.0.json'
def pid():
    values=subprocess.check_output(['pgrep','-x','WeChat'],text=True).split()
    return int(values[0]) if len(values)==1 else None
initial=pid();crashes=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat-*.ips'))
report={'pid':initial,'passed':False}
try:
    target=json.loads(Path('research/test-recipient.json').read_text())
    with NativeSession(profile,mode='full') as wx:
        report['before']=wx._rpc('completionStatus')
        payload=text_request(target['receiver'],'native-close-check-20261112',int(time.time()),secrets.randbits(32))
        report['submission']=wx._rpc('submit',list(payload))
        if not report['submission'].get('submitted'):raise RuntimeError('native task rejected')
    report['cleanup_errors']=wx.cleanup_errors
    if wx.cleanup_errors:raise RuntimeError('cleanup error')
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if pid()!=initial:raise RuntimeError('process changed while callback was pending')
        time.sleep(.5)
    with NativeSession(profile,mode='inventory') as wx:
        report['after']=wx._rpc('completionStatus')
    report['new_crash_reports']=[str(p) for p in set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat-*.ips'))-crashes]
    report['passed']=(pid()==initial and int(report['after']['completed'])==int(report['before']['completed'])+1
                      and report['after']['failures']==report['before']['failures'] and not report['new_crash_reports'])
except Exception as exc:
    report['error']=str(exc)
finally:
    Path('research/pending-completion-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)
if not report['passed']:raise SystemExit(1)
