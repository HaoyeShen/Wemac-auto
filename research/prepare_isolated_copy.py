"""Build a separate app identity and empty macOS containers for a second account.

Never copies user data or changes the installed original. Dry run by default.
"""
from pathlib import Path
import argparse,hashlib,json,plistlib,subprocess,sys,tempfile

from repair_copy_signing import plan,run,SOURCE,MACH_MAGICS

ROOT=Path(__file__).resolve().parent
TARGET=ROOT/'WeChat-Wemac.app'
OLD_ID='com.tencent.xinWeChat'
NEW_ID='com.wemac.auto.client'
SOURCE_CORE_SHA256='8180e3d032ca7e5e5136a17d117370143aae562686d37eec26af8215b3970cc2'


def remap(value):
    if isinstance(value,str):return value.replace(OLD_ID,NEW_ID)
    if isinstance(value,list):return [remap(x) for x in value]
    if isinstance(value,dict):return {remap(k):remap(v) for k,v in value.items()}
    return value


def isolated_entitlements(original,main=False):
    result=remap(original)
    if main:
        result['com.apple.security.get-task-allow']=True
        result['com.apple.security.cs.disable-library-validation']=True
    return result


def build(*,apply=False):
    assert len(OLD_ID.encode())==len(NEW_ID.encode())
    if TARGET.exists():raise ValueError('Isolated target already exists; inspect it rather than overwriting')
    source_info=plistlib.loads((SOURCE/'Contents/Info.plist').read_bytes())
    base_profile=json.loads((ROOT/'native-profile-4.2.0.json').read_text())
    if str(source_info['CFBundleVersion'])!=str(base_profile['build']):raise ValueError('Original WeChat build changed')
    if hashlib.sha256((SOURCE/'Contents/Resources/wechat.dylib').read_bytes()).hexdigest()!=SOURCE_CORE_SHA256:
        raise ValueError('Original core fingerprint changed; reanalyze before preparing another app')
    components=plan()
    report={'source':str(SOURCE),'app':str(TARGET),'bundle_id':NEW_ID,
            'container':str(Path.home()/'Library/Containers'/NEW_ID),
            'group_container':str(Path.home()/'Library/Group Containers'/('5A4RE8SF68.'+NEW_ID)),
            'copies_account_data':False,'original_modified':False,'components':len(components)}
    if not apply:return report
    run(['codesign','--verify','--deep','--strict',str(SOURCE)])
    # Refuse to reuse containers left by an earlier installation.
    for key in ['container','group_container']:
        if Path(report[key]).exists():raise ValueError('Existing isolated data requires manual inspection: '+key)
    run(['ditto',str(SOURCE),str(TARGET)])
    patched=[]
    for path in TARGET.rglob('*'):
        if path.is_symlink() or not path.is_file():continue
        if path.suffix=='.plist':
            try:old=plistlib.loads(path.read_bytes())
            except plistlib.InvalidFileException:continue
            new=remap(old)
            if path==TARGET/'Contents/Info.plist':
                new['CFBundleName']='Wemac';new['CFBundleDisplayName']='Wemac (Independent)'
                new['CFBundleURLTypes']=[{'CFBundleURLName':NEW_ID,'CFBundleURLSchemes':['wemac-auto']}]
            if new!=old:path.write_bytes(plistlib.dumps(new))
        else:
            with path.open('rb') as stream:magic=stream.read(4)
            if magic not in MACH_MAGICS:continue
            data=path.read_bytes();count=data.count(OLD_ID.encode())
            if count:
                path.write_bytes(data.replace(OLD_ID.encode(),NEW_ID.encode()))
                patched.append({'path':str(path.relative_to(TARGET)),'replacements':count})
    helper=TARGET/'Contents/Frameworks/libaumac_completion.dylib'
    run(['clang++','-std=c++17','-O2','-arch','arm64','-dynamiclib',str(ROOT.parent/'src/wechat_aumac/native/completion.cpp'),'-o',str(helper)])
    run(['codesign','--force','--sign','-','--timestamp=none',str(helper)])
    with tempfile.TemporaryDirectory(prefix='wemac-sign-') as temporary:
        for index,node in enumerate(components):
            destination=TARGET/node['path']
            command=['codesign','--force','--sign','-','--timestamp=none','--options','0','--identifier',remap(node['identifier'])]
            ent=isolated_entitlements(node['entitlements'],node['main'])
            if ent:
                location=Path(temporary)/f'{index}.plist';location.write_bytes(plistlib.dumps(ent))
                command+=['--entitlements',str(location)]
            run(command+[str(destination)])
    run(['codesign','--verify','--deep','--strict',str(TARGET)])
    run(['codesign','--verify','--deep','--strict',str(SOURCE)])
    profile=json.loads((ROOT/'native-profile-4.2.0.json').read_text())
    core=TARGET/'Contents/Resources/wechat.dylib'
    profile.update(app=str(TARGET),corePath=str(core),sha256=hashlib.sha256(core.read_bytes()).hexdigest(),
                   bundle_id=NEW_ID,completionHelper={'path':str(helper),'sha256':hashlib.sha256(helper.read_bytes()).hexdigest()})
    # Binary literals change the fingerprint. Require verification in the new process.
    profile['verified_capabilities']=[]
    for key in ['stability_verified','media_verification','moments_read_verification','recipient_confirmation','outgoing_observation_verification']:
        profile.pop(key,None)
    profile['isolation']={k:v for k,v in report.items() if k in ['bundle_id','container','group_container']}
    profile['moments_write_server_verified']=False
    (ROOT/'native-profile-isolated.json').write_text(json.dumps(profile,indent=2)+'\n')
    report['patched_literals']=patched;report['signature_verified']=True
    report['profile']=str(ROOT/'native-profile-isolated.json')
    (ROOT/'isolated-copy-build.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();print(json.dumps(build(apply=args.apply),indent=2))
