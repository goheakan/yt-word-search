# Tuto — `yts`, la recherche de mots dans les sous-titres YouTube

`yts` indexe les sous-titres (manuels puis automatiques) d'une chaîne, d'une
playlist ou d'une vidéo YouTube dans une base locale SQLite, puis permet de
chercher **un ou plusieurs mots** et d'obtenir :

- le mot trouvé, avec un extrait du passage où il apparaît,
- la **vidéo** concernée (titre, chaîne, date),
- son **adresse web** directe, avec le temps exact : `https://www.youtube.com/watch?v=<id>&t=99s`.

La recherche est **insensible aux accents et à la casse** : `reseau` trouve
« réseau », `Kernel` trouve « kernel » et « KERNEL ».

---

## 1. Installation

Prérequis (sur Arch) — Python ≥ 3.11 est fourni par les paquets `uv`/`yt-dlp` :

```bash
sudo pacman -S uv yt-dlp   # yt-dlp doit être dans le PATH
```

### 1.1 Méthode recommandée : `uv tool install` (aucun dépôt à cloner)

```bash
uv tool install "git+https://github.com/goheakan/yt-word-search"
fish_add_path ~/.local/bin      # ou ajouter ~/.local/bin au PATH
yts --help
uv tool upgrade yt-word-search  # mise à jour
```

L'outil est installé isolément (pas de pollution du Python système). Sans
installation, pour un essai immédiat :

```bash
uvx --from "git+https://github.com/goheakan/yt-word-search" yts search kubernetes
```

### 1.2 Méthode développeur : depuis les sources

```bash
git clone https://github.com/goheakan/yt-word-search
cd yt-word-search
uv sync            # crée l'environnement virtuel
```

Deux façons de lancer l'application dans ce cas :

```bash
uv run yts --help          # via uv (toujours à jour du code du projet)
yts --help                 # directement, si le venv est activé (source .venv/bin/activate)
```

### 1.3 Vérification

```bash
yts doctor --network
```

La commande `doctor` contrôle : version de `yt-dlp`, chemin du fichier de
configuration, chemin de la base SQLite et droit d'écriture, intégrité de la
base et (avec `--network`) l'accès réel à YouTube.

> **Note** : dans les exemples ci-dessous, `yts` est utilisé seul. Si vous
> travaillez depuis les sources sans le venv activé, remplacez-le par
> `uv run yts`.

---

## 2. Indexer

### 2.1 Une seule vidéo

```bash
yts index --video "https://www.youtube.com/watch?v=pf5tXJZM1Rw"
```

Environ 7 secondes pour une vidéo de ~6 min : téléchargement des sous-titres,
découpage en passages d'~160 caractères, stockage horodaté.

### 2.2 Une chaîne complète

```bash
yts index @Fireship
```

L'indexation est **incrémentale** : à la relance, seules les vidéos non encore
traitées sont prises en charge. Les vidéos déja en `ok` ne sont **pas**
retéléchargées.

Contrôler le volume :

```bash
yts index @Fireship --limit 20          # seulement les 20 dernières vidéos
yts index @Fireship --jobs 3            # 3 téléchargements parallèles (défaut 2)
yts index @Fireship --sleep 1.5         # ralentir entre requêtes (défaut 0.7 s)
```

### 2.3 Langue des sous-titres

Par défaut `fr` puis `en` (un sous-titre manuel est toujours préféré à un
automatique). Pour changer l'ordre :

```bash
yts index @UneChaîne --langs en,fr
```

### 2.4 Indexer à nouveau / rattraper les échecs

```bash
yts index @Fireship --refresh        # re-indexer TOUTES les vidéos
yts index @Fireship --retry-errors   # rejouer les vidéos en erreur ou vides
```

### 2.5 Accès restreint (vidéos privées / âge / premium)

```bash
yts index @MaChaîne --cookies-from-browser firefox
```

ou de façon permanente dans le fichier de configuration (voir §6).

### 2.6 Interruption

`Ctrl+C` arrête proprement : l'avancement déjà indexé est conservé, et la
relance reprend là où on s'est arrêté.

---

## 3. Rechercher

```bash
yts search kubernetes
```

Sortie typique :

```
kubernetes — 9 occurrences dans 3 passages (1 vidéo)

Kubernetes in 100 Seconds
Fireship — 2024-03-02

  01:39  so if you have to deploy a [kubernetes] cluster on your own…
  03:12  kubernetes 1.29 introduced a new [Kubernetes] scheduler…

https://www.youtube.com/watch?v=abc123&t=99s
https://www.youtube.com/watch?v=abc123&t=192s
```

Chaque passage affiche : **heure dans la vidéo**, extrait avec le mot
surligné `[...]`, titre, chaîne, date, et l'**URL directe vers le moment**.

### 3.1 Modes de recherche

| Mode    | Option               | Signification                                    | Exemple                              |
|---------|----------------------|--------------------------------------------------|--------------------------------------|
| `all`   | défaut               | **tous** les mots doivent être dans le passage   | `yts search kubernetes linux`        |
| `any`   | `-m any`             | au **moins un** des mots                         | `yts search docker k8s -m any`       |
| `phrase`| `-m phrase`          | les mots **dans cet ordre exact**                | `yts search "machine learning" -m phrase` |
| `near`  | `-m near --near 5`   | les mots à **N mots** l'un de l'autre (défaut 5) | `yts search container image -m near` |

### 3.2 Options utiles

```bash
yts search kuber --prefix                 # préfixe : trouve kubernetes, kubeadm…
yts search --count kubernetes             # simple comptage par vidéo, sans extraits
yts search kubernetes --json              # JSONL (une ligne JSON par vidéo)
yts search kubernetes --csv               # CSV (colonnes : video_id, title, channel, published_at, timestamp, start_ms, url, matches, snippet)
yts search kubernetes --context 200       # plus de contexte (défaut 90 caractères)
yts search kubernetes --per-video 5       # plus d'extraits par vidéo (défaut 3)
yts search kubernetes --channel @Fireship # limiter à une chaîne (handle ou channel_id)
yts search kubernetes --limit 2000        # élargir le plafond de passages analysés
```

> `--json`, `--csv`, `--count` s'additionnent à toutes les autres options
> (`-m`, `--prefix`, `--channel`…).

### 3.3 Codes de sortie

| Code | Signification                              |
|------|--------------------------------------------|
| 0    | succès (avec ou sans résultat)             |
| 1    | erreur (réseau, base, yt-dlp…)             |
| 2    | erreur d'utilisation (mauvais arguments)   |
| 3    | aucun résultat                             |

Utile dans les scripts : `yts search --count mot || …` pour distinguer
« aucun résultat » (3) d'« erreur » (1).

---

## 4. Suivre l'index

```bash
yts status
```

Exemple de sortie :

```
Base      ~/.local/share/yt-word-search/index.db (2.3 Mo)
Chaines   1
Videos    6  (ok 6, vides 0, erreurs 0, en attente 0, ignorees 0)
Passages  124
Texte     0.02 M caracteres
```

Les statuts des vidéos :

| Statut    | Signification                                          |
|-----------|--------------------------------------------------------|
| `ok`      | indexée avec succès                                    |
| `pending` | attendue, non encore traitée                           |
| `empty`   | aucun sous-titre exploitable (pas de sous-titres)      |
| `error`   | échec (réseau, 429, vidéo retirée…) — rejouable       |
| `skipped` | ignorée (vidéo live, non dispo…)                       |

En cas de blocus ou d'échec :

```bash
yts status            # liste les derniers échecs avec leur cause
yts index @Fireship --retry-errors   # rejoue erreurs + vides
```

Exporter tout le corpus indexé (sauvegarde, traitement externe) :

```bash
yts export                     # JSONL
yts export --format csv        # CSV
```

---

## 5. Configuration

Fichier `~/.config/yt-word-search/config.toml` (créé à la main si besoin).
Les options CLI et `--db` prennent le dessus.

```toml
# langues à privilégier, dans l'ordre (manuel > auto)
langs = "fr,en"

# 2 téléchargements parallèles, 0,7 s entre requêtes
concurrency = 2
sleep_requests = 0.7

# accès via cookies du navigateur (si nécessaire)
# cookies_from_browser = "firefox"

# chemin de la base SQLite
# db = "~/.local/share/yt-word-search/index.db"

# extraits : 90 caractères de contexte, 3 extraits par vidéo
context = 90
per_video = 3

# timeout par requête (s)
timeout = 120

# transcription locale par ASR — NON IMPLÉMENTÉ (jalon M4)
# asr = true
```

---

## 6. Recettes courantes

**« Où cette chaîne parle-t-elle de X ? »**

```bash
yts search X --channel @Fireship -m phrase
```

**« Combien de fois docker apparaît-il ? »**

```bash
yts search docker --count
```

**Trouver un terme technique avec ses variantes :**

```bash
yts search --prefix kuber        # kuber, kubernetes, kubeadm…
```

**Pipelines avec le résultat :**

Le `--json` produit **une ligne JSON par passage**, avec les champs :
`video_id`, `title`, `channel`, `published_at`, `start_ms`, `timestamp`,
`url`, `matches`, `snippet`, `text`.

```bash
# l'URL du 1er passage trouvé :
yts search --json kubernetes | head -1 | jq -r '.url'

# la liste dédupliquée des vidéos qui en parlent :
yts search --json docker | jq -r '[.video_id, .title] | @tsv' | sort -u

# le 1er extrait avec le mot surligné :
yts search --json kubernetes | head -1 | jq -r '.snippet'
```

**Index de travail séparé (ne pas polluer l'index principal) :**

```bash
yts --db /tmp/opencode/index-tpm.db index @MaChaîne
yts --db /tmp/opencode/index-tpm.db search mot
```

---

## 7. Limites connues et dépannage

| Symptôme                              | Cause / remède                                                             |
|---------------------------------------|----------------------------------------------------------------------------|
| `empty` sur une vidéo                 | pas de sous-titres (manuels ni auto) → `--retry-errors` après ajout        |
| erreur `HTTP 429`                     | rate-limit de YouTube → relancer plus tard, `--sleep 2`, `--jobs 1`       |
| erreur d'âge / accès                  | `--cookies-from-browser firefox` (ou config `cookies_from_browser`)        |
| mots non trouvés                      | le passage existe mais avec une ponctuation/orthographe différente ; essayer `-m any` ou `--prefix` |
| `yts: command not found`              | `uv tool install` place le binaire dans `~/.local/bin` → `fish_add_path ~/.local/bin` ; sinon `uv run yts …` |

Limites actuelles :

- **`--asr`** : transcription locale (whisper.cpp / faster-whisper) prévue au
  jalon M4, pas encore implémentée — `yts index --asr` affiche un avertissement
  et utilise les sous-titres quand même.
- **Vidéos live** : ignorées (`skipped`), pas de sous-titres stables.
- **Chaînes très volumineuses** : l'indexation complète peut prendre du temps
  (2-3 s/vidéo en rythme normal) ; commencez par `--limit 20` pour valider.

---

## 8. Rappel express

```bash
uv sync                                        # 1. install
uv run yts doctor --network                    # 2. vérifier
uv run yts index @MaChaîne --limit 20          # 3. indexer (petit)
uv run yts status                              #    contrôler
uv run yts search mon mot                      # 4. chercher
uv run yts search mot1 mot2 -m near --json     #    modes / sortie
uv run yts index @MaChaîne --retry-errors      # 5. rattraper
```
