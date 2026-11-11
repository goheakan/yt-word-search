from yt_search.normalize import normalize, normalize_with_map, tokenize


def test_fold_accents_and_case():
    assert normalize("Réseau, Kubernetes !") == "reseau kubernetes "
    assert normalize("ÉTÉ") == "ete"
    assert normalize("über") == "uber"


def test_map_points_to_original_characters():
    text = "Été réseau"
    norm, idx = normalize_with_map(text)
    assert norm == "ete reseau"
    assert len(idx) == len(norm)
    first = idx[norm.index("reseau")]
    assert text[first] == "r"
    assert text[idx[norm.index("reseau") + 1]] == "é"


def test_tokenize():
    assert tokenize("Kubernetes, c'est génial !") == ["kubernetes", "c", "est", "genial"]
    assert tokenize("") == []
