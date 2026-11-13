import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock

from wechat_aumac.native import NativeError, NativeSession
from wechat_aumac.native.wire import blob, integer, text_request


class NativeObservationTest(unittest.TestCase):
    def session(self, **kwargs):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        profile=Path(temp.name)/'profile.json'
        profile.write_text(json.dumps({'observations':{'image':{}},'mediaSubmits':{'image':'imageSubmit'},
                                       'requestTypes':{'image':{}},'verified_capabilities':['send_text_server_ack']}))
        return NativeSession(profile,**kwargs)

    def test_outgoing_requires_ack_and_keeps_exact_server_id(self):
        wx=self.session(mode='observe')
        request=text_request('123@chatroom','你好😀',100,1)
        wx._handle_event({'event':'text_request','taskId':7,'bytes':list(request)})
        self.assertEqual(wx.read(),[])
        response=blob(1,integer(1,0))+blob(3,integer(1,0)+integer(8,987654321012345678))
        event={'event':'text_response','taskId':7,'bytes':list(response)}
        wx._handle_event(event)
        wx._handle_event(event)
        messages=wx.read()
        self.assertEqual(len(messages),1)
        self.assertEqual(messages[0]['message_id'],'987654321012345678')
        self.assertEqual(messages[0]['direction'],'outgoing')
        self.assertEqual(messages[0]['text'],'你好😀')

    def test_rejected_or_uncorrelated_responses_do_not_invent_outgoing(self):
        for code in (0,5):
            wx=self.session(mode='observe')
            if code:
                wx._handle_event({'event':'text_request','taskId':1,'bytes':list(text_request('filehelper','test',1,1))})
            reply=blob(1,integer(1,code))+blob(3,integer(1,0)+integer(8,123))
            wx._handle_event({'event':'text_response','taskId':1,'bytes':list(reply)})
            self.assertEqual(wx.read(),[])

    def test_scene_correlates_request_before_native_task_id_is_assigned(self):
        wx=self.session(mode='observe')
        wx._handle_event({'event':'text_request','scene':'0x1234','taskId':0,
                          'bytes':list(text_request('target','test',1,1))})
        response=blob(1,integer(1,0))+blob(3,integer(1,0)+integer(8,999))
        wx._handle_event({'event':'text_response','scene':'0x1234','taskId':799,'bytes':list(response)})
        self.assertEqual(wx.read()[0]['message_id'],'999')
        self.assertIn(799,wx._replies)

    def test_partial_batch_does_not_confirm_failed_item(self):
        wx=self.session(mode='observe')
        first=blob(1,blob(1,'a'))+blob(2,'first')
        second=blob(1,blob(1,'b'))+blob(2,'second')
        wx._handle_event({'event':'text_request','taskId':1,'bytes':list(integer(1,2)+blob(2,first)+blob(2,second))})
        reply=(blob(1,integer(1,0))+blob(3,integer(1,0)+integer(8,11))
               +blob(3,integer(1,5)+integer(8,12)))
        wx._handle_event({'event':'text_response','taskId':1,'bytes':list(reply)})
        self.assertEqual([m['text'] for m in wx.read()],['first'])

    def test_invalid_incoming_does_not_reach_watch_as_a_message(self):
        wx=self.session()
        wx._handle_event({'event':'incoming_message','bytes':[255]})
        self.assertEqual(wx.next_event(0)['event'],'decode_error')
        self.assertIsNone(wx.next_event(0))

    def test_queue_is_bounded_by_bytes_and_reports_drops(self):
        wx=self.session()
        wx._event_budget=2200
        wx._enqueue({'event':'a','bytes':[0]*100})
        wx._enqueue({'event':'b','bytes':[0]*100})
        self.assertEqual(wx.dropped_events,1)
        self.assertEqual(wx.next_event(0)['event'],'b')
        self.assertEqual(wx._event_bytes,0)
        wx._enqueue({'event':'oversize','bytes':[0]*1000})
        self.assertEqual(wx.dropped_events,2)
        self.assertIsNone(wx.next_event(0))

    def test_observe_and_codec_modes_cannot_send(self):
        for mode in ('observe','codec'):
            wx=self.session(mode=mode)
            wx._script=object()
            with self.assertRaises(NativeError):wx.send_text('filehelper','test')
            with self.assertRaises(NativeError):wx._submit_media_request('image',integer(1,0))

    def test_moments_cannot_be_enabled_as_experimental_media(self):
        with self.assertRaisesRegex(ValueError,'Moments'):
            self.session(mode='full',experimental_operations=['moment_post'])

    def test_invalid_codec_payload_is_rejected_before_native_call(self):
        wx=self.session(mode='codec')
        wx._rpc=Mock()
        with self.assertRaises(ValueError):wx.roundtrip(b'\xff',kind='image')
        with self.assertRaises(ValueError):wx.roundtrip(b'',kind='unknown')
        wx._rpc.assert_not_called()

    def test_experimental_timeout_does_not_retry(self):
        wx=self.session(mode='full',experimental_operations=['image'])
        wx._rpc=Mock(return_value={'submitted':True,'taskId':5})
        result=wx._submit_media_request('image',integer(1,0),timeout=.001)
        self.assertEqual(result['status'],'unconfirmed')
        wx._rpc.assert_called_once()

    def test_native_response_correlated_by_operation_and_task(self):
        wx=self.session(mode='full',experimental_operations=['image'])
        def submit(*args):
            wx._handle_event({'event':'native_response','operation':'voice','taskId':5,'bytes':[8,0]})
            wx._handle_event({'event':'native_response','operation':'image','taskId':5,'bytes':[8,1]})
            return {'submitted':True,'taskId':5}
        wx._rpc=Mock(side_effect=submit)
        result=wx._submit_media_request('image',integer(1,0))
        self.assertEqual(result['bytes'],b'\x08\x01')
        self.assertEqual(result['status'],'response_received')

    def test_outgoing_watch_requires_a_mode_that_observes_requests(self):
        wx=self.session(mode='receive')
        with self.assertRaises(NativeError):next(wx.watch(direction='outgoing'))

    def test_malformed_reply_is_unconfirmed(self):
        wx=self.session(mode='full')
        wx._script=types.SimpleNamespace(exports_sync=types.SimpleNamespace(
            submit=Mock(return_value={'submitted':True,'taskId':5})))
        wx._replies[5]={'bytes':[255]}
        self.assertEqual(wx.send_text('filehelper','test')['status'],'unconfirmed')
