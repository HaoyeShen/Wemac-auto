"""Minimal read-only ARM64 Mach-O view for local reverse-engineering reports."""
import bisect
from pathlib import Path
import struct


class MachO:
    def __init__(self, path):
        self.data=Path(path).read_bytes()
        fat=0
        if self.data[:4]==bytes.fromhex('cafebabe'):
            for i in range(struct.unpack_from('>I',self.data,4)[0]):
                cpu,sub,off,size,align=struct.unpack_from('>IIIII',self.data,8+i*20)
                if cpu==0x100000c:
                    fat=off;break
        if self.data[fat:fat+4]!=bytes.fromhex('cffaedfe'):raise ValueError('ARM64 Mach-O expected')
        self.segments=[];self.starts=[]
        pos=fat+32;blob=b''
        for _ in range(struct.unpack_from('<I',self.data,fat+16)[0]):
            cmd,size=struct.unpack_from('<II',self.data,pos)
            if cmd==0x19:
                name=self.data[pos+8:pos+24].split(b'\0')[0]
                addr,span,offset,length=struct.unpack_from('<QQQQ',self.data,pos+24)
                self.segments.append((addr,length,fat+offset))
                if name==b'__TEXT':self.base=addr
            elif cmd==0x26:
                offset,length=struct.unpack_from('<II',self.data,pos+8)
                blob=self.data[fat+offset:fat+offset+length]
            pos+=size
        addr=self.base;value=shift=0
        for byte in blob:
            value|=(byte&127)<<shift
            if byte&128:shift+=7
            else:
                if not value:break
                addr+=value;self.starts.append(addr-self.base);value=shift=0

    def function(self, offset):
        i=bisect.bisect_right(self.starts,offset)-1
        return self.starts[i] if i>=0 else None

    def read(self, offset, length):
        address=self.base+offset
        for addr,size,fileoff in self.segments:
            if addr<=address and address+length<=addr+size:
                begin=fileoff+address-addr
                return self.data[begin:begin+length]
        raise ValueError('outside file-backed segments')
