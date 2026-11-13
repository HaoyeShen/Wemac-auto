"""Exercise native request codecs locally. No submit RPC or task entry is used."""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'src'))
from wechat_aumac.native import NativeSession
from wechat_aumac.native.wire import blob, integer, text_request


def fixtures():
    # Required-field fixtures only. These are synthetic codec data, never valid
    # operational credentials or requests prepared for transmission.
    base=blob(1,b'')+integer(2,0)+blob(3,b'')+integer(4,0)+blob(5,b'')+integer(6,0)
    buffer=integer(1,0)+blob(2,b'')
    string=blob(1,'codec-only')
    image=(blob(1,base)+blob(2,string)+blob(3,string)+blob(4,string)
           +integer(5,0)+integer(6,0)+integer(7,0)+blob(8,buffer))
    video=(blob(1,base)+blob(2,'codec-only')+blob(3,'codec-only')+blob(4,'codec-only')
           +integer(5,0)+integer(6,0)+blob(7,buffer)+integer(8,0)+integer(9,0)
           +blob(10,buffer)+integer(11,0)+integer(12,0)+integer(13,0)+integer(14,0))
    action=integer(5,0)+integer(6,0)
    group=integer(1,0)+blob(3,action)
    return {'text':text_request('codec-only','codec-only',1,1),
            'image':image,'video':video,'sticker':blob(1,base)+integer(2,0),
            'voice':blob(10,base), 'moment_post':blob(1,base)+blob(2,buffer),
            'moment_interaction':blob(1,base)+blob(2,group),
            'moment_objectop':blob(1,base)+integer(2,0),
            'moment_timeline':blob(1,base)+integer(3,0),
            'moment_detail':blob(1,base)+integer(2,0)}


if __name__=='__main__':
    reports=[]
    before=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat*.ips'))
    with NativeSession(ROOT/'native-profile-4.2.0.json',mode='codec') as wx:
        status=wx.status()
        for kind,data in fixtures().items():
            result=wx.roundtrip(data,kind=kind)
            item={'kind':kind,'parsed':result.get('parsed',False),'input_bytes':len(data),
                  'output_bytes':len(result.get('bytes',[])),
                  'identical':result.get('parsed',False) and bytes(result.get('bytes',[]))==data}
            reports.append(item)
            print(json.dumps(item),flush=True)
        alive=wx.status()
    after=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat*.ips'))
    report={'timestamp':time.time(),'mode':'codec','session':status,'final_session':alive,
            'results':reports,'cleanup_errors':wx.cleanup_errors,
            'new_crash_reports':[str(p) for p in sorted(after-before)],'submitted':False,
            'operations_performed':['native constructor/parser/serializer/destructor only']}
    (ROOT/'request-codec-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    if not all(r['identical'] for r in reports):raise SystemExit(1)
