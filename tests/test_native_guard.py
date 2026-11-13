import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wechat_aumac.native.guard import AgentBusyError, AgentGuard
from tests import test_native_session as fixtures


class NativeGuardTest(unittest.TestCase):
    def test_second_agent_refused_until_first_released(self):
        with tempfile.TemporaryDirectory() as root:
            first=AgentGuard(os.getpid(),root).acquire()
            second=AgentGuard(os.getpid(),root)
            try:
                with self.assertRaises(AgentBusyError):second.acquire()
            finally:first.release()
            second.acquire();second.release();second.release()

    def test_lock_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            guard=AgentGuard(os.getpid(),root)
            target=Path(root)/'other';target.write_text('unchanged')
            guard.path.symlink_to(target)
            with self.assertRaises(OSError):guard.acquire()
            self.assertEqual(target.read_text(),'unchanged')


class NativeCleanupTest(unittest.TestCase):
    session = fixtures.NativeSessionTest.session
    def test_failed_dispose_still_unloads_detaches_and_releases_lock(self):
        wx,_=self.session()
        wx._script.unload=Mock()
        wx._script.exports_sync.dispose=Mock(side_effect=RuntimeError('script is gone'))
        wx._session=Mock();wx._guard=Mock()
        script,session,guard=wx._script,wx._session,wx._guard
        wx.close()
        script.unload.assert_called_once()
        session.detach.assert_called_once()
        guard.release.assert_called_once()
        self.assertIsNone(wx._session)
        self.assertEqual(wx.cleanup_errors,['script is gone'])
