"""Build a standalone native CDN reader without modifying or restarting WeChat."""
import argparse,hashlib,json,subprocess,shutil
from pathlib import Path
from macho import MachO

def update(profile):
 p=json.loads(profile.read_text());m=MachO(p['corePath'])
 if hashlib.sha256(m.data).hexdigest()!=p['sha256']:raise ValueError('Unknown WeChat core')
 for name,off in {'decodeImageFile':0x4c77c34,'cdnDownload':0x5c201c8,'cdnHttpsDownload':0x5c207ec}.items():
  if off not in m.starts:raise ValueError('Not a native function entry')
  p['functions'][name]={'offset':off,'head':m.read(off,16).hex()}
 p['nativeResources']['imageDecoder']='decodeImageFile'
 source=Path(__file__).parents[1]/'src/wechat_aumac/native/cdn_download.cpp'
 output=profile.parent/'libwemac_cdn_download.dylib'
 subprocess.run(['clang++','-std=c++17','-dynamiclib','-O2','-mmacosx-version-min=13.0',str(source),'-o',str(output)],check=True,capture_output=True)
 subprocess.run(['codesign','--force','--sign','-','--timestamp=none',str(output)],check=True,capture_output=True)
 digest=hashlib.sha256(output.read_bytes()).hexdigest()
 root=Path.home()/'Library/Containers'/p['bundle_id']/'Data/Library/Caches/Wemac-auto'
 target=root/'Native'/('cdn-download-'+digest[:12]+'.dylib');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(output,target)
 p['nativeCdnDownload']={'bridge':{'path':str(target),'sha256':digest},'callbackVtableOffset':0x9fd8568,'cacheRoot':str(root/'Downloads')}
 profile.write_text(json.dumps(p,indent=2)+'\n')
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--profile',type=Path,required=True);args=a.parse_args();update(args.profile);print('Native C2C reader built and pinned; WeChat unchanged.')
