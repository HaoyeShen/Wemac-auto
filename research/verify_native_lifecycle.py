"""Bounded read-only verification of one existing client; never launches WeChat."""
import json,time
from pathlib import Path
from wechat_aumac.native import NativeSession
from wechat_aumac.hook_probe import select_process
root=Path(__file__).parent;profile=root/'native-profile-isolated.json';p=json.loads(profile.read_text());pid=select_process(Path(p['app']))
report={'pid_before':pid,'restarts':0,'sends':0,'reads':0,'errors':[]}
wx=NativeSession(profile,mode='full');ready=time.monotonic()
try:
 wx.connect();own=wx.identity()['user_id'];print('CONNECTED to existing PID',pid,flush=True)
 for tick in range(12):
  contact=wx.get_contact(own);wx.get_sessions(limit=10);wx.status();report['reads']+=3
  if tick%3==0:print('READS',report['reads'],'elapsed',round(time.monotonic()-ready),flush=True)
  deadline=time.monotonic()+5
  while time.monotonic()<deadline:wx.next_event(timeout=.25)
except Exception as exc:report['errors'].append(str(exc))
finally:
 report['clean_close']=wx.close();report['cleanup_errors']=wx.cleanup_errors
 try:report['pid_after']=select_process(Path(p['app']))
 except Exception:report['pid_after']=None
 report['same_process']=report['pid_after']==pid
 report['seconds']=round(time.monotonic()-ready,1)
 (root/'native-lifecycle-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print('RESULT',json.dumps(report,ensure_ascii=False),flush=True)
