"""Prevent parent sandbox entitlements from leaking into helper signatures."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('repair_copy_signing', Path(__file__).resolve().parents[1] / 'research/repair_copy_signing.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class CopySigningTest(unittest.TestCase):
    def test_helper_keeps_sandbox_inheritance_without_main_permissions(self):
        original = {'com.apple.security.app-sandbox': True,
                    'com.apple.security.inherit': True,
                    'com.apple.security.cs.allow-jit': True}
        result = repair.entitlements_for(original)
        self.assertEqual(result, original)
        self.assertNotIn('com.apple.security.get-task-allow', result)
        self.assertNotIn('com.apple.security.application-groups', result)

    def test_debug_permissions_only_added_to_main(self):
        original = {'com.apple.security.app-sandbox': True}
        result = repair.entitlements_for(original, main=True)
        self.assertTrue(result['com.apple.security.get-task-allow'])
        self.assertTrue(result['com.apple.security.cs.disable-library-validation'])
        self.assertEqual(original, {'com.apple.security.app-sandbox': True})
