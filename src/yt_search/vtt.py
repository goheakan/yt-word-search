"""Analyse des sous-titres WebVTT de YouTube.

Deux formats doivent etre geres :

* **sous-titres manuels** : cues classiques, texte complet ;
* **sous-titres automatiques** : chaque cue repete la ligne precedente puis
  ajoute les nouveaux mots avec des horodatages en ligne
  (``a<00:00:02.200><c> terrifying</c> ...``). Seule la derniere ligne est du
  texte nouveau ; les cues « filler » de 10 ms ne contiennent rien de neuf.

Les cues sont ensuite fusionnes en segments de lecture (~160 caracteres) pour
que les extraits de recherche soient comprehensibles et que l'index reste
compact.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from .normalize import normalize

TS_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
TAG_RE = re.compile(r"<[^>]*>")
WS_RE = re.compile(r"\s+")


@dataclass(slots=True)
class Cue:
    start_ms: int
    end_ms: int
    lines: list[str]


def _to_ms(match: re.Match[str]) -> int:
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    frac = match.group(4)
    millis = int(frac.ljust(3, "0")[:3])
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_timestamp(raw: str) -> int | None:
    m = TS_RE.search(raw)
    return _to_ms(m) if m else None


def clean_line(line: str) -> str:
    """Retire les balises (<c>, <00:00:02.200>, <v Mike>) et les entites."""
    # les horodatages inline ne sont pas des entites html : on les traite avant
    line = TAG_RE.sub("", line)
    line = html.unescape(line)
    line = line.replace("\u200b", "").replace("\ufeff", "")
    return WS_RE.sub(" ", line).strip()


def parse_vtt(raw: str) -> list[Cue]:
    """Decoupe un fichier VTT en cues (texte brut, balises retirees)."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    block: list[str] = []

    def flush() -> None:
        if not block:
            return
        times = [i for i, ln in enumerate(block) if "-->" in ln]
        if not times:
            block.clear()
            return
        i = times[0]
        parts = block[i].split("-->")
        if len(parts) != 2:
            block.clear()
            return
        start = parse_timestamp(parts[0])
        end = parse_timestamp(parts[1])
        if start is None:
            block.clear()
            return
        lines = block[i + 1 :]
        cues.append(Cue(start, end if end is not None else start, lines))
        block.clear()

    for line in raw.split("\n"):
        if not line.strip():
            if block and "-->" in block[-1]:
                # YouTube place une ligne « vide » (une espace) entre
                # l'horodatage et le texte de la premiere ligne : ce n'est pas
                # un separateur de cue.
                block.append(line)
            else:
                flush()
        else:
            block.append(line)
    flush()
    return cues


def cues_to_lines(cues: list[Cue], auto: bool) -> list[tuple[int, int, str]]:
    """Extrait le texte utile de chaque cue : [(start_ms, end_ms, texte)]."""
    out: list[tuple[int, int, str]] = []
    for cue in cues:
        lines = cue.lines
        if not lines:
            continue
        if auto:
            # ligne 0 = texte deja affiche ; derniere ligne = mots nouveaux.
            # Un cue "filler" repete la meme ligne (ou n'ajoute qu'une espace).
            first = clean_line(lines[0])
            last = clean_line(lines[-1])
            text = last if last and last != first else ""
        else:
            text = " ".join(clean_line(ln) for ln in lines)
            text = WS_RE.sub(" ", text).strip()
        if text:
            out.append((cue.start_ms, cue.end_ms, text))
    return out


def build_segments(
    cues: list[Cue],
    auto: bool,
    *,
    max_chars: int = 160,
    max_span_ms: int = 30_000,
    max_gap_ms: int = 1_500,
) -> list[tuple[int, int, str]]:
    """Fusionne les cues en passages de lecture. Retourne [(start, end, texte)]."""
    pieces = cues_to_lines(cues, auto)
    segments: list[tuple[int, int, str]] = []

    cur_start = 0
    cur_end = 0
    cur: list[str] = []
    cur_len = 0
    prev_end = None

    def flush() -> None:
        nonlocal cur, cur_len, cur_start, cur_end, prev_end
        if cur:
            text = WS_RE.sub(" ", " ".join(cur)).strip()
            if text:
                segments.append((cur_start, cur_end, text))
        cur = []
        cur_len = 0
        prev_end = None

    for start, end, text in pieces:
        if cur and prev_end is not None:
            gap = start - prev_end
            too_long = cur_len + len(text) + 1 > max_chars
            too_wide = end - cur_start > max_span_ms
            if gap > max_gap_ms or too_long or too_wide:
                flush()
        if not cur:
            cur_start = start
        # deduplication des repetitions du direct (sous-titres auto)
        joined = " ".join(cur[-2:])
        if text and normalize(text) and normalize(text) in normalize(joined) and len(text) < len(joined):
            prev_end = end
            cur_end = end
            continue
        cur.append(text)
        cur_len += len(text) + 1
        cur_end = end
        prev_end = end

    flush()
    return segments
