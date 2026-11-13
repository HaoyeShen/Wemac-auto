"""Version-specific media contracts pending/under live verification.

These builders never submit; the session separately controls experimental use.
"""
import hashlib
from .media import _one, base_request_placeholder
from .wire import blob, decode, integer


def _strings(*values):
    if any(not x or '\0' in x or len(x.encode('utf-8'))>128 for x in values):
        raise ValueError('Invalid media identifier')


def _buffer(data):return integer(1,len(data))+blob(2,data)


def _return_code(fields, field=1):
    base=_one(fields,field,2)
    if base is None:raise ValueError('Missing media BaseResponse')
    code=_one(decode(base),1,0)
    if code is None:raise ValueError('Missing media return code')
    return (code&0xffffffff)-(1<<32) if code&(1<<31) else code


def voice_request(sender, receiver, client_id, data, *, duration_ms, timestamp):
    _strings(sender,receiver,client_id)
    if not data.startswith(b'#!AMR\n') or not 0<len(data)<=65536:
        raise ValueError('This voice contract only supports one AMR-NB chunk')
    if not 0<duration_ms<=60000:raise ValueError('Invalid voice duration')
    return (blob(1,sender)+blob(2,receiver)+integer(3,0)+integer(4,len(data))
            +blob(5,client_id)+integer(6,0)+integer(7,duration_ms)+blob(8,_buffer(data))
            +integer(9,1)+blob(10,base_request_placeholder())+integer(11,0)
            +integer(13,0)+integer(14,timestamp)+integer(15,0))


def parse_voice_response(data):
    fields=decode(data)
    return {'return_code':_return_code(fields,10),
            'sender':_one(fields,1,2,b'').decode('utf-8'),
            'receiver':_one(fields,2,2,b'').decode('utf-8'),
            'offset':_one(fields,3,0),'length':_one(fields,4,0),
            'client_id':_one(fields,6,2,b'').decode('utf-8'),
            'created_at':_one(fields,5,0),'legacy_message_id':_one(fields,7,0),
            'duration_ms':_one(fields,8,0),'result_flag':_one(fields,9,0),
            'server_message_id':str(_one(fields,12,0,0))}


def amr_duration_ms(data):
    if not data.startswith(b'#!AMR\n'):raise ValueError('Expected AMR-NB audio')
    sizes=(13,14,16,18,20,21,27,32,6,None,None,None,None,None,None,1)
    pos=6;frames=0
    while pos<len(data):
        header=data[pos]
        size=sizes[(header>>3)&15]
        if header&0x83 or size is None or pos+size>len(data):
            raise ValueError('Invalid or truncated AMR frame')
        pos+=size;frames+=1
        if frames>3000:raise ValueError('Voice exceeds 60 seconds')
    if not frames:raise ValueError('Empty AMR audio')
    return frames*20


def sticker_request(receiver, client_id, data):
    _strings(receiver,client_id)
    if not data.startswith((b'GIF87a',b'GIF89a')) or not 0<len(data)<=65536:
        raise ValueError('This sticker contract only supports one GIF chunk')
    digest=hashlib.md5(data).hexdigest()
    item=(blob(1,digest)+integer(2,0)+integer(3,len(data))+blob(4,_buffer(data))
          +integer(5,2)+blob(6,receiver)+blob(9,client_id))
    return blob(1,base_request_placeholder())+integer(2,1)+blob(3,item),digest


def parse_sticker_response(data):
    fields=decode(data)
    entries=[]
    for n,w,v in fields:
        if n==3 and w==2:
            item=decode(v);code=_one(item,1,0)
            if code is not None and code&(1<<31):code=(code&0xffffffff)-(1<<32)
            entries.append({'return_code':code,'offset':_one(item,2,0),'total':_one(item,3,0),
                            'md5':_one(item,4,2,b'').decode('utf-8'),
                            'server_message_id':str(_one(item,6,0,0))})
    return {'return_code':_return_code(fields),'items':entries}


def video_request(sender,receiver,client_id,*,thumb_total,video_total,duration_seconds,
                  phase,offset,data):
    _strings(sender,receiver,client_id)
    if phase not in (0,1) or not data or len(data)>65536:
        raise ValueError('Invalid video chunk/phase')
    if not 0<thumb_total<=65536 or not 0<video_total<=20*1024*1024 or not 0<duration_seconds<=600:
        raise ValueError('Invalid video metadata')
    if offset<0 or offset+len(data)>(thumb_total if phase==0 else video_total):
        raise ValueError('Invalid video chunk bounds')
    return (blob(1,base_request_placeholder())+blob(2,client_id)+blob(3,sender)+blob(4,receiver)
            +integer(5,thumb_total)+integer(6,offset if phase==0 else thumb_total)
            +blob(7,_buffer(data if phase==0 else b''))+integer(8,video_total)
            +integer(9,0 if phase==0 else offset)+blob(10,_buffer(data if phase==1 else b''))
            +integer(11,duration_seconds)+integer(12,1)+integer(13,2)+integer(14,phase))


def parse_video_response(data):
    fields=decode(data)
    return {'return_code':_return_code(fields),'client_id':_one(fields,2,2,b'').decode('utf-8'),
            'thumb_offset':_one(fields,4,0),'video_offset':_one(fields,5,0),
            'server_message_id':str(_one(fields,6,0,0))}


def observed_requests(kind,data,own=None):
    """Metadata only; do not retain BaseRequest credentials or media bytes."""
    fields=decode(data)
    string=lambda n:_one(fields,n,2,b'').decode('utf-8')
    if kind=='voice':
        return [{'sender':string(1),'receiver':string(2),'client_id':string(5),
                 'offset':_one(fields,3,0,0),'total':_one(fields,3,0,0)+_one(fields,4,0,0),
                 'duration_ms':_one(fields,7,0,0)}]
    if kind=='video':
        return [{'sender':string(3),'receiver':string(4),'client_id':string(2),
                 'total':_one(fields,8,0,0),'duration_seconds':_one(fields,11,0,0)}]
    if kind=='sticker':
        result=[]
        for n,w,value in fields:
            if n!=3 or w!=2:continue
            item=decode(value)
            digest=_one(item,1,2,b'').decode('utf-8')
            result.append({'sender':own,'receiver':_one(item,6,2,b'').decode('utf-8'),
                           'client_id':_one(item,9,2,digest.encode()).decode('utf-8'),
                           'md5':digest,'total':_one(item,3,0,0)})
        return result
    raise ValueError('Unknown media observation type')


def confirmed_observations(kind,requests,data):
    """Pair final server results with captured request metadata, never submit."""
    result=[]
    if kind=='voice':
        reply=parse_voice_response(data)
        for item in requests:
            if (item['sender'] and item['receiver'] and reply['return_code']==0 and reply['result_flag']==2
                and all(reply[k]==item[k] for k in ['sender','receiver','client_id','duration_ms'])
                and reply['offset']+reply['length']==item['total'] and int(reply['server_message_id'])>0):
                result.append((item,reply['server_message_id']))
    elif kind=='video':
        reply=parse_video_response(data)
        for item in requests:
            if (item['receiver'] and reply['return_code']==0 and reply['client_id']==item['client_id']
                and reply['video_offset']==item['total'] and int(reply['server_message_id'])>0):
                result.append((item,reply['server_message_id']))
    elif kind=='sticker':
        reply=parse_sticker_response(data)
        if reply['return_code']==0:
            for response in reply['items']:
                for item in requests:
                    if (item['receiver'] and response['return_code']==0 and response['md5']==item['md5']
                        and response['offset']==item['total']==response['total'] and int(response['server_message_id'])>0):
                        result.append((item,response['server_message_id']))
    return result
