import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from wechat_aumac import cli
from wechat_aumac.models import ReadResult, SendResult
from wechat_aumac.transcript import parse_transcript

SAMPLE = """Harry昊昊
2026年10月31日  7:22
@阿洛娜 /admin

Harry昊昊
2026年10月31日  7:23
/no
"""


class FakeUI:
    def read_result(self, chat=None, limit=None):
        messages = parse_transcript(SAMPLE)
        if limit:
            messages = messages[-limit:]
        return ReadResult(raw=SAMPLE, messages=messages, window=(0, 33, 1512, 887))

    def read(self, chat=None, limit=None):
        return self.read_result(chat=chat, limit=limit).messages

    def read_raw(self, chat=None):
        return SAMPLE

    def send(self, text, chat=None, verify=False):
        return SendResult(ok=True, text=text, chat=chat, verified=verify)

    def open_chat(self, name):
        self.opened = name

    @staticmethod
    def doctor():
        return {
            "platform_ok": True,
            "running": True,
            "pid": 123,
            "window": [0, 33, 1512, 887],
            "screen": [0, 0, 1512, 982],
            "maximized": True,
            "fullscreen": False,
            "clipboard_ok": True,
            "error": "",
        }


class CliTest(unittest.TestCase):
    def run_cli(self, argv):
        buf = io.StringIO()
        with patch.object(cli, "WeChatUI", FakeUI), redirect_stdout(buf):
            code = cli.main(argv)
        return code, buf.getvalue()

    def test_read_json(self):
        code, out = self.run_cli(["read", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["text"], "@阿洛娜 /admin")

    def test_read_raw(self):
        code, out = self.run_cli(["read", "--raw"])
        self.assertEqual(code, 0)
        self.assertIn("@阿洛娜 /admin", out)

    def test_send(self):
        code, out = self.run_cli(["send", "hello", "world"])
        self.assertEqual(code, 0)
        self.assertIn("sent: hello world", out)

    def test_open(self):
        code, out = self.run_cli(["open", "test"])
        self.assertEqual(code, 0)
        self.assertIn("opened: test", out)

    def test_doctor(self):
        code, out = self.run_cli(["doctor"])
        self.assertEqual(code, 0)
        self.assertIn("maximized   : True", out)


if __name__ == "__main__":
    unittest.main()
