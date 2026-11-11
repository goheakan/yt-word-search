"""Construction des requetes FTS5 et mise en forme des extraits.

FTS5 indexe une version repliee du texte (``remove_diacritics 2``). Les
extraits sont reconstruits depuis le texte d'origine : accents, majuscules et
ponctuation sont donc preserves, et les correspondances encadrees par des
marqueurs invisibles (``\\x00`` / ``\\x01``) que l'affichage colore.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Passage, VideoHits
from .normalize import normalize_with_map, token_spans
from .store import Store

MARK_OPEN = "\x00"
MARK_CLOSE = "\x01"
ELLIPSIS = "…"

MODES = ("all", "any", "phrase", "near")


class QueryError(ValueError):
    """Requete invalide (aucun mot exploitable)."""


def build_match(tokens: list[str], mode: str, near: int = 5, prefix: bool = False) -> str:
    if not tokens:
        raise QueryError("aucun mot a rechercher")
    if mode not in MODES:
        raise QueryError(f"mode inconnu : {mode} (valeurs : {', '.join(MODES)})")

    def term(token: str) -> str:
        return f'"{token}"' + ("*" if prefix else "")

    quoted = [term(t) for t in tokens]
    if mode == "phrase":
        body = " ".join(tokens)
        return f'"{" ".join(quoted)}"' if prefix else f'"{body}"'
    if mode == "any":
        return " OR ".join(quoted)
    if mode == "near":
        return f"NEAR({' '.join(quoted)}, {max(1, near)})"
    return " AND ".join(quoted)


@dataclass(slots=True)
class Analysis:
    matches: int
    snippet: str


def _hits(norm: str, tokens: list[str], mode: str, near: int = 5) -> list[tuple[int, int]]:
    spans = token_spans(norm)
    wanted = set(tokens)
    if mode == "phrase":
        out = []
        for i in range(len(spans) - len(tokens) + 1):
            if all(spans[i + k][2] == tokens[k] for k in range(len(tokens))):
                out.append((spans[i][0], spans[i + len(tokens) - 1][1]))
        return out
    if mode == "near":
        out = []
        positions = [i for i, sp in enumerate(spans) if sp[2] in wanted]
        for a, b in zip(positions, positions[1:]):
            if spans[b][0] - spans[a][1] <= max(1, near) * 12:
                out.append((spans[a][0], spans[b][1]))
        if not out and positions:
            a = positions[0]
            out.append((spans[a][0], spans[a][1]))
        return out
    if mode == "any":
        return [(s, e) for s, e, t in spans if t in wanted]
    # mode "all" : on compte les occurrences du premier mot present
    primary = tokens[0]
    if not any(t == primary for _, _, t in spans):
        primary = next((t for _, _, t in spans if t in wanted), primary)
    return [(s, e) for s, e, t in spans if t == primary]


def analyse(text: str, tokens: list[str], mode: str, context: int = 90) -> Analysis:
    norm, idx = normalize_with_map(text)
    hits = _hits(norm, tokens, mode)
    if not hits:
        return Analysis(0, _plain(text, context))

    first_start, first_end = hits[0]
    # bornes en coordonnees d'origine
    orig_start = idx[first_start] if first_start < len(idx) else 0
    orig_end = idx[min(first_end, len(idx) - 1)] + 1
    lo = max(0, orig_start - context)
    hi = min(len(text), orig_end + context)
    # ne pas couper au milieu d'un mot
    while lo > 0 and not text[lo - 1].isspace() and not text[lo].isspace():
        lo -= 1
    while hi < len(text) and not text[hi].isspace() and not text[hi - 1].isspace():
        hi += 1

    pieces: list[str] = []
    cursor = lo
    for s, e in hits:
        if s < len(idx) and e - 1 < len(idx):
            a = idx[s]
            b = idx[e - 1] + 1
        else:  # pragma: no cover - garde-fou
            continue
        if b <= lo or a >= hi:
            continue
        a = max(a, lo)
        b = min(b, hi)
        if a > cursor:
            pieces.append(text[cursor:a])
        pieces.append(MARK_OPEN + text[a:b] + MARK_CLOSE)
        cursor = b
    pieces.append(text[cursor:hi])

    snippet = "".join(pieces).strip()
    if lo > 0:
        snippet = ELLIPSIS + snippet
    if hi < len(text):
        snippet = snippet + ELLIPSIS
    return Analysis(len(hits), snippet)

def _plain(text: str, context: int) -> str:
    text = text.strip()
    if len(text) <= context * 2:
        return text
    return text[: context * 2].rstrip() + ELLIPSIS


def search(
    store: Store,
    tokens: list[str],
    *,
    mode: str = "all",
    near: int = 5,
    prefix: bool = False,
    context: int = 90,
    per_video: int = 3,
    limit: int = 500,
    channel: str | None = None,
) -> list[VideoHits]:
    match = build_match(tokens, mode, near=near, prefix=prefix)
    rows = store.search(match, limit, channel=channel)
    grouped: dict[str, VideoHits] = {}
    order: list[str] = []
    for row in rows:
        vid = row["video_id"]
        if vid not in grouped:
            grouped[vid] = VideoHits(
                video_id=vid,
                title=row["title"],
                video_url=row["url"],
                channel=row["channel"],
                published_at=row["published_at"],
            )
            order.append(vid)
        group = grouped[vid]
        analysis = analyse(row["text"], tokens, mode, context=context)
        group.total_matches += analysis.matches
        if len(group.passages) >= per_video:
            continue
        group.passages.append(
            Passage(
                video_id=vid,
                title=row["title"],
                video_url=row["url"],
                channel=row["channel"],
                start_ms=row["start_ms"],
                text=row["text"],
                snippet=analysis.snippet,
                matches=analysis.matches,
                score=row["score"],
            )
        )
    groups = [grouped[vid] for vid in order]
    for group in groups:
        group.passages.sort(key=lambda p: p.start_ms)
    return groups
