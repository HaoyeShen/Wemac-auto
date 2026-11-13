import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from wechat_aumac import WeChatUI, Message
from wechat_aumac import cli
from wechat_aumac.errors import ReadError


def msg(text):
    return Message(sender='Alice', time='2026年10月31日 10:00', text=text)


class WatchTest(unittest.TestCase):
    def collect(self, snapshots, chat=None):
        results = []
        with patch.object(WeChatUI, 'read', side_effect=[*snapshots, ReadError('stop')]), patch.object(
            WeChatUI, 'open_chat'
        ) as opened, patch('wechat_aumac.api.time.sleep') as sleep:
            with self.assertRaises(ReadError):
                for message in WeChatUI().watch(chat=chat, interval=2):
                    results.append(message)
        sleep.assert_called_with(2)
        if chat:
            opened.assert_called_once_with(chat)
        else:
            opened.assert_not_called()
        return results

    def test_baseline_unchanged_then_batch(self):
        a, b, c = map(msg, ['a', 'b', 'c'])
        self.assertEqual(self.collect([[a], [a], [a, b, c]], chat='test'), [b, c])

    def test_repeated_identical_messages(self):
        a = msg('same')
        self.assertEqual(self.collect([[a], [a, a], [a, a, a]]), [a, a])

    def test_shifted_history(self):
        a, b, c = map(msg, ['a', 'b', 'c'])
        self.assertEqual(self.collect([[a, b], [b, c]]), [c])

    def test_no_overlap_resets_baseline(self):
        a, b, c = map(msg, ['a', 'b', 'c'])
        self.assertEqual(self.collect([[a], [b], [b, c]]), [c])

    def test_invalid_interval(self):
        for interval in [0, -1, float('nan'), float('inf')]:
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                next(WeChatUI().watch(interval=interval))

    def test_cli_json_and_interrupt(self):
        def events(**kwargs):
            self.assertEqual(kwargs, {'chat': 'test', 'interval': 2.0})
            yield msg('new')
            raise KeyboardInterrupt
        output = io.StringIO()
        with patch.object(WeChatUI, 'watch', side_effect=events), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['watch', '--chat', 'test', '--interval', '2', '--json']), 130)
        self.assertEqual(json.loads(output.getvalue())['text'], 'new')

    def test_cli_invalid_interval(self):
        for value in ['0', '-1', 'nan', 'inf', 'abc']:
            with self.subTest(value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                cli.main(['watch', '--interval', value])
            self.assertEqual(error.exception.code, 2)
