import unittest
from unittest.mock import patch

from wechat_aumac.api import WeChatUI
from wechat_aumac.errors import ReadError
from wechat_aumac.models import SendResult

SAMPLE = """Harry昊昊
2026年10月31日  7:22
@阿洛娜 /admin

Harry昊昊
2026年10月31日  7:23
/no
"""


class ApiTest(unittest.TestCase):
    def test_read_result(self):
        wx = WeChatUI()
        with patch("wechat_aumac.ui.select_and_copy", return_value=(SAMPLE, (0, 33, 1512, 887))):
            result = wx.read_result()
        self.assertEqual(len(result.messages), 2)
        self.assertEqual(result.messages[0].text, "@阿洛娜 /admin")
        self.assertEqual(result.window, (0, 33, 1512, 887))

    def test_read_limit(self):
        wx = WeChatUI()
        with patch("wechat_aumac.ui.select_and_copy", return_value=(SAMPLE, (0, 33, 1512, 887))):
            messages = wx.read(limit=1)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].text, "/no")

    def test_read_opens_chat(self):
        wx = WeChatUI()
        with patch("wechat_aumac.ui.open_chat") as open_chat, patch(
            "wechat_aumac.ui.select_and_copy", return_value=(SAMPLE, (0, 33, 1512, 887))
        ):
            messages = wx.read(chat="test")
        open_chat.assert_called_once_with("test")
        self.assertEqual(len(messages), 2)

    def test_read_empty_raises(self):
        wx = WeChatUI()
        with patch("wechat_aumac.ui.select_and_copy", return_value=("", (0, 33, 1512, 887))):
            with self.assertRaises(ReadError):
                wx.read_result()

    def test_send_calls_ui(self):
        wx = WeChatUI()
        with patch("wechat_aumac.ui.send_text") as send:
            result = wx.send("hello")
        self.assertIsInstance(result, SendResult)
        self.assertTrue(result.ok)
        send.assert_called_once_with("hello", verify_input=True)

    def test_open_chat_calls_ui(self):
        wx = WeChatUI()
        with patch("wechat_aumac.ui.open_chat") as open_chat:
            wx.open_chat("test")
        open_chat.assert_called_once_with("test")


if __name__ == "__main__":
    unittest.main()
