import math,struct,unittest
from wechat_aumac.native.voice import encode_pcm,decode_pcm,duration_ms,packets,HEADER
from wechat_aumac.native.media_experimental import voice_request
from wechat_aumac.native.wire import decode

class VoiceTest(unittest.TestCase):
    def test_malformed_framing_rejected(self):
        for data in (b'bad',HEADER,HEADER+b'\x01',HEADER+b'\xff\xff',HEADER+b'\x02\x00x'):
            with self.assertRaises(ValueError):list(packets(data))
    def test_local_silk_roundtrip_and_native_format(self):
        pcm=b''.join(struct.pack('<h',round(9000*math.sin(i*math.tau*440/24000))) for i in range(24000))
        try:data=encode_pcm(pcm)
        except RuntimeError as exc:
            if '未安装' in str(exc):self.skipTest(str(exc))
            raise
        out=decode_pcm(data)
        self.assertEqual(len(out),len(pcm));self.assertEqual(duration_ms(data),1000)
        samples=struct.unpack('<'+str(len(out)//2)+'h',out)
        self.assertGreater(sum(x*x for x in samples)/len(samples),100000)
        payload=voice_request('self','target','client',data,duration_ms=1000,timestamp=100)
        self.assertEqual(dict((n,v) for n,w,v in decode(payload))[13],4)
        with self.assertRaises(ValueError):voice_request('self','target','client',data,duration_ms=900,timestamp=100)
