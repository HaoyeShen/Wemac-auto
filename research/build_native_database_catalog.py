"""Pin embedded SQLite read APIs; never opens or decrypts a database file."""
import hashlib,json,shutil,subprocess
from pathlib import Path
from macho import MachO
from analyze_moments_layout import EXPECTED_SHA256

OFFSETS={'databaseVersion':0x5a412d4,'databaseExec':0x5a40d90,
         'databasePrepare':0x5a66b00,'databaseLockPrepare':0x5a6615c,
         'databaseClose':0x5a426b4,'databaseMutexTry':0x5a4af70,'databaseMutexLeave':0x5a4af90,'databaseEnter':0x5a4adac,'databaseLeave':0x5a4adc4}

def update(path):
    p=json.loads(path.read_text());original=MachO('/Applications/WeChat.app/Contents/Resources/wechat.dylib');local=MachO(p['corePath'])
    if hashlib.sha256(original.data).hexdigest()!=EXPECTED_SHA256:raise ValueError('Unrecognized original core')
    if hashlib.sha256(local.data).hexdigest()!=p['sha256']:raise ValueError('Local core changed')
    for name,offset in OFFSETS.items():
        if offset not in original.starts:raise ValueError('Not a function entry: '+name)
        head=original.read(offset,16)
        if head!=local.read(offset,16):raise ValueError('Function code changed: '+name)
        p['functions'][name]={'offset':offset,'head':head.hex()}
    p['nativeDatabase']={'version':3027002,'allocationSize':768,'magicOffset':112,'magic':0xa029a697,
                         'mutexTrySlot':0xa26faa8+0x98,'mutexLeaveSlot':0xa26faa8+0xa0}
    helper=Path(__file__).with_name('native-db-gate.dylib')
    subprocess.run(['codesign','--force','--sign','-','--timestamp=none',str(helper)],check=True,capture_output=True)
    digest=hashlib.sha256(helper.read_bytes()).hexdigest()
    if p.get('bundle_id')=='com.wemac.auto.client':
        folder=Path.home()/'Library/Containers/com.wemac.auto.client/Data/Library/Caches/Wemac-auto/Native'
        folder.mkdir(parents=True,exist_ok=True)
        installed=folder/('database-gate-'+digest[:12]+'.dylib')
        shutil.copy2(helper,installed);helper=installed
    p['nativeDatabase']['bridge']={'path':str(helper.resolve()),'sha256':digest}
    path.write_text(json.dumps(p,indent=2)+'\n')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',type=Path,required=True)
    update(parser.parse_args().profile);print('Native database read catalog pinned; no file opened and no data changed.')
