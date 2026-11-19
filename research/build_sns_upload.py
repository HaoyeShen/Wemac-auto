"""Build/pin an independent SNS CDN helper without changing or restarting WeChat."""
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path
from macho import MachO

def build(profile):
    p=json.loads(profile.read_text());core=MachO(p['corePath'])
    if hashlib.sha256(core.data).hexdigest()!=p['sha256']:raise ValueError('Unexpected core fingerprint')
    original=MachO('/Applications/WeChat.app/Contents/Resources/wechat.dylib')
    root=Path(__file__).resolve().parent;source=root.parent/'src/wechat_aumac/native/sns_upload.cpp';output=root/'sns-upload-native.dylib'
    subprocess.run(['clang++','-mmacosx-version-min=13.0','-std=c++17','-O2','-arch','arm64','-dynamiclib',str(source),'-o',str(output)],check=True)
    subprocess.run(['codesign','--force','--sign','-','--timestamp=none',str(output)],check=True)
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    cache=Path.home()/'Library/Containers'/p['bundle_id']/'Data/Library/Caches/Wemac-auto'
    destination=cache/'Native'/('sns-upload-'+digest[:12]+'.dylib');destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(output,destination)
    for name,offset in [('snsContextGetter',0x4795eb4),('snsCallbackFactory',0x3be1c6c),('snsCdnSend',0x5c200b8),('snsRequestCopy',0x35e8804)]:
        if offset not in core.starts or core.read(offset,16)!=original.read(offset,16):raise ValueError('SNS code mismatch')
        p['functions'][name]={'offset':offset,'head':core.read(offset,16).hex()}
    p['nativeSnsUpload']={'bridge':{'path':str(destination),'sha256':digest},'callbackVtableOffset':0x9fd8568,'cacheRoot':str(cache/'SNS')}
    profile.write_text(json.dumps(p,indent=2)+'\n');print('SNS upload helper pinned; WeChat unchanged')
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',type=Path,required=True);a=parser.parse_args();build(a.profile)
