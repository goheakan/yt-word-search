# Plan final — Interface graphique `yt-word-search` (Privacy-First, Self-Hosted, FLOSS)

Version 1.2 — 2026-11-11
Dépôt : **`yt-word-search`**, **public** — `https://github.com/goheakan/yt-word-search`
Périmètre : ajouter une interface graphique utilisable par un utilisateur lambda au
moteur `yts` existant (Python ≥ 3.11, zéro dépendance Python, SQLite FTS5, `yt-dlp`
en sous-processus), et le distribuer sur **n'importe quelle distribution Linux** et
**macOS (Intel + Apple Silicon)**.

Décisions verrouillées par le porteur du projet :

- **(a)** Distribution Linux : **AppImage + `.deb` / `.rpm` + `.tar.gz`**
- **(b)** macOS : **`.dmg` universal2, signature ad-hoc, procédure Gatekeeper documentée**
  (pas de compte Apple Developer, pas de notarisation)
- **Arch Linux** : installation **uniquement par `uv tool install` depuis le dépôt Git**.
  **Hors périmètre v1 : PKGBUILD, `.pkg.tar.zst`, AUR** (reportés en phase 2, §9).
- Mode d'affichage : **UI web locale servie par le binaire** (onglet navigateur)
- Licence : **Open Source intégral** — `AGPL-3.0-or-later`
- **Présentation du projet multilingue** (§3.5) : obligatoire en v1.

### Identité canonique (à respecter partout : code, paquets, docs, Pages)

| Élément | Valeur |
|---|---|
| Dépôt GitHub | `yt-word-search` (public) |
| Nom du projet / `pyproject.toml` | `yt-word-search` |
| Commande CLI | `yts` (courte, inchangée) |
| Module Python | `yt_search` (inchangé) |
| Nom affiché (GUI, `.desktop`, `.app`) | **YT Word Search** |
| Dossier de données | `~/.local/share/yt-word-search/` — **migration automatique** depuis `yt-search/` au premier lancement |
| Dossier de configuration | `~/.config/yt-word-search/` — idem |
| macOS | `~/Library/Application Support/yt-word-search/` |
| Assets de release | `yt-word-search-<ver>-x86_64.AppImage`, `yt-word-search_<ver>_amd64.deb`, `yt-word-search-<ver>.x86_64.rpm`, `yt-word-search-<ver>-linux-x86_64.tar.gz`, `YT-Word-Search-<ver>-universal.dmg` |

> Renommage `yt-search` → `yt-word-search` appliqué **partout** : paquets, dossiers XDG,
> interface, docs. Seuls le module Python (`yt_search`) et la commande (`yts`) restent
> inchangés, pour ne pas casser les scripts existants. L'index local n'est pas perdu :
> `_app_dir()` renomme `yt-search/` en `yt-word-search/` au premier lancement, et se replie
> sur l'ancien chemin si le renommage échoue (disque en lecture seule, permissions).

---

## 1. Les quatre contraintes, traduites en décisions vérifiables

### 1.1 Privacy First / Privacy by Design

| Principe | Décision technique |
|---|---|
| **Minimisation** | On ne stocke que le texte des sous-titres et les métadonnées nécessaires (id, titre, chaîne, date, langue, source manuel/auto). Aucune donnée sur l'utilisateur : ni identifiant, ni historique de navigation, ni préférences comportementales, ni adresse IP. |
| **Localité** | 100 % des données restent dans le dossier de données de l'utilisateur. Aucun serveur tiers, aucun compte, aucun cloud. |
| **Souveraineté de l'utilisateur** | Bouton « Effacer toutes les données » (index + config + cache yt-dlp), export complet en un clic (`yts export`), chemins affichés en clair dans l'écran Réglages. |
| **Aucune ressource distante dans l'UI** | Pas de Google Fonts, pas de CDN, pas de librairie JS tierce, **pas de miniatures YouTube** (`i.ytimg.com`). Vignettes remplacées par un monogramme généré localement (couleur dérivée du titre). Zéro CSS/JS/font externe. |
| **Aucune télémétrie** | Pas de crash reporting, pas d'analytics, pas de « ping » de démarrage, pas de sondage. |
| **Egress explicite et minimal** | Réseau sortant uniquement pour : (1) YouTube via `yt-dlp` quand **l'utilisateur lance une indexation**, (2) vérification de mise à jour **désactivée par défaut** et déclenchée par un clic. Rien d'autre. |
| **Sécurité locale** | Serveur lié à `127.0.0.1` uniquement, jeton aléatoire obligatoire, validation du `Host` (anti DNS-rebinding), `Content-Security-Policy: default-src 'self'`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`. |
| **Permissions de fichiers** | Dossier de données `0700`, base et config `0600`. Vérifié par test. |
| **Cookies** | Lus à la volée depuis le navigateur si l'utilisateur l'autorise (opt-in explicite), **jamais copiés dans la base, jamais journalisés**, jamais transmis ailleurs qu'à YouTube par `yt-dlp`. |
| **Journalisation** | Logs strictement locaux, sans IP, sans URL complète, rotation, désactivables. Écrits en `0600`. |
| **Pas de traçage des recherches** | Aucun historique de recherche persisté (champ vidé à la fermeture). |
| **Transparence** | `PRIVACY.md` (multilingue, §3.5) : « cette application ne collecte rien ; voici les 2 seuls accès réseau possibles et comment les couper ». |
| **Aucun tiers de traduction** | Traductions statiques versionnées dans le dépôt ; pas d'API de traduction appelée par l'app, pas de webfont par langue. |

**Preuves attendues (critères d'acceptation)** :
- `ss -tlnp` après lancement : uniquement `127.0.0.1:<port>`.
- `lsof -i` pendant une recherche : **aucune** connexion réseau.
- `grep -R "https\?://" src/yt_search/gui/static/` : aucune URL externe.
- UI fonctionnelle avec la carte réseau désactivée (hors indexation).
- `stat -c %a` sur la base et la config : `600`.

### 1.2 Self-Hosting

1. **Poste local** (défaut) — l'app est son propre serveur, lié à la boucle locale.
2. **Accès réseau opt-in** — `yts gui --host 0.0.0.0 --auth-token-file …` pour un
   accès LAN (tablette/téléphone), avec bandeau d'avertissement et recommandation de
   reverse proxy TLS. Désactivé par défaut, jamais silencieux.
3. **Conteneur** — image OCI (`Dockerfile` + `compose.yaml`) pour NAS / Raspberry Pi /
   serveur maison : volume pour la base, aucun port publié par défaut, healthcheck,
   doc Caddy en frontal TLS.
4. **Aucune dépendance à un service tiers** : pas d'API propriétaire, pas de
   fournisseur d'identité, pas de stockage objet. Un `git clone` + `uv sync` suffit.
5. **Distribution auto-hébergeable** : artefacts publiés sur GitHub Releases (gratuit),
   reconstruisibles depuis un fork ; la vérification de mise à jour accepte une URL de
   miroir arbitraire (`[update] channel = "https://mon-miroir/…"`) ou peut être coupée.
6. **Sauvegarde** — `yts export` (JSONL/CSV) et `VACUUM INTO` ; procédure documentée,
   aucune dépendance à l'app pour relire.

### 1.3 Open Core ou Open Source → **Open Source intégral**

Décision : **AGPL-3.0-or-later**, sans édition « Pro », sans clé de licence, sans
fonctionnalité bridée, sans télémétrie conditionnée à un abonnement.

Une promesse de confidentialité n'est **vérifiable** que si la totalité du code est
lisible et recompilable. Un cœur « open core » avec un module fermé rendrait la
promesse invérifiable et contredirait le principe de transparence.

L'AGPL (§13) couvre le seul scénario à risque : qu'un tiers repackage l'interface en
service réseau fermé sans publier ses modifications. Elle **n'empêche pas** l'usage
personnel, le self-hosting, la revente de prestations, ni le fork.

- `LICENSE` (texte verbatim AGPL-3.0) + `license = "AGPL-3.0-or-later"` dans `pyproject.toml` ;
- en-têtes SPDX dans les nouveaux fichiers ;
- `THIRD_PARTY.md` + textes de licence embarqués (AppImage : `usr/share/licenses/yt-word-search/`, `.app` : `Contents/Resources/licenses/`) ;
- lien « Code source (tag vX.Y.Z) » dans À propos (satisfait AGPL §6) ;
- `PRIVACY.md`, `CONTRIBUTING.md` (**en anglais**), `CODE_OF_CONDUCT.md` ;
- financement éventuel : dons uniquement ; marque/nom réservés pour éviter les builds trompeurs.

### 1.4 FLOSS (Free/Libre)

| Brique | Licence | Statut |
|---|---|---|
| Python ≥ 3.11 (python-build-standalone) | PSF-2.0 | libre, redistribuable |
| `yt-dlp` (binaire embarqué) | Unlicense | domaine public |
| SQLite | domaine public | libre |
| PyInstaller (bootloader) | GPL-2.0-or-later **+ exception** | bundling autorisé |
| `nfpm` (deb/rpm) | MIT | libre |
| `appimagetool` | MIT | libre |
| Police embarquée (si utilisée) | OFL-1.1 | libre |
| Frontend | **aucune lib tierce** (HTML/CSS/JS natif) | — |
| Icône / monogrammes | CC0, créés pour le projet | libre |

Aucune dépendance propriétaire, aucun binaire opaque autre que `yt-dlp` (provenance,
SHA-256 officiel et recette de compilation documentés). `SOURCE_DATE_EPOCH` fixé,
`SHA256SUMS` publié, SBOM CycloneDX généré ; reproductibilité bit-à-bit non garantie
avec PyInstaller — dit explicitement dans la doc.

---

## 2. Architecture

```
src/yt_search/
  gui/
    __init__.py
    server.py       # ThreadingHTTPServer, routage, jeton, statiques, en-têtes sécurité
    api.py          # handlers → JSON (fins, testables sans socket)
    jobs.py         # JobManager : 1 worker, anneau de progression, SSE
    static/
      index.html    # 5 écrans, zéro ressource externe
      app.js        # JS natif, fetch + EventSource, sans build step
      style.css     # clair/sombre via prefers-color-scheme, polices système
      i18n/fr.json  # chaînes UI (v1 : fr + en)
      i18n/en.json
      icons/        # SVG inline, CC0
  platform_paths.py # XDG (Linux) vs ~/Library/Application Support (macOS) + umask 077
  indexer.py        # + callback de progression (CLI inchangée)
  store.py          # + connexion par thread (WAL), + purge()
packaging/
  linux/  AppImage/AppRun, yt-word-search.desktop, icon.svg, nfpm.yaml, build.sh
  macos/  ytwordsearch.spec, Info.plist, entitlements, build_dmg.sh
  docker/ Dockerfile, compose.yaml, healthcheck
  ci/     build-linux.yml, build-macos.yml, release.yml
scripts/
  check_translations.py   # vérifie la fraîcheur des traductions (§3.5)
```

Entrées : `yts gui [--port 8765] [--no-browser] [--offline] [--lang fr|en] [--host] [--auth-token-file]`,
et un lanceur `yts-gui` (console_scripts) pour le double-clic.

### 2.1 API HTTP (loopback, JSON)

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/` | page unique (jeton en query, puis cookie `HttpOnly; SameSite=Strict`) |
| GET | `/api/status` | stats, config effective, langues disponibles, version app + yt-dlp, chemins |
| POST | `/api/index` | `{target, limit, langs, refresh, retry_errors}` → `{job_id}` |
| GET | `/api/jobs/{id}` | progression (`n/total`, vidéo courante, ETA, erreurs) |
| GET | `/api/jobs/{id}/events` | SSE (même flux, push) |
| POST | `/api/jobs/{id}/cancel` | arrêt propre |
| GET | `/api/search?q=&mode=&prefix=&channel=` | résultats groupés (réutilise `search.py`) |
| GET | `/api/videos?status=` | bibliothèque + statuts |
| POST | `/api/videos/{id}/retry` | rejouer une vidéo |
| GET | `/api/export?format=csv\|jsonl` | téléchargement |
| POST | `/api/privacy/purge` | efface index + config + cache (confirmation typée) |
| POST | `/api/shutdown` | quitter proprement |

### 2.2 Refactors du cœur (sans casser la CLI)

1. `Indexer.run(..., progress=None)` : callback d'événements au lieu des `print`.
2. `Store` : une connexion par thread/requête (WAL déjà en place).
3. `platform_paths.py` : chemins par OS + permissions `0700/0600`.
4. `doctor` exposé en fonction pour l'écran Diagnostic.
5. `pyproject.toml` : `name = "yt-word-search"`, `license`, `requires-python = ">=3.11"`
   (cohérence avec le venv 3.13 et la doc), `authors` **sans e-mail personnel**.

### 2.3 Écrans (FR + EN en v1, utilisateur lambda)

1. **Recherche** (accueil) — gros champ, Entrée = chercher ; mode discret
   (tous / au moins un / expression / proche) ; résultats groupés par vidéo :
   monogramme local, titre, chaîne, date, `01:39` + extrait surligné, bouton
   **« Ouvrir à 01:39 »**, bouton copier l'URL ; état vide pédagogique.
2. **Indexer** — un seul champ « Colle une URL de chaîne, de playlist ou de vidéo »,
   options repliées, barre de progression + journal + ETA, bouton Annuler.
3. **Bibliothèque** — tableau (statut, passages, date), filtres, actions « rejouer ».
4. **Réglages** — langues de sous-titres, `concurrency`, `sleep`, cookies navigateur
   (opt-in expliqué), chemin de base, **langue de l'interface**, thème, bloc
   Confidentialité (état des accès réseau, MAJ désactivée par défaut, « Effacer tout »).
5. **Diagnostic / À propos** — `doctor`, versions, licences tierces, lien source,
   bouton explicite « Mettre à jour yt-dlp ».

---

## 3. Distribution

### 3.1 Matrice des formats

| OS | Format | Chemin utilisateur | Remarque |
|---|---|---|---|
| Linux | **`.deb`** | double-clic → centre de logiciels → menu Applications | Debian, Ubuntu, Mint, Pop, Kali |
| Linux | **`.rpm`** | double-clic → menu Applications | Fedora, openSUSE, RHEL |
| Linux | **AppImage** | télécharger, `chmod +x`, lancer | distros restantes (Void…), universel |
| Linux | **`.tar.gz`** | décompresser, lancer `yts-gui` | secours sans FUSE, sans root |
| **Arch** | **`uv tool install` depuis le dépôt Git** | voir §3.2 | **voie unique retenue en v1** |
| macOS | **`.dmg`** universal2 | glisser dans Applications, puis Gatekeeper §3.4 | Intel + Apple Silicon |
| Tous | **conteneur OCI** | `podman compose up` | self-hosting NAS/serveur |
| Sources | `.tar.gz` + `git clone` | `uv sync && uv run yts gui` | vérifiabilité |

Détails Linux :
- AppImage **type 2** avec runtime statique ; la page de téléchargement rappelle
  `chmod +x` et le repli `--appimage-extract-and-run` si `libfuse2` est absent (Ubuntu 22.04+).
- `.deb`/`.rpm` générés par **`nfpm`** depuis un manifeste unique ; dépendances déclarées :
  **aucune** (Python et `yt-dlp` embarqués dans `/opt/yt-word-search`), `.desktop` + icône
  installés, aucun script réseau.
- Build **dans un conteneur Debian 11** (glibc 2.31) → compatible avec toutes les distros ≥ 2020.

### 3.2 Arch Linux — installation depuis le dépôt Git (`uv tool install`)

Voie **unique** en v1, et la plus simple : Arch fournit `uv` et `yt-dlp` dans `extra`,
le projet n'ayant **aucune dépendance Python**, l'installation est instantanée et
isolée (aucune pollution du Python système, aucun `makepkg`, aucun root après les
deux paquets).

```bash
sudo pacman -S uv yt-dlp                     # à lancer par l'utilisateur
uv tool install "git+https://github.com/goheakan/yt-word-search"
fish_add_path ~/.local/bin                   # ou ~/.local/bin dans le PATH
yts gui                                      # lancement
uv tool upgrade yt-word-search               # mise à jour = git pull + rebuild
```

- **Sans installation** (essai immédiat) : `uvx --from "git+https://github.com/goheakan/yt-word-search" yts search mot`
- **Équivalent pipx** (si l'utilisateur préfère) : `pipx install "git+…"` puis `pipx upgrade yt-word-search`
- **Version épinglée** pour la reproductibilité : `uv tool install "git+…@v1.0.0"`
- Désinstallation : `uv tool uninstall yt-word-search` (n'efface ni l'index ni la config ;
  « Effacer toutes les données » reste explicite dans l'UI).

**Hors périmètre v1 (reporté, §9)** : `PKGBUILD`, paquet `.pkg.tar.zst` attaché aux
releases, publication AUR (`yts-git`, `yts`). Raisons : ils ajoutent une maintenance
(`pkgver`, rebuilds) et des responsabilités d'empaqueteur qui n'apportent rien tant que
`uv tool install` couvre le besoin en une commande. Aucun travail d'empaquetage Arch
n'est donc produit aux jalons M9/M12.

**Critère d'acceptation v1** : sur un conteneur `archlinux:latest` vierge —
`pacman -Syu uv yt-dlp` → `uv tool install` → `yts doctor --network` → indexation d'une
vidéo → recherche → `yts gui` répond — **sans autre paquet installé**.

### 3.3 Détails macOS

- **universal2** : python-build-standalone universal2 + `yt-dlp_macos` universel ;
  aucune dépendance compilée tierce → universal2 trivial.
- `Info.plist` : `LSMinimumSystemVersion` = 11.0, `CFBundleIdentifier`,
  `NSHumanReadableCopyright`, pas de sandbox (l'app doit lancer `yt-dlp`).
- Signature **ad-hoc** en CI : `codesign --force --deep --sign - --options runtime`.
- `.dmg` via `hdiutil`, lien vers `/Applications`.

### 3.4 Procédure Gatekeeper (décision b — documentée, sans notarisation)

Pourquoi : signer et notariser exige un compte Apple Developer (99 $/an). Le projet
choisit la **signature ad-hoc** et assume une **étape manuelle unique** au premier
lancement. L'intégrité est garantie par `SHA256SUMS` + code source public, pas par Apple.

1. Télécharger le `.dmg` et vérifier l'empreinte : `shasum -a 256 ~/Downloads/*.dmg`
   → comparer à `SHA256SUMS`.
2. Ouvrir le `.dmg`, glisser **YT Word Search** dans **Applications**.
3. Premier lancement :
   - **macOS 15 et suivants** (le clic droit → Ouvrir a été supprimé) : double-clic →
     blocage → **Réglages Système → Confidentialité et sécurité** → « … a été bloqué » →
     **Ouvrir quand même** → Touch ID / mot de passe → **Ouvrir**.
   - **macOS ≤ 14** : clic droit (ctrl + clic) → **Ouvrir** → **Ouvrir**.
   - Terminal : `xattr -dr com.apple.quarantine "/Applications/YT Word Search.app"`.
4. Vérification de signature (optionnel) : `codesign --verify --deep --strict -v "…"`
   → `valid on disk` / `satisfies its Designated Requirement`.
5. Mises à jour : retélécharger le `.dmg` (aucune mise à jour automatique).

La doc précise aussi que `git clone` + `uv sync` n'est jamais bloqué (voie des
utilisateurs techniques).

### 3.5 Présentation multilingue du projet (obligatoire en v1)

La vitrine du projet (README, page de téléchargement, politique de confidentialité)
doit être lisible par un utilisateur non francophone : c'est une condition
d'accessibilité et de crédibilité FLOSS, pas un bonus.

**Langues v1** : `en` (source de vérité), `fr`, `es`, `de`, `pt-BR`, `zh-CN`
(six langues ; les suivantes se déclarent dans `docs/TRANSLATIONS.md`).

**Fichiers**
```
README.md               # anglais — source de vérité
README.fr.md            # français (traduction la plus à jour, maintenue par l'auteur)
README.es.md
README.de.md
README.pt-BR.md
README.zh-CN.md
PRIVACY.md / PRIVACY.fr.md / …        # mêmes langues (une promesse doit être lisible)
docs/TRANSLATIONS.md    # état, procédure, qui maintient quoi, langues manquantes
docs/GLOSSARY.md        # terminologie figée (indexer, passage, sous-titre auto, extrait…)
docs/screenshots/       # captures partagées par toutes les langues (pas de duplication)
```

**Règles**
1. **Barre de langues en tête de chaque README**, avec la langue courante non cliquable :
   `**English** · [Français](README.fr.md) · [Español](README.es.md) · [Deutsch](README.de.md) · [Português (BR)](README.pt-BR.md) · [简体中文](README.zh-CN.md)`
2. **Marqueur de fraîcheur** : `<!-- translation-of: README.md@<sha7> -->` en fin de
   fichier ; `scripts/check_translations.py` compare au dernier commit touchant
   `README.md` et signale « traduction en retard ». En CI : **avertissement**, pas échec
   bloquant (une traduction ne doit jamais bloquer une release).
3. **Glossaire obligatoire** : mêmes termes traduits de la même façon partout (sinon
   « passage »/« segment »/« extrait » divergent d'une langue à l'autre).
4. **Aucun service de traduction tiers** : traductions statiques versionnées ; pas de
   Google Translate/DeepL dans l'app ; pas de webfont par langue (polices système).
5. **Captures d'écran** : une seule série, référencée par tous les README (PNG < 300 Ko,
   thème sombre et clair), sinon le dépôt double de poids à chaque langue.
6. **`PRIVACY.md` traduit dans les six langues** — c'est le document dont la
   compréhension conditionne le consentement.
7. **`TUTO.md`** : français (existant) + anglais en v1 ; autres langues en phase 2
   (document long, à forte rotation).
8. **Non traduits en v1** : messages CLI/logs et messages d'erreur du moteur (anglais
   stable, évite de casser les tests) ; le **plan** lui-même (document interne).
9. **UI graphique** : `static/i18n/{fr,en}.json`, détection `navigator.language`,
   repli `en`, sélecteur dans Réglages, `--lang` en CLI. Les six langues du README
   rejoignent l'UI en v2 (l'infrastructure i18n est posée en v1).
10. **GitHub Pages** : même barre de langues, URL par langue (`/`, `/fr/`, `/es/`…),
    `<link rel="alternate" hreflang="…">` pour un référencement correct, sélecteur
    persistant (`localStorage` — local uniquement, aucune trace serveur).
11. **`CONTRIBUTING.md` en anglais** + section « Translations welcome » listant les
    langues à relire ; une traduction communautaire est acceptée si elle passe le
    script de fraîcheur et respecte le glossaire.

**Impact planning** : +0,5 j sur M8 (i18n UI fr/en) et +1 j sur M13 (six README,
`PRIVACY` multilingue, glossaire, script de vérification, barre de langues, Pages
multilingue). Aucun impact sur le reste.

**Critères d'acceptation** : chaque README affiche la barre de langues ; les liens
relatifs résolvent (`scripts/check_links.py`) ; `check_translations.py` ne signale que
des retards connus et documentés ; aucune requête vers un service de traduction ;
`PRIVACY` existe dans les six langues.

---

## 4. Hébergement (GitHub, gratuit, auto-hébergeable)

- **GitHub Releases** : artefacts + `SHA256SUMS` + SBOM (CycloneDX) + archive source
  automatique. Liens stables `releases/latest/download/<asset>`. Coût 0 €.
- **GitHub Actions** : builds Linux (conteneur Debian 11) et macOS (universal2),
  gratuits et illimités sur dépôt **public** ; matrice pilotée par tag `v*`.
- **GitHub Pages** : page de téléchargement statique multilingue (détection d'OS en JS,
  un bouton par plateforme, captures, section « vérifier l'intégrité »). Pages ne sert
  **que** de vitrine : l'UI de l'app reste locale (une page `https://` ne peut pas
  appeler `http://127.0.0.1` — mixed content).
- **Miroir** : toute release est reconstructible depuis un fork (`packaging/ci/` réutilisable).

### 4.1 Mise à jour de `yt-dlp` (risque n°1 dans le temps)

1. Binaire embarqué **inscriptible** : hors AppImage (lecture seule), copié au premier
   lancement dans le dossier de données puis mis à jour sur place (`yt-dlp -U`).
2. Bouton explicite « Mettre à jour yt-dlp » (Diagnostic), version avant/après.
3. Vérification de mise à jour **opt-in, coupée par défaut** (GitHub Releases pour
   l'app, PyPI pour `yt-dlp`) ; l'écran Réglages dit exactement quelles requêtes sont
   faites et vers qui.

---

## 5. Jalons

| Jalon | Contenu | Estim. |
|---|---|---|
| **M6** | Refactors cœur : callback de progression, `Store` thread-safe, `platform_paths` + permissions, `doctor` en fonction, `purge()`, `pyproject` (nom, licence, python ≥3.11), tests | 1 j |
| **M7** | `gui/server.py` + `api.py` + `jobs.py` : jeton, `Host`/CSP/no-referrer, instance unique, SSE ; tests d'API sans navigateur | 2 j |
| **M8** | Frontend 5 écrans : monogrammes locaux, surlignage, SSE, état vide, clavier, **i18n fr/en** (`static/i18n/`) | 3 j |
| **M9** | Linux : `nfpm` (.deb/.rpm), AppImage, `.tar.gz`, `.desktop` + icône CC0, build Debian 11, test Ubuntu/Fedora/Arch | 2 j |
| **M10** | macOS : `.app` + `.dmg` universal2, signature ad-hoc, procédure Gatekeeper, test Intel + ARM | 2 j |
| **M11** | Self-hosting : `Dockerfile` + `compose.yaml` + healthcheck + doc Caddy/TLS + `--host` avec jeton | 1 j |
| **M12** | Release : `release.yml`, `SHA256SUMS`, SBOM, Pages **multilingue**, MAJ opt-in, miroir documenté, **validation `uv tool install` sur Arch vierge (§3.2)** | 1,5 j |
| **M13** | Conformité & doc : `LICENSE` AGPL verbatim, SPDX, `THIRD_PARTY.md`, `PRIVACY` ×6, `CONTRIBUTING` (EN), glossaire, **6 README + script de fraîcheur**, `TUTO` FR/EN, release `v1.0.0` | 2,5 j |

Total v1 : **≈ 15–18 jours** de travail effectif.

**Phase 2 (hors périmètre, §9)** : M14 empaquetage Arch (PKGBUILD + `.pkg.tar.zst` +
AUR), M15 notarisation Apple, M16 Flatpak, M17 coquille native `--window`, M18 ASR local.

---

## 6. Tests & critères d'acceptation

**Automatisés (pytest)**
- API : `status`, `search` (4 modes), `index` (job simulé), `cancel`, `export`, `purge`,
  refus sans jeton, refus si `Host` invalide.
- Sécurité : CSP / no-referrer / nosniff présents ; cookie `HttpOnly`.
- Permissions : base `0600`, dossier `0700`.
- Anti-régression : aucune URL externe dans `static/` ; aucune chaîne UI manquante
  entre `fr.json` et `en.json` (`check_i18n.py`).
- Traductions : `check_translations.py` + `check_links.py` (avertissement non bloquant).
- Non-régression CLI : suite existante (19 tests) verte.

**Manuels (checklist de release)**
- `ss -tlnp` → loopback seul ; `lsof -i` pendant une recherche → rien.
- UI complète avec réseau coupé (hors indexation) ; bascule FR/EN correcte.
- `.deb` sur Ubuntu 22.04 propre : menu → recherche → résultat → YouTube.
- `.rpm` sur Fedora ; AppImage sur Void (avec et sans `libfuse2`) ; `.tar.gz` sans FUSE.
- **Arch vierge : `uv tool install` → `yts doctor` → recherche → `yts gui`, sans paquet supplémentaire.**
- macOS Intel + ARM : `.dmg` → Gatekeeper → recherche → lien `&t=` correct.
- Conteneur : `podman compose up` sur NAS, accès LAN avec jeton, port non publié par défaut.
- Rendu des six README sur GitHub (barre de langues, captures, liens).

---

## 7. Risques et parades

| Risque | Parade |
|---|---|
| YouTube casse `yt-dlp` | MAJ assistée (bouton), binaire inscriptible, avertissement de version, doc « 0 résultat » |
| AppImage sans FUSE (Ubuntu 22.04+) | `.deb`/`.rpm` en chemin principal + `.tar.gz` + `--appimage-extract-and-run` |
| Glibc trop récente au build | build en conteneur Debian 11, vérifié sur Arch/Fedora |
| Gatekeeper bloque sur macOS | procédure §3.4 documentée avec captures ; intégrité via `SHA256SUMS` |
| Traductions qui divergent / se périmer | glossaire + marqueur `translation-of` + script de fraîcheur en CI |
| AGPL mal comprise | section « licence en clair » dans le README (6 langues) |
| Promesse de confidentialité non tenue dans le temps | tests CI anti-régression (aucune URL externe, aucune connexion pendant la recherche), `PRIVACY` versionné, revue à chaque release |
| Dérive « open core » | décision écrite : aucune fonctionnalité conditionnée à un paiement ; dons uniquement |

---

## 8. Hors périmètre assumé (v1)

- Pas de réécriture Rust/Tauri ; coquille native `pywebview` seulement en option future.
- Pas d'Electron (+150 Mo), pas de Qt/Tk (dépendances système fragiles).
- Pas de cloud, pas de comptes, pas de SaaS, pas de télémétrie.
- Pas de notarisation Apple, pas de Flatpak, pas d'AUR/PKGBUILD (phase 2 §9).
- ASR local (whisper.cpp/faster-whisper) = jalon M4 du plan d'origine ; l'UI prévoit
  l'emplacement du bouton.

---

## 9. Phase 2 (reportée, décisions déjà prises)

| Élément | Condition de déclenchement |
|---|---|
| `PKGBUILD` + `.pkg.tar.zst` + AUR (`yts-git`, `yts`) | demande utilisateur Arch, ou v1 stable depuis ≥ 3 mois |
| Notarisation Apple (`Developer ID`) | achat du compte 99 $/an |
| Flatpak (mises à jour silencieuses) | demande utilisateur Linux desktop |
| Coquille native `--window` (pywebview) | retour d'utilisateurs sur l'onglet navigateur |
| UI dans les 6 langues | infrastructure i18n posée en v1 |

---

## 10. Livrables finaux v1

1. Interface graphique locale complète (5 écrans, FR + EN).
2. `yts gui` + lanceur `yts-gui`.
3. `yt-word-search-<ver>-x86_64.AppImage`, `yt-word-search_<ver>_amd64.deb`,
   `yt-word-search-<ver>.x86_64.rpm`, `yt-word-search-<ver>-linux-x86_64.tar.gz`.
4. `YT-Word-Search-<ver>-universal.dmg` (ad-hoc signé).
5. Image OCI + `compose.yaml` (self-hosting).
6. `SHA256SUMS`, SBOM CycloneDX, archive source.
7. Page GitHub Pages de téléchargement **multilingue**.
8. `LICENSE` (AGPL-3.0 verbatim), `THIRD_PARTY.md`, `PRIVACY.md` ×6, `CONTRIBUTING.md` (EN),
   `docs/GLOSSARY.md`, `docs/TRANSLATIONS.md`, `README.md` ×6, `TUTO.md` FR + EN.
9. Installation documentée pour Arch : **`uv tool install "git+https://github.com/goheakan/yt-word-search"`**.
