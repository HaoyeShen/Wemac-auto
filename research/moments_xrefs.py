"""Find ARM64 address materializations including vector literal loads."""
import json,re,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from macho import MachO
m=MachO('/Applications/WeChat.app/Contents/Resources/wechat.dylib')
known=json.loads(Path('research/moments-static-references.json').read_text())
targets={int(k,16):v for k,v in known['targets'].items()}
# Include method names embedded in compact metadata strings.
for term in [b'LikeOrUnLikeFeed',b'sns_publish_task',b'sns_publish_util',b'DoPublishIfNeed',b'SendPostRequest',b'CoGetImageBuffer']:
 for va,size,off in m.segments:
  blob=m.data[off:off+size];i=blob.find(term)
  if i>=0:targets[va+i-m.base]=term.decode()
pages={address&~0xfff for address in targets}
start=m.starts[0];code=m.read(start,m.starts[-1]+4-start)
cs=Cs(CS_ARCH_ARM64,CS_MODE_ARM);refs=[]
for i in range(0,len(code)-36,4):
 word=struct.unpack_from('<I',code,i)[0]
 if word&0x9f000000!=0x90000000:continue
 immediate=((word>>29)&3)|(((word>>5)&0x7ffff)<<2)
 if immediate&(1<<20):immediate-=1<<21
 pc=start+i;page=(pc&~0xfff)+(immediate<<12)
 if page not in pages:continue
 reg='x'+str(word&31)
 for ins in cs.disasm(code[i+4:i+36],pc+4):
  mem=re.search(r'\['+reg+r'(?:, #(0x[0-9a-f]+|[0-9]+))?\]',ins.op_str)
  if not mem:continue
  address=page+(int(mem.group(1),0) if mem.group(1) else 0)
  for target,term in targets.items():
   if address<=target<address+32:
    refs.append({'term':term,'target':hex(target),'access':hex(address),'instruction':hex(ins.address)+' '+ins.mnemonic+' '+ins.op_str,'function':hex(m.function(ins.address))})
Path('research/moments-literal-references.json').write_text(json.dumps(refs,indent=2))
for r in refs:print(r)
