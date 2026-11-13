"""Small, bounded protobuf wire codec for inspecting observed message payloads."""
from __future__ import annotations


def varint(value: int) -> bytes:
    if value < 0 or value >= 1 << 64:
        raise ValueError('expected unsigned 64-bit value')
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def integer(field: int, value: int) -> bytes:
    return varint(field << 3) + varint(value)


def blob(field: int, value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode('utf-8')
    return varint(field << 3 | 2) + varint(len(value)) + value


def decode(data: bytes, *, max_bytes: int = 4 * 1024 * 1024) -> list[tuple[int, int, int | bytes]]:
    if len(data) > max_bytes:
        raise ValueError('protobuf exceeds inspection limit')
    offset = 0

    def read_varint():
        nonlocal offset
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(data):
                raise ValueError('truncated varint')
            byte = data[offset]
            offset += 1
            if shift == 63 and byte > 1:
                raise ValueError('varint overflow')
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError('varint overflow')

    fields = []
    while offset < len(data):
        tag = read_varint()
        number, wire_type = tag >> 3, tag & 7
        if not 0 < number < (1 << 29):
            raise ValueError('invalid protobuf field')
        if wire_type == 0:
            value = read_varint()
        elif wire_type in (1, 2, 5):
            size = read_varint() if wire_type == 2 else (8 if wire_type == 1 else 4)
            if size > len(data) - offset:
                raise ValueError('truncated field')
            value = data[offset:offset+size]
            offset += size
        else:
            raise ValueError('unsupported wire type')
        fields.append((number, wire_type, value))
    return fields


def text_request(receiver: str, text: str, timestamp: int, client_id: int) -> bytes:
    if not receiver or '\x00' in receiver or not text or '\x00' in text:
        raise ValueError('receiver and text must be nonempty and contain no NUL')
    message = (blob(1, blob(1, receiver)) + blob(2, text) + integer(3, 1)
               + integer(4, timestamp) + integer(5, client_id)
               + blob(6, '<msgsource><alnode><fr>1</fr></alnode></msgsource>'))
    return integer(1, 1) + blob(2, message)


def parse_text_request(data: bytes) -> list[dict]:
    result = []
    for number, wire_type, value in decode(data):
        if number != 2 or wire_type != 2:
            continue
        fields = decode(value)
        item = {}
        for field, kind, payload in fields:
            if field == 1 and kind == 2:
                names = [v for n, w, v in decode(payload) if n == 1 and w == 2]
                if len(names) == 1:
                    item['receiver'] = names[0].decode('utf-8')
            elif field == 2 and kind == 2:
                item['text'] = payload.decode('utf-8')
            elif field in (3, 4, 5) and kind == 0:
                item[{3:'type', 4:'timestamp', 5:'client_id'}[field]] = payload
        if 'receiver' in item and 'text' in item:
            result.append(item)
    return result


def parse_text_response(data: bytes) -> dict:
    fields = decode(data)
    base = [value for n, w, value in fields if n == 1 and w == 2]
    if len(base) != 1:
        return {'acknowledged': False, 'reason': 'missing BaseResponse'}
    codes = [v for n, w, v in decode(base[0]) if n == 1 and w == 0]
    if len(codes) != 1:
        return {'acknowledged': False, 'reason': 'missing return code'}
    code = codes[0]
    if code & (1 << 31):
        code = (code & 0xffffffff) - (1 << 32)
    results = []
    for n, w, value in fields:
        if n == 3 and w == 2:
            results.append({field: val for field, kind, val in decode(value) if kind == 0})
    return {'acknowledged': code == 0, 'return_code': code, 'results': results}


def parse_add_message(data: bytes) -> dict:
    fields = decode(data)

    def number(field, default=0):
        return next((v for n,w,v in fields if n==field and w==0),default)

    def string(field, wrapped=False):
        value=next((v for n,w,v in fields if n==field and w==2),b'')
        if wrapped and value:
            value=next((v for n,w,v in decode(value) if n==1 and w==2),b'')
        return value.decode('utf-8')

    source=string(2,True)
    recipient=string(3,True)
    content=string(5,True)
    if not source or not recipient:
        raise ValueError('AddMsg is missing sender or receiver')
    chat=source if source.endswith('@chatroom') else recipient if recipient.endswith('@chatroom') else source
    sender=source
    if source.endswith('@chatroom') and ':\n' in content:
        sender,content=content.split(':\n',1)
    return {'message_id':str(number(12) or number(1)), 'from_user':source,
            'to_user':recipient,'chat_id':chat,'sender':sender,'text':content,
            'message_type':number(4),'timestamp':number(9), 'source_xml':string(10)}
