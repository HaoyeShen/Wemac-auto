"""One bounded image experiment, opt-in --send, to the previously bound test chat.

No UI send, retries, or Moments paths. A negative/unknown result is not success.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'src'))
from wechat_aumac.native import NativeSession
from wechat_aumac.native.wire import blob, integer, decode


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send',action='store_true')
    parser.add_argument('--to',required=True,help='Explicit recipient matching test-recipient.json')
    parser.add_argument('--file',type=Path,required=True,help='Authorized PNG file')
    args=parser.parse_args()
    path=args.file.resolve(strict=True)
    data=path.read_bytes()
    if not data.startswith(b'\x89PNG\r\n\x1a\n') or not 0<len(data)<=65536:
        raise SystemExit('Expected a PNG of at most one 64 KiB chunk')
    target=json.loads((ROOT/'test-recipient.json').read_text())['receiver']
    if target != args.to:raise SystemExit('Recipient must match --to and the local test binding')
    mode='full' if args.send else 'codec'
    before=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat*.ips'))
    report={'file':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
            'test_binding':'test-recipient.json','requested_send':args.send,'attempts':0,
            'moments_operations':[],'timestamp':time.time()}
    with NativeSession(ROOT/'native-profile-4.2.0.json',mode=mode,
                       experimental_operations=['image'] if args.send else ()) as wx:
        own=wx.identity()['user_id']
        base=blob(1,b'')+integer(2,0)+blob(3,b'')+integer(4,0)+blob(5,b'')+integer(6,0)
        client='aumac_'+uuid.uuid4().hex
        payload=(blob(1,base)+blob(2,blob(1,client))+blob(3,blob(1,own))+blob(4,blob(1,target))
                 +integer(5,len(data))+integer(6,0)+integer(7,len(data))
                 +blob(8,integer(1,len(data))+blob(2,data))+integer(9,3)+integer(11,0))
        codec=wx.roundtrip(payload,kind='image')
        report['native_codec_identical']=codec.get('parsed',False) and bytes(codec.get('bytes',[]))==payload
        if not report['native_codec_identical']:raise SystemExit('Native image codec failed')
        if args.send:
            report['completion_before']=wx._rpc('completionStatus')
            report['attempts']=1
            result=wx._submit_media_request('image',payload,timeout=20)
            raw=result.pop('bytes',None)
            report['transport']=result
            if raw is not None:
                fields=decode(raw)
                base_reply=next((v for n,w,v in fields if n==1 and w==2),b'')
                rc=next((v for n,w,v in decode(base_reply) if n==1 and w==0),None)
                if rc is not None and rc&(1<<31):rc=(rc&0xffffffff)-(1<<32)
                report['return_code']=rc
                report['response_numbers']={str(n):str(v) for n,w,v in fields if w==0}
                report['response_fields']=[{'number':n,'wire_type':w,**({'length':len(v)} if isinstance(v,bytes) else {})} for n,w,v in fields]
            # Allow task-end completion to run; no retransmission is made here.
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                cb=wx._rpc('completionStatus')
                if int(cb['completed'])>int(report['completion_before']['completed']):break
                time.sleep(.1)
            report['completion_after']=cb
            report['final_session']=wx.status()
    after=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat*.ips'))
    report['new_crash_reports']=[str(p) for p in sorted(after-before)]
    report['cleanup_errors']=wx.cleanup_errors
    report['status']=('codec_only' if not args.send else
                      'server_rejected' if report.get('return_code') not in (None,0) else
                      'server_response_requires_validation' if report.get('return_code')==0 else 'unconfirmed')
    (ROOT/('image-send-verification.json' if args.send else 'image-codec-verification.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
