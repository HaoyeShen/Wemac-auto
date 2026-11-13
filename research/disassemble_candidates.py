"""Disassemble static candidates from disk without accessing the running process."""
import argparse
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offset', action='append', type=lambda s:int(s,0))
parser.add_argument('--size', type=int, default=384)
args=parser.parse_args()

binary = Path('/Applications/WeChat.app/Contents/Resources/wechat.dylib').read_bytes()
fat = None
for i in range(struct.unpack_from('>I', binary, 4)[0]):
    cpu, sub, off, size, align = struct.unpack_from('>IIIII', binary, 8+i*20)
    if cpu == 0x100000c:
        fat = off
assert fat is not None
pos = fat + 32
segments = []
base = None
for _ in range(struct.unpack_from('<I', binary, fat+16)[0]):
    cmd, size = struct.unpack_from('<II', binary, pos)
    if cmd == 0x19:
        name = binary[pos+8:pos+24].split(b'\0')[0]
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', binary, pos+24)
        segments.append((vmaddr, filesize, fat+fileoff))
        if name == b'__TEXT':
            base = vmaddr
    pos += size
profile=json.loads(Path(__file__).with_name('wechat-4.2.0-send-candidates.json').read_text())
offsets=sorted({int(x['candidate_function_offset'],16) for x in profile['references'] if x['string'] in ('MMStartTask','MMReq2Buf')})
if args.offset: offsets=args.offset
cs=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
for offset in offsets:
    address = base + offset
    for vmaddr, filesize, fileoff in segments:
        if vmaddr <= address < vmaddr+filesize:
            begin = fileoff + address - vmaddr
            code = binary[begin:begin+args.size]
            break
    else:
        raise ValueError('candidate outside file-backed segments')
    print(f'\nCandidate {offset:#x} (unvalidated):')
    for insn in cs.disasm(code, offset):
        print(f'{insn.address:#x}: {insn.mnemonic} {insn.op_str}')
