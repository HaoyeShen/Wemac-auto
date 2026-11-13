# Wemac-auto

[中文说明](README.zh-CN.md)

Python automation for the **macOS WeChat client**, with a UI backend and an
experimental native function backend. The Python package and command retain the
names `wechat_aumac` and `wechat-aumac`.

## Status

- 95 unit tests pass, including message codecs, native session guards, media,
  Moments request construction, signing and UI behavior.
- Native backend tested on Apple Silicon, macOS 26.7.1 and WeChat 4.2.0
  (build 270348): text, PNG, GIF, short MP4 and AMR-NB voice sends were
  acknowledged by the server and receipt was confirmed on a phone.
- Native watching supports incoming and outgoing messages. Reading queries the
  observed session cache, rather than the complete historical database.
- Moments timeline/detail reads were tested. Publishing plain text, liking,
  unliking and commenting are experimental, disabled by default and have **not**
  been tested with server writes. No test Moments posts have been published.
- The UI backend was tested with WeChat 4.1.15. Native access requires a locally
  prepared research copy, optional Frida dependencies and an exact-build profile.

See [native API](docs/native-api.md), [native setup and stability](docs/background-send.md)
and [research files](research/README.md). WeChat binaries, account/chat data,
local profiles, media fixtures and runtime reports are excluded from this repository.

## Install

The repo ships a zero-install launcher:

```bash
cd Wemac-auto
./wechat-aumac doctor
# equivalent to:
PYTHONPATH=src python3 -m wechat_aumac doctor
```

Optional editable install (pip fetches the hatchling build backend):

```bash
python3 -m pip install -e .
```

Requirements: macOS, WeChat 4.x logged in, Accessibility permission for the
terminal/Python process, a maximized WeChat window, and Enter-to-send enabled.

## Quick start

```python
from wechat_aumac import WeChatUI

wx = WeChatUI()
messages = wx.read()                 # full loaded history of the current chat
for m in messages[-5:]:
    print(m.time, m.sender, m.text)

wx.open_chat("test")                 # search-open (best-effort, read only)
messages = wx.read(chat="test")      # read after opening
wx.send("hello from Python")         # send: current chat only
wx.send("hello", verify=True)        # send and read back
wx.export("exports", formats=("json", "txt", "md"))
```

`--chat`/`open_chat` use WeChat search: `Cmd+F` → paste → Return. The result list has no Accessibility
title, so search is best-effort and is used for **reading**. `send` always
targets the current chat: open the target manually (or `open_chat` + `read` to
confirm), then call `send(text)`.

## CLI

```bash
PYTHONPATH=src python3 -m wechat_aumac doctor
PYTHONPATH=src python3 -m wechat_aumac read --limit 5 --json
PYTHONPATH=src python3 -m wechat_aumac read --export exports --prefix test
PYTHONPATH=src python3 -m wechat_aumac send "hello" --verify
```

## How reading works

1. activate WeChat and maximize its normal window;
2. wheel the conversation to the bottom (4 × 60 lines);
3. click once at the far-right blank strip just above the input box;
4. press the left button at the horizontal middle (x=0.618) on that same bottom line;
5. drag to the top of the chat with a ~2° tilt over 2 seconds;
6. hold the left button still at the top for 3 seconds (auto-extends selection);
7. release, send `Cmd+C` to the WeChat PID, read the pasteboard;
8. parse `sender / Chinese date / body` blocks (bodies may contain blank lines).

Coordinates are window-relative and calibrated on a 1512×887 window. Tune with
`WECHAT_AUMAC_START_X_RATIO`, `WECHAT_AUMAC_START_Y_RATIO`,
`WECHAT_AUMAC_END_Y_RATIO`, `WECHAT_AUMAC_ANGLE_DEGREES`,
`WECHAT_AUMAC_DRAG_SECONDS`, `WECHAT_AUMAC_HOLD_SECONDS`.

## How sending stays stable

The sender clicks the input box, pastes from the clipboard, copies the input
back to **verify the text landed**, retries once if not, then presses End and
Return. `verify=True` reads the chat again and checks the last message.

## Limits

- Only messages currently loaded by the WeChat client are visible.
- Reading selects/copies and leaves the conversation scrolled to the top.
- `chat=`/`open_chat` search-open is best-effort and is used for **reading**;
  the result list has no Accessibility title. `send` always targets the
  current chat, so a failed search cannot send to the wrong conversation.
- The UI backend does not access databases or process memory. The optional native
  backend attaches to a separately prepared research copy; see its setup guide.

See [docs/ui-automation.md](docs/ui-automation.md) for permissions and
calibration details.

## Watch new messages

```bash
./wechat-aumac watch
./wechat-aumac watch --chat test --interval 10 --json
```

Or iterate over `WeChatUI().watch(interval=10)` in Python. The first read is
used as a baseline; subsequent reads emit newly appended messages. JSON output
contains one object per line. Ctrl+C stops listening. The optional chat is opened
once; keep that conversation open throughout monitoring.

This polls the UI and moves the mouse; each read takes several seconds, followed
by the configured wait. Both incoming and outgoing messages are included because
the copied transcript has no direction field. Ordered overlap preserves repeated
message occurrences. Snapshots without overlap reset the baseline without replay;
identical fixed-size snapshots cannot reveal replacement by identical messages.
Read errors stop monitoring and propagate to the caller.
