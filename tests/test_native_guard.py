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
    def test_failed_dispose_retains_agent_and_guard_until_retry(self):
        wx,_=self.session()
        wx._script.unload=Mock()
        wx._script.exports_sync.dispose=Mock(side_effect=RuntimeError('native callback busy'))
        wx._session=Mock();wx._guard=Mock()
        script,session,guard=wx._script,wx._session,wx._guard
        self.assertFalse(wx.close())
        script.unload.assert_not_called();session.detach.assert_not_called();guard.release.assert_not_called()
        self.assertIs(wx._session,session)
        with self.assertRaises(Exception):wx.status()
        script.exports_sync.dispose.side_effect=None
        self.assertTrue(wx.close())
        script.unload.assert_called_once();session.detach.assert_called_once();guard.release.assert_called_once()
        self.assertIsNone(wx._session)

    def test_database_quiescence_failure_never_unloads_parent(self):
        wx,_=self.session();wx._session=Mock();wx._guard=Mock()
        wx._database_reader=Mock();wx._database_reader.close.side_effect=RuntimeError('read still active')
        wx._script.unload=Mock();wx._script.exports_sync.dispose=Mock()
        self.assertFalse(wx.close())
        wx._script.unload.assert_not_called();wx._session.detach.assert_not_called()
        wx._guard.release.assert_not_called()
        wx._database_reader.close.side_effect=None
        self.assertTrue(wx.close())

    def test_close_waits_for_rpc_before_dispose(self):
        import threading,time
        wx,_=self.session();wx._session=Mock();wx._guard=Mock()
        entered=threading.Event();release=threading.Event()
        def status():entered.set();release.wait(2);return {}
        wx._script.exports_sync.status=status
        wx._script.exports_sync.dispose=Mock();wx._script.unload=Mock()
        caller=threading.Thread(target=lambda:wx._rpc('status'));caller.start()
        self.assertTrue(entered.wait(1))
        closer=threading.Thread(target=wx.close);closer.start();time.sleep(.03)
        wx._script.exports_sync.dispose.assert_not_called()
        release.set();caller.join(2);closer.join(2)
        self.assertFalse(caller.is_alive());self.assertFalse(closer.is_alive())
        self.assertIsNone(wx._session)
