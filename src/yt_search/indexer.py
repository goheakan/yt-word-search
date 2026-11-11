"""Orchestration de l'indexation : listing, telechargement, parsing, ecriture.

Les appels reseau tournent dans un pool de threads ; les ecritures SQLite sont
faites uniquement dans le thread principal, une transaction par video.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from . import youtube
from .config import Config
from .models import Channel, FetchResult, Segment, Video
from .normalize import sanitize
from .store import Store
from .vtt import build_segments, parse_vtt


class Skip(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class Counters:
    ok: int = 0
    empty: int = 0
    error: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.ok + self.empty + self.error + self.skipped


def _log(message: str) -> None:
    print(sanitize(message), file=sys.stderr, flush=True)


def _iso_date(upload_date: str | None) -> str | None:
    if upload_date and len(upload_date) == 8 and upload_date.isdigit():
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return None


def fetch_video(url: str, cfg: Config) -> FetchResult:
    """Recupere les sous-titres d'une video et les decoupe en passages."""
    meta = youtube.probe(url, cfg.timeout, cfg.cookies_from_browser)
    vid = meta.get("id") or url.rstrip("/").rsplit("=", 1)[-1]
    title = meta.get("title") or vid

    status = meta.get("live_status") or ""
    if status in ("is_live", "is_upcoming"):
        raise Skip("direct / premiere en cours")
    if meta.get("availability") in ("private", "premium_only", "subscriber_only"):
        raise Skip(f"indisponible ({meta.get('availability')})")

    video = Video(
        id=vid,
        title=title,
        url=youtube.watch_url(vid),
        channel_id=meta.get("channel_id"),
        duration_s=meta.get("duration"),
        published_at=_iso_date(meta.get("upload_date")),
    )

    caption = youtube.pick_caption(meta, cfg.langs)
    if caption is None:
        return FetchResult(video=video, note="no-subs")

    try:
        raw = youtube.fetch_vtt(caption.url, timeout=min(30, cfg.timeout))
    except youtube.YtError:
        raw = youtube.download_vtt(url, caption, cfg.timeout, cfg.cookies_from_browser)

    cues = parse_vtt(raw)
    pieces = build_segments(
        cues,
        caption.auto,
        max_chars=cfg.max_chars,
        max_span_ms=cfg.max_span_ms,
        max_gap_ms=cfg.max_gap_ms,
    )
    segments = [Segment(start, end, text) for start, end, text in pieces]
    return FetchResult(video=video, segments=segments, lang=caption.lang, auto=caption.auto)


class Indexer:
    def __init__(self, store: Store, cfg: Config):
        self.store = store
        self.cfg = cfg

    # -- listing ----------------------------------------------------------
    def register(self, target: str) -> tuple[Channel | None, list[str]]:
        """Enregistre la chaine (ou la video) et retourne les IDs concernes."""
        url = youtube.as_url(target)
        head, entries = youtube.list_videos(url, self.cfg.timeout, self.cfg.cookies_from_browser)

        channel: Channel | None = None
        channel_id = head.get("channel_id")
        if not channel_id and str(head.get("id", "")).startswith("UC"):
            channel_id = head["id"]
        if head.get("_type") == "video":
            channel_id = head.get("channel_id") or channel_id

        if channel_id:
            channel = Channel(
                id=channel_id,
                title=head.get("channel") or head.get("uploader") or head.get("title") or channel_id,
                url=f"https://www.youtube.com/channel/{channel_id}",
                handle=head.get("uploader_id"),
            )
            self.store.upsert_channel(channel)

        ids: list[str] = []
        for entry in entries:
            vid = entry.get("id")
            if not vid:
                continue
            self.store.upsert_video(
                Video(
                    id=vid,
                    title=entry.get("title") or vid,
                    url=youtube.watch_url(vid),
                    channel_id=channel_id,
                    duration_s=entry.get("duration"),
                    published_at=_iso_date(entry.get("upload_date")),
                )
            )
            ids.append(vid)

        if not ids and head.get("_type") == "video" and head.get("id"):
            ids.append(head["id"])
        return channel, ids

    # -- indexation -------------------------------------------------------
    def run(
        self,
        target: str,
        *,
        limit: int | None = None,
        refresh: bool = False,
        retry_errors: bool = False,
    ) -> Counters:
        started = time.monotonic()
        channel, _ = self.register(target)
        channel_id = channel.id if channel else None

        cap = limit if limit is not None else 1_000_000
        rows = self.store.candidates(channel_id, cap, refresh, retry_errors)
        if not rows:
            _log("Rien a indexer : tout est deja a jour.")
            return Counters()

        _log(f"{len(rows)} video(s) a traiter" + (f" — {channel.title}" if channel else ""))

        workers = max(1, min(self.cfg.concurrency, len(rows)))
        counters = Counters()
        total = len(rows)
        futures = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for row in rows:
                futures[pool.submit(self._worker, row["url"])] = row
            try:
                for done, future in enumerate(as_completed(futures), 1):
                    row = futures[future]
                    vid = row["id"]
                    label = f"[{done:>4}/{total}]"
                    try:
                        result = future.result()
                    except Skip as exc:
                        self.store.set_status(vid, "skipped", exc.reason)
                        counters.skipped += 1
                        _log(f"{label} ignore  {vid}  {exc.reason}")
                        continue
                    except youtube.YtError as exc:
                        self.store.set_status(vid, "error", str(exc)[:400])
                        counters.error += 1
                        _log(f"{label} erreur  {vid}  {exc}")
                        continue
                    except Exception as exc:  # noqa: BLE001 - isolation par video
                        self.store.set_status(vid, "error", f"{type(exc).__name__}: {exc}"[:400])
                        counters.error += 1
                        _log(f"{label} erreur  {vid}  {type(exc).__name__}: {exc}")
                        continue

                    self._persist(result)
                    if result.note == "no-subs":
                        counters.empty += 1
                        _log(f"{label} vide    {vid}  aucun sous-titre ({','.join(self.cfg.langs)})")
                    elif not result.segments:
                        counters.empty += 1
                        _log(f"{label} vide    {vid}  sous-titre vide")
                    else:
                        counters.ok += 1
                        kind = "auto" if result.auto else "manuel"
                        _log(
                            f"{label} ok      {vid}  {kind}/{result.lang}  {len(result.segments)} passages"
                        )
            except KeyboardInterrupt:
                _log("\nInterruption : arret propre, l'index reste coherent.")
                for future in futures:
                    future.cancel()
                raise

        elapsed = time.monotonic() - started
        _log("")
        _log(
            f"Termine en {elapsed:.0f}s : {counters.ok} ok, {counters.empty} sans texte, "
            f"{counters.error} erreur(s), {counters.skipped} ignoree(s)"
        )
        return counters

    def _worker(self, url: str) -> FetchResult:
        try:
            return fetch_video(url, self.cfg)
        finally:
            if self.cfg.sleep_requests > 0:
                time.sleep(self.cfg.sleep_requests)

    def _persist(self, result: FetchResult) -> None:
        self.store.upsert_video(result.video)
        if result.note == "no-subs":
            self.store.replace_segments(
                result.video.id, [], status="empty", lang=None, source=None
            )
            return
        if not result.segments:
            self.store.replace_segments(
                result.video.id, [], status="empty", lang=result.lang, source=None
            )
            return
        source = "auto" if result.auto else "manual"
        self.store.replace_segments(
            result.video.id,
            result.segments,
            status="ok",
            lang=result.lang,
            source=source,
        )
