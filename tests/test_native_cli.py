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
    def publish_moment(self,*args,**kwargs):raise AssertionError('CLI must not publish')


class NativeCLITest(unittest.TestCase):
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
