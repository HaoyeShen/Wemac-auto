"""Cross-process ownership of one native agent per WeChat PID."""
from __future__ import annotations
import fcntl
import os
from pathlib import Path
import tempfile


class AgentBusyError(RuntimeError):
    pass


class AgentGuard:
    def __init__(self, pid: int, directory: str | Path | None = None):
        root=Path(directory) if directory is not None else Path(tempfile.gettempdir())
        self.path=root / f'wechat-aumac-agent-{os.getuid()}-{pid}.lock'
        self._fd=None

    def acquire(self):
        if self._fd is not None:
            raise AgentBusyError('Agent lock is already held')
        fd=os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            if os.fstat(fd).st_uid != os.getuid():
                raise AgentBusyError('Agent lock belongs to another user')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AgentBusyError('Another native agent owns this WeChat process; close it first') from exc
            os.ftruncate(fd,0)
            os.write(fd,str(os.getpid()).encode())
            self._fd=fd
            return self
        except Exception:
            os.close(fd)
            raise

    def release(self):
        if self._fd is not None:
            fd,self._fd=self._fd,None
            try:
                fcntl.flock(fd,fcntl.LOCK_UN)
            finally:
                os.close(fd)
