from pathlib import Path
import tempfile,plistlib,unittest
from unittest.mock import patch
from wechat_aumac.hook_probe import select_process


class NativeProcessTest(unittest.TestCase):
    def app(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        app=Path(temp.name)/'Wemac.app';(app/'Contents').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'WeChat'}))
        return app

    def test_two_clients_are_selected_by_path_not_process_name(self):
        app=self.app();exe=str(app/'Contents/MacOS/WeChat')
        with patch('wechat_aumac.hook_probe._run',return_value={'stdout':'101\n202'}),patch(
            'wechat_aumac.hook_probe.process_path',side_effect=lambda pid:exe if pid==202 else '/Applications/WeChat.app/Contents/MacOS/WeChat'):
            self.assertEqual(select_process(app),202)
            with self.assertRaises(ValueError):select_process(app,pid=101)

    def test_ambiguous_same_copy_needs_explicit_pid(self):
        app=self.app()
        with patch('wechat_aumac.hook_probe._run',return_value={'stdout':'101\n202'}),patch(
            'wechat_aumac.hook_probe.process_path',return_value=str(app/'Contents/MacOS/WeChat')):
            with self.assertRaises(ValueError):select_process(app)
            self.assertEqual(select_process(app,pid=202),202)
