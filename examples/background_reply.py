#!/usr/bin/env python3
"""Explicitly reply to one selected chat through internal functions only.

Does not activate WeChat, simulate input, inspect windows or use the clipboard.
"""
import sys
from wechat_aumac.cli import main

if __name__=='__main__':
    raise SystemExit(main(['native-reply',*sys.argv[1:]]))
