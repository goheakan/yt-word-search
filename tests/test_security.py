"""Regressions de securite : injection terminal, formule CSV, droits, URL.

Chaque test correspond a un scenario d'attaque concret : titre de video ou
sous-titre piege, export ouvert dans un tableur, base lisible par les autres
comptes, URL de sous-titre pointee vers le reseau local.
"""

from __future__ import annotations

import pytest

from yt_search import youtube
from yt_search.models import Passage, VideoHits
from yt_search.normalize import sanitize
from yt_search.output import csv_safe, render_csv, render_table
from yt_search.search import MARK_CLOSE, MARK_OPEN
from yt_search.store import Store


def _group(title: str, snippet: str) -> VideoHits:
    group = VideoHits(
        video_id="pf5tXJZM1Rw",
        title=title,
        video_url="https://www.youtube.com/watch?v=pf5tXJZM1Rw",
        channel="chaine",
        published_at="2025-01-01",
    )
    group.passages.append(
        Passage(
            video_id=group.video_id,
            title=title,
            video_url=group.video_url,
            channel="chaine",
            start_ms=1500,
            text=snippet,
            snippet=snippet,
            matches=1,
            score=0.0,
        )
    )
    group.total_matches = 1
    return group


# -- injection de sequences de controle (CWE-150) ------------------------
def test_sanitize_retire_les_sequences_ansi_et_osc() -> None:
    hostile = "\x1b]0;titre pirate\x07\x1b[2Jkubernetes\x1b[31m"
    assert sanitize(hostile) == "]0;titre pirate[2Jkubernetes[31m"


def test_sanitize_ne_touche_pas_les_marqueurs_internes() -> None:
    assert sanitize(MARK_OPEN + "mot" + MARK_CLOSE) == MARK_OPEN + "mot" + MARK_CLOSE


def test_sanitize_aplatit_les_retours_a_la_ligne() -> None:
    assert sanitize("ligne1\nligne2\tfin") == "ligne1 ligne2 fin"


def test_table_ne_laisse_passer_aucun_echappement() -> None:
    group = _group("\x1b[2Jtitre\x1b]52;c;cGF5bG9hZA==\x07", "extrait \x1b[31mrouge\x1b[0m")
    out = render_table([group], ["rouge"], color=False)
    assert "\x1b" not in out
    assert "\x07" not in out
    assert "titre" in out


# -- injection de formule dans un tableur (CWE-1236) ---------------------
@pytest.mark.parametrize("payload", ["=1+1", "+1", "-1+1", "@SUM(A1)"])
def test_csv_safe_prefixe_les_formules(payload: str) -> None:
    assert csv_safe(payload) == "'" + payload


def test_csv_safe_laisse_le_texte_normal_intact() -> None:
    assert csv_safe("kubernetes") == "kubernetes"
    assert csv_safe(42) == 42


def test_csv_neutralise_un_titre_formule() -> None:
    out = render_csv([_group("=HYPERLINK(\"http://exemple\",\"clic\")", "texte")])
    ligne = out.splitlines()[1]
    assert "'=HYPERLINK" in ligne


# -- droits de la base (Privacy by Design) -------------------------------
def test_base_et_dossier_sont_prives(tmp_path) -> None:
    store = Store(tmp_path / "yt-word-search" / "index.db")
    try:
        folder, base = store.perms()
        assert folder == "700", "le dossier de l'index doit etre prive"
        assert base == "600", "la base doit etre lisible par le seul proprietaire"
    finally:
        store.close()


def test_droits_corriges_sur_un_dossier_existant(tmp_path) -> None:
    folder = tmp_path / "yt-word-search"
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)
    store = Store(folder / "index.db")
    try:
        assert store.perms() == ("700", "600")
    finally:
        store.close()


# -- validation des URL (injection d'argument, SSRF) ---------------------
@pytest.mark.parametrize(
    "url",
    ["-J", "--exec=rm -rf /", "file:///etc/passwd", "ftp://exemple.org/x", "", "http:///sans-hote"],
)
def test_safe_url_refuse_les_url_dangereuses(url: str) -> None:
    with pytest.raises(youtube.YtError):
        youtube.safe_url(url)


def test_safe_url_accepte_https() -> None:
    assert youtube.safe_url("https://www.youtube.com/watch?v=x") == "https://www.youtube.com/watch?v=x"


def test_caption_url_refuse_http_et_hotes_inconnus() -> None:
    with pytest.raises(youtube.YtError):
        youtube.caption_url("http://www.youtube.com/api/timedtext?fmt=vtt")
    with pytest.raises(youtube.YtError):
        youtube.caption_url("https://127.0.0.1/api/timedtext?fmt=vtt")
    with pytest.raises(youtube.YtError):
        youtube.caption_url("https://exemple.org/api/timedtext?fmt=vtt")


def test_caption_url_accepte_timedtext() -> None:
    url = "https://www.youtube.com/api/timedtext?v=abc&lang=fr"
    assert youtube.caption_url(url) == url


def test_fetch_vtt_borne_la_taille(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def read(self, size: int = -1) -> bytes:
            return self.payload[:size] if size >= 0 else self.payload

        def geturl(self) -> str:
            return "https://www.youtube.com/api/timedtext?v=abc&fmt=vtt"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=0):
        return FakeResponse(b"WEBVTT\n" + b"x" * (youtube.MAX_CAPTION_BYTES + 10))

    monkeypatch.setattr(youtube.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(youtube.YtError, match="volumineux"):
        youtube.fetch_vtt("https://www.youtube.com/api/timedtext?v=abc&lang=fr")


def test_fetch_vtt_refuse_une_redirection_hors_liste(monkeypatch) -> None:
    class FakeResponse:
        def read(self, size: int = -1) -> bytes:
            return b"WEBVTT\n"

        def geturl(self) -> str:
            return "http://192.168.1.1/secret"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(youtube.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    with pytest.raises(youtube.YtError):
        youtube.fetch_vtt("https://www.youtube.com/api/timedtext?v=abc&lang=fr")


# -- cookies et arguments passes a yt-dlp --------------------------------
def test_cookie_args_valides() -> None:
    assert youtube._cookie_args(None) == []
    assert youtube._cookie_args("firefox") == ["--cookies-from-browser", "firefox"]


def test_cookie_args_refuse_une_valeur_bizarre() -> None:
    with pytest.raises(youtube.YtError):
        youtube._cookie_args("firefox --exec rm")


def test_probe_transmet_cookies_et_separateur(monkeypatch) -> None:
    seen: dict[str, list[str]] = {}

    def fake_run(args: list[str], timeout: int):
        seen["args"] = args

        class P:
            returncode = 0
            stdout = '{"id": "x"}'
            stderr = ""

        return P()

    monkeypatch.setattr(youtube, "_run", fake_run)
    youtube.probe("https://www.youtube.com/watch?v=x", 10, "firefox")
    args = seen["args"]
    assert args[-2:] == ["--", "https://www.youtube.com/watch?v=x"]
    assert args[args.index("--cookies-from-browser") + 1] == "firefox"
