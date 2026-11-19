"""The native barrier preserves client concurrency and bounds exclusive waits."""
import ctypes,subprocess,tempfile,threading,unittest
from pathlib import Path

class NativeDatabaseGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if __import__('sys').platform!='darwin':raise unittest.SkipTest('macOS native bridge')
        cls.temp=tempfile.TemporaryDirectory();path=Path(cls.temp.name)/'gate.dylib'
        source=Path(__file__).resolve().parents[1]/'src/wechat_aumac/native/native_db_gate.c'
        subprocess.run(['clang','-std=c11','-dynamiclib',str(source),'-o',str(path)],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(path))
        for name in ('enter','leave'):getattr(cls.lib,'wemac_db_gate_'+name).argtypes=[ctypes.c_void_p]
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_parallel_clients_and_bounded_writer(self):
        lib=self.lib;self.assertEqual(lib.wemac_db_gate_start(),1)
        ready=threading.Barrier(3);release=threading.Event()
        def client():
            lib.wemac_db_gate_enter(None);lib.wemac_db_gate_enter(None)
            ready.wait();release.wait(2)
            lib.wemac_db_gate_leave(None);lib.wemac_db_gate_leave(None)
        threads=[threading.Thread(target=client) for _ in range(2)]
        for thread in threads:thread.start()
        ready.wait(timeout=2)
        self.assertEqual(lib.wemac_db_gate_active(),2)
        self.assertEqual(lib.wemac_db_gate_lock(),0,'exclusive read must time out while client operations run')
        release.set()
        for thread in threads:thread.join(2);self.assertFalse(thread.is_alive())
        self.assertEqual(lib.wemac_db_gate_active(),0)
        self.assertEqual(lib.wemac_db_gate_lock(),1)
        lib.wemac_db_gate_enter(None);lib.wemac_db_gate_leave(None)
        self.assertEqual(lib.wemac_db_gate_active(),1,'native calls nested in a read do not take a reader lock')
        lib.wemac_db_gate_unlock();self.assertEqual(lib.wemac_db_gate_active(),0)
        lib.wemac_db_gate_stop()
        self.assertEqual(lib.wemac_db_gate_lock(),0)
        lib.wemac_db_gate_enter(None);lib.wemac_db_gate_leave(None)
        self.assertEqual(lib.wemac_db_gate_active(),0)
