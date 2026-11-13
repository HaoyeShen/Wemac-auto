"""Read-only compatibility probe for an experimental in-process backend.

Never patches an app, hooks a function, or invokes a send routine. Optional
Frida attachment only enumerates modules and detaches in a bounded subprocess.
"""
from __future__ import annotations

import hashlib
import ctypes
import json
import platform
import plistlib
import subprocess
import sys
from pathlib import Path


def _run(args: list[str], timeout: float = 15) -> dict:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {"ok": result.returncode == 0, "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(), "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {timeout} seconds"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


# Kept in a subprocess so taskgate / Frida cannot hang the parent indefinitely.
_ATTACH_SCRIPT = r'''
import json
import sys
import frida
from wechat_aumac.native.guard import AgentGuard
session = None
guard = None
try:
    guard = AgentGuard(int(sys.argv[1])).acquire()
    session = frida.attach(int(sys.argv[1]))
    agent = session.create_script("""
        rpc.exports = {
            inventory() {
                return Process.enumerateModules()
                    .filter(m => m.name === 'wechat.dylib')
                    .map(m => ({name: m.name, path: m.path,
                               base: m.base.toString(), size: m.size}));
            }
        };
    """)
    agent.load()
    print(json.dumps({'ok': True, 'modules': agent.exports_sync.inventory()}))
except Exception as exc:
    print(json.dumps({'ok': False, 'error': str(exc), 'type': type(exc).__name__}))
    sys.exit(1)
finally:
    try:
        if session is not None:
            session.detach()
    finally:
        if guard is not None:
            guard.release()
'''


def attach_inventory(pid: int) -> dict:
    result = _run([sys.executable, '-c', _ATTACH_SCRIPT, str(pid)], timeout=20)
    try:
        return json.loads(result.get('stdout', ''))
    except json.JSONDecodeError:
        return result


def process_path(pid: int) -> str | None:
    """Resolve the executable rather than trusting its process name."""
    lib = ctypes.CDLL('/usr/lib/libproc.dylib')
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_pidpath.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(4096)
    if lib.proc_pidpath(pid, buffer, len(buffer)) <= 0:
        return None
    return buffer.value.decode('utf-8')


def probe(app: str | Path = '/Applications/WeChat.app', *, attach: bool = False) -> dict:
    app = Path(app).expanduser().resolve()
    report = {'app': str(app), 'platform': platform.system(),
              'architecture': platform.machine(), 'send_ready': False,
              'status': 'unvalidated', 'profile': None}
    if platform.system() != 'Darwin':
        return {**report, 'status': 'unsupported_platform'}
    try:
        with (app / 'Contents/Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as exc:
        return {**report, 'status': 'invalid_app', 'error': str(exc)}
    report['version'] = info.get('CFBundleShortVersionString')
    report['build'] = info.get('CFBundleVersion')
    report['bundle_id'] = info.get('CFBundleIdentifier')
    report['sip'] = _run(['csrutil', 'status'])
    report['signature'] = _run(['codesign', '-dv', '--verbose=4', str(app)])
    report['entitlements'] = _run(['codesign', '-d', '--entitlements', ':-', str(app)])
    modules = []
    for directory in ('Resources', 'Frameworks'):
        path = app / f'Contents/{directory}/wechat.dylib'
        if not path.is_file():
            continue
        modules.append({'path': str(path), 'bytes': path.stat().st_size,
                        'sha256': _fingerprint(path),
                        'uuid': _run(['dwarfdump', '--uuid', str(path)]),
                        'exports': _run(['nm', '-arch', platform.machine(), '-gU', str(path)])})
    report['modules'] = modules
    process = _run(['pgrep', '-x', 'WeChat'])
    report['pids'] = [int(p) for p in process.get('stdout', '').splitlines() if p.isdigit()]
    if attach:
        # Require an unambiguous target. Multi-instance selection needs an
        # explicit process identity check before instrumentation is attempted.
        if len(report['pids']) != 1:
            report['attach'] = {'ok': False, 'error': 'expected exactly one WeChat process'}
        else:
            pid = report['pids'][0]
            executable = process_path(pid)
            report['process_path'] = executable
            expected = app / 'Contents/MacOS' / info.get('CFBundleExecutable', 'WeChat')
            if executable is None or Path(executable).resolve() != expected.resolve():
                report['attach'] = {'ok': False, 'error': 'running process does not match requested app'}
            else:
                report['attach'] = attach_inventory(pid)
        if not report['attach'].get('ok'):
            report['status'] = 'attach_failed'
    report['next_step'] = (
        'Validate injection access, then discover and verify a send profile for '
        'this exact architecture, build and core-library SHA256. No send API is enabled.'
    )
    return report
