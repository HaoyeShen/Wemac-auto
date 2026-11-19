import hashlib,json,tempfile,unittest
from pathlib import Path
from wechat_aumac.native.wxgf import verify

class NativeWXGFProvenance(unittest.TestCase):
    def test_original_and_transcoded_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'image';path.write_bytes(b'original')
            digest=hashlib.md5(path.read_bytes()).hexdigest()
            self.assertTrue(verify(path,digest,{})['verified_md5'])
            path.write_bytes(b'transcoded-gif')
            record={'source_md5':digest,'native_decoded':True,'codec_sha256':'pinned',
                    'output_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            path.with_suffix('.native.json').write_text(json.dumps(record))
            self.assertTrue(verify(path,digest,{'sha256':'pinned'})['native_decoded'])
            with self.assertRaises(ValueError):verify(path,'0'*32,{'sha256':'pinned'})
            with self.assertRaises(ValueError):verify(path,digest,{'sha256':'changed-codec'})
            path.write_bytes(b'modified')
            with self.assertRaises(ValueError):verify(path,digest,{'sha256':'pinned'})
