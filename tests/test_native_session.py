import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock

from wechat_aumac.native import NativeError, WeChatNative
from wechat_aumac.native.wire import blob, integer, parse_add_message


class NativeSessionTest(unittest.TestCase):
    def session(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'profile.json'
        path.write_text(json.dumps({'verified_capabilities':['send_text_server_ack']}))
        wx=WeChatNative(path, mode='full')
        submit=Mock(return_value={'taskId':7,'submitted':True})
        wx._script=types.SimpleNamespace(exports_sync=types.SimpleNamespace(submit=submit))
        return wx,submit

    def test_requires_server_message_id_and_success_for_each_message(self):
        for code,expected in [(0,'acknowledged'),(4,'rejected')]:
            wx,submit=self.session()
            response=blob(1,integer(1,0))+blob(3,integer(1,code)+integer(8,987654321012345678))
            wx._replies[7]={'bytes':list(response)}
            result=wx.send_text('123@chatroom','测试😀')
            self.assertEqual(result['status'],expected)
            submit.assert_called_once()
            if code==0:self.assertEqual(result['server_message_id'],'987654321012345678')

    def test_timeout_does_not_retry(self):
        wx,submit=self.session()
        result=wx.send_text('filehelper','test',timeout=.001)
        self.assertEqual(result['status'],'unconfirmed')
        submit.assert_called_once()

    def test_unverified_profile_cannot_send(self):
        wx,submit=self.session();wx.profile['verified_capabilities']=[]
        with self.assertRaises(NativeError):wx.send_text('filehelper','test')
        submit.assert_not_called()

    def test_addmsg_preserves_64bit_id_and_group_sender(self):
        packet=(integer(1,123)+blob(2,blob(1,'123@chatroom'))+blob(3,blob(1,'wxid_self'))
                +integer(4,1)+blob(5,blob(1,'wxid_sender:\n你好😀'))+integer(9,1794476100)
                +integer(12,987654321012345678))
        result=parse_add_message(packet)
        self.assertEqual(result['message_id'],'987654321012345678')
        self.assertEqual(result['chat_id'],'123@chatroom')
        self.assertEqual(result['sender'],'wxid_sender')
        self.assertEqual(result['text'],'你好😀')
