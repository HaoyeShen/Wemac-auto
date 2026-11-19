"""Compile the permanent native C mutex bridge, without attaching to WeChat."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
source=ROOT.parent/'src/wechat_aumac/native/native_db_gate.c'
output=ROOT/'native-db-gate.dylib'
subprocess.run(['clang','-std=c11','-O2','-dynamiclib','-fvisibility=hidden','-arch','arm64',str(source),'-o',str(output)],check=True)
print(json.dumps({'path':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
