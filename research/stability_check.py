"""Bounded stability regression using one agent, never parallel controllers."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wechat_aumac.native import NativeSession
from wechat_aumac.native.wire import text_request


def current_pid():
    result=subprocess.run(['pgrep','-x','WeChat'],capture_output=True,text=True)
    values=result.stdout.split()
    return int(values[0]) if len(values)==1 else None


def reports():
    return {str(p) for p in Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat-*.ips')}


p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--seconds',type=float,default=60)
p.add_argument('--send-test',action='store_true')
args=p.parse_args()
if args.seconds<=0:raise SystemExit('seconds must be positive')
initial=current_pid();before=reports()
report={'initial_pid':initial,'phases':[],'new_crash_reports':[],'passed':False}
try:
    for mode,duration in [('inventory',15),('receive',args.seconds),('full',args.seconds)]:
        entry={'mode':mode,'planned_seconds':duration,'events':{},'passed':False}
        report['phases'].append(entry)
        start=time.monotonic()
        with NativeSession('research/native-profile-4.2.0.json',mode=mode) as wx:
            entry['status']=wx.status()
            if mode=='full':
                entry['completion_before']=wx._rpc('completionStatus')
                payload=text_request('filehelper','codec stability 中文😀',int(time.time()),987654321)
                for _ in range(10):
                    result=wx.roundtrip(payload)
                    if not result.get('parsed') or bytes(result['bytes'])!=payload:
                        raise RuntimeError('native codec roundtrip mismatch')
                entry['codec_roundtrips']=10
                if args.send_test:
                    target=json.loads(Path('research/test-recipient.json').read_text())
                    entry['send']=wx.send_text(target['receiver'],'native-stability-check-20261112')
                    if entry['send']['status']!='acknowledged':raise RuntimeError('text send was not acknowledged')
            counts=Counter()
            while time.monotonic()-start<duration:
                if current_pid()!=initial or wx._detached:raise RuntimeError('WeChat exited or changed PID')
                event=wx.next_event(timeout=.5)
                if event:
                    counts[event.get('event')]+=1
                    if event.get('event') in ('probe_error','decode_error'):raise RuntimeError(event.get('detail'))
            entry['events']=dict(counts)
            entry['observed_messages']=len(wx.read(limit=2000))
            if mode=='full':
                entry['completion_after']=wx._rpc('completionStatus')
                if args.send_test and int(entry['completion_after']['completed'])<=int(entry['completion_before']['completed']):
                    raise RuntimeError('Native completion callback did not execute')
            entry['dropped_events']=wx.dropped_events
        entry['cleanup_errors']=wx.cleanup_errors
        if wx.cleanup_errors:raise RuntimeError('agent cleanup failed')
        if current_pid()!=initial:raise RuntimeError('process changed after detach')
        entry['elapsed_seconds']=round(time.monotonic()-start,2)
        entry['passed']=True
        print(json.dumps(entry),flush=True)
        Path('research/stability-verification.json').write_text(json.dumps(report,indent=2))
    report['passed']=current_pid()==initial and not (reports()-before)
except Exception as exc:
    report['error']=str(exc)
finally:
    report['final_pid']=current_pid()
    report['new_crash_reports']=sorted(reports()-before)
    Path('research/stability-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'passed':report['passed'],'error':report.get('error'),'final_pid':report['final_pid'],'new_crashes':len(report['new_crash_reports'])}),flush=True)
if not report['passed']:raise SystemExit(1)
