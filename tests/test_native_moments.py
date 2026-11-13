import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wechat_aumac.native import NativeError,NativeSession
from wechat_aumac.native.moments import (timeline_request,detail_request,interaction_request,unlike_request,
    text_post_request,parse_object,parse_timeline_response,parse_detail_response,parse_objectop_response)
from wechat_aumac.native.wire import blob,integer,decode


def post(post_id=987654321012345678,owner='owner',text='hello'):
    xml=f'<TimelineObject><id>{post_id}</id><username>{owner}</username><contentDesc>{text}</contentDesc><private>1</private></TimelineObject>'.encode()
    return integer(1,post_id)+blob(2,owner)+blob(3,'name')+integer(4,100)+blob(5,integer(1,len(xml))+blob(2,xml))


class MomentsContractTest(unittest.TestCase):
    def session(self,**kwargs):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        profile=Path(temp.name)/'profile.json'
        profile.write_text(json.dumps({'readSubmits':{'moment_detail':'detail'},
            'momentSubmits':{'moment_post':'post','moment_interaction':'interaction','moment_objectop':'op'},
            'verified_capabilities':['read_moments_server_ack']}))
        return NativeSession(profile,**kwargs)

    def test_read_keeps_exact_ids_and_checks_xml_identity(self):
        value=post()
        result=parse_timeline_response(blob(1,integer(1,0))+integer(3,1)+blob(4,value))
        self.assertEqual(result['posts'][0]['post_id'],'987654321012345678')
        self.assertEqual(result['posts'][0]['text'],'hello')
        with self.assertRaises(ValueError):parse_timeline_response(blob(1,integer(1,0))+integer(3,2)+blob(4,value))
        bad=integer(1,1)+blob(2,'someone_else')+blob(5,blob(2,'<TimelineObject><username>owner</username></TimelineObject>'))
        with self.assertRaises(ValueError):parse_object(bad)

    def test_xml_declarations_rejected(self):
        value=integer(1,1)+blob(2,'owner')+blob(5,blob(2,'<!DOCTYPE x><TimelineObject/>'))
        with self.assertRaises(ValueError):parse_object(value)

    def test_invalid_ids_do_not_become_reads(self):
        for value in (0,-1,True,'1.2','',2**64):
            with self.assertRaises(ValueError):detail_request(value)
        for value in (-1,True,2**64):
            with self.assertRaises(ValueError):timeline_request(max_id=value)

    def test_writes_disabled_in_default_session_even_full(self):
        wx=self.session(mode='full');wx._rpc=Mock()
        for action in (lambda:wx.publish_moment('hello',visibility='private'),
                       lambda:wx.like_moment(1),lambda:wx.comment_moment(1,'hello'),lambda:wx.unlike_moment(1)):
            with self.assertRaises(NativeError):action()
        wx._rpc.assert_not_called()

    def test_read_only_modes_reject_write_enablement(self):
        for mode in ('receive','inventory','codec','observe'):
            with self.assertRaises(ValueError):self.session(mode=mode,moments_operations=['publish'])

    def test_publish_enablement_does_not_enable_comment(self):
        wx=self.session(mode='full',moments_operations=['publish']);wx._rpc=Mock()
        with self.assertRaises(NativeError):wx.comment_moment(1,'hello')
        wx._rpc.assert_not_called()

    def test_draft_uses_native_codec_but_never_calls_submit(self):
        wx=self.session(mode='codec');wx.identity=Mock(return_value={'user_id':'self'})
        wx.roundtrip=Mock(side_effect=lambda data,**kwargs:{'parsed':True,'bytes':list(data)})
        wx._perform_native_request=Mock()
        draft=wx.prepare_moment('A < B & C',visibility='private')
        self.assertFalse(draft['published']);self.assertFalse(draft['server_validated'])
        self.assertTrue(draft['native_codec_validated'])
        self.assertIn('&lt;',draft['description_xml'])
        wx._perform_native_request.assert_not_called()

    def test_post_privacy_matches_request_and_xml(self):
        for visibility,expected in [('private',1),('public',0)]:
            payload,xml=text_post_request('self','hello',visibility=visibility,client_id='client',timestamp=1)
            self.assertIn((5,0,expected),decode(payload))
            self.assertIn(f'<private>{expected}</private>',xml)
        with self.assertRaises(ValueError):text_post_request('self','hi',visibility='friends',client_id='client',timestamp=1)
        with self.assertRaises(ValueError):text_post_request('self','\x01',visibility='private',client_id='client',timestamp=1)

    def test_like_comment_and_unlike_use_distinct_contracts(self):
        for action in (1,2):
            payload=interaction_request(123,'self','owner',client_id='client',action=action,timestamp=1,text='hi' if action==2 else '')
            group=next(v for n,w,v in decode(payload) if n==2)
            inner=next(v for n,w,v in decode(group) if n==3)
            self.assertIn((5,0,action),decode(inner))
        op=next(v for n,w,v in decode(unlike_request(123)) if n==3)
        self.assertEqual(decode(op),[(1,0,123),(2,0,5)])

    def test_base_success_does_not_hide_failed_object_operation(self):
        ok=blob(1,integer(1,0))+integer(2,1)+blob(3,b'\0')
        bad=blob(1,integer(1,0))+integer(2,1)+blob(3,b'\x01')
        self.assertEqual(parse_objectop_response(ok)['status'],'acknowledged')
        self.assertEqual(parse_objectop_response(bad)['status'],'unconfirmed')

    def test_failed_target_read_never_writes(self):
        wx=self.session(mode='full',moments_operations=['like','comment','unlike'])
        wx.get_moment=Mock(return_value={'status':'rejected','post':None})
        wx._moment_write=Mock()
        with self.assertRaises(NativeError):wx.like_moment(123)
        with self.assertRaises(NativeError):wx.unlike_moment(123)
        wx._moment_write.assert_not_called()
