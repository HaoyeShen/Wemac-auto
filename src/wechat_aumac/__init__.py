"""WeChat auMac — drive the macOS WeChat client to read and send messages."""

from .api import WeChat, WeChatAuMac, WeChatUI
from .config import VERSION
from .errors import (
    ClipboardError,
    FullScreenError,
    NotMacOSError,
    ReadError,
    SendError,
    UIAutomationError,
    WeChatAuMacError,
    WeChatNotRunning,
    WindowNotFound,
)
from .models import Message, ReadResult, SendResult
from .native import WeChatNative, NativeError
from .transcript import format_messages, parse_transcript, parse_time

__version__ = VERSION
__all__ = [
    "WeChatUI",
    "WeChatNative",
    "NativeError",
    "WeChatAuMac",
    "WeChat",
    "Message",
    "ReadResult",
    "SendResult",
    "parse_transcript",
    "format_messages",
    "parse_time",
    "WeChatAuMacError",
    "NotMacOSError",
    "WeChatNotRunning",
    "WindowNotFound",
    "FullScreenError",
    "UIAutomationError",
    "ClipboardError",
    "ReadError",
    "SendError",
    "__version__",
]
