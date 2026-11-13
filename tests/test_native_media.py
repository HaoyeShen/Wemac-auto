import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wechat_aumac.native import NativeSession
from wechat_aumac.native.media import image_request, parse_image_request, parse_image_response, validate_image_response
from wechat_aumac.native.wire import blob, integer


def reply(request, *, code=0, next_offset=None, message_id=987654321012345678):
    return (blob(1,integer(1,code)) + blob(3,blob(1,request['client_id']))
            +blob(4,blob(1,request['sender']))+blob(5,blob(1,request['receiver']))
            +integer(6,request['total'])
            +integer(7,request['offset']+request['chunk_bytes'] if next_offset is None else next_offset)
            +integer(8,0)+integer(10,message_id))


class NativeImageTest(unittest.TestCase):
    def session(self, length=70000):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        profile=root/'profile.json'
        profile.write_text(json.dumps({'verified_capabilities':['send_image_server_ack'],'mediaSubmits':{'image':'submitImage'}}))
        wx=NativeSession(profile,mode='full')
        wx.identity=Mock(return_value={'user_id':'wxid_self'})
        path=root/'image.png'
        path.write_bytes(b'\x89PNG\r\n\x1a\n'+b'0'*(length-8))
        return wx,path

    def test_multiple_chunks_keep_client_id_and_confirm_whole_file(self):
        wx,path=self.session()
        seen=[]
        def send(kind,payload,**kwargs):
            request=parse_image_request(payload);seen.append(request)
            return {'status':'response_received','task_id':len(seen),'bytes':reply(request)}
        wx._submit_media_request=Mock(side_effect=send)
        result=wx.send_image('123@chatroom',path)
        self.assertEqual(result['status'],'acknowledged')
        self.assertEqual(result['uploaded_bytes'],70000)
        self.assertEqual(result['server_message_id'],'987654321012345678')
        self.assertEqual([r['offset'] for r in seen],[0,65536])
        self.assertEqual(seen[0]['client_id'],seen[1]['client_id'])
        self.assertEqual(wx.read()[0]['message_type'],3)
        self.assertEqual(len(wx.read()),1)

    def test_timeout_stops_chunks_and_does_not_retry(self):
        wx,path=self.session()
        wx._submit_media_request=Mock(return_value={'status':'unconfirmed','task_id':1})
        self.assertEqual(wx.send_image('123@chatroom',path)['status'],'unconfirmed')
        wx._submit_media_request.assert_called_once()
        self.assertEqual(wx.read(),[])

    def test_zero_return_code_without_full_chunk_confirmation_is_not_success(self):
        wx,path=self.session()
        def send(kind,payload,**kwargs):
            request=parse_image_request(payload)
            return {'status':'response_received','task_id':1,'bytes':reply(request,next_offset=0)}
        wx._submit_media_request=Mock(side_effect=send)
        self.assertEqual(wx.send_image('123@chatroom',path)['status'],'unconfirmed')
        wx._submit_media_request.assert_called_once()

    def test_server_rejection_stops_upload(self):
        wx,path=self.session()
        def send(kind,payload,**kwargs):
            return {'status':'response_received','task_id':1,'bytes':reply(parse_image_request(payload),code=4)}
        wx._submit_media_request=Mock(side_effect=send)
        self.assertEqual(wx.send_image('123@chatroom',path)['status'],'rejected')
        wx._submit_media_request.assert_called_once()

    def test_mismatched_response_or_missing_final_id_is_not_accepted(self):
        request=parse_image_request(image_request('self','target','client',b'png',total=3,offset=0))
        response=parse_image_response(reply(request))
        for change in ({'receiver':'someone_else'},{'client_id':'old'},{'server_message_id':'0'}):
            with self.assertRaises(ValueError):validate_image_response(request,{**response,**change})

    def test_invalid_files_and_destination_do_not_send(self):
        wx,path=self.session()
        wx._submit_media_request=Mock()
        with self.assertRaises(ValueError):wx.send_image('',path)
        path.write_bytes(b'not an image')
        with self.assertRaises(ValueError):wx.send_image('target',path)
        wx._submit_media_request.assert_not_called()

    def test_chunk_bounds_and_duplicate_response_fields_are_rejected(self):
        for offset,total in [(-1,3),(1,3),(0,20*1024*1024+1)]:
            with self.assertRaises(ValueError):image_request('a','b','c',b'png',offset=offset,total=total)
        request=parse_image_request(image_request('a','b','c',b'png',offset=0,total=3))
        with self.assertRaises(ValueError):parse_image_response(reply(request)+integer(7,3))

    def test_own_synchronized_message_is_outgoing(self):
        wx,path=self.session()
        wx._own_user_id='wxid_self'
        packet=(integer(1,1)+blob(2,blob(1,'123@chatroom'))+blob(3,blob(1,'wxid_self'))
                +integer(4,3)+blob(5,blob(1,'wxid_self:\n<msg/>'))+integer(12,999))
        wx._handle_event({'event':'incoming_message','bytes':list(packet)})
        event=wx.next_event(0)
        self.assertEqual(event['event'],'outgoing_message')
        self.assertEqual(wx.read()[0]['direction'],'outgoing')
