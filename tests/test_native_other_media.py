import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wechat_aumac.native import NativeSession
from wechat_aumac.native.media_experimental import (amr_duration_ms,parse_voice_response,
    voice_request,sticker_request,video_request)
from wechat_aumac.native.wire import blob,integer,decode


class OtherMediaTest(unittest.TestCase):
    def session(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        p=root/'profile.json';p.write_text(json.dumps({'verified_capabilities':[
            'send_voice_server_ack','send_sticker_server_ack','send_video_server_ack'],
            'mediaSubmits':{'voice':'voice','sticker':'sticker','video':'video'}}))
        wx=NativeSession(p,mode='full');wx.identity=Mock(return_value={'user_id':'self'})
        return wx,root

    def test_amr_duration_rejects_reserved_and_truncated_frames(self):
        valid=b'#!AMR\n'+b'\x3c'+bytes(31)
        self.assertEqual(amr_duration_ms(valid),20)
        for bad in (valid[:-1],b'#!AMR\n',b'#!AMR\n\x4c',b'not amr'):
            with self.assertRaises(ValueError):amr_duration_ms(bad)

    def test_voice_timestamp_duration_result_and_legacy_id_are_distinct(self):
        raw=integer(5,1794499614)+integer(7,892257299)+integer(8,520)+integer(9,2)+blob(10,integer(1,0))+integer(12,999)
        response=parse_voice_response(raw)
        self.assertEqual(response['duration_ms'],520)
        self.assertEqual(response['created_at'],1794499614)
        self.assertEqual(response['result_flag'],2)
        self.assertEqual(response['legacy_message_id'],892257299)

    def test_voice_api_confirms_identity_length_and_id(self):
        wx,root=self.session();path=root/'test.amr';path.write_bytes(b'#!AMR\n'+b'\x3c'+bytes(31))
        def send(kind,payload,**kwargs):
            f={n:v for n,w,v in decode(payload)}
            raw=(blob(1,'self')+blob(2,'target')+integer(3,0)+integer(4,path.stat().st_size)
                 +integer(5,100)+blob(6,f[5])+integer(7,123)+integer(8,20)+integer(9,2)
                 +blob(10,integer(1,0))+integer(12,999))
            return {'status':'response_received','task_id':1,'bytes':raw}
        wx._submit_media_request=Mock(side_effect=send)
        self.assertEqual(wx.send_voice('target',path)['status'],'acknowledged')
        self.assertEqual(wx.read()[0]['message_type'],34)

    def test_sticker_api_confirms_digest_and_complete_offset(self):
        wx,root=self.session();path=root/'test.gif';path.write_bytes(b'GIF89a'+bytes(12))
        def send(kind,payload,**kwargs):
            info=next(v for n,w,v in decode(payload) if n==3)
            f={n:v for n,w,v in decode(info)}
            result=integer(1,0)+integer(2,f[3])+integer(3,f[3])+blob(4,f[1])+integer(6,999)
            return {'status':'response_received','task_id':1,'bytes':blob(1,integer(1,0))+integer(2,1)+blob(3,result)}
        wx._submit_media_request=Mock(side_effect=send)
        self.assertEqual(wx.send_sticker('target',path)['status'],'acknowledged')
        self.assertEqual(wx.read()[0]['message_type'],47)

    def test_video_thumbnail_then_data_chunks_are_confirmed_separately(self):
        wx,root=self.session();video=root/'test.mp4';thumb=root/'thumb.jpg'
        video.write_bytes(b'\0\0\0\x14ftyp'+bytes(70000));thumb.write_bytes(b'\xff\xd8\xff'+bytes(10))
        seen=[]
        def send(kind,payload,**kwargs):
            f={n:v for n,w,v in decode(payload)};seen.append(f)
            phase=f[14]
            chunk=dict((n,v) for n,w,v in decode(f[7] if phase==0 else f[10]))[2]
            thumb_pos=f[6]+len(chunk) if phase==0 else f[5]
            video_pos=f[9]+len(chunk) if phase==1 else 0
            raw=blob(1,integer(1,0))+blob(2,f[2])+integer(4,thumb_pos)+integer(5,video_pos)+integer(6,999 if video_pos==video.stat().st_size else 0)
            return {'status':'response_received','task_id':len(seen),'bytes':raw}
        wx._submit_media_request=Mock(side_effect=send)
        result=wx.send_video('target',video,thumbnail=thumb,duration_seconds=2)
        self.assertEqual(result['status'],'acknowledged')
        self.assertEqual([f[14] for f in seen],[0,1,1])
        self.assertEqual([f[9] for f in seen],[0,0,65536])
        self.assertEqual(wx.read()[0]['message_type'],43)

    def test_voice_unknown_result_does_not_retry(self):
        wx,root=self.session();path=root/'test.amr';path.write_bytes(b'#!AMR\n'+b'\x3c'+bytes(31))
        wx._submit_media_request=Mock(return_value={'status':'unconfirmed','task_id':1})
        self.assertEqual(wx.send_voice('target',path)['status'],'unconfirmed')
        wx._submit_media_request.assert_called_once()

    def test_passive_media_events_correlate_before_task_id_assignment(self):
        wx,root=self.session();wx._own_user_id='self'
        amr=b'#!AMR\n'+b'\x3c'+bytes(31)
        voice=voice_request('self','target','voice-client',amr,duration_ms=20,timestamp=100)
        voice_reply=(blob(1,'self')+blob(2,'target')+integer(3,0)+integer(4,len(amr))
                     +integer(5,100)+blob(6,'voice-client')+integer(7,123)+integer(8,20)+integer(9,2)
                     +blob(10,integer(1,0))+integer(12,1001))
        gif=b'GIF89a'+bytes(12);sticker,digest=sticker_request('target','sticker-client',gif)
        sticker_reply=blob(1,integer(1,0))+integer(2,1)+blob(3,integer(1,0)+integer(2,len(gif))+integer(3,len(gif))+blob(4,digest)+integer(6,1002))
        video=video_request('self','target','video-client',thumb_total=10,video_total=20,
                            duration_seconds=2,phase=1,offset=0,data=bytes(20))
        video_reply=blob(1,integer(1,0))+blob(2,'video-client')+integer(4,10)+integer(5,20)+integer(6,1003)
        for i,(kind,request,response) in enumerate([('voice',voice,voice_reply),('sticker',sticker,sticker_reply),('video',video,video_reply)]):
            scene=f'0x{i+1:x}'
            wx._handle_event({'event':'native_request','operation':kind,'taskId':0,'scene':scene,'bytes':list(request)})
            wx._handle_event({'event':'native_response','operation':kind,'taskId':100+i,'scene':scene,'bytes':list(response)})
        self.assertEqual([m['message_type'] for m in wx.read()],[34,47,43])
        self.assertTrue(all(m['direction']=='outgoing' for m in wx.read()))
