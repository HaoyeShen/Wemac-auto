import hashlib,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree.ElementTree import Element
from wechat_aumac.native.resources import NativeResources

class IncomingEmojiTests(unittest.TestCase):
 def test_cache_pending_uses_exact_original_native_download(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);data=b'GIF89a-exact-original';source=root/'original';source.write_bytes(data)
   digest=hashlib.md5(data).hexdigest();entry={'md5':digest}
   native=Mock(return_value={'path':str(source)})
   reader=object.__new__(NativeResources);reader.session=SimpleNamespace(download_public_resource=native)
   reader.download_sticker=Mock(side_effect=RuntimeError('sync before cache'))
   node=Element('emoji',{'cdnurl':'http://example.com/original','thumburl':'https://example.com/thumbnail'})
   output=reader.download_emoji(entry,node,root/'out')
   self.assertEqual(output.read_bytes(),data)
   native.assert_called_once_with('https://example.com/original',timeout=15)
   source.write_bytes(b'different picture')
   with self.assertRaises(ValueError):reader.download_emoji(entry,node,root/'other')
 def test_ready_cache_does_not_download_again(self):
  reader=object.__new__(NativeResources);reader.download_sticker=Mock(return_value=Path('/exact'))
  reader.session=SimpleNamespace(download_public_resource=Mock())
  self.assertEqual(reader.download_emoji({},Element('emoji'),'/unused'),Path('/exact'))
  reader.session.download_public_resource.assert_not_called()
