"""Read SNS protobuf metadata and serializer call sites from disk, never a process.

This is a version-specific static report, not a native-call profile or sender.
The tiny constant evaluator only reconstructs straight-line GetTypeName literals.
It does not execute ARM code, resolve business field names, or prove an ABI.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from macho import MachO


EXPECTED_SHA256 = '8180e3d032ca7e5e5136a17d117370143aae562686d37eec26af8215b3970cc2'
CORE = Path('/Applications/WeChat.app/Contents/Resources/wechat.dylib')
VTABLES = {
    'post_request': 0xa041558,
    'comment_request': 0xa042200,
    'comment_operation': 0xa042188,
    'action': 0xa042110,
    'object_operation_request': 0xa042728,
    'object_operation': 0xa0424d0,
}
MEDIA_VTABLES = {
    'image_request': 0xa028f28,
    'video_request': 0xa029180,
    'emoji_request': 0xa029a68,
    'voice_request': 0x9fddba8,
}
READ_VTABLES = {'timeline_request':0xa041a08,'detail_request':0xa041648,
               'timeline_response':0xa041af8,'detail_response':0xa0416c0,'sns_object':0xa040f40}
WRITERS = {
    0x5c1e8d4: 'message',
    0x5c1e73c: 'length_delimited_string_storage',
    0x5c1e5e4: 'varint_64',
    0x5c1e618: 'varint_32',
    0x5c1e598: 'varint_signed_32',
}


def instructions(macho, address):
    index = bisect.bisect_right(macho.starts, address)
    end = macho.starts[index]
    return list(Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(macho.read(address, end-address), address))


def reconstruct_type_name(macho, address):
    """Evaluate the literal initialization prefix up to strlen, without calls."""
    regs = {'xzr': 0, 'wzr': 0}
    vectors, memory = {}, {}
    evidence = []
    sequence = instructions(macho, address)
    skip_until = 0
    for index, ins in enumerate(sequence):
        if ins.address < skip_until:
            continue
        op, s = ins.mnemonic, ins.op_str
        # Recognize the exact byte-literal decoder shape present in the voice
        # type name. Bound its source, key and output; never follow native calls.
        if op == 'add' and s == 'x12, x10, x9':
            window = sequence[index:index+11]
            patterns = [
                ('add', 'x12, x10, x9'), ('ldrb', r'w12, \[x12, #(0x[\da-f]+)\]'),
                ('sub', r'w12, w12, #(0x[\da-f]+)'), ('and', 'x13, x9, #0xf'),
                ('add', 'x13, x10, x13'), ('ldrb', r'w13, \[x13, #(0x[\da-f]+)\]'),
                ('eor', 'w12, w12, w13'), ('strb', r'w12, \[x11, x9\]'),
                ('add', 'x9, x9, #1'), ('cmp', r'x9, #(0x[\da-f]+)'),
                ('b.ne', rf'#{hex(ins.address)}'),
            ]
            captures=[]
            if len(window)!=len(patterns):raise ValueError('truncated literal decoder')
            for item,(mnemonic,pattern) in zip(window,patterns):
                match=re.fullmatch(pattern,item.op_str)
                if item.mnemonic!=mnemonic or match is None:
                    raise ValueError(f'unsupported literal decoder at {item.address:#x}')
                captures.extend(int(value,0) for value in match.groups())
            encoded_offset,subtract,key_offset,length=captures
            if not 0<length<=512:raise ValueError('unbounded literal decoder')
            encoded=macho.read(regs['x10']+encoded_offset,length)
            key=macho.read(regs['x10']+key_offset,16)
            for i,byte in enumerate(encoded):
                memory[regs['x11']+i]=((byte-subtract)&255)^key[i&15]
            evidence.append({'instruction':hex(ins.address), 'literal':hex(regs['x10']+encoded_offset),
                             'bytes':length, 'decoder':'bounded subtract-xor byte loop'})
            skip_until=window[-1].address+4
            continue
        if op == 'bl':
            if s != '#0x72aef18':
                raise ValueError(f'unexpected call before type name: {ins.address:#x}')
            ptr = regs['x0']
            raw = bytearray()
            for i in range(256):
                value = memory.get(ptr+i)
                if value is None:
                    value = macho.read(ptr+i, 1)[0]
                if value == 0:
                    name = raw.decode('ascii')
                    if not name.startswith('micromsg.'):
                        raise ValueError(f'unexpected type name {name!r}')
                    return name, evidence
                raw.append(value)
            raise ValueError('unterminated type name')
        match = re.fullmatch(r'(x\d+), #([\dxabcdef]+)', s)
        if op == 'adrp' and match:
            regs[match[1]] = int(match[2], 0)
        match = re.fullmatch(r'(x\d+), (x\d+), #(0x[\da-f]+|\d+)', s)
        if op == 'add' and match and match[2] in regs:
            regs[match[1]] = regs[match[2]] + int(match[3], 0)
        match = re.fullmatch(r'([xw]\d+), #(-?0x[\da-f]+|-?\d+)', s)
        if op == 'mov' and match:
            regs[match[1]] = int(match[2], 0)
        match = re.fullmatch(r'([dsq])(\d+), \[(x\d+)(?:, #(0x[\da-f]+|\d+))?\]', s)
        if op == 'ldr' and match and match[3] in regs:
            size = {'s':4, 'd':8, 'q':16}[match[1]]
            literal = regs[match[3]] + int(match[4] or '0', 0)
            vectors[match[2]] = bytearray(macho.read(literal, size).ljust(16, b'\0'))
            evidence.append({'instruction':hex(ins.address), 'literal':hex(literal), 'bytes':size})
        match = re.fullmatch(r'v(\d+)\.s\[(\d+)\], v(\d+)\.s\[(\d+)\]', s)
        if op == 'mov' and match:
            dest, lane, source, source_lane = match.groups()
            begin, other = int(lane)*4, int(source_lane)*4
            vectors[dest][begin:begin+4] = vectors[source][other:other+4]
        match = re.fullmatch(r'([dsq])(\d+), \[(x\d+)(?:, #(0x[\da-f]+|\d+))?\]', s)
        if op == 'str' and match and match[3] in regs:
            size = {'s':4, 'd':8, 'q':16}[match[1]]
            ptr = regs[match[3]] + int(match[4] or '0', 0)
            memory.update({ptr+i:b for i,b in enumerate(vectors[match[2]][:size])})
        match=re.fullmatch(r'q(\d+), q(\d+), \[(x\d+)(?:, #(0x[\da-f]+|\d+))?\]',s)
        if op=='stp' and match and match[3] in regs:
            ptr=regs[match[3]]+int(match[4] or '0',0)
            data=vectors[match[1]]+vectors[match[2]]
            memory.update({ptr+i:b for i,b in enumerate(data)})
        match = re.fullmatch(r'([xw](?:\d+|zr)), \[(x\d+)(?:, #(0x[\da-f]+|\d+))?\]', s)
        if op in ('strh', 'strb', 'str') and match and match[1] in regs and match[2] in regs:
            size = {'strh':2, 'strb':1, 'str':8 if match[1].startswith('x') else 4}[op]
            ptr = regs[match[2]] + int(match[3] or '0', 0)
            value = regs[match[1]] & ((1 << (8*size))-1)
            memory.update({ptr+i:b for i,b in enumerate(value.to_bytes(size,'little'))})
    raise ValueError('GetTypeName strlen not found')


def serializer_fields(macho, address):
    """List explicit writer calls; storage offsets are evidence, not field names."""
    field = None
    source = None
    fields = []
    arrays = {}
    for ins in instructions(macho, address):
        match = re.fullmatch(r'w0, #(0x[\da-f]+|\d+)', ins.op_str)
        if ins.mnemonic == 'mov' and match:
            field = int(match[1], 0)
        match = re.fullmatch(r'([xw])1, \[x20(?:, #(0x[\da-f]+|\d+))?\]', ins.op_str)
        if ins.mnemonic == 'ldr' and match:
            source = {'storage_offset':hex(int(match[2] or '0',0)), 'load_bits':64 if match[1]=='x' else 32,
                      'load_instruction':hex(ins.address)}
        match = re.fullmatch(r'(x\d+), \[x20, #(0x[\da-f]+|\d+)\]', ins.op_str)
        if ins.mnemonic == 'ldr' and match:
            arrays[match[1]] = int(match[2], 0)
        match = re.fullmatch(r'x1, \[(x\d+), x\d+, lsl #3\]', ins.op_str)
        if ins.mnemonic == 'ldr' and match and match[1] in arrays:
            source = {'storage_offset':hex(arrays[match[1]]), 'load_bits':64,
                      'repeated_pointer_array':True, 'load_instruction':hex(ins.address)}
        if ins.mnemonic in ('bl', 'b') and ins.op_str.startswith('#'):
            target = int(ins.op_str[1:], 0)
            if target in WRITERS:
                fields.append({'number':field, 'encoding':WRITERS[target], **(source or {'storage_offset':None}),
                               'writer_call':hex(ins.address), 'writer':hex(target)})
            if ins.mnemonic == 'bl':
                field = None
                source = None
    return fields


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', type=Path, default=CORE)
    parser.add_argument('--scope', choices=['moments','media','read','all'], default='moments')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('moments-request-layout.json'))
    args = parser.parse_args()
    macho = MachO(args.core)
    digest = hashlib.sha256(macho.data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit('Core hash mismatch: this report only supports the analyzed 4.2.0 build')
    types = {}
    tables = (VTABLES if args.scope=='moments' else MEDIA_VTABLES if args.scope=='media'
              else READ_VTABLES if args.scope=='read' else {**VTABLES,**MEDIA_VTABLES,**READ_VTABLES})
    for role, table in tables.items():
        # This file uses chained rebase pointers. The low 32 bits hold these RVAs.
        slot = lambda offset: struct.unpack('<Q',macho.read(table+offset,8))[0] & 0xffffffff
        name, literals = reconstruct_type_name(macho, slot(0x10))
        types[role] = {'type_name':name, 'vtable':hex(table), 'get_type_name':hex(slot(0x10)),
                       'serializer':hex(slot(0x50)), 'type_name_literals':literals,
                       'fields':serializer_fields(macho,slot(0x50))}
    # Pin important business assignments to their decoded instructions. These
    # checks are local code reads, not execution of the instructions themselves.
    checks = {
        0x3aeba10: ('str', 'x8, [x24, #8]'),
        0x3aeb8f0: ('add', 'x1, x19, #0x30'),
        0x3aebedc: ('ldr', 'w10, [x20, #0x78]'),
        0x3aebee8: ('stp', 'w10, wzr, [x23, #0x28]'),
        0x3b9c788: ('mov', 'w8, #1'),
        0x3afa80c: ('mov', 'w9, #5'),
        0x3afa81c: ('str', 'w9, [sp, #0x48]'),
        0x3afaa38: ('bl', '#0x26aeb5c'),
    }
    code_checks = []
    for address, expected in checks.items():
        ins = next(Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(macho.read(address,4),address))
        if (ins.mnemonic,ins.op_str) != expected:
            raise ValueError(f'business evidence mismatch at {address:#x}')
        code_checks.append({'offset':hex(address), 'instruction':f'{ins.mnemonic} {ins.op_str}'})
    report = {'version':'4.2.0', 'build':'270348', 'core_sha256':digest,
              'method':'offline static literal reconstruction and serializer call inspection',
              'dynamic_verified':False, 'operations_performed':[], 'types':types,
              'business_instruction_checks':code_checks,
              'limitations':['Fields list only covers recognized direct writer calls; repeated and other encodings can be absent.',
                            'Type names and wire numbers do not establish business semantics, enum values, or a callable ABI.']}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({role:{'type':item['type_name'], 'direct_fields':len(item['fields'])} for role,item in types.items()},indent=2))


if __name__ == '__main__':
    main()
