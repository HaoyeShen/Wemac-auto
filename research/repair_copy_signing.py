"""Rebuild the experimental copy with per-component entitlements.

Dry-run by default. Never writes to the installed application or account data.
"""
from pathlib import Path
import argparse
import json
import plistlib
import re
import subprocess
import sys
import tempfile

SOURCE = Path('/Applications/WeChat.app')
TARGET = Path(__file__).resolve().parent / 'WeChat-Hook.app'
MACH_MAGICS = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}


def run(args):
    return subprocess.run(args, check=True, capture_output=True)


def entitlements_for(original, main=False):
    result = dict(original)
    if main:
        result['com.apple.security.get-task-allow'] = True
        result['com.apple.security.cs.disable-library-validation'] = True
    return result


def plan():
    nodes = {SOURCE}
    for path in SOURCE.rglob('*'):
        if path.is_symlink():
            continue
        if path.is_dir() and path.suffix in ('.app', '.framework', '.xpc', '.bundle'):
            if subprocess.run(['codesign', '-dv', str(path)], capture_output=True).returncode == 0:
                nodes.add(path)
        elif path.is_file():
            with path.open('rb') as stream:
                magic = stream.read(4)
            if magic in MACH_MAGICS:
                nodes.add(path)
    # A bundle and its executable share one signature. Sign the bundle once,
    # otherwise the main executable appears twice with conflicting plans.
    managed = set()
    for bundle in list(nodes):
        if not bundle.is_dir():
            continue
        for info_path in (bundle / 'Contents/Info.plist', bundle / 'Resources/Info.plist'):
            if info_path.is_file():
                info = plistlib.loads(info_path.read_bytes())
                name = info.get('CFBundleExecutable')
                if name:
                    executable = bundle / ('Contents/MacOS' if bundle.suffix != '.framework' else '') / name
                    managed.add(executable.resolve())
                break
    nodes = {p for p in nodes if p.is_dir() or p.resolve() not in managed}
    result = []
    for path in sorted(nodes, key=lambda p: (-len(p.parts), str(p))):
        signed = run(['codesign', '-dv', str(path)])
        identifier = re.search(r'^Identifier=(.*)$', signed.stderr.decode(), re.M)
        if not identifier:
            raise RuntimeError(f'Missing identity: {path}')
        raw = run(['codesign', '-d', '--entitlements', ':-', str(path)]).stdout
        original = plistlib.loads(raw) if raw.strip() else {}
        ents = entitlements_for(original, path == SOURCE)
        result.append({'path': str(path.relative_to(SOURCE)), 'identifier': identifier.group(1),
                       'entitlements': ents, 'main': path == SOURCE})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    # Fixed paths and process checks deliberately exclude the original app.
    assert TARGET != SOURCE and TARGET.parent == Path(__file__).resolve().parent
    sys.path.insert(0, str(TARGET.parent.parent / 'src'))
    from wechat_aumac.hook_probe import process_path
    processes = subprocess.run(['pgrep', '-x', 'WeChat'], capture_output=True, text=True)
    for line in processes.stdout.splitlines():
        path = process_path(int(line))
        if path and Path(path).is_relative_to(TARGET):
            raise SystemExit('Stop the experimental copy before repairing it')
    components = plan()
    (TARGET.parent / 'component-signing-plan.json').write_text(json.dumps(components, indent=2))
    print(f'{len(components)} components; plan saved', flush=True)
    if not args.apply:
        return
    run(['codesign', '--verify', '--deep', '--strict', str(SOURCE)])
    run(['ditto', str(SOURCE), str(TARGET)])
    with tempfile.TemporaryDirectory() as root:
        for index, node in enumerate(components):
            destination = TARGET / node['path']
            command = ['codesign', '--force', '--sign', '-', '--timestamp=none', '--options', '0',
                       '--identifier', node['identifier']]
            if node['entitlements']:
                ent = Path(root) / f'{index}.plist'
                ent.write_bytes(plistlib.dumps(node['entitlements']))
                command += ['--entitlements', str(ent)]
            run(command + [str(destination)])
    run(['codesign', '--verify', '--deep', '--strict', str(TARGET)])
    run(['codesign', '--verify', '--deep', '--strict', str(SOURCE)])
    print('Repaired copy verified; original signature verified', flush=True)


if __name__ == '__main__':
    main()
