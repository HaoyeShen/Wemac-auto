"""One bounded background text exchange between the two selected native clients.

Uses the existing local test binding and text 'test'. No UI or Moments writes.
"""
import argparse,json,secrets,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wechat_aumac.native import NativeSession
from wechat_aumac.native.wire import text_request,parse_text_response
from verify_background_reply import front_bundle

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--send',required=True,action='store_true');p.parse_args()
    root=Path(__file__).resolve().parent;target=json.loads((root/'test-recipient.json').read_text())['receiver']
    report={'ui_operations':0,'attempts':0,'reply_attempts':0,'timestamp':int(time.time())}
    path=root/'two-account-background-verification.json'
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with NativeSession(root/'native-profile-4.2.0.json',mode='full') as original, NativeSession(root/'native-profile-isolated.json',mode='full') as isolated:
        first=original.identity()['user_id'];second=isolated.identity()['user_id']
        if first==second:raise SystemExit('The clients must use different accounts')
        report['different_accounts']=True;report['front_at_send']=front_bundle();save()
        if any(x in report['front_at_send'] for x in ['com.tencent.xinWeChat','com.wemac.auto.client']):
            raise SystemExit('Leave both clients in the background before this verification')
        payload=text_request(target,'test',int(time.time()),secrets.randbelow(0xffffffff)+1)
        codec=isolated.roundtrip(payload)
        if not codec.get('parsed') or bytes(codec.get('bytes',[]))!=payload:raise SystemExit('New client codec mismatch')
        report['attempts']=1;save()
        # First isolated-build server validation; do not mark a capability before
        # the actual native response. This is the same checked submit ABI as SDK sends.
        task=isolated._rpc('submit',list(payload))['taskId'];deadline=time.monotonic()+20
        with isolated._reply_condition:
            while task not in isolated._replies and time.monotonic()<deadline:
                isolated._reply_condition.wait(max(0,deadline-time.monotonic()))
            event=isolated._replies.pop(task,None)
        response=parse_text_response(bytes(event['bytes'])) if event else {}
        accepted=bool(response.get('acknowledged') and len(response.get('results',[]))==1
                      and response['results'][0].get(1)==0 and response['results'][0].get(8,0)>0)
        report['isolated_send_acknowledged']=accepted;save();print('isolated_send',accepted,flush=True)
        if not accepted:raise SystemExit('No confirmed first send; no automatic retry')
        incoming=next((m for m in original.watch(chat_id=target,timeout=25) if m['sender']==second and m['text']=='test'),None)
        report['original_received_in_background']=incoming is not None;save()
        if incoming is None:raise SystemExit('No matching incoming sync event; no reply sent')
        report['front_at_reply']=front_bundle();report['reply_attempts']=1;save()
        reply=original.reply(incoming,'test',timeout=15)
        report['original_reply_status']=reply['status'];save();print('original_reply',reply['status'],flush=True)
        returned=next((m for m in isolated.watch(chat_id=target,timeout=25) if m['sender']==first and m['text']=='test'),None)
        report['isolated_received_reply_in_background']=returned is not None;save()
    report['cleanup_errors']=original.cleanup_errors+isolated.cleanup_errors
    report['all_background']=not any(x in report.get(k,'') for k in ['front_at_send','front_at_reply'] for x in ['com.tencent.xinWeChat','com.wemac.auto.client'])
    save();print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    if report.get('isolated_received_reply_in_background') and report['all_background']:
        profile=root/'native-profile-isolated.json';value=json.loads(profile.read_text())
        value['verified_capabilities']=list(dict.fromkeys(value.get('verified_capabilities',[])+['send_text_server_ack','watch_incoming_addmsg']))
        profile.write_text(json.dumps(value,indent=2)+'\n')
