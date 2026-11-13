"""Parse the plain-text transcript copied from a WeChat chat window.

WeChat's multi-select "复制" action produces blocks like::

    Harry昊昊
    2026年10月31日  7:23
    已进入管理员模式

    Harry昊昊
    2026年10月31日  7:23
    /end

Message bodies can contain blank lines, so the body is delimited by the next
``sender + date`` header rather than by blank lines.
"""
from __future__ import annotations

import re
from datetime import datetime

from .models import Message

#: sender line (short, no newline) followed by a Chinese date line.
HEADER_RE = re.compile(
    r"(?m)^([^\n]{1,100})\n"
    r"(\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2})\n"
)

_TIME_RE = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})"
)


def parse_time(value: str) -> datetime | None:
    """Parse ``2026年10月31日  7:23`` into a :class:`datetime`."""
    m = _TIME_RE.search(value or "")
    if not m:
        return None
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)),
        )
    except ValueError:
        return None


def parse_transcript(text: str) -> list[Message]:
    """Parse a copied transcript into messages.

    Returns an empty list when the clipboard does not look like a WeChat
    transcript.
    """
    if not text:
        return []
    headers = list(HEADER_RE.finditer(text))
    if not headers:
        return []
    messages: list[Message] = []
    for i, header in enumerate(headers):
        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end].strip()
        time_text = header.group(2).strip()
        messages.append(
            Message(
                sender=header.group(1).strip(),
                time=time_text,
                text=body,
                timestamp=parse_time(time_text),
            )
        )
    return messages


def format_messages(messages: list[Message], style: str = "text") -> str:
    """Format parsed messages as ``text`` or ``markdown``."""
    if style == "markdown":
        out = []
        for m in messages:
            out.append(f"## {m.time} · {m.sender}\n\n{m.text}\n")
        return "\n---\n\n".join(out)
    return "\n".join(f"[{m.time}] {m.sender}: {m.text}" for m in messages)
