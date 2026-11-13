"""Public data models for the UI backend."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Message:
    """One message copied out of a WeChat chat window."""

    sender: str
    time: str
    text: str
    timestamp: datetime | None = field(default=None, compare=False)

    def to_dict(self) -> dict:
        return {
            "sender": self.sender,
            "time": self.time,
            "timestamp": self.timestamp.isoformat() if self.timestamp else "",
            "text": self.text,
        }


@dataclass
class ReadResult:
    """The raw clipboard transcript and its parsed messages."""

    raw: str
    messages: list[Message]
    window: tuple[int, int, int, int] | None = None

    def to_dict(self) -> dict:
        return {
            "window": list(self.window) if self.window else None,
            "count": len(self.messages),
            "messages": [m.to_dict() for m in self.messages],
            "raw": self.raw,
        }


@dataclass
class SendResult:
    """Outcome of a send operation."""

    ok: bool
    text: str
    chat: str | None = None
    verified: bool = False
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "text": self.text,
            "chat": self.chat,
            "verified": self.verified,
            "detail": self.detail,
        }
