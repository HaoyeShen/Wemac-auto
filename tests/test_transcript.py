import unittest

from wechat_aumac.transcript import format_messages, parse_time, parse_transcript

SAMPLE = """Harry昊昊
2026年10月31日  7:22
@阿洛娜 /admin

Harry昊昊
2026年10月31日  7:23
是否保存刚刚的修改？回复 /yes 保存，回复 /no 放弃。

【国服】
国服官网说，10月29日14:00开始维护更新。
"""

SAMPLE_TWO = """Harry昊昊
2026年10月31日  7:22
@阿洛娜 /admin

Harry昊昊
2026年10月31日  7:23
/no
"""


class TranscriptTest(unittest.TestCase):
    def test_parse_two_messages_and_body(self):
        messages = parse_transcript(SAMPLE_TWO)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].sender, "Harry昊昊")
        self.assertEqual(messages[0].time, "2026年10月31日  7:22")
        self.assertEqual(messages[0].text, "@阿洛娜 /admin")
        self.assertEqual(messages[1].text, "/no")
        self.assertEqual(messages[1].timestamp.year, 2026)
        self.assertEqual(messages[1].timestamp.minute, 23)

    def test_multiline_body_keeps_blank_lines(self):
        messages = parse_transcript(SAMPLE)
        self.assertEqual(len(messages), 2)
        self.assertIn("【国服】", messages[1].text)
        self.assertIn("\n\n", messages[1].text)

    def test_empty_or_unknown(self):
        self.assertEqual(parse_transcript(""), [])
        self.assertEqual(parse_transcript("just some text"), [])

    def test_parse_time(self):
        dt = parse_time("2026年10月30日  0:09")
        self.assertIsNotNone(dt)
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2026, 10, 30, 0, 9))
        self.assertIsNone(parse_time("not a date"))

    def test_format(self):
        messages = parse_transcript(SAMPLE_TWO)
        text = format_messages(messages, "text")
        self.assertIn("@阿洛娜 /admin", text)
        md = format_messages(messages, "markdown")
        self.assertIn("## 2026年10月31日  7:22 · Harry昊昊", md)


if __name__ == "__main__":
    unittest.main()
