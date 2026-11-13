"""Find request descriptors by literal command IDs; never execute target code."""
import struct,json
from pathlib import Path
from macho import MachO
m=MachO('/Applications/WeChat.app/Contents/Resources/wechat.dylib')
start=m.starts[0];code=m.read(start,m.starts[-1]+4-start)
needle=struct.pack('<I',0x3d800260) # str q0, [x19]
rows=[];cursor=0
while True:
 i=code.find(needle,cursor)
 if i<0:break
 cursor=i+4
 if i%4 or i<12:continue
 load=struct.unpack_from('<I',code,i-4)[0]
 if load&0xffc0001f!=0x3dc00000:continue
 rn=(load>>5)&31
 for back in [8,12,16]:
  adr=struct.unpack_from('<I',code,i-back)[0]
  if adr&0x9f00001f!=0x90000000|rn:continue
  imm=((adr>>29)&3)|(((adr>>5)&0x7ffff)<<2)
  if imm&(1<<20):imm-=1<<21
  address=((start+i-back)&~0xfff)+(imm<<12)+(((load>>10)&0xfff)*16)
  try:values=struct.unpack('<4I',m.read(address,16))
  except ValueError:continue
  if values[0] in tuple(range(207,220)):
   rows.append({'function':hex(m.function(start+i)),'literal':hex(address),'values':values})
Path('research/sns-request-descriptor-candidates.json').write_text(json.dumps(rows,indent=2))
for row in rows:print(row)
