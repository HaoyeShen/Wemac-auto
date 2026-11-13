"""Export parsed WeChat messages to JSON/CSV/TXT/Markdown."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Message
from .transcript import format_messages

DEFAULT_FORMATS = ("json", "csv", "txt", "md")


def export_messages(
    messages: list[Message],
    out_dir: str | Path,
    *,
    formats: tuple[str, ...] = DEFAULT_FORMATS,
    prefix: str = "chat",
) -> dict[str, str]:
    """Write ``messages`` in the requested formats and return their paths."""
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    prefix = prefix or "chat"
    paths: dict[str, str] = {}

    for fmt in formats:
        fmt = fmt.lower().lstrip(".")
        if fmt == "json":
            path = out / f"{prefix}.json"
            path.write_text(
                json.dumps([m.to_dict() for m in messages], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif fmt == "csv":
            path = out / f"{prefix}.csv"
            with path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["sender", "time", "timestamp", "text"])
                for m in messages:
                    writer.writerow([
                        m.sender,
                        m.time,
                        m.timestamp.isoformat() if m.timestamp else "",
                        m.text,
                    ])
        elif fmt in {"txt", "text"}:
            path = out / f"{prefix}.txt"
            path.write_text(format_messages(messages, "text") + "\n", encoding="utf-8")
        elif fmt in {"md", "markdown"}:
            path = out / f"{prefix}.md"
            path.write_text(
                f"# {prefix}\n\n" + format_messages(messages, "markdown") + "\n",
                encoding="utf-8",
            )
        else:
            raise ValueError(f"unsupported export format: {fmt}")
        paths[fmt] = str(path)
    return paths
