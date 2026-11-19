"""Add statically checked app-message/revoke ABIs; does not grant send capabilities."""
import hashlib,json
from pathlib import Path
from macho import MachO
from analyze_moments_layout import EXPECTED_SHA256


def update(path):
    p=json.loads(path.read_text());original=MachO('/Applications/WeChat.app/Contents/Resources/wechat.dylib')
    if hashlib.sha256(original.data).hexdigest()!=EXPECTED_SHA256:raise ValueError('Unrecognized original core')
    local=MachO(p['corePath'])
    if hashlib.sha256(local.data).hexdigest()!=p['sha256']:raise ValueError('Local core changed')
    for kind,ctor,dtor,size,submit,serialize,response,command in [
        ('app_message',0x524b59c,0x52644b0,0x68,0x3165850,0x3165b0c,0x3165bcc,107),
        ('revoke',0x5248900,0x5248de8,0x48,0x365d180,0x365d43c,0x365d4fc,536)]:
        symbols={}
        for role,offset in [('constructor',ctor),('destructor',dtor),('submit',submit),('serialize',serialize),('response',response)]:
            if offset not in original.starts:raise ValueError(f'Not a function entry: {kind} {role} {offset:#x}')
            name=kind+'_'+role;head=original.read(offset,16)
            if head!=local.read(offset,16):raise ValueError('Instruction mismatch: '+name)
            p['functions'][name]={'offset':offset,'head':head.hex()};symbols[role]=name
        p.setdefault('requestTypes',{})[kind]={'constructor':symbols['constructor'],'destructor':symbols['destructor'],'size':size}
        p.setdefault('messageSubmits',{})[kind]=symbols['submit']
        p.setdefault('observations',{})[kind]={'serialize':symbols['serialize'],'response':symbols['response'],'command_id':command,'source':'offline scene/copy/codec call analysis'}
    path.write_text(json.dumps(p,indent=2)+'\n')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',type=Path,default=Path(__file__).with_name('native-profile-4.2.0.json'))
    update(parser.parse_args().profile)
    print('Catalog updated; no sending, revocation or capability enablement performed')
