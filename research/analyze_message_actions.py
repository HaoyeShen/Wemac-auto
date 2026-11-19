"""Offline ARM64 references for quote sending, revocation and app isolation."""
import argparse,json,re,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from macho import MachO


def references(m,terms=(),targets=None):
    targets=dict(targets or {})
    for va,size,off in m.segments:
        data=m.data[off:off+size]
        for term in terms:
            cursor=0
            while True:
                index=data.find(term.encode(),cursor)
                if index<0:break
                targets[va+index-m.base]=term;cursor=index+len(term)
    pages={address&~0xfff for address in targets}
    start=m.starts[0];code=m.read(start,m.starts[-1]+4-start)
    cs=Cs(CS_ARCH_ARM64,CS_MODE_ARM);result=[]
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
            add=re.fullmatch(r'x\d+, '+reg+r', #(0x[0-9a-f]+|[0-9]+)',ins.op_str) if ins.mnemonic=='add' else None
            if not mem and not add:continue
            match=mem or add;address=page+(int(match.group(1),0) if match.group(1) else 0)
            for target,term in targets.items():
                if address<=target<address+(32 if mem else 1):
                    result.append({'term':term,'target':hex(target),'instruction':hex(ins.address)+' '+ins.mnemonic+' '+ins.op_str,'function':hex(m.function(ins.address))})
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--term',action='append');p.add_argument('--output',type=Path,default=Path(__file__).with_name('message-action-references.json'))
    a=p.parse_args();m=MachO('/Applications/WeChat.app/Contents/Resources/wechat.dylib')
    result=references(m,a.term or ['CoSendAppMsgCgi','SendRevokeReques','GetRevokeMessage','refermsg','RevokeMsg','5A4RE8SF68','FileProviderXPCService'])
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
