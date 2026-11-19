"""Validate native contracts in the isolated client using the bound test chat.

Each chosen fixture is sent once and immediately recalled. No Moments writes.
"""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wechat_aumac.native import NativeSession
from wechat_aumac.native.moments import timeline_request,parse_timeline_response
from verify_request_codecs import fixtures

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--send',action='store_true',required=True);parser.parse_args()
    root=Path(__file__).resolve().parent;profile=root/'native-profile-isolated.json'
    target=json.loads((root/'test-recipient.json').read_text())['receiver']
    reference=json.loads((root/'quote-reference.json').read_text())
    report={'timestamp':int(time.time()),'ui_operations':0,'retries':0,'results':[],'codecs':[]}
    verified=[]
    def save():(root/'isolated-features-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with NativeSession(profile,mode='full',experimental_operations=['image','voice','video','sticker'],
                       message_operations=['quote','revoke'],read_operations=['moment_timeline']) as wx:
        for kind,data in fixtures().items():
            result=wx.roundtrip(data,kind=kind);identical=result.get('parsed') and bytes(result.get('bytes',[]))==data
            report['codecs'].append({'kind':kind,'identical':identical})
            if not identical:save();raise SystemExit('Codec mismatch; no fixture sent')
        read=wx._fetch_native_request('moment_timeline',timeline_request(),timeout=15)
        timeline=parse_timeline_response(read['bytes']) if read['status']=='response_received' else read
        report['moments_read_status']=timeline['status']
        if timeline['status']=='acknowledged':verified.append('read_moments_server_ack')
        operations=[('quote',lambda:wx.send_quote(target,'test',reference,timeout=15)),
                    ('image',lambda:wx.send_image(target,root/'fixtures/test-thumb.jpg',timeout=20)),
                    ('sticker',lambda:wx.send_sticker(target,root/'fixtures/test.gif',timeout=20)),
                    ('voice',lambda:wx.send_voice(target,root/'fixtures/test.amr',timeout=20)),
                    ('video',lambda:wx.send_video(target,root/'fixtures/test.mp4',thumbnail=root/'fixtures/test-thumb.jpg',duration_seconds=2,timeout=25))]
        for kind,send in operations:
            result=send();item={'kind':kind,'send_status':result['status']};report['results'].append(item);save()
            print(kind,result['status'],flush=True)
            if result['status']!='acknowledged':break
            verified.append(f'send_{kind}_server_ack')
            message=next((m for m in wx.read(target,limit=2000) if m['message_id']==result['server_message_id']),None)
            if message is None:item['revoke_status']='missing_metadata';save();break
            recalled=wx.revoke_message(message,timeout=15);item['revoke_status']=recalled['status'];item['revoke_return_code']=recalled.get('return_code');save()
            print('revoke',kind,recalled['status'],flush=True)
            if recalled['status']!='acknowledged':break
            verified.append('revoke_message_server_ack')
    report['cleanup_errors']=wx.cleanup_errors;save()
    value=json.loads(profile.read_text());value['verified_capabilities']=list(dict.fromkeys(value['verified_capabilities']+verified))
    profile.write_text(json.dumps(value,indent=2)+'\n')
    print('closed',wx.cleanup_errors,flush=True)
