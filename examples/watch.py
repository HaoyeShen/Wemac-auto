#!/usr/bin/env python3
"""Listen for new messages. Usage: PYTHONPATH=src python3 examples/watch.py --help"""
from __future__ import annotations

import sys

from wechat_aumac.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["watch", *sys.argv[1:]]))
