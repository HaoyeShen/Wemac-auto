"""Exception hierarchy for WeChat auMac."""
from __future__ import annotations


class WeChatAuMacError(Exception):
    """Base error."""


class NotMacOSError(WeChatAuMacError):
    """The UI backend only runs on macOS."""


class WeChatNotRunning(WeChatAuMacError):
    """WeChat is not running or has no accessible window."""


class WindowNotFound(WeChatAuMacError):
    """The WeChat window could not be located."""


class FullScreenError(WeChatAuMacError):
    """WeChat could not be maximized to a usable full window."""


class UIAutomationError(WeChatAuMacError):
    """A CoreGraphics / AppleScript automation step failed."""


class ClipboardError(UIAutomationError):
    """Reading or writing the pasteboard failed."""


class ReadError(WeChatAuMacError):
    """Copying or parsing chat history failed."""


class SendError(WeChatAuMacError):
    """Typing or sending a message failed."""
