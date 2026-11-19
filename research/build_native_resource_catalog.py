"""Pin the account-bound native emoticon key getter; no key is exported."""
import hashlib,json
from pathlib import Path
from macho import MachO
from analyze_moments_layout import EXPECTED_SHA256

def update(path):
    p=json.loads(path.read_text());original=MachO('/Applications/WeChat.app/Contents/Resources/wechat.dylib');local=MachO(p['corePath'])
    if hashlib.sha256(original.data).hexdigest()!=EXPECTED_SHA256 or hashlib.sha256(local.data).hexdigest()!=p['sha256']:
        raise ValueError('Unrecognized core')
    address=0x487d90c
    if address not in original.starts:raise ValueError('Native resource getter is not a function entry')
    head=original.read(address,16)
    if head!=local.read(address,16):raise ValueError('Native resource getter changed')
    p['functions']['resourceKeyGetter']={'offset':address,'head':head.hex()}
    p['functions'].pop('resourceStorageMask',None)
    codec=Path(p['app'])/'Contents/Resources/MultiMediaDyn.framework/Versions/A/MultiMediaDyn'
    reference=Path('/Applications/WeChat.app/Contents/Resources/MultiMediaDyn.framework/Versions/A/MultiMediaDyn')
    digest=hashlib.sha256(codec.read_bytes()).hexdigest()
    original_codec,local_codec=MachO(reference),MachO(codec)
    begin,end=original_codec.starts[0],original_codec.starts[-1]+4
    if original_codec.read(begin,end-begin)!=local_codec.read(begin,end-begin):raise ValueError('Native WXGF codec code changed')
    p['nativeResources']={'keyGetter':'resourceKeyGetter','cipher':'AES-128-CBC','key_exported':False,
        'wxgfCodec':{'path':str(codec.resolve()),'sha256':digest,'abi':'wxam-5-bgra'}}
    path.write_text(json.dumps(p,indent=2)+'\n')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',type=Path,required=True)
    update(parser.parse_args().profile);print('Native resource getter pinned; no process attached and no key exported.')
