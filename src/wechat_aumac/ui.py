"""Low-level macOS UI automation for WeChat.

The backend is intentionally narrow and does not touch WeChat's databases.
It works the way a user would:

* bring WeChat to the front and maximize it;
* wheel the conversation to the bottom;
* left-drag from the blank strip above the input box to the top of the chat
  with a ~2 degree tilt, hold still for three seconds, then copy;
* for sending, click the input box, paste, verify the input, press Return.

Keyboard and scroll events are posted to the WeChat process directly.  Mouse
events use the HID tap because that is what WeChat's Qt message view expects.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import math
import re
import subprocess
import time
from dataclasses import dataclass

from . import config
from .errors import (
    ClipboardError,
    FullScreenError,
    SendError,
    UIAutomationError,
    WeChatAuMacError,
    WeChatNotRunning,
    WindowNotFound,
)

# ---------------------------------------------------------------------------
# CoreGraphics bindings
# ---------------------------------------------------------------------------

_cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


_cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
_cg.CGEventCreateMouseEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32
]
_cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
_cg.CGEventCreateScrollWheelEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32
]
_cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
_cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
_cg.CGEventSetFlags.restype = None
_cg.CGEventSetLocation.argtypes = [ctypes.c_void_p, CGPoint]
_cg.CGEventSetLocation.restype = None
_cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
_cg.CGEventPost.restype = None
_cg.CGEventPostToPid.argtypes = [ctypes.c_int32, ctypes.c_void_p]
_cg.CGEventPostToPid.restype = None
_cg.CGMainDisplayID.restype = ctypes.c_uint32
_cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
_cg.CGDisplayBounds.restype = CGRect

_cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
_cf.CFRelease.argtypes = [ctypes.c_void_p]
_cf.CFRelease.restype = None

# Event types
_LEFT_DOWN = 1
_LEFT_UP = 2
_LEFT_DRAGGED = 6
_HID_TAP = 0

# Key codes (US layout, ANSI virtual key codes)
_KEY_A = 0
_KEY_C = 8
_KEY_V = 9
_KEY_F = 3
_KEY_RETURN = 36
_KEY_ESCAPE = 53
_KEY_END = 119

_FLAG_SHIFT = 1 << 17
_FLAG_CONTROL = 1 << 18
_FLAG_OPTION = 1 << 19
_FLAG_COMMAND = 1 << 20

# Scroll units
_SCROLL_LINE = 1


def _release(event) -> None:
    if event:
        _cf.CFRelease(event)


def _point(x: float, y: float) -> CGPoint:
    return CGPoint(float(x), float(y))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def screen_bounds() -> tuple[int, int, int, int]:
    """Return ``(x, y, width, height)`` of the main display in points."""
    rect = _cg.CGDisplayBounds(_cg.CGMainDisplayID())
    return (
        int(rect.origin.x),
        int(rect.origin.y),
        int(rect.size.width),
        int(rect.size.height),
    )


def is_maximized(
    bounds: tuple[int, int, int, int],
    screen: tuple[int, int, int, int] | None = None,
) -> bool:
    """Whether a window covers most of the usable screen."""
    sx, sy, sw, sh = screen or screen_bounds()
    x, y, w, h = bounds
    return (
        w >= sw * config.MAXIMIZED_WIDTH_RATIO
        and h >= sh * config.MAXIMIZED_HEIGHT_RATIO
        and x <= sx + 2
        and y <= sy + 120
    )


def selection_points(
    bounds: tuple[int, int, int, int],
    angle_degrees: float | None = None,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return the calibrated ``(start, end)`` points of the copy gesture."""
    x, y, w, h = bounds
    sx = x + w * config.START_X_RATIO
    sy = y + h * config.START_Y_RATIO
    ey = y + h * config.END_Y_RATIO
    angle = config.ANGLE_DEGREES if angle_degrees is None else angle_degrees
    ex = sx + math.tan(math.radians(angle)) * (sy - ey)
    return (sx, sy), (ex, ey)


def focus_point(bounds: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, w, h = bounds
    return x + w * config.FOCUS_X_RATIO, y + h * config.FOCUS_Y_RATIO


def input_point(bounds: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, w, h = bounds
    return x + w * config.INPUT_X_RATIO, y + h * config.INPUT_Y_RATIO


def _osascript(script: str, timeout: float = 8.0) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        raise UIAutomationError(message or "osascript failed")
    return proc.stdout.strip()


def get_clipboard() -> str:
    try:
        proc = subprocess.run(
            ["pbpaste"], capture_output=True, text=True,
            timeout=config.CLIPBOARD_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClipboardError(f"pbpaste failed: {exc}") from exc
    if proc.returncode != 0:
        raise ClipboardError(proc.stderr.strip() or "pbpaste failed")
    return proc.stdout


def set_clipboard(text: str) -> None:
    try:
        proc = subprocess.run(
            ["pbcopy"], input=text, text=True,
            timeout=config.CLIPBOARD_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClipboardError(f"pbcopy failed: {exc}") from exc
    if proc.returncode != 0:
        raise ClipboardError(proc.stderr.strip() or "pbcopy failed")


def wechat_pid() -> int | None:
    for args in (
        ["pgrep", "-x", config.WECHAT_PROCESS],
        ["pgrep", "-f", f"{config.WECHAT_APP}.app/Contents/MacOS/{config.WECHAT_PROCESS}"],
    ):
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
    return None


def activate() -> None:
    """Bring WeChat to the front without toggling the full-screen Space."""
    if wechat_pid() is None:
        raise WeChatNotRunning("WeChat is not running")
    try:
        subprocess.run(
            ["open", "-a", config.WECHAT_APP],
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UIAutomationError(f"cannot activate WeChat: {exc}") from exc
    time.sleep(0.6)


def window_bounds() -> tuple[int, int, int, int]:
    """Return the WeChat window position and size via System Events."""
    script = (
        'tell application "System Events" to tell process "WeChat" to '
        'get {position of window 1, size of window 1}'
    )
    try:
        out = _osascript(script)
    except UIAutomationError as exc:
        raise WindowNotFound(
            "cannot read the WeChat window; grant Accessibility to the "
            "terminal/Python process and make sure WeChat is running"
        ) from exc
    nums = [int(n) for n in re.findall(r"-?\d+", out)]
    if len(nums) < 4:
        raise WindowNotFound(f"unexpected window bounds: {out!r}")
    return nums[0], nums[1], nums[2], nums[3]


def fullscreen_state() -> bool | None:
    """Return macOS full-screen state, or ``None`` if unavailable."""
    try:
        out = _osascript(
            'tell application "System Events" to tell process "WeChat" to '
            'get value of attribute "AXFullScreen" of window 1'
        )
    except UIAutomationError:
        return None
    return out.strip().lower() == "true"


def ensure_fullscreen() -> tuple[int, int, int, int]:
    """Activate WeChat and maximize its normal window.

    We deliberately use the normal window zoom rather than the macOS
    full-screen Space: a Space switch makes synthetic mouse coordinates hit
    the wrong desktop and is what broke earlier attempts.
    """
    activate()
    bounds = window_bounds()
    if is_maximized(bounds):
        return bounds

    sx, sy, sw, sh = screen_bounds()
    x, y, w, h = bounds
    top = sy + 33
    target_h = h if h >= sh * config.MAXIMIZED_HEIGHT_RATIO else int(sh * 0.90)

    # 1) Directly position/size the normal window.  This also repairs a
    # window that is full-screen-width but shifted off the left edge (a common
    # result of search/zoom interactions).
    try:
        _osascript(
            'tell application "System Events" to tell process "WeChat" to '
            f"set position of window 1 to {{{sx}, {top}}}"
        )
        _osascript(
            'tell application "System Events" to tell process "WeChat" to '
            f"set size of window 1 to {{{sw}, {target_h}}}"
        )
    except UIAutomationError:
        pass
    time.sleep(0.6)
    bounds = window_bounds()
    if is_maximized(bounds):
        return bounds

    # 2) Use the accessibility zoom action.
    try:
        _osascript(
            'tell application "System Events" to tell process "WeChat" to '
            'perform action "AXZoomWindow" of window 1'
        )
    except UIAutomationError:
        pass
    time.sleep(0.8)
    bounds = window_bounds()
    if is_maximized(bounds):
        return bounds

    # 3) Double-click the title bar as a fallback.
    x, y, w, h = bounds
    double_click(x + w / 2, y + 10)
    time.sleep(0.8)
    bounds = window_bounds()
    if is_maximized(bounds):
        return bounds

    # 4) Final direct geometry attempt.
    try:
        _osascript(
            'tell application "System Events" to tell process "WeChat" to '
            f"set position of window 1 to {{{sx}, {top}}}"
        )
        _osascript(
            'tell application "System Events" to tell process "WeChat" to '
            f"set size of window 1 to {{{sw}, {target_h}}}"
        )
    except UIAutomationError:
        pass
    time.sleep(0.6)
    bounds = window_bounds()
    if not is_maximized(bounds):
        raise FullScreenError(
            f"WeChat window is not maximized: {bounds}; screen={screen_bounds()}"
        )
    return bounds


# ---------------------------------------------------------------------------
# Synthetic events
# ---------------------------------------------------------------------------


def _post_key(pid: int | None, keycode: int, flags: int = 0, *, global_tap: bool = False) -> None:
    for down in (True, False):
        event = _cg.CGEventCreateKeyboardEvent(None, keycode, down)
        if not event:
            raise UIAutomationError(f"cannot create key event {keycode}")
        try:
            if flags:
                _cg.CGEventSetFlags(event, flags)
            if global_tap or pid is None:
                _cg.CGEventPost(_HID_TAP, event)
            else:
                _cg.CGEventPostToPid(pid, event)
        finally:
            _release(event)
        time.sleep(0.035)


def _post_mouse(event_type: int, x: float, y: float, *, pid: int | None = None) -> None:
    event = _cg.CGEventCreateMouseEvent(None, event_type, _point(x, y), 0)
    if not event:
        raise UIAutomationError("cannot create mouse event")
    try:
        _cg.CGEventSetLocation(event, _point(x, y))
        if pid is None:
            _cg.CGEventPost(_HID_TAP, event)
        else:
            _cg.CGEventPostToPid(pid, event)
    finally:
        _release(event)


def click(x: float, y: float) -> None:
    _post_mouse(_LEFT_DOWN, x, y)
    time.sleep(0.05)
    _post_mouse(_LEFT_UP, x, y)


def double_click(x: float, y: float) -> None:
    click(x, y)
    time.sleep(0.08)
    click(x, y)


def post_scroll(pid: int, lines: int, x: float, y: float) -> None:
    event = _cg.CGEventCreateScrollWheelEvent(None, _SCROLL_LINE, 1, int(lines))
    if not event:
        raise UIAutomationError("cannot create scroll event")
    try:
        _cg.CGEventSetLocation(event, _point(x, y))
        _cg.CGEventPostToPid(pid, event)
    finally:
        _release(event)


def wheel_bottom(pid: int, bounds: tuple[int, int, int, int]) -> None:
    x, y, w, h = bounds
    cx, cy = x + w / 2, y + h / 2
    for _ in range(config.WHEEL_REPEAT):
        post_scroll(pid, config.WHEEL_LINES, cx, cy)
        time.sleep(0.12)
    time.sleep(0.3)


def drag_select(pid: int, bounds: tuple[int, int, int, int]) -> None:
    """The validated copy gesture: 2 degree upward drag, hold 3 s."""
    (sx, sy), (ex, ey) = selection_points(bounds)
    _post_mouse(_LEFT_DOWN, sx, sy)
    time.sleep(0.15)
    steps = 30
    for i in range(1, steps + 1):
        x = sx + (ex - sx) * i / steps
        y = sy + (ey - sy) * i / steps
        _post_mouse(_LEFT_DRAGGED, x, y)
        time.sleep(config.DRAG_SECONDS / steps)
    # Hold the left button still at the top.  This is what makes WeChat
    # extend the selection and auto-scroll through earlier messages.
    time.sleep(config.HOLD_SECONDS)
    _post_mouse(_LEFT_UP, ex, ey)
    time.sleep(0.7)


def copy_selection(pid: int) -> str:
    """Copy the current WeChat selection, preserving the pasteboard.

    The pasteboard is cleared first.  If WeChat did not actually select
    anything, the result is empty instead of a stale unrelated clipboard from
    another app.
    """
    old = get_clipboard()
    try:
        set_clipboard("")
        _post_key(pid, _KEY_C, _FLAG_COMMAND)
        time.sleep(0.5)
        return get_clipboard()
    finally:
        set_clipboard(old)


def select_and_copy() -> tuple[str, tuple[int, int, int, int]]:
    """Maximize, wheel to bottom, focus, run the gesture, and copy."""
    bounds = ensure_fullscreen()
    pid = wechat_pid()
    if pid is None:
        raise WeChatNotRunning("WeChat is not running")
    wheel_bottom(pid, bounds)
    # Single click at the far-right blank strip just above the input box,
    # then start the selection drag from the horizontal middle at the same
    # bottom line.
    fx, fy = focus_point(bounds)
    click(fx, fy)
    time.sleep(0.3)
    drag_select(pid, bounds)
    text = copy_selection(pid)
    return text, bounds


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def focus_input(bounds: tuple[int, int, int, int]) -> None:
    x, y = input_point(bounds)
    click(x, y)
    time.sleep(0.25)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def send_text(text: str, *, verify_input: bool = True) -> None:
    """Type ``text`` into the WeChat input box and press Return."""
    if not text.strip():
        raise SendError("message text is empty")
    bounds = ensure_fullscreen()
    pid = wechat_pid()
    if pid is None:
        raise WeChatNotRunning("WeChat is not running")

    focus_input(bounds)
    old = get_clipboard()
    try:
        set_clipboard(text)
        _post_key(pid, _KEY_A, _FLAG_COMMAND)
        _post_key(pid, _KEY_V, _FLAG_COMMAND)
        time.sleep(0.45)

        if verify_input:
            # Copy the input box back and make sure the paste landed before
            # pressing Return, so a failed focus never sends the wrong text.
            _post_key(pid, _KEY_A, _FLAG_COMMAND)
            _post_key(pid, _KEY_C, _FLAG_COMMAND)
            time.sleep(0.35)
            pasted = get_clipboard()
            if _normalise(text) not in _normalise(pasted):
                # One retry after clicking the input again.
                focus_input(bounds)
                _post_key(pid, _KEY_A, _FLAG_COMMAND)
                _post_key(pid, _KEY_V, _FLAG_COMMAND)
                time.sleep(0.45)
                _post_key(pid, _KEY_A, _FLAG_COMMAND)
                _post_key(pid, _KEY_C, _FLAG_COMMAND)
                time.sleep(0.35)
                pasted = get_clipboard()
                if _normalise(text) not in _normalise(pasted):
                    raise SendError(
                        "the text did not reach the WeChat input box; "
                        "check that WeChat is frontmost and the chat is open"
                    )

        # Collapse the selection to the end, then send.
        _post_key(pid, _KEY_END)
        time.sleep(0.1)
        _post_key(pid, _KEY_RETURN)
        time.sleep(0.45)
    finally:
        set_clipboard(old)


# ---------------------------------------------------------------------------
# Chat search
# ---------------------------------------------------------------------------


def dismiss_overlays(bounds: tuple[int, int, int, int]) -> None:
    """Close the search overlay and focus the message view."""
    pid = wechat_pid()
    if pid is None:
        return
    _post_key(pid, _KEY_ESCAPE)
    time.sleep(0.25)
    x, y, w, h = bounds
    # Far-right blank margin: outside the bubble and inside the window.
    click(x + w * 0.97, y + h * 0.5)
    time.sleep(0.4)


def open_chat(name: str) -> None:
    """Open a chat with WeChat's search: Cmd+F, paste, Return.

    This is the sequence the user confirmed: Command-F focuses WeChat's
    search field, the name is pasted, and Return opens the first result.
    WeChat's result list has no Accessibility title, so callers should read
    the chat and confirm its content before sending anything important.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("chat name is empty")
    ensure_fullscreen()
    pid = wechat_pid()
    if pid is None:
        raise WeChatNotRunning("WeChat is not running")
    old = get_clipboard()
    try:
        set_clipboard(name)
        _post_key(pid, _KEY_F, _FLAG_COMMAND)
        time.sleep(0.5)
        _post_key(pid, _KEY_A, _FLAG_COMMAND)
        _post_key(pid, _KEY_V, _FLAG_COMMAND)
        time.sleep(1.3)
        _post_key(pid, _KEY_RETURN)
        time.sleep(1.6)
    finally:
        set_clipboard(old)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@dataclass
class DoctorReport:
    platform_ok: bool
    running: bool
    pid: int | None
    window: tuple[int, int, int, int] | None
    screen: tuple[int, int, int, int]
    maximized: bool
    fullscreen: bool | None
    clipboard_ok: bool
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "platform_ok": self.platform_ok,
            "running": self.running,
            "pid": self.pid,
            "window": list(self.window) if self.window else None,
            "screen": list(self.screen),
            "maximized": self.maximized,
            "fullscreen": self.fullscreen,
            "clipboard_ok": self.clipboard_ok,
            "error": self.error,
        }


def doctor() -> DoctorReport:
    import platform

    platform_ok = platform.system() == "Darwin"
    pid = wechat_pid()
    screen = screen_bounds()
    bounds = None
    maximized = False
    fs = None
    clipboard_ok = False
    error = ""
    try:
        get_clipboard()
        clipboard_ok = True
    except ClipboardError as exc:
        error = str(exc)
    if pid:
        try:
            bounds = window_bounds()
            maximized = is_maximized(bounds, screen)
            fs = fullscreen_state()
        except WeChatAuMacError as exc:  # type: ignore[name-defined]
            error = str(exc)
    return DoctorReport(
        platform_ok=platform_ok,
        running=pid is not None,
        pid=pid,
        window=bounds,
        screen=screen,
        maximized=maximized,
        fullscreen=fs,
        clipboard_ok=clipboard_ok,
        error=error,
    )
