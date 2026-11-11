"""Configuration : fichier TOML + surcharges CLI/environnement."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


APP_NAME = "yt-word-search"
"""Nom applicatif : dossiers XDG, paquets, releases."""

LEGACY_APP_NAME = "yt-search"
"""Ancien nom, migre automatiquement au premier lancement."""


def _xdg(name: str, default: str) -> Path:
    base = os.environ.get(name) or default
    return Path(base).expanduser()


def _app_dir(env_name: str, default: str) -> Path:
    """Dossier applicatif, en migrant l'ancien nommage s'il est encore seul."""
    base = _xdg(env_name, default)
    target = base / APP_NAME
    legacy = base / LEGACY_APP_NAME
    if not target.exists() and legacy.is_dir():
        try:
            legacy.rename(target)
        except OSError:
            # disque en lecture seule, permissions : on continue sur l'ancien chemin
            return legacy
    return target


def default_config_path() -> Path:
    return _app_dir("XDG_CONFIG_HOME", "~/.config") / "config.toml"


def default_db_path() -> Path:
    return _app_dir("XDG_DATA_HOME", "~/.local/share") / "index.db"


@dataclass(slots=True)
class Config:
    db: Path = None  # type: ignore[assignment]
    langs: tuple[str, ...] = ("fr", "en")
    concurrency: int = 2
    sleep_requests: float = 0.7
    retries: int = 3
    timeout: int = 120
    cookies_from_browser: str | None = None
    # segmentation
    max_chars: int = 160
    max_span_ms: int = 30_000
    max_gap_ms: int = 1_500
    # recherche
    context: int = 90
    per_video: int = 3
    asr: bool = False
    color: bool = True

    def __post_init__(self) -> None:
        if self.db is None:
            self.db = default_db_path()

    @property
    def db_path(self) -> Path:
        return Path(self.db).expanduser()


_ALIASES = {"language": "langs", "jobs": "concurrency", "workers": "concurrency"}


def load_config(path: Path | None = None, overrides: dict[str, object] | None = None) -> Config:
    """Charge le TOML puis applique les surcharges non nulles."""
    cfg = Config()
    path = path or default_config_path()
    if path.is_file():
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        known = {f.name for f in fields(Config)}
        clean: dict[str, object] = {}
        for key, value in data.items():
            key = _ALIASES.get(key, key)
            if key in known and value is not None:
                clean[key] = value
        if "langs" in clean:
            val = clean["langs"]
            clean["langs"] = tuple(val.split(",")) if isinstance(val, str) else tuple(val)  # type: ignore[union-attr]
        cfg = Config(**{**{f.name: getattr(cfg, f.name) for f in fields(Config)}, **clean})  # type: ignore[arg-type]
        if isinstance(cfg.db, str):
            cfg.db = Path(cfg.db).expanduser()  # type: ignore[assignment]
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                setattr(cfg, key, value)
    if isinstance(cfg.db, str):
        cfg.db = Path(cfg.db).expanduser()  # type: ignore[assignment]
    return cfg
