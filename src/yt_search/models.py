"""Modeles de donnees partages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Channel:
    id: str
    title: str
    url: str
    handle: str | None = None


@dataclass(slots=True)
class Video:
    id: str
    title: str
    url: str
    channel_id: str | None = None
    duration_s: int | None = None
    published_at: str | None = None
    status: str = "pending"
    lang: str | None = None
    source: str | None = None
    error: str | None = None


@dataclass(slots=True)
class Segment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(slots=True)
class Caption:
    lang: str
    auto: bool
    url: str


@dataclass(slots=True)
class FetchResult:
    video: Video
    segments: list[Segment] = field(default_factory=list)
    lang: str | None = None
    auto: bool = False
    note: str | None = None


@dataclass(slots=True)
class Passage:
    """Un passage (segment) correspondant a la recherche."""

    video_id: str
    title: str
    video_url: str
    channel: str | None
    start_ms: int
    text: str
    snippet: str
    matches: int
    score: float


@dataclass(slots=True)
class VideoHits:
    video_id: str
    title: str
    video_url: str
    channel: str | None
    published_at: str | None
    passages: list[Passage] = field(default_factory=list)
    total_matches: int = 0

    @property
    def matches(self) -> int:
        if self.total_matches:
            return self.total_matches
        return sum(p.matches for p in self.passages)
