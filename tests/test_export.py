import json
import tempfile
import unittest
from pathlib import Path

from wechat_aumac.export import export_messages
from wechat_aumac.transcript import parse_transcript

SAMPLE = """Harry昊昊
2026年10月31日  7:22
@阿洛娜 /admin

Harry昊昊
2026年10月31日  7:23
/no
"""


class ExportTest(unittest.TestCase):
    def test_export_all_formats(self):
        messages = parse_transcript(SAMPLE)
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_messages(messages, tmp, prefix="test")
            self.assertEqual(set(paths), {"json", "csv", "txt", "md"})
            for path in paths.values():
                self.assertTrue(Path(path).is_file())
            data = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["text"], "@阿洛娜 /admin")
            self.assertIn("@阿洛娜 /admin", Path(paths["txt"]).read_text(encoding="utf-8"))

    def test_unknown_format(self):
        messages = parse_transcript(SAMPLE)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                export_messages(messages, tmp, formats=("xml",))


if __name__ == "__main__":
    unittest.main()
