import unittest
from wechat_aumac.native.cards import inspect_card,enrich_message,parse_xml


class NativeCardTest(unittest.TestCase):
    def test_fragment_payload_and_unknown_subtype_preserve_all_link_fields(self):
        xml=('<appmsg><type>999</type><title>card</title><url>https://example.org/a?x=1&amp;y=2</url>'
             '<unknown href="https://example.org/attr"><nested>https://example.org/deep</nested></unknown>'
             '</appmsg><fromusername>sender</fromusername>')
        card=inspect_card(xml)
        self.assertEqual(card['subtype'],'999')
        self.assertEqual([x['url'] for x in card['links']],
                         ['https://example.org/a?x=1&y=2','https://example.org/attr','https://example.org/deep'])
        self.assertEqual(card['link_scope'],'embedded_payload_only')

    def test_nested_record_and_mini_program_routes_do_not_invent_web_urls(self):
        xml=('<msg><appmsg><type>19</type><recorditem><![CDATA[<recordinfo><dataitem>'
             '<weburl>https://example.org/inside</weburl></dataitem></recordinfo>]]></recorditem>'
             '<weappinfo><appid>wxapp</appid><pagepath>pages/index?a=1</pagepath></weappinfo></appmsg></msg>')
        card=inspect_card(xml)
        self.assertEqual([x['url'] for x in card['links']],['https://example.org/inside'])
        self.assertEqual(card['mini_programs'][0]['pagepath'],'pages/index?a=1')

    def test_quote_escaping_is_not_executed_or_fetched(self):
        xml='<appmsg><type>57</type><refermsg><svrid>18446744073709551615</svrid><content>&lt;msg&gt;https://example.org/x&lt;/msg&gt;</content></refermsg></appmsg>'
        card=inspect_card(xml)
        self.assertEqual(card['quote']['svrid'],'18446744073709551615')
        self.assertIn('https://example.org/x',[x['url'] for x in card['links']])

    def test_malformed_card_still_remains_a_native_message(self):
        value=enrich_message({'message_id':'1','text':'<appmsg><url>broken'})
        self.assertIn('card_error',value);self.assertEqual(value['message_id'],'1')
        self.assertIsNone(inspect_card('https://example.org/plain-text'))

    def test_dtd_nested_dtd_depth_and_size_are_bounded(self):
        for xml in ['<!DOCTYPE msg><msg/>','<msg><![CDATA[<!DOCTYPE msg><msg/>]]></msg>',
                    '<x>'*66+'</x>'*66,'<msg>'+('x'*1024*1024)+'</msg>']:
            with self.subTest(xml=xml[:40]),self.assertRaises(ValueError):inspect_card(xml) if '<![CDATA[' in xml else parse_xml(xml)
