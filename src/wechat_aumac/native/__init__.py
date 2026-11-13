"""Experimental native backend; only explicitly verified capabilities are exposed."""

from .session import NativeError, NativeSession

WeChatNative = NativeSession

__all__ = ['WeChatNative', 'NativeSession', 'NativeError']
