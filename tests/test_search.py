import pytest

from yt_search.models import Channel, Segment, Video
from yt_search.search import MARK_CLOSE, MARK_OPEN, QueryError, build_match, search
from yt_search.store import Store

VID = "aaaaaaaaaaa"


@pytest.fixture()
def store(tmp_path):
    st = Store(tmp_path / "index.db")
    st.upsert_channel(Channel(id="UC123", title="Test Channel", url="https://youtube.com/@test"))
    st.upsert_video(
        Video(id=VID, title="Reseau et Kubernetes", url="https://youtu.be/aaaaaaaaaaa", channel_id="UC123", published_at="2024-05-01")
    )
    st.replace_segments(
        VID,
        [
            Segment(12_000, 18_000, "Le réseau Kubernetes est un orchestre de conteneurs"),
            Segment(30_000, 34_000, "un reseau prive pour les pods"),
        ],
        status="ok",
        lang="fr",
        source="manual",
    )
    yield st
    st.close()


def test_build_match_modes():
    assert build_match(["a", "b"], "all") == '"a" AND "b"'
    assert build_match(["a", "b"], "any") == '"a" OR "b"'
    assert build_match(["a", "b"], "phrase") == '"a b"'
    assert build_match(["a", "b"], "near", near=3) == 'NEAR("a" "b", 3)'
    assert build_match(["a"], "all", prefix=True) == '"a"*'


def test_empty_query_rejected():
    with pytest.raises(QueryError):
        build_match([], "all")


def test_accent_insensitive_search(store):
    hits = search(store, ["reseau"])
    assert len(hits) == 1
    assert hits[0].video_id == VID
    assert hits[0].matches == 2  # « réseau » et « reseau »
    snippet = " ".join(p.snippet.replace(MARK_OPEN, "").replace(MARK_CLOSE, "") for p in hits[0].passages)
    assert "réseau" in snippet  # l'accent d'origine est preserve


def test_snippet_marks_the_match(store):
    hits = search(store, ["kubernetes"])
    snippet = hits[0].passages[0].snippet
    assert MARK_OPEN in snippet and MARK_CLOSE in snippet
    inner = snippet.split(MARK_OPEN)[1].split(MARK_CLOSE)[0]
    assert inner.lower() == "kubernetes"


def test_phrase_mode(store):
    assert search(store, ["reseau", "kubernetes"], mode="phrase")
    assert not search(store, ["kubernetes", "reseau"], mode="phrase")


def test_all_mode_requires_every_word(store):
    # « réseau » et « orchestre » sont dans le meme passage : ca matche
    assert search(store, ["reseau", "orchestre"], mode="all")
    # « pods » et « orchestre » sont dans des passages differents : non
    assert search(store, ["pods", "orchestre"], mode="all") == []


def test_any_mode(store):
    hits = search(store, ["pods", "orchestre"], mode="any")
    assert len(hits) == 1
    assert hits[0].matches == 2


def test_limit_per_video(store):
    hits = search(store, ["reseau"], per_video=1)
    assert len(hits[0].passages) == 1
    assert hits[0].matches == 2


def test_unknown_word_returns_nothing(store):
    assert search(store, ["zzz"]) == []


def test_channel_filter(store):
    assert search(store, ["reseau"], channel="UC123")
    assert search(store, ["reseau"], channel="UC999") == []
