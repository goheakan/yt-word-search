"""Rendu des resultats : table lisible, JSONL, CSV."""

from __future__ import annotations

import csv
import io
import json
import sys
from typing import Iterable, Sequence

from .models import VideoHits
from .normalize import sanitize
from .search import MARK_CLOSE, MARK_OPEN
from .youtube import timestamp_url

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
MATCH = "\x1b[1;33m"

#: Un tableur interprete ces prefixes comme une formule : un titre de video
#: pourrait donc executer du code a l'ouverture du CSV.
_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> object:
    """Neutralise l'injection de formule dans un export CSV/tableur."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIX):
        return "'" + value
    return value


def clock(ms: int) -> str:
    total = max(0, ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _marks(text: str, color: bool) -> str:
    if not color:
        return text.replace(MARK_OPEN, "[").replace(MARK_CLOSE, "]")
    return text.replace(MARK_OPEN, MATCH).replace(MARK_CLOSE, RESET)


def _short(text: str, limit: int = 100) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rstrip() + "…"
    # ne pas laisser un marqueur de surlignage ouvert
    if cut.count(MARK_OPEN) > cut.count(MARK_CLOSE):
        cut = cut[: cut.rfind(MARK_OPEN)]
    return cut


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("s" if n > 1 else "")


def render_table(groups: Sequence[VideoHits], tokens: Sequence[str], *, color: bool = True) -> str:
    total_passages = sum(len(g.passages) for g in groups)
    total_matches = sum(g.matches for g in groups)
    word = sanitize(" ".join(tokens))
    out: list[str] = []

    header = (
        f"{word} — {_plural(total_matches, 'occurrence')} dans "
        f"{_plural(total_passages, 'passage')} ({_plural(len(groups), 'vidéo')})"
    )
    out.append(header)
    out.append("")

    for group in groups:
        title = _short(sanitize(group.title), 90)
        meta = ", ".join(sanitize(x) for x in (group.channel, group.published_at) if x)
        if color:
            out.append(f"{BOLD}{title}{RESET}" + (f"  {DIM}({meta}){RESET}" if meta else ""))
        else:
            out.append(title + (f"  ({meta})" if meta else ""))
        for passage in group.passages:
            snippet = _marks(_short(sanitize(passage.snippet), 240), color)
            stamp = clock(passage.start_ms)
            url = timestamp_url(passage.video_id, passage.start_ms)
            if color:
                out.append(f"  {DIM}{stamp}{RESET}  {snippet}")
                out.append(f"  {DIM}      {url}{RESET}")
            else:
                out.append(f"  {stamp}  {snippet}")
                out.append(f"        {url}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_jsonl(groups: Iterable[VideoHits]) -> str:
    buf: list[str] = []
    for group in groups:
        for passage in group.passages:
            buf.append(
                json.dumps(
                    {
                        "video_id": passage.video_id,
                        "title": passage.title,
                        "channel": passage.channel,
                        "published_at": group.published_at,
                        "start_ms": passage.start_ms,
                        "timestamp": clock(passage.start_ms),
                        "url": timestamp_url(passage.video_id, passage.start_ms),
                        "matches": passage.matches,
                        "snippet": passage.snippet.replace(MARK_OPEN, "").replace(MARK_CLOSE, ""),
                        "text": passage.text,
                    },
                    ensure_ascii=False,
                )
            )
    return "\n".join(buf) + ("\n" if buf else "")


def render_csv(groups: Iterable[VideoHits]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "video_id",
            "title",
            "channel",
            "published_at",
            "timestamp",
            "start_ms",
            "url",
            "matches",
            "snippet",
        ]
    )
    for group in groups:
        for passage in group.passages:
            writer.writerow(
                [
                    csv_safe(passage.video_id),
                    csv_safe(sanitize(passage.title)),
                    csv_safe(sanitize(passage.channel or "")),
                    csv_safe(group.published_at or ""),
                    clock(passage.start_ms),
                    passage.start_ms,
                    timestamp_url(passage.video_id, passage.start_ms),
                    passage.matches,
                    csv_safe(sanitize(passage.snippet.replace(MARK_OPEN, "").replace(MARK_CLOSE, ""))),
                ]
            )
    return out.getvalue()


def supports_color(stream=None) -> bool:
    stream = stream or sys.stdout
    return hasattr(stream, "isatty") and stream.isatty()
