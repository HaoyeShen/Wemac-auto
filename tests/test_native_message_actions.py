import json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import Mock
from wechat_aumac.native import NativeSession,NativeError
from wechat_aumac.native.message_actions import (quote_request,quote_xml,parse_app_request,parse_app_response,
    validate_app_response,revoke_request,parse_revoke_response,revoke_metadata)
from wechat_aumac.native.cards import inspect_card
from wechat_aumac.native.wire import blob,integer,decode


def message(**updates):
    return {'message_id':'18446744073709551615','chat_id':'group@chatroom','sender':'self',
            'from_user':'self','to_user':'group@chatroom','text':'quoted <text> & value','message_type':1,
            'timestamp':100,'revoke_client_id':123,'direction':'outgoing',**updates}


class NativeMessageActionsTest(unittest.TestCase):
    def session(self,actions=(),mode='full'):
        root=tempfile.TemporaryDirectory();self.addCleanup(root.cleanup)
        p=Path(root.name)/'profile.json';p.write_text(json.dumps({'messageSubmits':{'app_message':'quote','revoke':'revoke'}}))
        wx=NativeSession(p,mode=mode,message_operations=actions)
        wx.identity=Mock(return_value={'user_id':'self'})
        wx.roundtrip=Mock(side_effect=lambda data,**kwargs:{'parsed':True,'bytes':list(data)})
        wx._perform_native_request=Mock()
        return wx

    def test_quote_preserves_id_escaping_and_binds_the_same_chat(self):
        xml=quote_xml('group@chatroom','A < B & C',message())
        card=inspect_card(xml)
        self.assertEqual(card['subtype'],'57');self.assertEqual(card['title'],'A < B & C')
        self.assertEqual(card['quote']['svrid'],'18446744073709551615')
        self.assertEqual(card['quote']['content'],'quoted <text> & value')
        with self.assertRaises(ValueError):quote_xml('another','reply',message())
        with self.assertRaises(ValueError):quote_xml('group@chatroom','\x01',message())

    def test_app_response_must_match_sender_receiver_client_subtype_and_server_id(self):
        payload=quote_request('self','group@chatroom','reply',message(),client_id='client',timestamp=100)
        request=parse_app_request(payload)
        wire=(blob(1,integer(1,0))+blob(3,'self')+blob(4,'group@chatroom')+blob(6,'client')
              +integer(8,57)+integer(9,18446744073709551615))
        reply=parse_app_response(wire)
        self.assertEqual(validate_app_response(request,reply),'acknowledged')
        for key,value in [('sender','other'),('receiver','other'),('client_id','other'),('subtype',5),('server_message_id','0')]:
            with self.subTest(key=key),self.assertRaises(ValueError):validate_app_response(request,{**reply,key:value})

    def test_default_and_read_only_sessions_do_not_enable_writes(self):
        wx=self.session()
        with self.assertRaises(NativeError):wx.send_quote('group@chatroom','hi',message())
        with self.assertRaises(NativeError):wx.revoke_message(message())
        wx._perform_native_request.assert_not_called()
        for mode in ('inventory','receive','observe','codec'):
            with self.assertRaises(ValueError):self.session(('quote',),mode=mode)

    def test_revoke_rejects_other_sender_missing_metadata_and_wrong_destination_before_submit(self):
        wx=self.session(('revoke',))
        for value in [message(sender='other'),message(direction='incoming'),message(to_user='other'),
                      message(revoked=True),message(revoke_client_id=None),message(timestamp=True)]:
            with self.subTest(value=value),self.assertRaises(ValueError):wx.revoke_message(value)
        wx._perform_native_request.assert_not_called()

    def test_single_revoke_uses_original_metadata_and_exact_uint64_id(self):
        wire=revoke_request('self','group@chatroom','18446744073709551615',request_id=123,timestamp=100)
        fields=decode(wire)
        self.assertIn((2,2,b'group@chatroom_100_123'),fields)
        self.assertIn((3,0,123),fields);self.assertIn((4,0,100),fields)
        self.assertIn((9,0,18446744073709551615),fields)
        wx=self.session(('revoke',));wx._messages=[message()]
        wx._perform_native_request.return_value={'status':'response_received','task_id':9,'bytes':blob(1,integer(1,0))+blob(3,'已撤回')}
        result=wx.revoke_message(message())
        self.assertEqual(result['status'],'acknowledged');self.assertTrue(wx._messages[0]['revoked'])
        self.assertEqual(wx._perform_native_request.call_args.args[:2],('writeMessage','revoke'))

    def test_revoke_timeout_rejection_and_malformed_response_do_not_erase_messages(self):
        for response in [{'status':'unconfirmed','task_id':9},
                         {'status':'response_received','task_id':9,'bytes':blob(1,integer(1,4))},
                         {'status':'response_received','task_id':9,'bytes':b''}]:
            wx=self.session(('revoke',));wx._messages=[message()];wx._perform_native_request.return_value=response
            result=wx.revoke_message(message())
            self.assertNotEqual(result['status'],'acknowledged');self.assertNotIn('revoked',wx._messages[0])
            wx._perform_native_request.assert_called_once()

    def test_background_reply_cannot_loop_on_self_or_protocol_events(self):
        wx=self.session();wx.send_text=Mock(return_value={'status':'acknowledged'})
        for value in [message(),message(direction='incoming'),message(direction='incoming',sender='other',message_type=10002)]:
            with self.assertRaises(ValueError):wx.reply(value,'reply')
        wx.send_text.assert_not_called()
        wx.reply(message(direction='incoming',sender='other'),'reply')
        wx.send_text.assert_called_once_with('group@chatroom','reply',timeout=15)

    def test_sdk_media_client_token_keeps_original_revoke_metadata(self):
        self.assertEqual(revoke_metadata('aumac_100_123',200),{'timestamp':100,'revoke_client_id':123})
        self.assertEqual(revoke_metadata('opaque-uuid',200),{'timestamp':200})

    def test_idle_watcher_honors_timeout_without_ui_or_messages(self):
        wx=self.session(mode='receive');wx._session=object()
        self.assertEqual(list(wx.watch(timeout=.005)),[])
