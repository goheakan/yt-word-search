# YT Word Search — Plan de conception du cœur

Projet : **`yt-word-search`** (commande `yts`, module `yt_search`).
Plan de l'interface graphique et de la distribution : [`GUI_YTS_v1.md`](GUI_YTS_v1.md).

Recherche de mots ou d'expressions dans **toutes les vidéos d'une chaîne YouTube**, à partir
des sous-titres existants (manuels ou auto-générés) et, en dernier recours, d'une transcription
locale de l'audio.

Sortie attendue : **le mot trouvé**, **la vidéo** (titre + chaîne), **l'horodatage** et **l'URL
cliquable** (`https://www.youtube.com/watch?v=<id>&t=<secondes>s`).

> Version de Python retenue pour le paquet : `requires-python = ">=3.11"` (testé 3.12 et
> 3.13). La contrainte « 3.12 » ci-dessous ne concerne que l'ASR (`ctranslate2`), optionnelle
> et non implémentée (jalon M4).

---

## 1. Choix du langage — verdict

**Python 3.12 (géré par `uv`)** pour le cœur du projet, avec un binaire externe optionnel
(`whisper.cpp`) pour l'ASR.

Justification, en toute honnêteté :

| Critère | Python | Rust |
|---|---|---|
| Extraction YouTube (sous-titres, listing, cookies, PO tokens) | `yt-dlp` = référence du domaine, maintenu au jour le jour | `rustube`/`youtubei` cassent à chaque changement côté Google ; on finit par appeler `yt-dlp` en sidecar |
| Sous-titres sans téléchargement | `youtube-transcript-api` | réimplémentation manuelle de `timedtext` |
| ASR local | `faster-whisper`, bindings whisper.cpp | `whisper-rs` (bon, mais compilation lourde) |
| Recherche plein texte | SQLite FTS5 (module natif, aucune dépendance) | `tantivy` (excellent, mais dépendance à construire) |
| Coût de maintenance | faible — le travail réel est l'adaptation aux changements de l'API YouTube | élevé — on maintient en plus le client YouTube |
| Distribution | `uv tool install` / `pipx` | binaire unique (seul vrai avantage) |

La **robustesse** demandée ne vient pas du langage mais de l'architecture : reprise après
interruption, idempotence, cache, isolation des erreurs par vidéo, sorties déterministes.
Python offre la même robustesse *opérationnelle* avec un écosystème YouTube nettement plus
résistant. Rust ne se justifierait que si le livrable devait être un binaire unique distribué à
des tiers non techniques — ce n'est pas le cas ici.

> Décision : **Python 3.12 + SQLite FTS5 + yt-dlp**, ASR de secours via `whisper.cpp` (Vulkan,
> adapté au RX 7800 XT) ou `faster-whisper` en CPU int8 (i7-14700KF, 28 threads).

Python 3.12 et non 3.14 (présent sur la machine) : `ctranslate2` / `faster-whisper` n'ont pas
encore de wheels fiables en 3.14 ; `uv` installe et épingle 3.12 sans toucher au système.

---

## 2. Périmètre fonctionnel

### Entrées

- `--channel <url|@handle|id>` : chaîne entière (comportement par défaut du projet).
- `--playlist <url>` : playlist publique.
- `--video <url|id>` : une seule vidéo (mode diagnostic).
- `--limit N`, `--since AAAA-MM-JJ`, `--until AAAA-MM-JJ` : bornage du corpus.

### Requêtes

- **Un ou plusieurs mots** : `yts search "kubernetes"`, `yts search "kubernetes ingress"`.
- Modes : `--any` (OU), `--all` (ET, défaut), `--phrase` (expression exacte),
  `--near 5` (mots à ±5 mots d'écart).
- Insensible à la casse **et aux accents** (`reseau` trouve « réseau »), insensible à la
  ponctuation, avec option `--case-sensitive`, `--accent-sensitive`, `--word` (mot entier).
- `--lang fr,en` : langues de sous-titres acceptées, par ordre de préférence.

### Sorties

- Table lisible par défaut : mot, extrait, titre, horodatage, URL.
- `--json` (JSONL, un objet par occurrence) et `--csv` pour la réutilisation.
- `--count` : nombre d'occurrences par vidéo, sans extraits.
- Chaque URL pointe à la seconde près (`&t=754s`).

---

## 3. Architecture

```
yt-word-search/
├── pyproject.toml
├── README.md
├── PLAN.md
├── src/yt_search/
│   ├── cli.py           # argparse/typer : index | search | status | export | doctor
│   ├── config.py        # TOML (~/.config/yt-word-search/config.toml) + overrides CLI/env
│   ├── models.py        # dataclasses Video, Segment, Hit
│   ├── youtube/
│   │   ├── channel.py   # résolution handle → channel_id, listing paginé
│   │   ├── subs.py      # youtube-transcript-api puis yt-dlp --write-auto-subs
│   │   └── audio.py     # téléchargement audio bestaudio + garde-fou taille/durée
│   ├── asr.py           # whisper.cpp (Vulkan) / faster-whisper (CPU int8)
│   ├── normalize.py     # casing, accents (NFD), ponctuation, offsets
│   ├── store.py         # SQLite WAL + migrations + FTS5
│   ├── indexer.py       # orchestration : file de travail, reprise, idempotence
│   ├── search.py        # construction des requêtes FTS5, scoring, extraits
│   └── output.py        # table / jsonl / csv, codes de sortie
└── tests/
    ├── fixtures/*.vtt   # sous-titres réels figés → tests 100 % hors-ligne
    └── test_*.py
```

### Flux

```
channel → listing (yt-dlp --flat-playlist)
        → pour chaque vidéo non indexée :
             1. sous-titres manuels (fr, en)          ┐
             2. sinon sous-titres auto-générés        ├─ source "subs"
             3. sinon ASR local sur l'audio           ┘─ source "asr"
        → normalisation → segments (start, end, texte, texte_norm)
        → INSERT en transaction (vidéo + segments + FTS)
search → FTS5 (MATCH) → jointure vidéos → snippet → tri → rendu
```

### Schéma SQLite

```sql
PRAGMA journal_mode = WAL;

channels(id TEXT PRIMARY KEY, handle TEXT, title TEXT, url TEXT, last_sync_at TEXT);
videos(id TEXT PRIMARY KEY,            -- ID YouTube à 11 caractères
       channel_id TEXT REFERENCES channels(id),
       title TEXT NOT NULL, duration_s INTEGER, published_at TEXT,
       url TEXT NOT NULL,
       status TEXT NOT NULL,           -- pending | subs | asr | empty | error | skipped
       lang TEXT, source TEXT,         -- manual | auto | asr
       error TEXT, fetched_at TEXT, retries INTEGER DEFAULT 0);

segments(id INTEGER PRIMARY KEY, video_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
         start_ms INTEGER NOT NULL, end_ms INTEGER, text TEXT NOT NULL, text_norm TEXT NOT NULL);

CREATE INDEX idx_segments_video ON segments(video_id);

CREATE VIRTUAL TABLE segments_fts USING fts5(
    text_norm, content='segments', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);
-- triggers AFTER INSERT/UPDATE/DELETE sur segments pour garder l'index synchronisé
```

`remove_diacritics 2` gère nativement « réseau » ↔ « reseau » ; la normalisation Python ne
sert qu'à garantir la stabilité des offsets pour les extraits.

---

## 4. Robustesse — exigences concrètes

1. **Idempotence** : `index` peut être relancé à volonté ; une vidéo déjà indexée avec succès
   n'est jamais retéléchargée (`--refresh` pour forcer).
2. **Reprise** : état persisté par vidéo (`status`, `retries`) ; `Ctrl-C` laisse la base
   cohérente (une transaction par vidéo, jamais de segments orphelins).
3. **Isolation des pannes** : une vidéo privée/supprimée/géobloquée n'arrête pas le lot ; elle
   est marquée `error` avec le message, et `status` liste les échecs.
4. **Retries** : backoff exponentiel (3 tentatives) uniquement sur les erreurs réseau/429 ;
   jamais sur « sous-titres absents » (qui déclenche le fallback ASR).
5. **Débit maîtrisé** : 2–3 téléchargements parallèles maximum, `--sleep-requests`, aucun
   contournement de limitation ; `--cookies-from-browser` pour les vidéos à age-restriction.
6. **Chaîne de repli explicite** : manuel → auto → ASR → `empty` (vidéo sans parole utile).
   Le champ `source` rend toujours l'origine de la citation visible dans la sortie.
7. **Déterminisme** : même corpus ⇒ même ordre de résultats (tri par vidéo, puis date de
   publication, puis `start_ms`), horodatages en ms, UTF-8 partout.
8. **Codes de sortie** : `0` succès, `1` erreur interne, `2` usage invalide, `3` aucun résultat.
9. **Observabilité** : `-v` journalise en JSONL ; `yts status` affiche le compteur par statut,
   la couverture (vidéos indexées / total) et les 10 derniers échecs.
10. **Diagnostic** : `yts doctor` vérifie `yt-dlp` (version), accès réseau, présence du modèle
    ASR, permissions du cache, intégrité FTS (`INSERT INTO segments_fts(segments_fts) VALUES('integrity-check')`).

---

## 5. Interface CLI (cible)

```bash
# Indexer toute la chaîne (première fois : long ; ensuite : incrémental)
yts index --channel @Fireship --lang en

# Rechercher plusieurs mots (ET) dans tout le corpus déjà indexé
yts search "rust borrow checker"

# Expression exacte, avec contexte de 80 caractères
yts search --phrase "zero cost abstraction" --context 80

# Résultats machine
yts search "sqlite" --json | jq -r '.url'

# État de l'index, échecs, relance ciblée
yts status
yts index --retry-errors
```

Exemple de sortie :

```
kubernetes  —  3 occurrences dans 2 vidéos

1. Kubernetes in 100 Seconds · Fireship
   « … kubernetes is an open source container orchestration … »
   00:12  https://www.youtube.com/watch?v=PziYflu8cB8&t=12s

2. Why Kubernetes is hard · Fireship
   « … people think kubernetes solves scaling, it does not … »
   04:31  https://www.youtube.com/watch?v=6BfCVXkQw8A&t=271s
```

---

## 6. Décisions techniques à trancher (proposées par défaut)

| Sujet | Proposition par défaut | Alternative |
|---|---|---|
| Langue d'indexation | `fr` + `en`, priorité manuel > auto | une seule langue pour alléger |
| ASR | désactivé par défaut, `--asr` pour l'activer | toujours actif (coûteux) |
| Modèle ASR | `small` int8 CPU (~1× temps réel, 28 threads) | `large-v3` Vulkan, meilleur mais gourmand |
| Stockage | `~/.local/share/yt-word-search/index.db` | `./data/index.db` en mode projet |
| Granularité | segment (cue) de sous-titre | fenêtre glissante de 15 s |
| Multi-mots | `AND` par défaut | `NEAR` par défaut (plus bruité) |
| Dépendance ASR | `whisper.cpp` compilé en Vulkan, binaire détecté à l'exécution | `faster-whisper` pip |

---

## 7. Jalons

**M0 — squelette (0,5 j)** : `pyproject.toml` (uv, ruff, pytest), CLI `--help`, `config.py`,
`doctor` minimal, base SQLite + migration initiale.

**M1 — sous-titres (1 j)** : listing d'une chaîne, récupération des sous-titres manuels puis
auto, parsing VTT/SRT en segments, insertion transactionnelle. *Critère* : `yts index --limit 5`
puis `yts search "le"` renvoie des occurrences avec URL horodatée exacte.

**M2 — recherche (0,5 j)** : FTS5, modes any/all/phrase/near, accents, snippets, sorties
table/jsonl/csv, code de sortie 3 si vide. *Critère* : fixtures hors-ligne, tests verts.

**M3 — robustesse (1 j)** : reprise, retries, isolation d'erreurs, `status`, incrémental,
`--refresh`, cookies. *Critère* : `kill -9` pendant l'indexation → relance → aucun doublon,
aucune perte, couverture identique.

**M4 — ASR de secours (1–2 j)** : extraction audio, appel `whisper.cpp`/`faster-whisper`,
conversion en segments, provenance `asr`. *Critère* : vidéo sans sous-titres indexée et
retrouvée par recherche.

**M5 — finitions** : README + exemples, `--export jsonl` d'un corpus complet, mesure de
performance (cible : 1000 vidéos, < 500 Mo de base, requête < 100 ms).

---

## 8. Risques et parades

| Risque | Impact | Parade |
|---|---|---|
| YouTube casse l'accès aux sous-titres (`timedtext`, PO tokens) | élevé, récurrent | double implémentation (API puis `yt-dlp`), mise à jour de `yt-dlp` documentée dans `doctor`, cookies navigateur |
| Blocage 429 / IP | moyen | parallélisme faible, backoff, cache agressif, reprise |
| Sous-titres auto de mauvaise qualité (ponctuation absente) | moyen | normalisation tolérante, recherche par mots plutôt que phrase, `--near` |
| Vidéos longues sans sous-titres (coût ASR) | moyen | `--asr` opt-in, plafond de durée (`--max-duration`), modèle `small` |
| Base volumineuse | faible | FTS5 + `segments` seuls (pas d'audio conservé), `VACUUM` occasionnel |
| Conformité CGU YouTube | juridique | usage personnel, pas de redistribution de transcriptions, débit poli |

---

## 9. Hors périmètre (v1)

- Interface web ou TUI (CLI d'abord ; une TUI `textual` pourra venir après M5).
- Recherche sémantique / embeddings (FTS5 lexical suffit pour « chercher un mot »).
- Téléchargement des vidéos, sous-titres traduits, résumé par LLM.
- Comptes privés / playlists nécessitant une authentification complète.
