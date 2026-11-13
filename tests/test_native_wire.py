import unittest
from wechat_aumac.native.wire import blob, decode, integer, parse_text_request, parse_text_response, text_request, varint


class NativeWireTest(unittest.TestCase):
    def test_unicode_and_large_identifiers_preserved(self):
        data=text_request('123@chatroom', '中文😀\nsecond line', 1794476100, 0xffffffff)
        self.assertEqual(parse_text_request(data), [{'receiver':'123@chatroom','text':'中文😀\nsecond line','type':1,'timestamp':1794476100,'client_id':0xffffffff}])

    def test_varint_boundaries(self):
        for value in [0,127,128,16384,(1<<32)-1,(1<<64)-1]:
            self.assertEqual(decode(integer(1,value)),[(1,0,value)])
        for value in [-1,1<<64]:
            with self.assertRaises(ValueError):varint(value)

    def test_rejects_truncated_and_overflow(self):
        for data in [b'\x08\x80',b'\x12\x05ab',b'\x00',b'\x0b',b'\x08'+b'\xff'*10]:
            with self.subTest(data=data), self.assertRaises(ValueError):decode(data)

    def test_response_requires_explicit_base_return_code(self):
        self.assertFalse(parse_text_response(b'')['acknowledged'])
        self.assertFalse(parse_text_response(blob(1,b''))['acknowledged'])
        self.assertTrue(parse_text_response(blob(1,integer(1,0)))['acknowledged'])
        result=parse_text_response(blob(1,integer(1,0xfffffffc)))
        self.assertEqual(result['return_code'],-4)
        self.assertFalse(result['acknowledged'])
