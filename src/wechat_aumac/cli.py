"""Native-function-only command-line interface for Wemac-auto."""
from __future__ import annotations

import argparse
import json
import sys
import math
from pathlib import Path
import time

from .config import VERSION
from .errors import WeChatAuMacError


def _json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _interval(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("interval must be a finite positive number")
    return number


def cmd_hook_probe(args) -> int:
    from .hook_probe import probe

    report = probe(args.app, attach=args.attach)
    _json(report)
    return 1 if report['status'] in {'attach_failed', 'invalid_app', 'unsupported_platform'} else 0


def cmd_native(args) -> int:
    from .native import WeChatNative

    sends={'native-send','native-send-image','native-send-sticker','native-send-voice','native-send-video','native-send-quote','native-revoke','native-reply','native-moment-publish'}
    mode = ('full' if args.command in sends or args.command in {'native-moments','native-moment','native-moment-like','native-moment-comment','native-moment-unlike'} else
            'inventory' if args.command == 'native-status' else
            'codec' if args.command in {'native-codec','native-moment-draft'} else
            'observe' if args.command in {'native-observe','native-read','native-card-links'} or getattr(args,'direction','incoming')!='incoming'
            else 'receive')
    operations = getattr(args,'operation',()) or ()
    if args.command in {'native-watch','native-read','native-card-links'} and mode=='observe':operations=None
    experimental=()
    if getattr(args,'experimental',False):experimental=(args.command.removeprefix('native-send-'),)
    reads=(('moment_timeline',) if args.command=='native-moments' else
           ('moment_detail',) if args.command=='native-moment' else ())
    if args.command=='native-reply' and args.max_replies<1:raise ValueError('max-replies must be positive')
    kwargs={}
    moment_action={'native-moment-like':'like','native-moment-comment':'comment','native-moment-unlike':'unlike'}.get(args.command)
    if moment_action:kwargs['moments_operations']=(moment_action,)
    if args.command=='native-moment-publish':kwargs['moments_operations']=('publish',)
    actions=(('quote',) if args.command=='native-send-quote' or (args.command=='native-reply' and args.quote) else
             ('revoke',) if args.command=='native-revoke' else ())
    if actions:kwargs['message_operations']=actions
    if getattr(args,'pid',None) is not None:kwargs['pid']=args.pid
    with WeChatNative(args.profile, mode=mode, observe_operations=operations,
                      experimental_operations=experimental,read_operations=reads,**kwargs) as wx:
        if args.command == 'native-status':
            _json({'session': wx.status(), 'verified_capabilities': wx.profile.get('verified_capabilities', [])})
        elif args.command == 'native-send':
            result = wx.send_text(args.to, args.text, timeout=args.timeout)
            _json(result)
            return 0 if result['status'] == 'acknowledged' else 1
        elif args.command == 'native-send-image':
            result=wx.send_image(args.to,args.path,timeout=args.timeout)
            _json(result)
            return 0 if result['status']=='acknowledged' else 1
        elif args.command in {'native-send-sticker','native-send-voice','native-send-video'}:
            kind=args.command.removeprefix('native-send-')
            kwargs={'timeout':args.timeout}
            if kind=='video':kwargs.update(thumbnail=args.thumbnail,duration_seconds=args.duration)
            result=getattr(wx,'send_'+kind)(args.to,args.path,**kwargs)
            _json(result)
            return 0 if result['status']=='acknowledged' else 1
        elif args.command=='native-send-quote':
            reference=json.loads(Path(args.reference).read_text())
            result=wx.send_quote(args.to,args.text,reference,timeout=args.timeout);_json(result)
            return 0 if result['status']=='acknowledged' else 1
        elif args.command=='native-revoke':
            message=json.loads(Path(args.message).read_text())
            result=wx.revoke_message(message,timeout=args.timeout);_json(result)
            return 0 if result['status']=='acknowledged' else 1
        elif args.command=='native-reply':
            count=0;deadline=time.monotonic()+args.seconds
            for message in wx.watch(chat_id=args.chat,direction='incoming',timeout=args.seconds):
                if time.monotonic()>=deadline:break
                if message.get('message_type',0)>=10000:continue
                result=wx.reply(message,args.text,quote=args.quote,timeout=args.timeout)
                _json(result);count+=1
                if result['status']!='acknowledged':return 1
                if count>=args.max_replies:break
        elif args.command in {'native-read','native-card-links'}:
            # Events are captured in the WeChat sync hook without moving focus.
            deadline=time.monotonic()+args.seconds
            while time.monotonic()<deadline:
                wx.next_event(timeout=min(.25,max(0,deadline-time.monotonic())))
                if wx._detached:raise WeChatAuMacError('WeChat detached; collection stopped')
            messages=wx.read(chat_id=args.chat,limit=args.limit)
            _json([wx.get_card_links(m) for m in messages if 'card' in m or 'card_error' in m] if args.command=='native-card-links' else messages)
        elif args.command=='native-moment-publish':
            result=(wx.publish_image_moment(args.text,args.image,visibility=args.visibility,timeout=args.timeout) if args.image else
                    wx.publish_moment(args.text,visibility=args.visibility,timeout=args.timeout))
            _json(result);return 0 if result['status']=='acknowledged' else 1
        elif moment_action:
            method=getattr(wx,moment_action+'_moment')
            result=(method(args.id,args.text,timeout=args.timeout) if moment_action=='comment' else
                    method(args.id,timeout=args.timeout))
            _json(result);return 0 if result['status']=='acknowledged' else 1
        elif args.command=='native-moments':
            result=wx.get_moments(max_id=args.max_id,timeout=args.timeout);_json(result)
            return 0 if result['status']=='acknowledged' else 1
        elif args.command=='native-moment':
            result=wx.get_moment(args.id,timeout=args.timeout);_json(result)
            return 0 if result['status']=='acknowledged' else 1
        elif args.command=='native-moment-draft':
            draft=wx.prepare_moment(args.text,visibility=args.visibility)
            _json({k:v for k,v in draft.items() if k!='payload'})
        elif args.command == 'native-codec':
            data=Path(args.payload).read_bytes()
            result=wx.roundtrip(data,kind=args.kind)
            output=bytes(result.get('bytes',[]))
            _json({'kind':args.kind,'parsed':result.get('parsed',False),
                   'input_bytes':len(data),'output_bytes':len(output),
                   'identical':result.get('parsed',False) and output==data,
                   'submitted':False})
            return 0 if result.get('parsed') else 1
        elif args.command == 'native-observe':
            from .native.wire import decode
            deadline=time.monotonic()+args.seconds
            print('Observing native requests; this mode cannot submit messages.',file=sys.stderr,flush=True)
            try:
                while time.monotonic()<deadline:
                    event=wx.next_event(timeout=min(.5,max(0,deadline-time.monotonic())))
                    if event is None:
                        if wx._detached:
                            raise WeChatAuMacError('WeChat detached; observation stopped')
                        continue
                    summary={key:value for key,value in event.items()
                             if key not in {'bytes','message'}}
                    if 'bytes' in event:
                        summary['payload_bytes']=len(event['bytes'])
                        try:
                            summary['fields']=[{'number':n,'wire_type':w,
                                                **({'length':len(v)} if isinstance(v,bytes) else {})}
                                               for n,w,v in decode(bytes(event['bytes']))]
                        except ValueError as exc:
                            summary['decode_error']=str(exc)
                    print(json.dumps(summary,ensure_ascii=False),flush=True)
            except KeyboardInterrupt:
                return 130
            _json({'observation_complete':True,'dropped_events':wx.dropped_events,'submitted':False})
        else:
            try:
                for message in wx.watch(chat_id=args.chat,direction=args.direction):
                    print(json.dumps(message, ensure_ascii=False), flush=True)
            except KeyboardInterrupt:
                return 130
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wechat-aumac",
        description="Control WeChat through version-pinned internal functions.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = p.add_subparsers(dest="command", required=True)

    hook = sub.add_parser("hook-probe", help="inspect compatibility for experimental background sending")
    hook.add_argument("--app", default="/Applications/WeChat.app", help="WeChat app bundle path")
    hook.add_argument("--attach", action="store_true", help="attempt Frida module enumeration; does not send")
    hook.set_defaults(func=cmd_hook_probe)

    native_status = sub.add_parser('native-status', help='check a version-pinned native session')
    native_status.add_argument('--profile', required=True)
    native_status.set_defaults(func=cmd_native)
    native_send = sub.add_parser('native-send', help='send text through internal functions and wait for server reply')
    native_send.add_argument('--profile', required=True)
    native_send.add_argument('--to', required=True, help='internal wxid or chatroom ID; not a display name')
    native_send.add_argument('--timeout', type=_interval, default=15)
    native_send.add_argument('text')
    native_send.set_defaults(func=cmd_native)
    native_image=sub.add_parser('native-send-image',help='send a PNG/JPEG through internal functions')
    native_image.add_argument('--profile',required=True)
    native_image.add_argument('--to',required=True,help='internal wxid or chatroom ID')
    native_image.add_argument('--timeout',type=_interval,default=30)
    native_image.add_argument('--experimental',action='store_true',help='explicitly opt into the image contract before local server verification')
    native_image.add_argument('path')
    native_image.set_defaults(func=cmd_native)
    for kind,help_text in [('sticker','send a GIF sticker (at most 64 KiB)'),
                           ('voice','send Tencent SILK or AMR-NB voice (at most 64 KiB / 60 seconds)'),
                           ('video','send MP4 video with a JPEG thumbnail')]:
        command=sub.add_parser('native-send-'+kind,help=help_text)
        command.add_argument('--profile',required=True)
        command.add_argument('--to',required=True,help='internal wxid or chatroom ID')
        command.add_argument('--timeout',type=_interval,default=60 if kind=='video' else 30)
        command.add_argument('--experimental',action='store_true',help='explicitly opt into an unverified media contract')
        if kind=='video':
            command.add_argument('--thumbnail',required=True,help='JPEG thumbnail of at most 64 KiB')
            command.add_argument('--duration',type=int,required=True,help='duration in seconds (1 through 600)')
        command.add_argument('path');command.set_defaults(func=cmd_native)
    native_watch = sub.add_parser('native-watch', help='read new messages from the internal sync path (JSON Lines)')
    native_watch.add_argument('--profile', required=True)
    native_watch.add_argument('--chat', help='filter by internal chat ID')
    native_watch.add_argument('--direction', choices=['incoming','outgoing','both'],default='incoming')
    native_watch.set_defaults(func=cmd_native)
    native_observe = sub.add_parser('native-observe',help='observe native request buffers; cannot submit')
    native_observe.add_argument('--profile',required=True)
    native_observe.add_argument('--seconds',type=_interval,default=30)
    native_observe.add_argument('--operation',action='append',choices=[
        'image','video','sticker','voice','moment_post','moment_interaction','moment_objectop','moment_timeline','moment_detail','app_message','revoke'],
        help='additional operation to observe (repeatable); default: text only')
    native_observe.set_defaults(func=cmd_native)
    native_codec = sub.add_parser('native-codec',help='parse/serialize a protobuf request locally; cannot submit')
    native_codec.add_argument('--profile',required=True)
    native_codec.add_argument('--kind',required=True,choices=[
        'text','image','video','sticker','voice','moment_post','moment_interaction','moment_objectop','moment_timeline','moment_detail','app_message','revoke'])
    native_codec.add_argument('--payload',required=True,help='protobuf wire file, not an image/audio file')
    native_codec.set_defaults(func=cmd_native)
    timeline=sub.add_parser('native-moments',help='read one visible Moments page; never publishes')
    timeline.add_argument('--profile',required=True)
    timeline.add_argument('--max-id',type=int,default=0)
    timeline.add_argument('--timeout',type=_interval,default=15)
    timeline.set_defaults(func=cmd_native)
    detail=sub.add_parser('native-moment',help='read one Moments post by ID')
    detail.add_argument('--profile',required=True);detail.add_argument('--id',required=True)
    detail.add_argument('--timeout',type=_interval,default=15);detail.set_defaults(func=cmd_native)
    draft=sub.add_parser('native-moment-draft',help='prepare and codec-check a text post; never publishes')
    draft.add_argument('--profile',required=True);draft.add_argument('--visibility',required=True,choices=['private','public'])
    draft.add_argument('text');draft.set_defaults(func=cmd_native)
    publish=sub.add_parser('native-moment-publish',help='publish a text or one-image Moments post through native functions')
    publish.add_argument('--profile',required=True);publish.add_argument('--visibility',required=True,choices=['private','public'])
    publish.add_argument('--image');publish.add_argument('--timeout',type=_interval,default=40)
    publish.add_argument('text');publish.set_defaults(func=cmd_native)

    for name in ('native-read','native-card-links'):
        command=sub.add_parser(name,help='collect native background messages'+(' and embedded card links' if name.endswith('links') else ''))
        command.add_argument('--profile',required=True);command.add_argument('--chat')
        command.add_argument('--seconds',type=_interval,default=5);command.add_argument('--limit',type=int,default=50)
        command.set_defaults(func=cmd_native)
    quote=sub.add_parser('native-send-quote',help='send a native quoted reply to an explicit chat')
    quote.add_argument('--profile',required=True);quote.add_argument('--to',required=True)
    quote.add_argument('--reference',required=True,help='JSON message from native observation, including chat_id and message_id')
    quote.add_argument('--timeout',type=_interval,default=15);quote.add_argument('text');quote.set_defaults(func=cmd_native)
    revoke=sub.add_parser('native-revoke',help='recall one of our own native messages')
    revoke.add_argument('--profile',required=True);revoke.add_argument('--message',required=True,help='JSON outgoing native message')
    revoke.add_argument('--timeout',type=_interval,default=15);revoke.set_defaults(func=cmd_native)
    for action in ('like','comment','unlike'):
        command=sub.add_parser('native-moment-'+action,help='explicit native Moments '+action+' (experimental)')
        command.add_argument('--profile',required=True);command.add_argument('--id',required=True)
        command.add_argument('--timeout',type=_interval,default=15)
        if action=='comment':command.add_argument('text')
        command.set_defaults(func=cmd_native)
    reply=sub.add_parser('native-reply',help='receive and reply in the background, restricted to one internal chat ID')
    reply.add_argument('--profile',required=True);reply.add_argument('--chat',required=True)
    reply.add_argument('--text',required=True);reply.add_argument('--quote',action='store_true')
    reply.add_argument('--timeout',type=_interval,default=15);reply.add_argument('--seconds',type=_interval,default=300)
    reply.add_argument('--max-replies',type=int,default=1);reply.set_defaults(func=cmd_native)
    for command in sub.choices.values():
        if command.get_default('func') is cmd_native:command.add_argument('--pid',type=int,help='exact PID belonging to the selected app/profile')

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (WeChatAuMacError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
