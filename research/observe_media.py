"""Observe candidate task entry points without changing arguments or sending."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import os
import threading
import frida
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wechat_aumac.hook_probe import process_path

AGENT = r'''
const core = Process.enumerateModules().find(m => m.path.endsWith('/Resources/wechat.dylib'));
if (!core || !core.path.includes('/research/WeChat-Hook.app/')) throw Error('Unexpected module');
const events = [];
function emit(value) { value.time = Date.now(); events.push(value); send(value); }
function taskMeta(p) {
    let value = {taskPointer:p.toString()};
    try {
        value.taskId=p.readU32(); value.commandId=p.add(4).readU32();
        const size=p.add(0x20).readU64().toNumber();
        if(size<1 || size>256)return value;
        let text=p.add(0x18).readPointer().readUtf8String(size);
        const nul=text.indexOf('\x00'); if(nul>=0)text=text.slice(0,nul);
        if(/^\/cgi-bin\/[a-z0-9/_-]+$/i.test(text))value.cgi=text;
    } catch (_) {}
    return value;
}
const targets = [
 ['wrapper',0x5add114,'sub sp, sp, #0x1d0'],


];
for (const [name,off,expected] of targets) {
    const address=core.base.add(off);
    const first=Instruction.parse(address).toString();
    if(first!==expected)throw Error('Prologue mismatch: '+name+' '+first);
    Interceptor.attach(address,{
        onEnter(args) {
            const entry={event:name,thread:Process.getCurrentThreadId()};
            if(name==='wrapper')Object.assign(entry,taskMeta(args[0]));
            if(name==='manager') {
                entry.context=args[0].toString();Object.assign(entry,taskMeta(args[1]));
            }
            if(name==='req2buf') {entry.taskId=args[1].toUInt32();}
            if(!entry.cgi || !/(send|upload|sns)/i.test(entry.cgi))return;
            if(true) {
                entry.backtrace=Thread.backtrace(this.context,Backtracer.ACCURATE)
                    .slice(0,16).map(p=>p.sub(core.base).toString());
            }
            emit(entry);
        }
    });
}
emit({event:'ready',base:core.base.toString()});
'''

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds',type=float,default=25)
    p.add_argument('--output',default='research/media-task-observation.jsonl')
    args=p.parse_args()
    raise SystemExit('Archived unstable multi-agent probe. Use the unified NativeSession instead.')
    pid=int(subprocess.check_output(['pgrep','-x','WeChat'],text=True).strip())
    expected=Path(__file__).resolve().parent/'WeChat-Hook.app/Contents/MacOS/WeChat'
    if Path(process_path(pid)).resolve()!=expected:raise SystemExit('Expected experiment process')
    Path('research/media-observer-controller.pid').write_text(str(os.getpid()))
    ready=threading.Event()
    failure=[]
    session=frida.attach(pid)
    try:
        with Path(args.output).open('w') as stream:
            def on_message(message,data):
                value=message.get('payload',message)
                if value.get('event')=='ready': ready.set()
                if message.get('type')=='error': failure.append(message);ready.set()
                stream.write(json.dumps(value)+'\n');stream.flush()
                print(json.dumps(value),flush=True)
            script=session.create_script(AGENT)
            script.on('message',on_message)
            script.load()
            if not ready.wait(5) or failure: raise RuntimeError('Observer installation failed')
            time.sleep(args.seconds)
    finally:
        session.detach()
