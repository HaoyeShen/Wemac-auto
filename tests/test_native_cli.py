from contextlib import redirect_stdout,redirect_stderr
import io
import unittest
from unittest.mock import patch

from wechat_aumac import cli


class FakeNative:
    last=None
    def __init__(self,profile,**kwargs):
        FakeNative.last=self;self.options=kwargs;self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def send_image(self,*args,**kwargs):self.calls.append(('image',args,kwargs));return {'status':'acknowledged'}
    def send_voice(self,*args,**kwargs):self.calls.append(('voice',args,kwargs));return {'status':'acknowledged'}
    def send_sticker(self,*args,**kwargs):self.calls.append(('sticker',args,kwargs));return {'status':'acknowledged'}
    def send_video(self,*args,**kwargs):self.calls.append(('video',args,kwargs));return {'status':'acknowledged'}
    def get_moments(self,**kwargs):self.calls.append(('timeline',kwargs));return {'status':'acknowledged','posts':[]}
    def get_moment(self,*args,**kwargs):self.calls.append(('detail',args,kwargs));return {'status':'acknowledged','post':{}}
    def prepare_moment(self,*args,**kwargs):
        self.calls.append(('draft',args,kwargs));return {'published':False,'payload':b'bytes'}
    def send_quote(self,*args,**kwargs):self.calls.append(('quote',args,kwargs));return {'status':'acknowledged'}
    def revoke_message(self,*args,**kwargs):self.calls.append(('revoke',args,kwargs));return {'status':'acknowledged'}
    def like_moment(self,*args,**kwargs):self.calls.append(('like',args,kwargs));return {'status':'acknowledged'}
    def comment_moment(self,*args,**kwargs):self.calls.append(('comment',args,kwargs));return {'status':'acknowledged'}
    def unlike_moment(self,*args,**kwargs):self.calls.append(('unlike',args,kwargs));return {'status':'acknowledged'}
    def publish_moment(self,*args,**kwargs):self.calls.append(('publish',args,kwargs));return {'status':'acknowledged'}
    def publish_image_moment(self,*args,**kwargs):self.calls.append(('publish_image',args,kwargs));return {'status':'acknowledged'}


class NativeCLITest(unittest.TestCase):
    def test_explicit_publishing_routes_image_and_visibility(self):
        result,out,wx=self.run_cli(['native-moment-publish','--profile','profile','--visibility','private','--image','image.png','test'])
        self.assertEqual(result,0);self.assertEqual(wx.options['moments_operations'],('publish',))
        self.assertEqual(wx.options['mode'],'full');self.assertEqual(wx.calls[0][0],'publish_image')
        self.assertEqual(wx.calls[0][1],('test','image.png'));self.assertEqual(wx.calls[0][2]['visibility'],'private')
    def run_cli(self,args):
        out=io.StringIO()
        with patch('wechat_aumac.native.WeChatNative',FakeNative),redirect_stdout(out),redirect_stderr(io.StringIO()):
            result=cli.main(args)
        return result,out.getvalue(),FakeNative.last

    def test_media_commands_dispatch_with_exact_receiver_and_path(self):
        for kind in ('image','voice','sticker'):
            result,out,wx=self.run_cli(['native-send-'+kind,'--profile','profile','--to','123@chatroom','/tmp/file'])
            self.assertEqual(result,0);self.assertEqual(wx.options['mode'],'full')
            self.assertEqual(wx.calls[0][1],('123@chatroom','/tmp/file'))
            self.assertEqual(wx.options['experimental_operations'],())

    def test_unverified_media_opt_in_is_explicit(self):
        result,out,wx=self.run_cli(['native-send-voice','--profile','profile','--to','target','--experimental','/tmp/test.amr'])
        self.assertEqual(result,0);self.assertEqual(wx.options['experimental_operations'],('voice',))

    def test_video_preserves_thumbnail_and_duration_arguments(self):
        result,out,wx=self.run_cli(['native-send-video','--profile','profile','--to','target',
                                  '--thumbnail','/tmp/thumb.jpg','--duration','2','/tmp/test.mp4'])
        self.assertEqual(result,0)
        self.assertEqual(wx.calls[0][2]['duration_seconds'],2)
        self.assertEqual(wx.calls[0][2]['thumbnail'],'/tmp/thumb.jpg')

    def test_timeline_and_detail_select_read_operations(self):
        for command,operation,extra in [('native-moments','moment_timeline',[]),('native-moment','moment_detail',['--id','123'])]:
            result,out,wx=self.run_cli([command,'--profile','profile',*extra])
            self.assertEqual(result,0);self.assertEqual(wx.options['read_operations'],(operation,))
            self.assertNotIn('moments_operations',wx.options)

    def test_draft_has_no_publishing_side_effect_or_payload_dump(self):
        result,out,wx=self.run_cli(['native-moment-draft','--profile','profile','--visibility','private','draft text'])
        self.assertEqual(result,0);self.assertEqual(wx.options['mode'],'codec')
        self.assertEqual(wx.calls[0][0],'draft')
        self.assertIn('"published": false',out);self.assertNotIn('payload',out)

    def test_invalid_file_is_a_user_error_without_traceback(self):
        with patch.object(FakeNative,'send_image',side_effect=FileNotFoundError('missing')):
            result,out,wx=self.run_cli(['native-send-image','--profile','profile','--to','target','/missing'])
        self.assertEqual(result,1)

    def test_moments_commands_enable_only_the_requested_action(self):
        for action in ('like','comment','unlike'):
            args=['native-moment-'+action,'--profile','profile','--id','123']
            if action=='comment':args.append('exact text')
            result,out,wx=self.run_cli(args)
            self.assertEqual(result,0);self.assertEqual(wx.options['moments_operations'],(action,))
            self.assertEqual(wx.calls[0][0],action)
            self.assertEqual(wx.calls[0][1],('123','exact text') if action=='comment' else ('123',))

    def test_old_ui_commands_and_exports_are_removed(self):
        import wechat_aumac,importlib.util
        choices=cli.build_parser()._subparsers._group_actions[0].choices
        for command in ('read','send','open','watch','doctor'):self.assertNotIn(command,choices)
        self.assertFalse(hasattr(wechat_aumac,'WeChatUI'))
        self.assertIsNone(importlib.util.find_spec('wechat_aumac.ui'))
        self.assertIs(wechat_aumac.WeChat,wechat_aumac.WeChatNative)

    def test_quote_and_revoke_use_native_metadata_file_and_exact_pid(self):
        import tempfile,json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            reference=Path(root)/'reference.json';reference.write_text(json.dumps({'chat_id':'target','message_id':'123'}))
            result,out,wx=self.run_cli(['native-send-quote','--profile','profile','--to','target',
                                      '--reference',str(reference),'--pid','42','reply'])
            self.assertEqual(result,0);self.assertEqual(wx.options['message_operations'],('quote',))
            self.assertEqual(wx.options['pid'],42);self.assertEqual(wx.calls[0][1][:2],('target','reply'))
            result,out,wx=self.run_cli(['native-revoke','--profile','profile','--message',str(reference)])
            self.assertEqual(result,0);self.assertEqual(wx.options['message_operations'],('revoke',))
            self.assertEqual(wx.calls[0][0],'revoke')
