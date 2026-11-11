"""Normalisation du texte : accents, casse, ponctuation.

`normalize_with_map()` produit une chaine repliee ("reseau" pour "Reseau")
*et* une table de correspondance vers les index d'origine, ce qui permet de
reconstruire un extrait avec les accents et la casse reels du sous-titre.
"""

from __future__ import annotations

import re
import unicodedata

TOKEN_RE = re.compile(r"[0-9a-z]+")


def _fold_char(ch: str) -> str:
    """Replie un caractere : minuscule, decomposition NFD, sans diacritiques."""
    low = ch.lower()
    decomposed = unicodedata.normalize("NFD", low)
    kept = [c for c in decomposed if not unicodedata.combining(c)]
    out = "".join(kept)
    if not out:
        return ""
    if out.isalnum():
        return out
    return ""


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Retourne (texte normalise, index d'origine de chaque caractere)."""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        folded = _fold_char(ch)
        if folded:
            for c in folded:
                out.append(c)
                idx.append(i)
        else:
            # tout caractere non alphanumerique devient un separateur unique
            if not out or out[-1] != " ":
                out.append(" ")
                idx.append(i)
    return "".join(out), idx


def normalize(text: str) -> str:
    """Version courte : utile pour alimenter la colonne FTS et les requetes."""
    return normalize_with_map(text)[0]


def tokenize(text: str) -> list[str]:
    """Decoupe un texte deja normalise (ou non) en mots normalises."""
    return TOKEN_RE.findall(normalize(text))


def token_spans(norm: str) -> list[tuple[int, int, str]]:
    """Spans des mots d'un texte normalise : [(start, end, token), ...]."""
    return [(m.start(), m.end(), m.group()) for m in TOKEN_RE.finditer(norm)]
