"""Build the native completion bridge; install only into the stopped research copy."""
from pathlib import Path
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wechat_aumac.hook_probe import process_path

root=Path(__file__).resolve().parent
app=root/'WeChat-Hook.app'
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--install',action='store_true');args=p.parse_args()
source=root.parent/'src/wechat_aumac/native/completion.cpp'
output=root/'native-completion.dylib'
subprocess.run(['clang++','-std=c++17','-O2','-arch','arm64','-dynamiclib',str(source),'-o',str(output)],check=True)
subprocess.run(['codesign','--force','--sign','-','--timestamp=none',str(output)],check=True)
if args.install:
    proc=subprocess.run(['pgrep','-x','WeChat'],capture_output=True,text=True)
    for text in proc.stdout.split():
        actual=process_path(int(text))
        if actual and Path(actual).is_relative_to(app):raise SystemExit('Stop the experimental copy before installation')
    raw=subprocess.run(['codesign','-d','--entitlements',':-',str(app)],check=True,capture_output=True).stdout
    ent=root/'completion-install-entitlements.plist';ent.write_bytes(raw)
    destination=app/'Contents/Frameworks/libaumac_completion.dylib'
    shutil.copy2(output,destination)
    subprocess.run(['codesign','--force','--sign','-','--options','0','--entitlements',str(ent),str(app)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    output=destination
profile=root/'native-profile-4.2.0.json'
r=json.loads(profile.read_text());r['completionHelper']={'path':str(output),'sha256':hashlib.file_digest(output.open('rb'),'sha256').hexdigest()}
profile.write_text(json.dumps(r,indent=2))
print('Completion bridge:',output)
