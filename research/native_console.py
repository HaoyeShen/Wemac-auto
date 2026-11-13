"""Local stdin controller; no network listener and no automatic sending."""
import json
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wechat_aumac.native.session import NativeSession
from wechat_aumac.native.wire import text_request

session=NativeSession('research/native-profile-4.2.0.json', mode='full').connect()
stop=threading.Event()
def consume():
    with open('research/native-events.jsonl','a') as stream:
        while not stop.is_set():
            event=session.next_event(.2)
            if event:
                stream.write(json.dumps(event)+'\n');stream.flush()
                print(json.dumps({k:v for k,v in event.items() if k not in ('bytes','message')}),flush=True)
thread=threading.Thread(target=consume,daemon=True);thread.start()
print(json.dumps({'connected':session.status()}),flush=True)
try:
    for line in sys.stdin:
        try:
            command=json.loads(line)
            op=command['op']
            if op=='status':result=session.status()
            elif op=='readSummary':
                result={'observed_messages':len(session.read(limit=2000)),'types':sorted({m['message_type'] for m in session.read(limit=2000)})}
            elif op=='apiSendTest':
                target=json.loads(Path('research/test-recipient.json').read_text())
                result=session.send_text(target['receiver'],command['text'])
            elif op=='completion':result=session._rpc('completionStatus')
            elif op=='context':result=session._script.exports_sync.context()
            elif op=='submitTest':
                target=json.loads(Path('research/test-recipient.json').read_text())
                payload=text_request(target['receiver'],command['text'],int(time.time()),int(time.time()*1000)&0xffffffff)
                result=session._script.exports_sync.submit(list(payload))
            elif op=='roundtrip':
                data=text_request(command['receiver'],command['text'],int(time.time()),123456789)
                result=session.roundtrip(data)
                result={'parsed':result.get('parsed'),'identical':bytes(result.get('bytes',[]))==data,'length':len(result.get('bytes',[]))}
            elif op=='close':break
            else:raise ValueError('Unknown operation')
            print(json.dumps({'result':result}),flush=True)
        except Exception as exc:
            print(json.dumps({'error':str(exc)}),flush=True)
finally:
    stop.set();thread.join(2);session.close()
