import hashlib,json,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock
from wechat_aumac.native import NativeSession
from wechat_aumac.native.sns_upload import validate_result
from wechat_aumac.native.moments import image_post_request
from wechat_aumac.native.wire import blob,integer,decode

def media():
    data=b'fixture'
    return data,dict(ready=True,status='acknowledged',return_code=0,secondary_error=0,data_type=3,file_type=101,
        scene=20201,uploaded_bytes=len(data),client_id='client',md5=hashlib.md5(data).hexdigest(),
        url='http://mmsns.qpic.cn/mmsns/fixture/0',thumb='http://mmsns.qpic.cn/mmsns/fixture/150',
        width=320,height=240,source_sha256=hashlib.sha256(data).hexdigest())

class SnsUploadTest(unittest.TestCase):
    def session(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);p=Path(temp.name)/'p.json'
        p.write_text(json.dumps({'momentSubmits':{'moment_post':'submit'}}))
        wx=NativeSession(p,mode='full',moments_operations=['publish']);wx.identity=Mock(return_value={'user_id':'self'})
        wx._sns_upload_reader=Mock();wx._sns_upload_reader.upload.return_value=media()[1]
        return wx
    def test_result_identity_checksum_size_and_origin_checked(self):
        data,result=media();self.assertTrue(validate_result(result,'client',data))
        for changes in ({'return_code':-1},{'secondary_error':1},{'client_id':'other'},
                {'uploaded_bytes':999},{'md5':'0'*32},{'file_type':1},{'scene':1},
                {'url':'https://mmsns.qpic.cn.evil.test/mmsns/x/0'},
                {'thumb':'http://user@mmsns.qpic.cn/mmsns/x/150'}):
            with self.assertRaises(ValueError):validate_result({**result,**changes},'client',data)
        self.assertFalse(validate_result({'ready':False},'client',data))
    def test_xml_contains_one_uploaded_image_and_escapes_text(self):
        raw,xml=image_post_request('self','A < B & C',media()[1],visibility='private',client_id='client',timestamp=1)
        root=ET.fromstring(xml);self.assertEqual(root.findtext('contentDesc'),'A < B & C')
        self.assertEqual(root.findtext('private'),'1');self.assertEqual(root.findtext('./ContentObject/contentStyle'),'1')
        self.assertEqual(len(root.findall('./ContentObject/mediaList/media')),1)
        self.assertIn((5,0,1),decode(raw))
        with self.assertRaises(ValueError):image_post_request('self','test',{**media()[1],'status':'unconfirmed'},visibility='public',client_id='client',timestamp=1)
    def test_upload_failure_never_submits_post(self):
        for status in ('rejected','unconfirmed'):
            wx=self.session();wx._sns_upload_reader.upload.return_value={'status':status,'published':False};wx._moment_write=Mock()
            self.assertEqual(wx.publish_image_moment('test','fixture',visibility='private')['status'],status)
            wx._moment_write.assert_not_called();wx._sns_upload_reader.upload.assert_called_once()
    def test_exact_media_is_checked_against_native_post_response(self):
        wx=self.session()
        def submit(kind,payload,**kwargs):
            wrapper=dict((n,v) for n,w,v in decode(payload))[2]
            xml=dict((n,v) for n,w,v in decode(wrapper))[2]
            root=ET.fromstring(xml);root.find('id').text='123'
            obj=integer(1,123)+blob(2,'self')+blob(5,blob(2,ET.tostring(root,encoding='utf-8')))
            return {'status':'response_received','task_id':1,'bytes':blob(1,integer(1,0))+blob(2,obj)}
        wx._moment_write=Mock(side_effect=submit)
        self.assertEqual(wx.publish_image_moment('test','fixture',visibility='private')['image_count'],1)
        wx._moment_write.assert_called_once()
        wx._moment_write=Mock(return_value={'status':'unconfirmed','task_id':2})
        self.assertEqual(wx.publish_image_moment('test','fixture',visibility='public')['status'],'unconfirmed')
        wx._moment_write.assert_called_once()
    def test_invalid_draft_is_rejected_before_upload(self):
        wx=self.session()
        with self.assertRaises(ValueError):wx.publish_image_moment('bad\0text','fixture',visibility='public')
        wx._sns_upload_reader.upload.assert_not_called()
