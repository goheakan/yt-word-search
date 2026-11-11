# YT Word Search

`yts` — recherche de mots ou d'expressions dans **toutes les vidéos d'une chaîne YouTube**,
à partir des sous-titres (manuels ou automatiques). La sortie donne le mot trouvé, la vidéo
et l'URL horodatée à la seconde.

**Privacy-first** : l'index reste chez vous (SQLite local), aucune télémétrie, aucun compte,
aucun serveur tiers, aucune ressource distante dans l'interface.
**Licence** : [AGPL-3.0-or-later](LICENSE) — logiciel libre, auto-hébergeable.

## Prérequis

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) (ou `pipx`)
- `yt-dlp` dans le `PATH` (Arch : `sudo pacman -S yt-dlp`)

## Installation

Depuis le dépôt Git (recommandé : isole l'outil, ne touche pas au Python système) :

```bash
uv tool install "git+https://github.com/goheakan/yt-word-search"
yts --help
uv tool upgrade yt-word-search     # mise à jour
```

Sans installation, pour essayer :

```bash
uvx --from "git+https://github.com/goheakan/yt-word-search" yts search kubernetes
```

Pour développer ou modifier le code :

```bash
git clone https://github.com/goheakan/yt-word-search
cd yt-word-search
uv sync                 # crée .venv et installe yts
uv run yts --help
```

## Utilisation

```bash
# 1. Indexer une chaîne entière (incrémental : relançable à volonté)
yts index @Fireship --langs en
yts index "https://www.youtube.com/@Fireship" --limit 50

# 2. Indexer une seule vidéo
yts index --video "https://www.youtube.com/watch?v=pf5tXJZM1Rw"

# 3. Chercher
yts search kubernetes
yts search "reseau" --json | jq -r .url
yts search entorse orchestre --mode phrase

# 4. État et diagnostic
yts status
yts doctor --network
```

## Sorties

- par défaut : table lisible, correspondances surlignées, URL `...&t=12s` ;
- `--json` : une ligne JSON par passage ;
- `--csv` : tableau pour tableur ;
- `--count` : nombre d'occurrences par vidéo.

## Modes de recherche

| Option | Sens |
|---|---|
| `-m all` (défaut) | tous les mots présents dans le même passage |
| `-m any` | au moins un mot |
| `-m phrase` | expression exacte |
| `-m near --near 5` | les mots à moins de 5 mots d'écart |

La recherche ignore la casse **et les accents** (`reseau` trouve « réseau »), grâce au
tokenizer FTS5 `unicode61 remove_diacritics 2`. Les extraits affichés conservent, eux, les
accents et la casse d'origine.

## Modèle de données

SQLite + FTS5, une transaction par vidéo, reprise exacte après interruption :

- `channels` — chaîne indexée ;
- `videos` — statut (`pending`, `ok`, `empty`, `error`, `skipped`), provenance (`manual`
  ou `auto`), langue ;
- `segments` — passages fusionnés (~160 caractères) avec `start_ms` / `end_ms`, doublés dans
  `segments_fts`.

Base par défaut : `~/.local/share/yt-word-search/index.db` (`--db` pour changer).
Configuration : `~/.config/yt-word-search/config.toml`.
Sur macOS : `~/Library/Application Support/yt-word-search/`.

> L'ancien nommage (`yt-search`) est migré automatiquement au premier lancement :
> le dossier de données et le fichier de configuration sont renommés s'ils existent encore.

## Confidentialité

- aucune donnée ne quitte la machine, sauf les requêtes vers YouTube déclenchées par une
  indexation ;
- aucune télémétrie, aucun compte, aucune vérification réseau au démarrage ;
- les cookies d'un navigateur, s'ils sont utilisés (`--cookies-from-browser`), sont lus à la
  volée et jamais écrits dans la base ni dans les journaux.

## Limites connues

- **La transcription locale (ASR) n'est pas implémentée** : `--asr` affiche un avertissement,
  seuls les sous-titres existants sont utilisés (jalon M4 de `PLAN.md`).
- Les vidéos sans sous-titres sont marquées `empty` et peuvent être retentées avec
  `--retry-errors`.
- YouTube limite parfois les demandes de sous-titres (HTTP 429) : l'indexation continue,
  les vidéos concernées sont marquées `error` et rejouables.

## Tests

```bash
uv run pytest
```

## Licence

Copyright (C) 2026 yt-word-search contributors.

Ce programme est un logiciel libre : vous pouvez le redistribuer et/ou le modifier selon les
termes de la licence **GNU Affero General Public License** version 3 ou ultérieure, publiée
par la Free Software Foundation. Voir [LICENSE](LICENSE).

Le code source complet est publié à l'adresse
<https://github.com/goheakan/yt-word-search> (AGPL §13 : toute version modifiée exposée en
service réseau doit offrir le même accès au source).
