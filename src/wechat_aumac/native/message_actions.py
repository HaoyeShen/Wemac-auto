"""App-message quote contracts and strictly bound message references."""
from __future__ import annotations
import xml.etree.ElementTree as ET
from .cards import parse_xml
from .media import _one,base_request_placeholder
from .wire import blob,decode,integer


def identifier(value):
    if not isinstance(value,str) or not value or '\0' in value or len(value.encode('utf-8'))>128:
        raise ValueError('Invalid internal identifier')
    return value


def message_reference(message,receiver):
    identifier(receiver)
    if not isinstance(message,dict) or message.get('chat_id')!=receiver:
        raise ValueError('Referenced message must belong to the explicit destination chat')
    value=message.get('message_id')
    if isinstance(value,bool) or not str(value).isascii() or not str(value).isdigit() or not 0<int(value)<1<<64:
        raise ValueError('Reference requires a real unsigned 64-bit server message ID')
    sender=identifier(message.get('sender'))
    kind=message.get('message_type')
    if isinstance(kind,bool) or not isinstance(kind,int) or not 0<kind<1<<32:
        raise ValueError('Reference requires the original native message type')
    if message.get('revoked'):raise ValueError('Cannot use an already revoked message')
    return str(value),sender,kind


def quote_xml(receiver,text,reference):
    server_id,sender,kind=message_reference(reference,receiver)
    if not isinstance(text,str) or not text or '\0' in text or len(text.encode('utf-8'))>16384:
        raise ValueError('Quote text must be nonempty and at most 16 KiB')
    root=ET.Element('appmsg',{'appid':'','sdkver':'0'})
    for tag,value in [('title',text),('des',''),('action',''),('type','57'),('showtype','0'),('content',''),('url','')]:
        ET.SubElement(root,tag).text=value
    ref=ET.SubElement(root,'refermsg')
    for tag,value in [('type',str(kind)),('svrid',server_id),('fromusr',sender),
                      ('chatusr',sender if receiver.endswith('@chatroom') else ''),
                      ('displayname',reference.get('display_name',sender)),
                      ('content',reference.get('text','')),('msgsource',reference.get('source_xml','')),
                      ('createtime',str(reference.get('timestamp',0)))]:
        if not isinstance(value,str) or '\0' in value:raise ValueError('Invalid quote reference metadata')
        ET.SubElement(ref,tag).text=value
    xml=ET.tostring(root,encoding='unicode')
    try:parse_xml(xml)
    except ET.ParseError as exc:raise ValueError('Quote contains invalid XML characters') from exc
    if len(xml.encode())>65536:raise ValueError('Quote XML exceeds 64 KiB')
    return xml


def quote_request(sender,receiver,text,reference,*,client_id,timestamp):
    for item in [sender,receiver,client_id]:identifier(item)
    if isinstance(timestamp,bool) or not isinstance(timestamp,int) or not 0<timestamp<1<<32:
        raise ValueError('Invalid message timestamp')
    xml=quote_xml(receiver,text,reference)
    app=(blob(1,sender)+blob(2,'')+integer(3,0)+blob(4,receiver)+integer(5,57)
         +blob(6,xml)+integer(7,timestamp)+blob(8,client_id)+integer(10,1)
         +blob(12,'<msgsource><alnode><fr>1</fr></alnode></msgsource>')
         +blob(13,'')+blob(14,'')+blob(15,''))
    return (blob(1,base_request_placeholder())+blob(2,app)+blob(5,'')+integer(9,0)
            +integer(10,0)+integer(11,2))


def parse_app_request(data):
    root=decode(data);app=_one(root,2,2)
    if app is None:raise ValueError('Missing AppMsg')
    fields=decode(app)
    result={key:_one(fields,n,2,b'').decode('utf-8') for key,n in
            [('sender',1),('receiver',4),('content',6),('client_id',8)]}
    result.update(subtype=_one(fields,5,0),timestamp=_one(fields,7,0))
    return result


def parse_app_response(data):
    fields=decode(data);base=_one(fields,1,2)
    if base is None:raise ValueError('Missing app-message BaseResponse')
    code=_one(decode(base),1,0)
    if code is None:raise ValueError('Missing app-message return code')
    if code&(1<<31):code=(code&0xffffffff)-(1<<32)
    return {'return_code':code,'sender':_one(fields,3,2,b'').decode('utf-8'),
            'receiver':_one(fields,4,2,b'').decode('utf-8'),
            'legacy_message_id':str(_one(fields,5,0,0)),
            'client_id':_one(fields,6,2,b'').decode('utf-8'),
            'timestamp':_one(fields,7,0,0),'subtype':_one(fields,8,0),
            'server_message_id':str(_one(fields,9,0,0))}


def validate_app_response(request,response):
    if response['return_code']!=0:return 'rejected'
    if any(request[key]!=response[key] for key in ['sender','receiver','client_id','subtype']):
        raise ValueError('App-message response does not match the request')
    if int(response['server_message_id'])<=0:raise ValueError('App-message response lacks a server message ID')
    return 'acknowledged'


def revoke_request(sender,receiver,server_id,*,request_id,timestamp):
    """Single-message revoke schema observed on 4.2.0, not BatchRevokeMsgRequest.

    Request fields 2/3/4 form the local request correlation token. Field 9 is the
    original server message ID. The legacy 32-bit server ID is zero in captures.
    """
    for value in (sender,receiver):identifier(value)
    for value in (request_id,timestamp):
        if isinstance(value,bool) or not isinstance(value,int) or not 0<value<1<<32:
            raise ValueError('Revoke request ID and timestamp must be positive uint32 values')
    if isinstance(server_id,bool) or not str(server_id).isascii() or not str(server_id).isdigit() or not 0<int(server_id)<1<<64:
        raise ValueError('Revoke requires an unsigned 64-bit server message ID')
    token=f'{receiver}_{timestamp}_{request_id}'
    return (blob(1,base_request_placeholder())+blob(2,token)+integer(3,request_id)
            +integer(4,timestamp)+integer(5,0)+blob(6,sender)+blob(7,receiver)
            +integer(8,0)+integer(9,int(server_id)))


def parse_revoke_response(data):
    fields=decode(data);base=_one(fields,1,2)
    if base is None:raise ValueError('Missing revoke BaseResponse')
    code=_one(decode(base),1,0)
    if code is None:raise ValueError('Missing revoke return code')
    if code&(1<<31):code=(code&0xffffffff)-(1<<32)
    return {'status':'acknowledged' if code==0 else 'rejected','return_code':code,
            'text':_one(fields,3,2,b'').decode('utf-8')}


def revoke_metadata(client_id, timestamp):
    """Recover the local numeric correlation only from SDK/native metadata."""
    if isinstance(client_id,int) and not isinstance(client_id,bool):
        return {'revoke_client_id':client_id,'timestamp':timestamp}
    if isinstance(client_id,str):
        parts=client_id.rsplit('_',2)
        if len(parts)==3 and all(part.isascii() and part.isdigit() for part in parts[1:]):
            stamp,number=map(int,parts[1:])
            if 0<stamp<1<<32 and 0<number<1<<32:
                return {'revoke_client_id':number,'timestamp':stamp}
    return {'timestamp':timestamp}
