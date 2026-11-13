"""Static ARM64 references to Moments publishing and interaction strings."""
import json
import struct
from pathlib import Path
from macho import MachO

path=Path('/Applications/WeChat.app/Contents/Resources/wechat.dylib')
m=MachO(path)
terms=[b'DoPublishIfNeed',b'SendPostRequest',b'PreprocessVideo',b'LikeOrUnLikeFeed',
       b'mmui::SnsPublishViewModel',b'mmui::SnsPublishPanel',b'SnsPublishPanel',
       b'Comment',b'AddComment',b'DeleteComment',b'SendComment',b'LikeFeed',b'UnlikeFeed']
targets={}
for va,size,offset in m.segments:
    data=m.data[offset:offset+size]
    for term in terms:
        cursor=0
        while True:
            index=data.find(term+b'\0',cursor)
            if index<0:break
            targets[va+index-m.base]=term.decode()
            cursor=index+len(term)
pages={address&~0xfff for address in targets}
refs=[]
# Function starts bound the code region; do not scan literal pools as instructions.
start=m.starts[0];end=m.starts[-1]+4
code=m.read(start,end-start)
for i in range(0,len(code)-4,4):
    word=struct.unpack_from('<I',code,i)[0]
    if word&0x9f000000!=0x90000000:continue
    immediate=((word>>29)&3)|(((word>>5)&0x7ffff)<<2)
    if immediate&(1<<20):immediate-=1<<21
    pc=start+i
    page=(pc&~0xfff)+(immediate<<12)
    if page not in pages:continue
    register=word&31
    for distance in range(4,min(36,len(code)-i),4):
        add=struct.unpack_from('<I',code,i+distance)[0]
        if add&0xffc00000!=0x91000000 or (add>>5)&31!=register:continue
        address=page+((add>>10)&0xfff)
        if address not in targets:continue
        ref=pc+distance
        refs.append({'term':targets[address],'string_offset':hex(address),'xref':hex(ref),'function':hex(m.function(ref)),'dynamic_verified':False})
result={'build':'270348','architecture':'arm64','source':str(path),'targets':{hex(k):v for k,v in targets.items()},'references':refs,'published':False,'liked':False,'commented':False}
Path('research/moments-static-references.json').write_text(json.dumps(result,indent=2))
for ref in refs:print(ref)
