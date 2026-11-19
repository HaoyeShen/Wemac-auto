"""Read-only bounded capture for manually sent quotes, revokes and card messages."""
import argparse,json,sys,time,signal,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wechat_aumac.native import NativeSession
from wechat_aumac.native.wire import decode,blob,integer

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seconds',type=float,default=300)
    a=p.parse_args();root=Path(__file__).resolve().parent
    stopped=threading.Event()
    for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,lambda *args:stopped.set())
    target=json.loads((root/'test-recipient.json').read_text())['receiver']
    output=root/'message-actions-capture.jsonl';deadline=time.monotonic()+a.seconds
    with NativeSession(root/'native-profile-4.2.0.json',mode='observe',observe_operations=['app_message','revoke']) as wx, output.open('a') as stream:
        print('READY: observing app messages/revokes and test-chat incoming XML; cannot submit',flush=True)
        while time.monotonic()<deadline and not stopped.is_set():
            event=wx.next_event(timeout=.5)
            if not event:continue
            name=event.get('event');entry=None
            if name in {'native_request','native_response'}:
                entry={k:v for k,v in event.items() if k!='bytes'}
                # Never persist prepared BaseRequest credentials (root field 1).
                fields=[(n,w,v) for n,w,v in decode(bytes(event['bytes'])) if n!=1]
                entry['fields']=[{'number':n,'wire':w,'value':v.hex() if isinstance(v,bytes) else str(v)} for n,w,v in fields]
            elif name in {'incoming_message','outgoing_message'} and event.get('message',{}).get('chat_id')==target:
                entry=event
            elif name in {'probe_error','decode_error'}:entry=event
            if entry:
                stream.write(json.dumps(entry,ensure_ascii=False)+'\n');stream.flush()
                print(json.dumps({'event':name,'operation':entry.get('operation'),'size':len(event.get('bytes',[]))}),flush=True)
        print('DONE',wx.cleanup_errors,flush=True)
