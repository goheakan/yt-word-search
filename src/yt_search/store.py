"""Persistance SQLite + index plein texte FTS5.

Une transaction par video : une interruption (Ctrl-C, kill) laisse la base
coherente et l'indexation reprend exactement la ou elle s'est arretee.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .models import Channel, Segment, Video
from .normalize import normalize

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id           TEXT PRIMARY KEY,
    handle       TEXT,
    title        TEXT,
    url          TEXT,
    last_sync_at TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    id         TEXT PRIMARY KEY,
    channel_id TEXT REFERENCES channels(id) ON DELETE SET NULL,
    title      TEXT NOT NULL,
    duration_s INTEGER,
    published_at TEXT,
    url        TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    lang       TEXT,
    source     TEXT,
    segments   INTEGER NOT NULL DEFAULT 0,
    error      TEXT,
    retries    INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_status  ON videos(status);

CREATE TABLE IF NOT EXISTS segments (
    id        INTEGER PRIMARY KEY,
    video_id  TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    start_ms  INTEGER NOT NULL,
    end_ms    INTEGER,
    text      TEXT NOT NULL,
    text_norm TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_segments_video ON segments(video_id);

CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text_norm,
    content='segments',
    content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);

CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text_norm) VALUES (new.id, new.text_norm);
END;

CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text_norm)
        VALUES ('delete', old.id, old.text_norm);
END;

CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text_norm)
        VALUES ('delete', old.id, old.text_norm);
    INSERT INTO segments_fts(rowid, text_norm) VALUES (new.id, new.text_norm);
END;
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    # -- infrastructure ---------------------------------------------------
    def _migrate(self) -> None:
        self.conn.executescript(SCHEMA)
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if current < SCHEMA_VERSION:
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        # index FTS eventuellement vide alors que des segments existent
        segs = self.conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        if segs:
            fts = self.conn.execute("SELECT COUNT(*) FROM segments_fts").fetchone()[0]
            if not fts:
                self.conn.execute("INSERT INTO segments_fts(segments_fts) VALUES('rebuild')")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

    def integrity(self) -> str:
        return str(self.conn.execute("PRAGMA quick_check").fetchone()[0])

    def fts_integrity(self) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO segments_fts(segments_fts) VALUES('integrity-check')"
            )
            return True
        except sqlite3.DatabaseError:
            return False

    # -- ecriture ---------------------------------------------------------
    def upsert_channel(self, channel: Channel) -> None:
        self.conn.execute(
            """INSERT INTO channels(id, handle, title, url, last_sync_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   handle=excluded.handle,
                   title=excluded.title,
                   url=excluded.url,
                   last_sync_at=excluded.last_sync_at""",
            (channel.id, channel.handle, channel.title, channel.url, now_iso()),
        )

    def upsert_video(self, video: Video) -> None:
        self.conn.execute(
            """INSERT INTO videos(id, channel_id, title, duration_s, published_at, url, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   channel_id=excluded.channel_id,
                   title=excluded.title,
                   duration_s=COALESCE(excluded.duration_s, videos.duration_s),
                   published_at=COALESCE(excluded.published_at, videos.published_at),
                   url=excluded.url""",
            (
                video.id,
                video.channel_id,
                video.title,
                video.duration_s,
                video.published_at,
                video.url,
                video.status,
            ),
        )

    def status_of(self, video_id: str) -> str | None:
        row = self.conn.execute("SELECT status FROM videos WHERE id=?", (video_id,)).fetchone()
        return row["status"] if row else None

    def replace_segments(
        self,
        video_id: str,
        segments: Sequence[Segment],
        *,
        status: str,
        lang: str | None,
        source: str | None,
        error: str | None = None,
    ) -> None:
        rows = [(video_id, s.start_ms, s.end_ms, s.text, normalize(s.text)) for s in segments]
        with self.tx() as conn:
            conn.execute("DELETE FROM segments WHERE video_id=?", (video_id,))
            conn.executemany(
                "INSERT INTO segments(video_id, start_ms, end_ms, text, text_norm) VALUES (?,?,?,?,?)",
                rows,
            )
            conn.execute(
                """UPDATE videos SET status=?, lang=?, source=?, error=?, segments=?,
                          fetched_at=?, retries=0
                   WHERE id=?""",
                (status, lang, source, error, len(rows), now_iso(), video_id),
            )

    def set_status(self, video_id: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            """UPDATE videos SET status=?, error=?, retries=retries+1, fetched_at=?
               WHERE id=?""",
            (status, error, now_iso(), video_id),
        )

    # -- lecture ----------------------------------------------------------
    def known_ids(self) -> set[str]:
        return {r["id"] for r in self.conn.execute("SELECT id FROM videos")}

    def candidates(self, channel_id: str | None, limit: int, refresh: bool, retry_errors: bool) -> list[sqlite3.Row]:
        sql = "SELECT * FROM videos WHERE 1=1"
        params: list[object] = []
        if channel_id:
            sql += " AND channel_id=?"
            params.append(channel_id)
        if refresh:
            pass
        elif retry_errors:
            sql += " AND status IN ('error','empty','pending')"
        else:
            sql += " AND status='pending'"
        sql += " ORDER BY (published_at IS NULL), published_at DESC, rowid ASC LIMIT ?"
        params.append(limit)
        return list(self.conn.execute(sql, params))

    def search(self, match: str, limit: int, channel: str | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT s.id AS sid, s.video_id, s.start_ms, s.end_ms, s.text, s.text_norm,
                   v.title, v.url, v.published_at,
                   c.title AS channel,
                   bm25(segments_fts) AS score
            FROM segments_fts
            JOIN segments s ON s.id = segments_fts.rowid
            JOIN videos v   ON v.id = s.video_id
            LEFT JOIN channels c ON c.id = v.channel_id
            WHERE segments_fts MATCH ?
        """
        params: list[object] = [match]
        if channel:
            sql += " AND (v.channel_id = ? OR c.handle = ?)"
            params.extend([channel, channel])
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)
        return list(self.conn.execute(sql, params))

    def export_rows(self) -> Iterable[sqlite3.Row]:
        return self.conn.execute(
            """SELECT v.id, v.title, v.url, v.published_at, v.source, v.lang,
                      s.start_ms, s.text
               FROM videos v JOIN segments s ON s.video_id = v.id
               WHERE v.status='ok'
               ORDER BY v.published_at DESC, s.start_ms"""
        )

    def stats(self) -> dict[str, object]:
        by_status = {
            r["status"]: r["n"]
            for r in self.conn.execute("SELECT status, COUNT(*) AS n FROM videos GROUP BY status")
        }
        segments = self.conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        videos = self.conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        channels = self.conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        words = self.conn.execute(
            "SELECT COALESCE(SUM(LENGTH(text)), 0) FROM segments"
        ).fetchone()[0]
        size = self.path.stat().st_size if self.path.exists() else 0
        return {
            "videos": videos,
            "channels": channels,
            "segments": segments,
            "chars": words,
            "db_bytes": size,
            "by_status": by_status,
        }

    def errors(self, limit: int = 10) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT id, title, error, fetched_at FROM videos
                   WHERE status='error' ORDER BY fetched_at DESC LIMIT ?""",
                (limit,),
            )
        )

    def pending_count(self, channel_id: str | None = None) -> int:
        if channel_id:
            return self.conn.execute(
                "SELECT COUNT(*) FROM videos WHERE status='pending' AND channel_id=?",
                (channel_id,),
            ).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM videos WHERE status='pending'").fetchone()[0]
