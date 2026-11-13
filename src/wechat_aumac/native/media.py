"""Wire contracts verified against this client's native image codec and server.

BaseRequest placeholders are populated by the client's scene preparation code.
Never persist the prepared credentials observed in a serialized request.
"""
from .wire import blob, decode, integer


def base_request_placeholder() -> bytes:
    return blob(1,b'')+integer(2,0)+blob(3,b'')+integer(4,0)+blob(5,b'')+integer(6,0)


def image_request(sender: str, receiver: str, client_id: str, data: bytes,
                  *, total: int, offset: int) -> bytes:
    for value in (sender,receiver,client_id):
        if not value or '\0' in value or len(value.encode('utf-8'))>128:
            raise ValueError('Invalid image sender, receiver or client ID')
    if not data or len(data)>65536 or offset<0 or total<offset+len(data) or total>20*1024*1024:
        raise ValueError('Invalid image chunk bounds')
    return (blob(1,base_request_placeholder())+blob(2,blob(1,client_id))
            +blob(3,blob(1,sender))+blob(4,blob(1,receiver))
            +integer(5,total)+integer(6,offset)+integer(7,len(data))
            +blob(8,integer(1,len(data))+blob(2,data))+integer(9,3)+integer(11,0))


def _one(fields, number, wire_type, default=None):
    values=[v for n,w,v in fields if n==number and w==wire_type]
    if len(values)>1:
        raise ValueError(f'Duplicate singular field {number}')
    return values[0] if values else default


def _wrapped(fields, number):
    value=_one(fields,number,2)
    if value is None:return None
    inner=_one(decode(value),1,2)
    return inner.decode('utf-8') if inner is not None else None


def parse_image_request(data: bytes) -> dict:
    fields=decode(data)
    result={'client_id':_wrapped(fields,2),'sender':_wrapped(fields,3),
            'receiver':_wrapped(fields,4),'total':_one(fields,5,0),
            'offset':_one(fields,6,0),'chunk_bytes':_one(fields,7,0)}
    if any(v is None for v in result.values()):raise ValueError('Incomplete image request')
    if result['total']==result['offset']==result['chunk_bytes']==0:
        return result  # CDN/MD5-hit metadata request; no inline upload bytes.
    if not 0<=result['offset']<result['total']<=20*1024*1024:
        raise ValueError('Invalid observed image bounds')
    if not 0<result['chunk_bytes']<=65536 or result['offset']+result['chunk_bytes']>result['total']:
        raise ValueError('Invalid observed image chunk length')
    return result


def parse_image_response(data: bytes) -> dict:
    fields=decode(data)
    base=_one(fields,1,2)
    if base is None:raise ValueError('Missing image BaseResponse')
    code=_one(decode(base),1,0)
    if code is None:raise ValueError('Missing image return code')
    if code&(1<<31):code=(code&0xffffffff)-(1<<32)
    return {'return_code':code,'client_id':_wrapped(fields,3),'sender':_wrapped(fields,4),
            'receiver':_wrapped(fields,5),'total':_one(fields,6,0),
            'next_offset':_one(fields,7,0),'remaining_chunk_bytes':_one(fields,8,0),
            'server_message_id':str(_one(fields,10,0,0))}


def validate_image_response(request: dict, response: dict) -> str:
    """Return rejected/progress/acknowledged; inconsistent replies raise."""
    if response['return_code']!=0:return 'rejected'
    if any(response[k]!=request[k] for k in ('client_id','sender','receiver','total')):
        raise ValueError('Image response does not match submitted request')
    expected=request['offset']+request['chunk_bytes']
    if response['next_offset']!=expected:
        raise ValueError('Server did not confirm the complete submitted image chunk')
    if expected==request['total']:
        if int(response['server_message_id'])<=0:
            raise ValueError('Final image response has no server message ID')
        return 'acknowledged'
    return 'progress'
