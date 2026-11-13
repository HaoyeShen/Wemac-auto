import hashlib
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wechat_aumac.hook_probe import probe, attach_inventory


class HookProbeTest(unittest.TestCase):
    def test_exact_binary_identity_and_no_implicit_attach(self):
        with tempfile.TemporaryDirectory() as root:
            contents = Path(root) / 'Contents'
            (contents / 'Resources').mkdir(parents=True)
            (contents / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleVersion': '270348', 'CFBundleShortVersionString': '4.2.0'}))
            (contents / 'Resources/wechat.dylib').write_bytes(b'core')
            with patch('wechat_aumac.hook_probe.platform.system', return_value='Darwin'), patch(
                'wechat_aumac.hook_probe._run', return_value={'ok': True, 'stdout': ''}
            ), patch('wechat_aumac.hook_probe.attach_inventory') as attach:
                report = probe(root)
            attach.assert_not_called()
            self.assertFalse(report['send_ready'])
            self.assertIsNone(report['profile'])
            self.assertEqual(report['build'], '270348')
            self.assertEqual(report['modules'][0]['sha256'], hashlib.sha256(b'core').hexdigest())

    def test_attach_timeout_is_reported(self):
        with patch('wechat_aumac.hook_probe.subprocess.run', side_effect=subprocess.TimeoutExpired('frida', 20)):
            report = attach_inventory(123)
        self.assertFalse(report['ok'])
        self.assertIn('timed out', report['error'])

    def test_attach_failure_preserves_error(self):
        output = json.dumps({'ok': False, 'error': 'access denied', 'type': 'PermissionDeniedError'})
        with patch('wechat_aumac.hook_probe.subprocess.run', return_value=subprocess.CompletedProcess([], 1, output, '')):
            self.assertEqual(attach_inventory(123)['error'], 'access denied')

    def test_missing_app_is_reported(self):
        with patch('wechat_aumac.hook_probe.platform.system', return_value='Darwin'):
            self.assertEqual(probe('/nonexistent/WeChat.app')['status'], 'invalid_app')

    def test_attach_refuses_different_app_with_same_process_name(self):
        with tempfile.TemporaryDirectory() as root:
            contents = Path(root) / 'Contents'
            contents.mkdir()
            (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'WeChat'}))
            with patch('wechat_aumac.hook_probe.platform.system', return_value='Darwin'), patch(
                'wechat_aumac.hook_probe._run', return_value={'ok': True, 'stdout': '123'}
            ), patch('wechat_aumac.hook_probe.process_path', return_value='/Applications/WeChat.app/Contents/MacOS/WeChat'), patch(
                'wechat_aumac.hook_probe.attach_inventory'
            ) as attach:
                report = probe(root, attach=True)
            attach.assert_not_called()
            self.assertEqual(report['status'], 'attach_failed')
            self.assertIn('does not match', report['attach']['error'])
