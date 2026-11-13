"""Send one authorized >64 KiB PNG to the bound test chat, without retries."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'src'))
from wechat_aumac.native import NativeSession

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send',action='store_true',required=True)
    parser.add_argument('--to',required=True,help='Explicit recipient matching test-recipient.json')
    parser.add_argument('--file',type=Path,required=True,help='Authorized two-chunk PNG file')
    args=parser.parse_args()
    asset=args.file.resolve(strict=True)
    if not 65536<asset.stat().st_size<=131072:raise SystemExit('Expected exactly two chunks')
    prior=json.loads((ROOT/'image-send-verification.json').read_text())
    if prior.get('return_code')!=0 or not prior.get('response_numbers',{}).get('10'):
        raise SystemExit('Successful single-chunk experiment must precede this test')
    target=json.loads((ROOT/'test-recipient.json').read_text())['receiver']
    if target != args.to:raise SystemExit('Recipient must match --to and the local test binding')
    before=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat*.ips'))
    with NativeSession(ROOT/'native-profile-4.2.0.json',mode='full',experimental_operations=['image']) as wx:
        # Keep the capability local to this opt-in experiment until it succeeds.
        wx.profile['verified_capabilities'].append('send_image_server_ack')
        cb_before=wx._rpc('completionStatus')
        result=wx.send_image(target,asset,timeout=30)
        end=time.monotonic()+3
        while time.monotonic()<end:
            cb_after=wx._rpc('completionStatus')
            if int(cb_after['completed'])-int(cb_before['completed'])>=len(result.get('task_ids',[])):break
            time.sleep(.1)
        report={'file':str(asset),'bytes':asset.stat().st_size,'result':result,
                'completion_before':cb_before,'completion_after':cb_after,
                'observed_outgoing_images':len([m for m in wx.read() if m.get('message_type')==3 and m.get('direction')=='outgoing']),
                'session':wx.status(),'moments_operations':[],'timestamp':time.time()}
    after=set(Path.home().joinpath('Library/Logs/DiagnosticReports').glob('WeChat*.ips'))
    report['cleanup_errors']=wx.cleanup_errors
    report['new_crash_reports']=[str(p) for p in sorted(after-before)]
    (ROOT/'image-chunked-send-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if result['status']!='acknowledged':raise SystemExit(1)
