# Local native research

This directory publishes analysis/build scripts and selected static schema metadata
for WeChat 4.2.0, build 270348, Apple Silicon. It does not include WeChat binaries,
disassembly dumps, dependencies, captured messages, account identifiers, test media
or verification reports. Report paths mentioned in the documentation refer to local
artifacts from the recorded verification session; they are not distributed evidence.

The original `/Applications/WeChat.app` is not modified by these scripts. Prepare
any research copy locally before attempting native access. The native backend is
pinned to an exact app version, executable paths, core SHA-256, function heads and
completion-helper SHA-256. A different build requires new analysis.

Copy `native-profile-4.2.0.example.json` to `native-profile-4.2.0.json` and replace
its app/core paths and local fingerprints after inspecting the research copy.
The example intentionally has no verified capabilities. Copying an example does
not establish that sending or reading is validated on a new installation. Building
the native catalog does not grant capabilities. See
[setup and stability](../docs/background-send.md) and
[native API](../docs/native-api.md) for the verification scope and explicit opt-ins.

`build_completion.py` needs Xcode command-line tools. `--install` requires the
research copy to be stopped. `repair_copy_signing.py` prints a plan by default;
`--apply` changes only the local research copy. Do not run either as part of normal
unit tests. `observe_tasks.py` and `observe_media.py` are archived unsafe prototypes
and deliberately refuse live operation; use the SDK observer instead.

The opt-in send verification scripts require a local, ignored `test-recipient.json`:

```json
{"display_name": "your test chat", "receiver": "YOUR_CONFIRMED_INTERNAL_CHAT_ID"}
```

Also pass the same internal ID with `--to`. Image scripts require an explicit
`--file`; sending requires `--send`. They retain their local prerequisite-report
checks. No sample recipient is a usable destination. No script should be invoked
against a real conversation without choosing its target and content first.

`make_media_fixtures.swift /absolute/path/to/source.png` generates small local GIF,
JPEG and MP4 fixtures in `research/fixtures/`. The AMR fixture encoder additionally
requires a locally built OpenCORE AMR library; those third-party files are excluded.
Some verification scripts require previous local reports and fixtures, so they are
research tools rather than an unattended test suite.

To run the distributable unit suite without sending messages or publishing Moments:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

All runtime outputs under this directory are ignored by default. Add only reviewed
source or static metadata to the allowlist in `.gitignore`.


Version 0.3 uses internal functions only; no Accessibility/UI backend remains.
Use `prepare_isolated_copy.py` to create `WeChat-Wemac.app` without copying account
containers, and see [account isolation](../docs/account-isolation.md). Analysis scripts
that use Capstone require `python3 -m pip install 'capstone>=5,<6'` in the research
environment; the core SDK and isolated-copy builder do not require Capstone.

`build_message_actions_catalog.py` records exact app-message/single-revoke function
entries, including a Mach-O function-boundary check. It grants no capabilities.
The shipped profile example includes this static catalog, with empty capabilities
and placeholder local hashes. Capture and all `verify_*` scripts keep their local
outputs ignored. Send experiments require an explicit `--send` and local binding.
Do not run them as an unattended test suite. The two-account check uses exactly
the existing bound test chat, not arbitrary newly observed chats.
