"""Output formats: plain terminal table, Markdown, CSV."""

from __future__ import annotations

import csv
import io
import shutil

from .timeline import Event

HEADERS = ["Date", "Type", "Code", "Description", "Value", "Flag"]


def _row(e: Event) -> list[str]:
    code = f"{e.code_system} {e.code}".strip()
    return [e.date_str, e.kind, code, e.display, e.value, e.flag]


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def to_table(events: list[Event]) -> str:
    rows = [HEADERS] + [_row(e) for e in events]
    widths = [min(max(len(r[i]) for r in rows), 48) for i in range(len(HEADERS))]
    # Shrink Description, then Value, so the table fits the terminal (with minimum widths).
    available = shutil.get_terminal_size((120, 24)).columns
    for col, floor in ((3, 20), (4, 12)):
        overflow = sum(widths) + 2 * (len(widths) - 1) - available
        if overflow <= 0:
            break
        widths[col] = max(floor, widths[col] - overflow)
    lines = []
    for n, r in enumerate(rows):
        lines.append("  ".join(_clip(c, widths[i]).ljust(widths[i]) for i, c in enumerate(r)).rstrip())
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def to_markdown(events: list[Event]) -> str:
    out = ["| " + " | ".join(HEADERS) + " |", "|" + "|".join(["---"] * len(HEADERS)) + "|"]
    for e in events:
        out.append("| " + " | ".join(c.replace("|", "\\|") for c in _row(e)) + " |")
    return "\n".join(out)


def to_csv(events: list[Event]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADERS)
    for e in events:
        w.writerow(_row(e))
    return buf.getvalue()


FORMATTERS = {"table": to_table, "markdown": to_markdown, "csv": to_csv}
