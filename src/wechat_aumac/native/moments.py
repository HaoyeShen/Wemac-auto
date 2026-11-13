"""Bounded SNS wire contracts. Builders themselves never submit a request.

Reads are server-verified. Write builders are experimental static contracts;
their native codec checks do not establish server acceptance.
"""
import xml.etree.ElementTree as ET

from .media import _one, base_request_placeholder
from .wire import blob, decode, integer


def timeline_request(*, max_id: int = 0, first_page_md5: str = '') -> bytes:
    if isinstance(max_id,bool) or not isinstance(max_id,int) or not 0<=max_id<1<<64:
        raise ValueError('max_id must be an unsigned 64-bit ID')
    if '\0' in first_page_md5 or len(first_page_md5.encode('utf-8'))>128:
        raise ValueError('Invalid first page digest')
    return blob(1,base_request_placeholder())+blob(2,first_page_md5)+integer(3,max_id)


def detail_request(post_id: str | int) -> bytes:
    if isinstance(post_id,bool) or not str(post_id).isascii() or not str(post_id).isdigit():
        raise ValueError('post_id must be a decimal unsigned 64-bit ID')
    value=int(post_id)
    if not 0<value<1<<64:raise ValueError('post_id is out of range')
    return blob(1,base_request_placeholder())+integer(2,value)


def _base_code(fields):
    base=_one(fields,1,2)
    if base is None:raise ValueError('Missing SNS BaseResponse')
    code=_one(decode(base),1,0)
    if code is None:raise ValueError('Missing SNS return code')
    return (code&0xffffffff)-(1<<32) if code&(1<<31) else code


def parse_object(data: bytes) -> dict:
    fields=decode(data)
    post_id=_one(fields,1,0)
    owner=_one(fields,2,2)
    if not post_id or owner is None:raise ValueError('SNS object has no ID or owner')
    owner=owner.decode('utf-8')
    result={'post_id':str(post_id),'owner_id':owner,
            'nickname':_one(fields,3,2,b'').decode('utf-8'),
            'timestamp':_one(fields,4,0),'text':None}
    wrapped=_one(fields,5,2)
    if wrapped is not None:
        xml=_one(decode(wrapped),2,2,b'')
        if len(xml)>1024*1024:raise ValueError('SNS XML exceeds the inspection limit')
        if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
            raise ValueError('SNS XML declarations are not allowed')
        result['description_xml']=xml.decode('utf-8')
        if xml:
            try:
                root=ET.fromstring(xml)
            except ET.ParseError:
                result['xml_parsed']=False
            else:
                result['xml_parsed']=True
                xml_owner=root.findtext('username')
                xml_id=root.findtext('id')
                if xml_owner and xml_owner!=owner:raise ValueError('SNS XML owner mismatch')
                if xml_id and xml_id!=str(post_id):raise ValueError('SNS XML ID mismatch')
                result['text']=root.findtext('contentDesc')
    return result


def parse_timeline_response(data: bytes) -> dict:
    fields=decode(data)
    code=_base_code(fields)
    if code!=0:return {'status':'rejected','return_code':code,'posts':[]}
    posts=[parse_object(v) for n,w,v in fields if n==4 and w==2]
    count=_one(fields,3,0)
    if count is not None and count!=len(posts):raise ValueError('SNS object count mismatch')
    return {'status':'acknowledged','return_code':code,'posts':posts,
            'first_page_md5':_one(fields,2,2,b'').decode('utf-8')}


def parse_detail_response(data: bytes) -> dict:
    fields=decode(data)
    code=_base_code(fields)
    if code!=0:return {'status':'rejected','return_code':code,'post':None}
    post=_one(fields,2,2)
    if post is None:raise ValueError('Missing SNS detail object')
    return {'status':'acknowledged','return_code':code,'post':parse_object(post)}


def _identifier(value):
    if not isinstance(value,str) or not value or '\0' in value or len(value.encode('utf-8'))>128:
        raise ValueError('Invalid SNS account/client identifier')
    return value


def interaction_request(post_id, sender, owner, *, client_id, action, timestamp, text='',nickname=''):
    # The checked business chain sets SnsAction field 5 to 1 for likes and 2
    # for root comments, field 6 to zero, field 7 to its creation timestamp.
    post=int(post_id)
    if not 0<post<1<<64 or action not in (1,2):raise ValueError('Invalid SNS interaction')
    _identifier(sender);_identifier(owner);_identifier(client_id)
    if not 0<timestamp<1<<32:raise ValueError('Invalid SNS timestamp')
    if '\0' in text or len(text.encode('utf-8'))>4096 or (action==2 and not text):
        raise ValueError('Comment must be nonempty and at most 4096 UTF-8 bytes')
    if action==1 and text:raise ValueError('A like cannot contain comment text')
    if '\0' in nickname or len(nickname.encode('utf-8'))>256:raise ValueError('Invalid nickname')
    item=(blob(1,sender)+blob(2,owner)+blob(3,nickname)+blob(4,owner)
          +integer(5,action)+integer(6,0)+integer(7,timestamp))
    if action==2:item+=blob(8,text)
    group=integer(1,post)+blob(3,item)
    return blob(1,base_request_placeholder())+blob(2,group)+blob(3,client_id)


def unlike_request(post_id):
    post=int(post_id)
    if not 0<post<1<<64:raise ValueError('Invalid SNS post ID')
    operation=integer(1,post)+integer(2,5)
    return blob(1,base_request_placeholder())+integer(2,1)+blob(3,operation)


def text_post_request(sender, text, *, visibility, client_id, timestamp):
    _identifier(sender);_identifier(client_id)
    if visibility not in {'private','public'}:raise ValueError('visibility must be private or public')
    if not text or '\0' in text or len(text.encode('utf-8'))>10000:
        raise ValueError('Post text must be nonempty and at most 10000 UTF-8 bytes')
    if not 0<timestamp<1<<32:raise ValueError('Invalid SNS timestamp')
    privacy=1 if visibility=='private' else 0
    root=ET.Element('TimelineObject')
    for name,value in [('id','0'),('username',sender),('createTime',str(timestamp)),
                       ('contentDesc',text),('contentDescShowType','0'),('contentDescScene','0'),
                       ('private',str(privacy))]:ET.SubElement(root,name).text=value
    content=ET.SubElement(root,'ContentObject')
    for name,value in [('contentStyle','2'),('title',''),('description',''),('contentUrl','')]:
        ET.SubElement(content,name).text=value
    xml=ET.tostring(root,encoding='utf-8')
    try:ET.fromstring(xml)
    except ET.ParseError as exc:raise ValueError('Post text contains invalid XML characters') from exc
    # No media URLs, tags or visibility lists are synthesized. Plain text only.
    payload=(blob(1,base_request_placeholder())+blob(2,integer(1,len(xml))+blob(2,xml))
             +integer(3,0)+integer(5,privacy)+integer(6,0)+blob(7,client_id))
    return payload,xml.decode('utf-8')


def parse_objectop_response(data):
    fields=decode(data);code=_base_code(fields)
    if code!=0:return {'status':'rejected','return_code':code}
    count=_one(fields,2,0)
    packed=[v for n,w,v in fields if n==3 and w==2]
    unpacked=[v for n,w,v in fields if n==3 and w==0]
    # The native serializer emits field 3 as packed signed int32 returns.
    if count==1 and ((packed==[b'\0'] and not unpacked) or (unpacked==[0] and not packed)):
        return {'status':'acknowledged','return_code':0}
    return {'status':'unconfirmed','return_code':0,'detail':'Object operation result was not a single success'}
