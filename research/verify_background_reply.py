"""One background reply to an exact marker in the locally bound test chat."""
import argparse,json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wechat_aumac.native import NativeSession


def front_bundle():
    p=subprocess.run(['lsappinfo','front'],capture_output=True,text=True)
    return subprocess.run(['lsappinfo','info','-only','bundleid',p.stdout.strip()],capture_output=True,text=True).stdout.strip()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--seconds',type=float,default=900)
    parser.add_argument('--send',action='store_true',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parent
    target=json.loads((root/'test-recipient.json').read_text())['receiver']
    stop=root/'background-reply.stop';stop.unlink(missing_ok=True)
    report={'trigger':'bg-native-test','reply':'test','ui_operations':0,'attempts':0,'received':False,'timestamp':int(time.time())}
    path=root/'background-reply-verification.json'
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with NativeSession(root/'native-profile-4.2.0.json',mode='full') as wx:
        report['front_at_start']=front_bundle();save();deadline=time.monotonic()+args.seconds
        print('READY: only an incoming bg-native-test in the bound test chat can trigger one test reply',flush=True)
        while time.monotonic()<deadline and not stop.exists():
            event=wx.next_event(timeout=.5)
            if wx._detached:raise RuntimeError('WeChat detached')
            if not event or event.get('event')!='incoming_message':continue
            message=event['message']
            if message['chat_id']!=target or message['text']!='bg-native-test' or message['message_type']!=1:continue
            report['received']=True;report['front_at_reply']=front_bundle();report['attempts']=1;save()
            result=wx.reply(message,'test',timeout=15)
            report['reply_status']=result['status'];report['task_id']=result.get('task_id')
            report['server_message_id']=result.get('server_message_id');save()
            print(json.dumps({k:v for k,v in report.items() if not k.startswith('front')},ensure_ascii=False),flush=True)
            break
    report['cleanup_errors']=wx.cleanup_errors;report['finished']=True;save();print('DONE',flush=True)
