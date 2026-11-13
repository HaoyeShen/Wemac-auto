"""High-level WeChat auMac UI API."""
from __future__ import annotations

from pathlib import Path
import math
import time
from collections.abc import Iterator

from . import ui
from .errors import ReadError
from .export import export_messages
from .models import Message, ReadResult, SendResult
from .transcript import parse_transcript


class WeChatUI:
    """Read and send WeChat messages through the macOS client.

    Every read follows the calibrated sequence: activate/maximize WeChat,
    wheel to the bottom, left-drag with a 2 degree tilt to the top, hold for
    three seconds, then copy the selection.  Sending clicks the input box,
    pastes, verifies the input, then presses Return.

    With no ``chat`` argument the current chat is used.  ``chat=`` opens the
    chat through WeChat's search box (``Cmd+F``, paste, Return, Escape); the
    search result list is not exposed via Accessibility, so callers should
    read the chat and check its content before an important send.
    """

    def __init__(self, *, verify_input: bool = True):
        self.verify_input = verify_input

    # ------------------------------------------------------------- reads

    def read_raw(self, chat: str | None = None) -> str:
        """Copy a chat and return the raw clipboard transcript."""
        if chat:
            ui.open_chat(chat)
        text, _bounds = ui.select_and_copy()
        return text

    def read_result(self, chat: str | None = None, limit: int | None = None) -> ReadResult:
        """Copy and parse a chat (the current chat by default)."""
        if chat:
            ui.open_chat(chat)
        text, bounds = ui.select_and_copy()
        messages = parse_transcript(text)
        if not messages:
            # A search overlay or a partially scrolled long message can leave
            # a header-less snippet on the clipboard.  Close overlays and
            # retry the calibrated gesture once.
            ui.dismiss_overlays(bounds)
            text, bounds = ui.select_and_copy()
            messages = parse_transcript(text)
        if not messages:
            preview = text[:160].replace("\n", " / ")
            raise ReadError(
                "the copied clipboard does not look like a WeChat transcript "
                f"(length={len(text)}): {preview!r}"
            )
        if limit is not None and limit > 0:
            messages = messages[-limit:]
        return ReadResult(raw=text, messages=messages, window=bounds)

    def read(self, chat: str | None = None, limit: int | None = None) -> list[Message]:
        """Read messages from the current chat, or open ``chat`` first."""
        return self.read_result(chat=chat, limit=limit).messages

    # ------------------------------------------------------------- send

    def watch(self, chat: str | None = None, *, interval: float = 10.0) -> Iterator[Message]:
        """Yield newly appended messages, using the first read as a baseline.

        Polls the UI; each read takes several seconds and moves the mouse.
        Includes both incoming and outgoing messages (the transcript has no
        direction field). Keep this chat open while watching. If snapshots
        have no overlap, reset the baseline without replaying unknown history.
        Read failures propagate to the caller. Ctrl+C stops iteration.
        """
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("interval must be a finite positive number")
        if chat:
            self.open_chat(chat)
        previous = self.read()
        while True:
            time.sleep(interval)
            current = self.read()
            # Match ordered occurrences, so identical messages sent in the
            # same minute are still emitted when another occurrence appears.
            overlap = 0
            for size in range(min(len(previous), len(current)), 0, -1):
                if previous[-size:] == current[:size]:
                    overlap = size
                    break
            previous = current
            if overlap:
                yield from current[overlap:]

    def send(self, text: str, *, verify: bool = False) -> SendResult:
        """Send ``text`` from the WeChat input box of the **current** chat.

        Open the target chat first (manually, or with ``open_chat`` and then
        ``read`` to confirm it).  Sending is intentionally never combined with
        search: a failed search must not be able to send to the wrong chat.
        With ``verify=True`` the sent message is read back.
        """
        ui.send_text(text, verify_input=self.verify_input)
        verified = False
        if verify:
            try:
                last = self.read(limit=1)
                verified = bool(last and text.strip() in last[-1].text)
            except Exception:
                verified = False
        return SendResult(
            ok=True,
            text=text,
            verified=verified,
            detail="sent" if not verify else ("verified" if verified else "sent, not verified"),
        )

    def open_chat(self, name: str) -> None:
        """Open a chat by name through WeChat's search box (best-effort)."""
        ui.open_chat(name)

    # ------------------------------------------------------------- export / diagnostics

    def export(
        self,
        out_dir: str | Path,
        chat: str | None = None,
        formats: tuple[str, ...] = ("json", "csv", "txt", "md"),
        prefix: str = "chat",
    ) -> dict:
        messages = self.read(chat=chat)
        return export_messages(messages, out_dir, formats=formats, prefix=prefix)

    @staticmethod
    def doctor() -> dict:
        return ui.doctor().to_dict()


#: Backwards-compatible name for code written against the old database API.
WeChatAuMac = WeChatUI

#: Short alias.
WeChat = WeChatUI


__all__ = ["WeChatUI", "WeChatAuMac", "WeChat"]
