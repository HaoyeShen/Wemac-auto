#!/usr/bin/env python3
"""Read the current WeChat chat and optionally send a message.

Open the target chat in WeChat first; the library operates on the current chat.

Examples:
    PYTHONPATH=src python3 examples/basic.py --limit 5
    PYTHONPATH=src python3 examples/basic.py --send "hello" --verify
"""
from __future__ import annotations

import argparse

from wechat_aumac import WeChatUI


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat", help="open this chat by name first (best-effort)")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--send", help="send this text instead of only reading")
    parser.add_argument("--verify", action="store_true", help="verify sent text by reading back")
    parser.add_argument("--export", metavar="DIR", help="also export the messages")
    args = parser.parse_args()

    wx = WeChatUI()
    if args.send:
        if args.chat:
            raise SystemExit(
                "sending always targets the current chat; open it manually "
                "or call open_chat()/read() first, then send()"
            )
        result = wx.send(args.send, verify=args.verify)
        print(f"sent: {result.text}  verified={result.verified}")
        return 0

    messages = wx.read(chat=args.chat, limit=args.limit)
    for m in messages:
        print(f"[{m.time}] {m.sender}: {m.text}")
        print()

    if args.export:
        paths = wx.export(args.export, chat=args.chat, prefix="chat")
        for fmt, path in paths.items():
            print(f"{fmt}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
