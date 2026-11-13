"""Explicit single attempts with generated fixtures in the bound test chat.

No retry or Moments operation. Video proceeds to its data phase only after the
thumbnail is confirmed. Prepared credentials are never written to the report.
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
from wechat_aumac.native.media_experimental import (
    voice_request,sticker_request,video_request,
    parse_voice_response,parse_sticker_response,parse_video_response,amr_duration_ms)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--send',required=True,action='store_true')
    p.add_argument('--to',required=True,help='Explicit recipient matching test-recipient.json')
    args=p.parse_args()
    target=json.loads((ROOT/'test-recipient.json').read_text())['receiver']
    if target != args.to:raise SystemExit('Recipient must match --to and the local test binding')
    prior=json.loads((ROOT/'media-fixture-codec-verification.json').read_text())
    if not all(r['identical'] for r in prior['results']):raise SystemExit('Native codecs must pass first')
    before=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat*.ips'))
    report={'results':[],'moments_operations':[],'timestamp':time.time(),'automatic_retries':0}
    def save():
        (ROOT/'remaining-media-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with NativeSession(ROOT/'native-profile-4.2.0.json',mode='full',experimental_operations=['voice','sticker','video']) as wx:
        own=wx.identity()['user_id']; cb_before=wx._rpc('completionStatus')
        def request(kind,payload,parse):
            codec=wx.roundtrip(payload,kind=kind)
            if not codec.get('parsed') or bytes(codec['bytes'])!=payload:raise ValueError('Native codec mismatch')
            result=wx._submit_media_request(kind,payload,timeout=20)
            raw=result.pop('bytes',None)
            return result,parse(raw) if raw is not None else None
        data=(ROOT/'fixtures/test.amr').read_bytes();client='aumac_'+uuid.uuid4().hex
        payload=voice_request(own,target,client,data,
                              duration_ms=json.loads((ROOT/'fixtures/amr-fixture.json').read_text())['duration_ms'],timestamp=int(time.time()))
        transport,response=request('voice',payload,parse_voice_response)
        valid=bool(response and response['return_code']==0 and response['sender']==own and response['receiver']==target
                   and response['client_id']==client and int(response['server_message_id'])>0
                   and response['result_flag']==2 and response['duration_ms']==amr_duration_ms(data)
                   and response['offset']+response['length']==len(data))
        if response:
            response={k:v for k,v in response.items() if k not in {'sender','receiver','client_id'}}
        item={'kind':'voice','bytes':len(data),'transport':transport,'response':response,
              'status':'acknowledged' if valid else 'unconfirmed'}
        report['results'].append(item);save();print(json.dumps(item),flush=True)

        data=(ROOT/'fixtures/test.gif').read_bytes();client='aumac_'+uuid.uuid4().hex
        payload,digest=sticker_request(target,client,data)
        transport,response=request('sticker',payload,parse_sticker_response)
        valid=bool(response and response['return_code']==0 and len(response['items'])==1
                   and response['items'][0]['return_code']==0 and response['items'][0]['md5']==digest
                   and int(response['items'][0]['server_message_id'])>0)
        item={'kind':'sticker','bytes':len(data),'transport':transport,'response':response,
              'status':'acknowledged' if valid else 'unconfirmed'}
        report['results'].append(item);save();print(json.dumps(item),flush=True)

        thumb=(ROOT/'fixtures/test-thumb.jpg').read_bytes();video=(ROOT/'fixtures/test.mp4').read_bytes()
        client='aumac_'+uuid.uuid4().hex
        phases=[]
        for phase,data in [(0,thumb),(1,video)]:
            payload=video_request(own,target,client,thumb_total=len(thumb),video_total=len(video),duration_seconds=2,
                                  phase=phase,offset=0,data=data)
            transport,response=request('video',payload,parse_video_response)
            valid=bool(response and response['return_code']==0 and response['client_id']==client
                       and response['thumb_offset']==len(thumb)
                       and response['video_offset']==(0 if phase==0 else len(video))
                       and (phase==0 or int(response['server_message_id'])>0))
            if response:response={k:v for k,v in response.items() if k!='client_id'}
            phases.append({'phase':phase,'transport':transport,'response':response,'confirmed':valid})
            if not valid:break
        valid=len(phases)==2 and all(r['confirmed'] for r in phases)
        item={'kind':'video','bytes':len(video),'thumb_bytes':len(thumb),'phases':phases,
              'status':'acknowledged' if valid else 'unconfirmed'}
        report['results'].append(item);save();print(json.dumps(item),flush=True)
        time.sleep(.5)
        report['completion_before']=cb_before
        report['completion_after']=wx._rpc('completionStatus')
        report['session']=wx.status()
    report['cleanup_errors']=wx.cleanup_errors
    report['new_crash_reports']=[str(p) for p in sorted(set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat*.ips'))-before)]
    save()
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
