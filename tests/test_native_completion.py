"""Compile the native completion regression outside the WeChat process."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(platform.system()=='Darwin' and shutil.which('clang++'), 'requires macOS libc++')
class NativeCompletionTest(unittest.TestCase):
    def test_nonempty_completion_survives_copy_and_original_destruction(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/'completion-test'
            result=subprocess.run(['clang++','-std=c++17','-O2',str(root/'tests/native_completion_test.cpp'),
                                   str(root/'src/wechat_aumac/native/completion.cpp'),'-o',str(exe)],
                                  capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
