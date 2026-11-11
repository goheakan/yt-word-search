"""Acces YouTube : tout passe par `yt-dlp` (binaire externe).

Choix assume : yt-dlp est la seule implementation qui survit aux changements
d'API de YouTube. On l'appelle en sous-processus, ce qui evite toute
dependance Python et isole les plantages.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .models import Caption

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

HANDLE_RE = re.compile(r"^@?[\w.\-]{3,}$")


class YtError(RuntimeError):
    """Erreur d'extraction, message destine a l'utilisateur."""


def binary() -> str:
    return os.environ.get("YTDLP", "yt-dlp")


def available() -> bool:
    return shutil.which(binary()) is not None


def version(timeout: int = 30) -> str | None:
    if not available():
        return None
    try:
        out = subprocess.run(
            [binary(), "--version"], capture_output=True, text=True, timeout=timeout
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [binary(), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except FileNotFoundError as exc:  # pragma: no cover - depend de la machine
        raise YtError("yt-dlp introuvable : installe-le (pacman -S yt-dlp)") from exc
    except subprocess.TimeoutExpired as exc:
        raise YtError(f"yt-dlp a depasse le delai de {timeout}s") from exc


def _last_error(proc: subprocess.CompletedProcess[str]) -> str:
    for line in reversed(proc.stderr.strip().splitlines()):
        line = line.strip()
        if line.startswith("ERROR:"):
            return line[6:].strip()
    tail = proc.stderr.strip().splitlines()
    return tail[-1].strip() if tail else "echec yt-dlp"


def _json(proc: subprocess.CompletedProcess[str]) -> dict:
    if proc.returncode != 0 or not proc.stdout.strip():
        raise YtError(_last_error(proc))
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - sortie inattendue
        raise YtError(f"reponse yt-dlp illisible ({exc})") from exc


def as_url(target: str) -> str:
    """Accepte @handle, UC..., une URL de chaine, de playlist ou de video."""
    target = target.strip()
    if target.startswith(("http://", "https://")):
        return target
    if target.startswith("UC") and len(target) == 24:
        return f"https://www.youtube.com/channel/{target}"
    if re.fullmatch(r"[\w-]{11}", target):
        return f"https://www.youtube.com/watch?v={target}"
    if target.startswith("@"):
        return f"https://www.youtube.com/{target}"
    return f"https://www.youtube.com/@{target}"


def _channel_url(url: str) -> str:
    base = url.rstrip("/")
    if base.endswith(("/videos", "/shorts", "/streams", "/playlists")):
        return base
    if "/watch" in base or "list=" in base or "/channel/" in base or "/c/" in base or "/user/" in base:
        return base
    return base + "/videos"


def list_videos(url: str, timeout: int) -> tuple[dict, list[dict]]:
    """Liste les videos d'une chaine/playlist. Retourne (entete, entrees)."""
    args = ["--flat-playlist", "-J", "--ignore-errors", "--no-warnings", _channel_url(url)]
    data = _json(_run(args, timeout))
    if data.get("_type") == "video":
        return data, [data]
    entries = data.get("entries") or []
    seen: set[str] = set()
    clean: list[dict] = []
    for entry in entries:
        if not entry:
            continue
        vid = entry.get("id")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        clean.append(entry)
    return data, clean


def probe(url: str, timeout: int) -> dict:
    """Metadonnees completes d'une video (sous-titres inclus)."""
    proc = _run(["-J", "--skip-download", "--no-warnings", url], timeout)
    return _json(proc)


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def timestamp_url(video_id: str, start_ms: int) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={max(0, start_ms // 1000)}s"


def _base_lang(lang: str) -> str:
    return lang.split("-")[0].lower()


def _find_lang(table: dict, langs: tuple[str, ...]) -> str | None:
    for lang in langs:
        if lang in table:
            return lang
        for key in table:
            if _base_lang(key) == _base_lang(lang):
                return key
    return None


def pick_caption(meta: dict, langs: tuple[str, ...]) -> Caption | None:
    """Choisit le meilleur sous-titre : manuel d'abord, puis automatique."""
    manual = meta.get("subtitles") or {}
    auto = meta.get("automatic_captions") or {}
    for table, is_auto in ((manual, False), (auto, True)):
        lang = _find_lang(table, langs)
        if not lang:
            continue
        entries = table.get(lang) or []
        if not entries:
            continue
        scored = sorted(
            entries,
            key=lambda e: (e.get("ext") != "vtt", e.get("ext") != "json3", e.get("ext") != "srv3"),
        )
        best = scored[0]
        raw_url = best.get("url")
        if not raw_url:
            continue
        return Caption(lang=lang, auto=is_auto, url=raw_url)
    return None


def fetch_vtt(url: str, timeout: int = 30) -> str:
    """Telecharge un sous-titre en WebVTT depuis l'URL timedtext."""
    if "fmt=" in url:
        target = re.sub(r"fmt=[^&]*", "fmt=vtt", url)
    else:
        target = url + ("&" if "?" in url else "?") + "fmt=vtt"
    req = urllib.request.Request(target, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise YtError(f"HTTP {exc.code} sur les sous-titres") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise YtError(f"reseau indisponible ({exc})") from exc
    text = raw.decode("utf-8", "replace").lstrip("\ufeff")
    if not text.lstrip().startswith("WEBVTT"):
        raise YtError("reponse timedtext inattendue (pas du WebVTT)")
    return text


def download_vtt(video_url: str, caption: Caption, timeout: int) -> str:
    """Repli : laisse yt-dlp telecharger et convertir le sous-titre en VTT."""
    with tempfile.TemporaryDirectory(prefix="yts-sub-") as tmp:
        args = [
            "--no-simulate",
            "--skip-download",
            "--no-warnings",
            "-q",
            "--write-auto-subs" if caption.auto else "--write-subs",
            "--sub-langs",
            caption.lang,
            "--sub-format",
            "vtt",
            "--convert-subs",
            "vtt",
            "-o",
            str(Path(tmp) / "%(id)s.%(ext)s"),
            video_url,
        ]
        proc = _run(args, timeout)
        files = sorted(Path(tmp).glob("*.vtt"))
        if not files:
            raise YtError(_last_error(proc) if proc.returncode else "aucun sous-titre ecrit")
        return files[0].read_text(encoding="utf-8", errors="replace")
