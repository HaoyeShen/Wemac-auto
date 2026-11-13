"""Pin codec/observer addresses to local code bytes. Does not attach or submit."""
import hashlib
import json
from pathlib import Path

from analyze_moments_layout import EXPECTED_SHA256
from macho import MachO

ROOT = Path(__file__).resolve().parent
profile_path = ROOT / 'native-profile-4.2.0.json'
profile = json.loads(profile_path.read_text())
original = MachO('/Applications/WeChat.app/Contents/Resources/wechat.dylib')
copy = MachO(profile['corePath'])
if hashlib.sha256(original.data).hexdigest() != EXPECTED_SHA256:
    raise SystemExit('Original core changed; reanalyze before building catalog')
if hashlib.sha256(copy.data).hexdigest() != profile['sha256']:
    raise SystemExit('Experiment core fingerprint mismatch')
media = json.loads((ROOT / 'media-functions.json').read_text())
types = {'text':{'constructor':'requestConstructor', 'destructor':'requestDestructor', 'size':48}}
observations = {}
submits = {}
for name, kind in [('uploadmsgimg','image'), ('uploadvideo','video'),
                   ('sendemoji','sticker'), ('uploadvoice','voice')]:
    entry = media[name]
    ctor, dtor = f'{kind}RequestConstructor', f'{kind}RequestDestructor'
    for symbol, key in [(ctor,'request_constructor'),(dtor,'request_destructor')]:
        offset = int(entry[key],16)
        head = original.read(offset,16)
        if head != copy.read(offset,16):raise SystemExit(f'Code mismatch: {symbol}')
        profile['functions'][symbol] = {'offset':offset, 'head':head.hex()}
    types[kind] = {'constructor':ctor, 'destructor':dtor, 'size':entry['request_size']}
    observations[kind] = {'serialize':f'serialize_{name}', 'response':f'response_{name}',
                          'command_id':entry['command_id'], 'source':'previously observed task path'}
    symbol=f'{kind}Submit'
    offset=int(entry['submit'],16)
    head=original.read(offset,16)
    if head!=copy.read(offset,16):raise SystemExit(f'Code mismatch: {symbol}')
    profile['functions'][symbol]={'offset':offset,'head':head.hex()}
    submits[kind]=symbol
for kind, ctor, dtor, size, serialize, response, command in [
    ('moment_post',0x5476c1c,0x5492494,0x1a0,0x3b03ab4,0x3b03b74,209),
    ('moment_interaction',0x5476ffc,0x54ae8c4,0x28,0x3af4704,0x3af47c4,213),
    ('moment_objectop',0x5477134,0x54b656c,0x40,0x26b15d4,0x26b1694,218),
]:
    symbols={}
    for role,offset in [('constructor',ctor),('destructor',dtor),('serialize',serialize),('response',response)]:
        symbol=f'{kind}_{role}'
        head=original.read(offset,16)
        if head!=copy.read(offset,16):raise SystemExit(f'Code mismatch: {symbol}')
        profile['functions'][symbol]={'offset':offset,'head':head.hex()}
        symbols[role]=symbol
    types[kind]={'constructor':symbols['constructor'],'destructor':symbols['destructor'],'size':size}
    observations[kind]={'serialize':symbols['serialize'],'response':symbols['response'],
                        'command_id':command,'source':'static scene serializer/parser analysis; not dynamically observed'}
profile['requestTypes']=types
profile['observations']=observations
profile['mediaSubmits']=submits
read_submits={}
for kind,ctor,dtor,size,serialize,response,submit,command in [
    ('moment_timeline',0x5476d80,0x549d0f0,0x98,0x3bb29a0,0x3bb2a60,0x3bb26e4,211),
    ('moment_detail',0x5476ce0,0x5497088,0x28,0x3bc88b8,0x3bc8978,0x3bc85fc,210),
]:
    symbols={}
    for role,offset in [('constructor',ctor),('destructor',dtor),('serialize',serialize),('response',response),('submit',submit)]:
        symbol=f'{kind}_{role}'
        head=original.read(offset,16)
        if head!=copy.read(offset,16):raise SystemExit(f'Code mismatch: {symbol}')
        profile['functions'][symbol]={'offset':offset,'head':head.hex()}
        symbols[role]=symbol
    types[kind]={'constructor':symbols['constructor'],'destructor':symbols['destructor'],'size':size}
    observations[kind]={'serialize':symbols['serialize'],'response':symbols['response'],
                        'command_id':command,'source':'static read-only scene analysis'}
    read_submits[kind]=symbols['submit']
profile['readSubmits']=read_submits
moment_submits={}
for kind,offset in [('moment_post',0x3b037f8),('moment_interaction',0x3af4448),('moment_objectop',0x26b1318)]:
    symbol=f'{kind}_submit'
    head=original.read(offset,16)
    if head!=copy.read(offset,16):raise SystemExit(f'Code mismatch: {symbol}')
    profile['functions'][symbol]={'offset':offset,'head':head.hex()}
    moment_submits[kind]=symbol
profile['momentSubmits']=moment_submits
profile['moments_write_server_verified']=False
offset=0x479cd48
head=original.read(offset,16)
if head!=copy.read(offset,16):raise SystemExit('Account getter code mismatch')
profile['functions']['accountGetter']={'offset':offset,'head':head.hex()}
# Static catalog generation never enables Moments writing or adds verified
# capabilities. Live/replay verification reports control the capability list.
profile_path.write_text(json.dumps(profile,indent=2)+'\n')
print(json.dumps({'codec_types':list(types),'observers':list(observations),
                  'verified_capabilities':profile['verified_capabilities']},indent=2))
