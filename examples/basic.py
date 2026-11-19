#!/usr/bin/env python3
"""Inspect a pinned native client, or explicitly send to an internal chat ID."""
import argparse,json
from wechat_aumac import WeChat


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',required=True);parser.add_argument('--pid',type=int)
    parser.add_argument('--to');parser.add_argument('--send')
    args=parser.parse_args()
    if args.send is not None and not args.to:parser.error('--send requires --to')
    with WeChat(args.profile,pid=args.pid,mode='full' if args.send is not None else 'inventory') as wx:
        result=wx.send_text(args.to,args.send) if args.send is not None else wx.status()
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
