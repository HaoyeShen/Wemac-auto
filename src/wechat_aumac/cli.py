"""Command-line interface for WeChat auMac."""
from __future__ import annotations

import argparse
import json
import sys
import math
from pathlib import Path
import time

from .api import WeChatUI
from .config import VERSION
from .errors import WeChatAuMacError


def _json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _print_messages(messages) -> None:
    for m in messages:
        print(f"[{m.time}] {m.sender}: {m.text}")
        if m is not messages[-1]:
            print()


def cmd_read(args) -> int:
    wx = WeChatUI()
    if args.raw:
        print(wx.read_raw(chat=args.chat), end="")
        return 0
    result = wx.read_result(chat=args.chat, limit=args.limit)
    if args.export:
        from .export import export_messages

        paths = export_messages(
            result.messages, args.export, prefix=args.prefix,
            formats=tuple(args.format) if args.format else ("json", "csv", "txt", "md"),
        )
        if args.json:
            _json({"count": len(result.messages), "files": paths})
        else:
            for fmt, path in paths.items():
                print(f"{fmt}: {path}")
        return 0
    if args.json:
        _json([m.to_dict() for m in result.messages])
    else:
        _print_messages(result.messages)
    return 0


def cmd_send(args) -> int:
    text = " ".join(args.text)
    wx = WeChatUI()
    result = wx.send(text, verify=args.verify)
    if args.json:
        _json(result.to_dict())
    else:
        print(f"sent: {result.text}")
        if args.verify:
            print("verified" if result.verified else "not verified")
    return 0


def cmd_open(args) -> int:
    WeChatUI().open_chat(args.chat)
    print(f"opened: {args.chat}")
    return 0


def _interval(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("interval must be a finite positive number")
    return number


def cmd_watch(args) -> int:
    print("Listening for new messages; Ctrl+C to stop.", file=sys.stderr, flush=True)
    try:
        for message in WeChatUI().watch(chat=args.chat, interval=args.interval):
            if args.json:
                print(json.dumps(message.to_dict(), ensure_ascii=False), flush=True)
            else:
                print(f"[{message.time}] {message.sender}: {message.text}", flush=True)
    except KeyboardInterrupt:
        return 130
    return 0


def cmd_hook_probe(args) -> int:
    from .hook_probe import probe

    report = probe(args.app, attach=args.attach)
    _json(report)
    return 1 if report['status'] in {'attach_failed', 'invalid_app', 'unsupported_platform'} else 0


def cmd_native(args) -> int:
    from .native import WeChatNative

    sends={'native-send','native-send-image','native-send-sticker','native-send-voice','native-send-video'}
    mode = ('full' if args.command in sends or args.command in {'native-moments','native-moment'} else
            'inventory' if args.command == 'native-status' else
            'codec' if args.command in {'native-codec','native-moment-draft'} else
            'observe' if args.command == 'native-observe' or getattr(args,'direction','incoming')!='incoming'
            else 'receive')
    operations = getattr(args,'operation',()) or ()
    if args.command=='native-watch' and mode=='observe':operations=None
    experimental=()
    if getattr(args,'experimental',False):experimental=(args.command.removeprefix('native-send-'),)
    reads=(('moment_timeline',) if args.command=='native-moments' else
           ('moment_detail',) if args.command=='native-moment' else ())
    with WeChatNative(args.profile, mode=mode, observe_operations=operations,
                      experimental_operations=experimental,read_operations=reads) as wx:
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


def cmd_doctor(args) -> int:
    report = WeChatUI.doctor()
    if args.json:
        _json(report)
        return 0
    print(f"WeChat auMac {VERSION}")
    print(f"platform ok : {report['platform_ok']}")
    print(f"running     : {report['running']}  pid={report['pid']}")
    print(f"window      : {report['window']}")
    print(f"screen      : {report['screen']}")
    print(f"maximized   : {report['maximized']}")
    print(f"fullscreen  : {report['fullscreen']}")
    print(f"clipboard   : {report['clipboard_ok']}")
    if report.get("error"):
        print(f"error       : {report['error']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wechat-aumac",
        description="Read and send WeChat messages through the macOS WeChat client.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = p.add_subparsers(dest="command", required=True)

    read = sub.add_parser("read", help="copy and parse the current chat history")
    read.add_argument("--chat", help="open this chat by name first (best-effort)")
    read.add_argument("--limit", type=int, help="return only the last N messages")
    read.add_argument("--json", action="store_true", help="print JSON")
    read.add_argument("--raw", action="store_true", help="print the raw copied transcript")
    read.add_argument("--export", metavar="DIR", help="also export the messages to DIR")
    read.add_argument("--prefix", default="chat", help="export filename prefix")
    read.add_argument(
        "--format", action="append", choices=["json", "csv", "txt", "md"],
        help="export format (repeatable; default: all)",
    )
    read.set_defaults(func=cmd_read)

    send = sub.add_parser("send", help="send a message from the current chat's input box")
    send.add_argument("text", nargs="+", help="message text")
    send.add_argument("--verify", action="store_true", help="read the message back after sending")
    send.add_argument("--json", action="store_true", help="print JSON")
    send.set_defaults(func=cmd_send)

    open_p = sub.add_parser("open", help="open a chat by name (best-effort search)")
    open_p.add_argument("chat")
    open_p.set_defaults(func=cmd_open)

    watch = sub.add_parser("watch", help="poll the current chat for newly appended messages")
    watch.add_argument("--chat", help="open this chat once before listening (best-effort)")
    watch.add_argument("--interval", type=_interval, default=10.0, help="seconds between reads (default: 10)")
    watch.add_argument("--json", action="store_true", help="output one JSON object per new message")
    watch.set_defaults(func=cmd_watch)

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
    native_image.add_argument('path')
    native_image.set_defaults(func=cmd_native)
    for kind,help_text in [('sticker','send a GIF sticker (at most 64 KiB)'),
                           ('voice','send AMR-NB voice (at most 64 KiB / 60 seconds)'),
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
        'image','video','sticker','voice','moment_post','moment_interaction','moment_objectop','moment_timeline','moment_detail'],
        help='additional operation to observe (repeatable); default: text only')
    native_observe.set_defaults(func=cmd_native)
    native_codec = sub.add_parser('native-codec',help='parse/serialize a protobuf request locally; cannot submit')
    native_codec.add_argument('--profile',required=True)
    native_codec.add_argument('--kind',required=True,choices=[
        'text','image','video','sticker','voice','moment_post','moment_interaction','moment_objectop','moment_timeline','moment_detail'])
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

    doc = sub.add_parser("doctor", help="show permissions/window diagnostics")
    doc.add_argument("--json", action="store_true", help="print JSON")
    doc.set_defaults(func=cmd_doctor)

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
