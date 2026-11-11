"""Interface en ligne de commande."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, youtube
from .config import Config, default_config_path, load_config
from .indexer import Indexer
from .normalize import tokenize
from .output import render_csv, render_jsonl, render_table, supports_color
from .search import MODES, QueryError, search as run_search
from .store import Store

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_EMPTY = 3


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--db", type=Path, help="chemin de la base SQLite")
    p.add_argument("--config", type=Path, dest="config_path", help="fichier TOML")
    p.add_argument("--no-color", action="store_true", help="desactive les couleurs")
    p.add_argument("-q", "--quiet", action="store_true", help="moins de messages")
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yts",
        description="Recherche de mots dans les sous-titres d'une chaine YouTube.",
        epilog="Exemples : yts index @Fireship --limit 20 ; yts search kubernetes",
    )
    parser.add_argument("--version", action="version", version=f"yts {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    common = _common()

    idx = sub.add_parser("index", parents=[common], help="indexer une chaine ou une video")
    idx.add_argument("target", nargs="?", help="chaine (@handle, URL), playlist ou video")
    idx.add_argument("--channel", help="alias de la cible : URL de chaine")
    idx.add_argument("--video", help="indexer une seule video")
    idx.add_argument("--limit", type=int, help="nombre maximum de videos a traiter")
    idx.add_argument("--langs", help="langues preferees, ex. fr,en")
    idx.add_argument("--refresh", action="store_true", help="reindexer meme les videos deja faites")
    idx.add_argument("--retry-errors", action="store_true", help="reessayer erreurs et videos vides")
    idx.add_argument("--asr", action="store_true", help="transcription locale (jalon M4, non implemente)")
    idx.add_argument("--jobs", type=int, help="telechargements paralleles (defaut 2)")
    idx.add_argument("--sleep", type=float, dest="sleep_requests", help="pause entre requetes (s)")
    idx.add_argument("--cookies-from-browser", help="navigateur pour les cookies (firefox, chrome...)")
    idx.add_argument("--timeout", type=int, help="delai maximal par requete (s)")

    sch = sub.add_parser("search", parents=[common], help="chercher dans l'index")
    sch.add_argument("words", nargs="+", help="un ou plusieurs mots")
    sch.add_argument("-m", "--mode", choices=MODES, default="all", help="all (defaut), any, phrase, near")
    sch.add_argument("--near", type=int, default=5, help="distance en mots pour le mode near")
    sch.add_argument("--prefix", action="store_true", help="prefixes (kuber* trouve kubernetes)")
    sch.add_argument("--word", action="store_true", help="mot entier (comportement par defaut)")
    sch.add_argument("--json", action="store_true", help="sortie JSONL")
    sch.add_argument("--csv", action="store_true", help="sortie CSV")
    sch.add_argument("--count", action="store_true", help="compte par video, sans extraits")
    sch.add_argument("--limit", type=int, default=500, help="passages analyses au maximum")
    sch.add_argument("--per-video", type=int, default=3, help="extraits affiches par video")
    sch.add_argument("--context", type=int, default=90, help="caracteres de contexte")
    sch.add_argument("--channel", help="restreindre a un channel_id ou handle")

    sub.add_parser("status", parents=[common], help="etat de l'index")

    exp = sub.add_parser("export", parents=[common], help="exporter tout le corpus indexe")
    exp.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")

    doc = sub.add_parser("doctor", parents=[common], help="diagnostic de l'installation")
    doc.add_argument("--network", action="store_true", help="teste aussi l'acces a YouTube")

    return parser


def _config(args: argparse.Namespace) -> Config:
    overrides: dict[str, object] = {}
    for key in (
        "db",
        "langs",
        "concurrency",
        "sleep_requests",
        "cookies_from_browser",
        "timeout",
        "context",
        "per_video",
        "asr",
    ):
        if hasattr(args, key):
            overrides[key] = getattr(args, key)
    overrides["concurrency"] = getattr(args, "jobs", None)
    if getattr(args, "no_color", False):
        overrides["color"] = False
    langs = getattr(args, "langs", None)
    if isinstance(langs, str):
        overrides["langs"] = tuple(x.strip() for x in langs.split(",") if x.strip())
    return load_config(getattr(args, "config_path", None), overrides)


def _cmd_index(args: argparse.Namespace, cfg: Config) -> int:
    target = args.video or args.channel or args.target
    if not target:
        print("yts index : cible manquante (chaine, playlist ou --video)", file=sys.stderr)
        return EXIT_USAGE
    if cfg.asr:
        print(
            "note : --asr n'est pas encore implemente (jalon M4) ; seuls les sous-titres sont utilises.",
            file=sys.stderr,
        )
    store = Store(cfg.db_path)
    try:
        Indexer(store, cfg).run(
            target,
            limit=args.limit,
            refresh=args.refresh,
            retry_errors=args.retry_errors,
        )
    finally:
        store.close()
    return EXIT_OK


def _cmd_search(args: argparse.Namespace, cfg: Config) -> int:
    tokens = tokenize(" ".join(args.words))
    if not tokens:
        print("yts search : aucun mot exploitable", file=sys.stderr)
        return EXIT_USAGE
    store = Store(cfg.db_path)
    try:
        try:
            groups = run_search(
                store,
                tokens,
                mode=args.mode,
                near=args.near,
                prefix=args.prefix,
                context=args.context or cfg.context,
                per_video=args.per_video,
                limit=args.limit,
                channel=args.channel,
            )
        except QueryError as exc:
            print(f"yts search : {exc}", file=sys.stderr)
            return EXIT_USAGE
        if not groups:
            print(f"aucun resultat pour « {' '.join(tokens)} »", file=sys.stderr)
            return EXIT_EMPTY
        if args.json:
            sys.stdout.write(render_jsonl(groups))
        elif args.csv:
            sys.stdout.write(render_csv(groups))
        elif args.count:
            world = " ".join(tokens)
            total = sum(g.matches for g in groups)
            print(f"{world} — {total} occurrence" + ("s" if total > 1 else ""))
            print("")
            for group in sorted(groups, key=lambda g: g.matches, reverse=True):
                print(f"{group.matches:>5}  {group.title}")
        else:
            color = cfg.color and supports_color()
            sys.stdout.write(render_table(groups, tokens, color=color))
    finally:
        store.close()
    return EXIT_OK


def _human_bytes(size: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} Go"


def _cmd_status(args: argparse.Namespace, cfg: Config) -> int:
    if not cfg.db_path.exists():
        print(f"aucun index : {cfg.db_path}", file=sys.stderr)
        return EXIT_EMPTY
    store = Store(cfg.db_path)
    try:
        stats = store.stats()
        by = stats["by_status"]
        print(f"Base      {cfg.db_path} ({_human_bytes(stats['db_bytes'])})")  # type: ignore[arg-type]
        print(f"Chaines   {stats['channels']}")
        print(
            f"Videos    {stats['videos']}  "
            f"(ok {by.get('ok', 0)}, vides {by.get('empty', 0)}, "
            f"erreurs {by.get('error', 0)}, en attente {by.get('pending', 0)}, "
            f"ignorees {by.get('skipped', 0)})"
        )
        print(f"Passages  {stats['segments']}")
        print(f"Texte     {stats['chars'] / 1_000_000:.2f} M caracteres")
        errors = store.errors(5)
        if errors:
            print("")
            print("Derniers echecs :")
            for row in errors:
                print(f"  {row['id']}  {row['title'][:60]}  —  {row['error']}")
    finally:
        store.close()
    return EXIT_OK


def _cmd_export(args: argparse.Namespace, cfg: Config) -> int:
    store = Store(cfg.db_path)
    try:
        rows = list(store.export_rows())
    finally:
        store.close()
    if not rows:
        print("index vide", file=sys.stderr)
        return EXIT_EMPTY
    if args.format == "csv":
        import csv

        writer = csv.writer(sys.stdout, lineterminator="\n")
        writer.writerow(["video_id", "title", "url", "published_at", "source", "lang", "start_ms", "text"])
        for row in rows:
            writer.writerow(list(row))
    else:
        for row in rows:
            print(json.dumps(dict(row), ensure_ascii=False))
    return EXIT_OK


def _cmd_doctor(args: argparse.Namespace, cfg: Config) -> int:
    ok = True
    print(f"yts           {__version__}")
    binary = youtube.binary()
    version = youtube.version()
    if version:
        print(f"yt-dlp        {version}  ({binary})")
    else:
        print(f"yt-dlp        INTROUVABLE ({binary}) — installe-le : pacman -S yt-dlp")
        ok = False

    print(f"config        {getattr(args, 'config_path', None) or default_config_path()}")
    print(f"base          {cfg.db_path}")
    try:
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg.db_path.parent / ".yts-write-test", "w", encoding="utf-8") as fh:
            fh.write("ok")
        (cfg.db_path.parent / ".yts-write-test").unlink()
        print("ecriture      ok")
    except OSError as exc:
        print(f"ecriture      ECHEC ({exc})")
        ok = False

    print(f"langues       {','.join(cfg.langs)}")
    if cfg.db_path.exists():
        store = Store(cfg.db_path)
        try:
            print(f"integrite     {store.integrity()}")
            fts_ok = store.fts_integrity()
            print(f"index FTS     {'ok' if fts_ok else 'CORROMPU — relancer : yts export > /dev/null'}")
            ok = ok and fts_ok
            stats = store.stats()
            print(f"contenu       {stats['videos']} videos, {stats['segments']} passages")
        finally:
            store.close()

    if args.network:
        try:
            head, entries = youtube.list_videos("https://www.youtube.com/@YouTube", cfg.timeout)
            print(f"reseau        ok ({len(entries)} videos listees)")
        except youtube.YtError as exc:
            print(f"reseau        ECHEC ({exc})")
            ok = False

    return EXIT_OK if ok else EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = _config(args)
    try:
        if args.command == "index":
            return _cmd_index(args, cfg)
        if args.command == "search":
            return _cmd_search(args, cfg)
        if args.command == "status":
            return _cmd_status(args, cfg)
        if args.command == "export":
            return _cmd_export(args, cfg)
        if args.command == "doctor":
            return _cmd_doctor(args, cfg)
    except KeyboardInterrupt:
        print("\ninterrompu", file=sys.stderr)
        return 130
    except youtube.YtError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
