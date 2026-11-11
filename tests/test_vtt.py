from pathlib import Path

from yt_search.vtt import build_segments, clean_line, parse_timestamp, parse_vtt

FIXTURE = Path(__file__).parent / "fixtures" / "sample_auto.vtt"


def test_parse_timestamp():
    assert parse_timestamp("00:00:02.090") == 2090
    assert parse_timestamp("01:02:03.500") == 3_723_500
    assert parse_timestamp("00:02.100") == 2100
    assert parse_timestamp("n'importe quoi") is None


def test_clean_line_strips_inline_tags():
    raw = "a<00:00:02.200><c> terrifying</c><00:00:02.900><c> unreleased</c>"
    assert clean_line(raw) == "a terrifying unreleased"
    assert clean_line("&amp; voilà&nbsp;!") == "& voilà !"
    assert clean_line("<v Mike>salut</v>") == "salut"


def test_parse_real_auto_captions():
    cues = parse_vtt(FIXTURE.read_text(encoding="utf-8"))
    assert len(cues) > 100
    assert cues[0].start_ms == 0
    assert cues[-1].end_ms > cues[0].start_ms


def test_auto_segments_have_no_duplicates():
    segments = build_segments(parse_vtt(FIXTURE.read_text(encoding="utf-8")), auto=True)
    text = " ".join(t for _, _, t in segments)
    assert "kernel" in text
    assert "Anthropic" in text
    # la phrase d'ouverture ne doit apparaitre qu'une fois malgre les cues repetes
    assert text.count("At the end of October") == 1
    starts = [s for s, _, _ in segments]
    assert starts == sorted(starts)
    assert all(t.strip() for _, _, t in segments)
    assert all(len(t) <= 250 for _, _, t in segments)


def test_manual_captions_keep_all_lines():
    raw = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "Bonjour a tous\n\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "et bienvenue dans\n"
        "cette video\n"
    )
    segments = build_segments(parse_vtt(raw), auto=False, max_chars=40)
    joined = " ".join(t for _, _, t in segments)
    assert joined == "Bonjour a tous et bienvenue dans cette video"
    assert len(segments) == 2


def test_segments_start_at_first_cue():
    raw = (
        "WEBVTT\n\n"
        "00:00:10.000 --> 00:00:12.000\n"
        "premier\n\n"
        "00:00:12.000 --> 00:00:14.000\n"
        "second\n"
    )
    segments = build_segments(parse_vtt(raw), auto=False)
    assert segments == [(10_000, 14_000, "premier second")]
