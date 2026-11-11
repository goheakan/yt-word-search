"""Nom applicatif, chemins XDG et migration de l'ancien nommage."""

from __future__ import annotations

import pytest

from yt_search import config


def test_app_name_is_canonical() -> None:
    assert config.APP_NAME == "yt-word-search"
    assert config.LEGACY_APP_NAME == "yt-search"


def test_paths_use_app_name(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    assert config.default_db_path() == tmp_path / "data" / "yt-word-search" / "index.db"
    assert config.default_config_path() == tmp_path / "cfg" / "yt-word-search" / "config.toml"


def test_legacy_data_dir_is_migrated(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    data = tmp_path / "data"
    legacy = data / config.LEGACY_APP_NAME
    legacy.mkdir(parents=True)
    (legacy / "index.db").write_bytes(b"ancien index")

    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    path = config.default_db_path()

    assert path == data / config.APP_NAME / "index.db"
    assert path.read_bytes() == b"ancien index"
    assert not legacy.exists()


def test_existing_target_is_not_overwritten(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    data = tmp_path / "data"
    (data / config.APP_NAME).mkdir(parents=True)
    legacy = data / config.LEGACY_APP_NAME
    legacy.mkdir()

    monkeypatch.setenv("XDG_DATA_HOME", str(data))

    assert config.default_db_path() == data / config.APP_NAME / "index.db"
    assert legacy.exists(), "les deux dossiers coexistent : on ne touche a rien"
