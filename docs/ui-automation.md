# UI automation notes

This backend drives the normal WeChat desktop window. It does not touch the
WeChat database, process memory, or app signature.

## Permissions

Give **Accessibility** to the terminal/IDE that runs Python:

`System Settings → Privacy & Security → Accessibility`

Then confirm:

```bash
PYTHONPATH=src python3 -m wechat_aumac doctor --json
```

Expected: `running: true`, a non-null `window`, and `maximized: true`.
If `window` is `null`, macOS is blocking System Events; grant Accessibility and
restart the terminal.

## "Full screen" means maximized normal window

We deliberately **do not** toggle the macOS full-screen Space (`Ctrl+Cmd+F`).
A Space switch moves WeChat to another desktop, and synthetic mouse coordinates
then land on the wrong desktop — this was the main failure mode during
development.

`ensure_fullscreen()` activates WeChat and:

1. accepts the window if it covers ≥95% of the display width and ≥80% height;
2. otherwise tries `AXZoomWindow`;
3. then double-clicks the title bar;
4. then tries to set position/size directly.

For a 1512×982 display the calibrated window is `(0, 33, 1512, 887)`.

## Copy gesture

The copy path is:

```
wheel to bottom (4 × 60 lines)
  ↓
single click at (window.x + 0.960w, window.y + 0.820h)
    — far-right blank strip just above the input box
  ↓
left down at (window.x + 0.618w, window.y + 0.820h)
  ↓
2° tilt upward drag to (x + 0.633w, y + 0.0305h) over 2s
  ↓
hold left button still at the top for 3s
  ↓
left up
  ↓
Cmd+C targeted at the WeChat PID
```

The hold is important: it lets WeChat extend the selection and auto-scroll
through earlier messages. Without it, only the newest screenful is copied.

The exact points for `(0, 33, 1512, 887)` are focus `(1451.5, 760.3)`,
start `(934.4, 760.3)`, and end `(958.9, 60.1)`.

Keyboard and scroll events use `CGEventPostToPid(wechat_pid, event)` so they
reach WeChat even when another window has keyboard focus. Mouse events use the
HID tap because WeChat's Qt message view expects normal mouse events; keep
WeChat in front while reading.

## Sending

`send_text()`:

1. clicks the input box at `(0.50w, 0.91h)`;
2. writes the text to the pasteboard and sends `Cmd+V` to WeChat;
3. `Cmd+A`, `Cmd+C` to copy the input box back;
4. checks the expected text is present; retries once after re-clicking the
   input box;
5. `End`, `Return`;
6. restores the old pasteboard.

This verification step prevents a lost focus from sending an empty message or
the wrong draft. `WeChatUI.send(..., verify=True)` additionally reads the chat
and checks the last message.

If WeChat is configured to send with `Cmd+Enter`, change the final key in
`send_text` accordingly; the default is Enter-to-send.

## Chat search

`open_chat(name)` and `read(chat=name)` use WeChat's search:

```
Cmd+F → Cmd+A → paste name → Return
```

WeChat's search result list has no Accessibility title, so this is
**best-effort** and is used for reading. `send()` always targets the current
chat: open the target manually (or `open_chat` + `read` to confirm), then call
`send(text)`.

## Tuning

| Env var | Default | Use |
|---|---|---|
| `WECHAT_AUMAC_START_X_RATIO` | 0.618 | middle drag start x |
| `WECHAT_AUMAC_START_Y_RATIO` | 0.820 | blank strip above input |
| `WECHAT_AUMAC_END_Y_RATIO` | 0.0305 | top y |
| `WECHAT_AUMAC_ANGLE_DEGREES` | 2.0 | drag tilt |
| `WECHAT_AUMAC_DRAG_SECONDS` | 2.0 | drag duration |
| `WECHAT_AUMAC_HOLD_SECONDS` | 3.0 | hold at top |
| `WECHAT_AUMAC_WHEEL_LINES` | 60 | wheel pulse |
| `WECHAT_AUMAC_WHEEL_REPEAT` | 4 | wheel pulses |
| `WECHAT_AUMAC_FOCUS_X_RATIO` | 0.960 | far-right focus click x |
| `WECHAT_AUMAC_FOCUS_Y_RATIO` | 0.820 | far-right focus click y |
| `WECHAT_AUMAC_INPUT_X_RATIO` | 0.50 | input click x |
| `WECHAT_AUMAC_INPUT_Y_RATIO` | 0.91 | input click y |


If a WeChat update changes the input box height, adjust `START_Y_RATIO` first:
it must sit in the blank strip above the input, not inside it. A start too low
will select the input box; a start too high may start on a message link.

## Troubleshooting

- **Clipboard contains the terminal's old selection** — the drag did not reach
  WeChat. Check that WeChat is frontmost/maximized and retry.
- **Only the last screenful copied** — the hold at the top was too short or the
  drag ended below the top. Increase `WECHAT_AUMAC_HOLD_SECONDS` or verify
  `END_Y_RATIO`.
- **Text sent to the wrong chat** — `send()` only targets the current chat;
  open the intended chat and confirm with `read()` first.
- **Search opened the wrong chat** — the result list has no AX title; confirm
  with `read(chat=...)` or open the chat manually.
- **`WindowNotFound`** — Accessibility permission missing, or WeChat is not
  running.

## Security

No network, no telemetry, no database/key access, no app modification. Reading
uses the public clipboard and the normal macOS event APIs. Sending uses the
normal input box and Return key.
