"""Wemac-auto: macOS WeChat automation through internal functions only."""
from .config import VERSION
from .errors import WeChatAuMacError
from .native import NativeSession, WeChatNative, NativeError

__version__ = VERSION
WeChat = WeChatNative
WeChatAuMac = WeChatNative
__all__ = ['NativeSession', 'WeChatNative', 'WeChat', 'WeChatAuMac',
           'NativeError', 'WeChatAuMacError', '__version__']
