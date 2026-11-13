"""Find ARM64 string references; candidates are NOT verified callable functions."""
import argparse
import bisect
import hashlib
import json
import struct
from pathlib import Path


def locate(path, terms=None):
    data = Path(path).read_bytes()
    fat = 0
    if data[:4] == bytes.fromhex('cafebabe'):
        count = struct.unpack_from('>I', data, 4)[0]
        for i in range(count):
            cpu, sub, offset, size, align = struct.unpack_from('>IIIII', data, 8 + i * 20)
            if cpu == 0x100000c:
                fat = offset
                break
        else:
            raise ValueError('No ARM64 slice')
    if data[fat:fat+4] != bytes.fromhex('cffaedfe'):
        raise ValueError('Expected little-endian Mach-O 64')
    ncmds = struct.unpack_from('<I', data, fat + 16)[0]
    commands = fat + 32
    sections = []
    starts_blob = None
    base = None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, commands)
        if cmd == 0x19:
            name = data[commands+8:commands+24].split(b'\0')[0]
            if name == b'__TEXT':
                base = struct.unpack_from('<Q', data, commands+24)[0]
            nsects = struct.unpack_from('<I', data, commands+64)[0]
            for j in range(nsects):
                pos = commands + 72 + j * 80
                sect = data[pos:pos+16].split(b'\0')[0].decode()
                addr, length, offset = struct.unpack_from('<QQI', data, pos+32)
                sections.append((sect, addr, length, fat+offset))
        elif cmd == 0x26:
            offset, length = struct.unpack_from('<II', data, commands+8)
            starts_blob = data[fat+offset:fat+offset+length]
        commands += size
    starts = []
    address = base
    value = shift = 0
    for byte in starts_blob or b'':
        value |= (byte & 0x7f) << shift
        if byte & 0x80:
            shift += 7
        else:
            if not value:
                break
            address += value
            starts.append(address)
            value = shift = 0
    targets = {}
    for name, addr, length, offset in sections:
        if name != '__cstring':
            continue
        blob = data[offset:offset+length]
        for term in (terms or (b'MMStartTask', b'MMReq2Buf', b'Req2Buf', b'/cgi-bin/micromsg-bin/newsendmsg')):
            cursor = 0
            while True:
                n = blob.find(term+b'\0', cursor)
                if n < 0:
                    break
                # Only match the full C string, not a suffix.
                if n == 0 or blob[n-1] == 0:
                    targets[addr+n] = term.decode()
                cursor = n + len(term)
    pages = {address & ~0xfff for address in targets}
    refs = []
    for name, addr, length, offset in sections:
        if name != '__text':
            continue
        for i in range(0, length-4, 4):
            word = struct.unpack_from('<I', data, offset+i)[0]
            if word & 0x9f000000 != 0x90000000:  # ADRP
                continue
            imm = ((word >> 29) & 3) | (((word >> 5) & 0x7ffff) << 2)
            if imm & (1 << 20):
                imm -= 1 << 21
            page = ((addr+i) & ~0xfff) + (imm << 12)
            if page not in pages:
                continue
            register = word & 31
            for distance in range(4, min(36, length-i), 4):
                add = struct.unpack_from('<I', data, offset+i+distance)[0]
                if add & 0xffc00000 != 0x91000000 or ((add >> 5) & 31) != register:
                    continue
                target = page + ((add >> 10) & 0xfff)
                if target not in targets:
                    continue
                pc = addr+i+distance
                index = bisect.bisect_right(starts, pc)-1
                start = starts[index] if index >= 0 else None
                refs.append({'string': targets[target], 'string_offset': hex(target-base),
                             'xref_offset': hex(pc-base),
                             'candidate_function_offset': hex(start-base) if start is not None else None,
                             'verified': False})
    return {'binary': str(Path(path).resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
            'architecture': 'arm64', 'heuristic': 'ADRP + nearby ADD, nearest LC_FUNCTION_STARTS entry',
            'warning': 'Static candidates only; register clobbers and function roles require validation.',
            'references': refs}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary')
    parser.add_argument('--term', action='append', help='exact C string to locate (repeatable)')
    args = parser.parse_args()
    print(json.dumps(locate(args.binary, [s.encode() for s in args.term] if args.term else None), indent=2))
