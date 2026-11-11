# Security policy

`yts` reads untrusted data (YouTube titles, subtitles, metadata) and writes it to
your disk. This page states what is guaranteed, what is out of scope, and how to
report a problem.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |
| older | no — upgrade with `uv tool upgrade yt-word-search` |

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Use GitHub private vulnerability reporting:
<https://github.com/goheakan/yt-word-search/security/advisories/new>

If that is unavailable, open an issue titled `security: contact request` with no
details, and a maintainer will provide a private channel.

Best effort: acknowledgement within 7 days, coordinated disclosure within 90 days.
Credit is given unless you ask otherwise. There is no bug bounty.

## Threat model

### In scope

The following classes are treated as vulnerabilities and fixed:

| Class | Example |
|---|---|
| Command / argument injection | a crafted URL reaching `yt-dlp` as an option (`--exec`) |
| SSRF | a caption URL in video metadata pointing at `127.0.0.1` or the LAN |
| Resource exhaustion | unbounded response read, unbounded query result |
| Terminal escape injection (CWE-150) | a title containing `ESC ]52` writing to the clipboard |
| CSV / spreadsheet formula injection (CWE-1236) | a title starting with `=` executed on open |
| Local data exposure | index readable by other local accounts, cookies written to disk |
| SQL / FTS injection | query operators injected through `yts search` arguments |
| Supply chain | compromised dependency, mutable GitHub Actions tag |

### Out of scope

- **YouTube content itself.** Titles and transcripts are untrusted by definition;
  the tool neutralises control characters before display but the text is still
  whatever the channel published.
- **`yt-dlp`.** It is a separate project invoked as a subprocess with a sanitised
  argument list. A vulnerability in `yt-dlp` should be reported upstream; here we
  only pin the minimum documented version and surface it in `yts doctor`.
- **Local attackers with your user account.** A process running as you can read
  the index, and no file permission can prevent that.
- Machine-in-the-middle on a compromised network: subtitle traffic is HTTPS, but
  certificate trust depends on your system store.
- Denial of service against YouTube (rate limits, account bans): `yts` throttles
  requests (`sleep_requests`, default 0.7 s) but cannot prevent them.

## Guarantees enforced by the code

These are checked by tests (`tests/test_security.py`) rather than promised in prose:

1. Index directory `0700`, index file `0600` — re-applied every time the database
   is opened, so a permissive umask cannot weaken it.
2. Every URL handed to `yt-dlp` is validated (`http`/`https` only, no leading
   `-`) and passed after `--`, so it can never be parsed as an option.
3. Caption downloads are restricted to `https` plus a host allowlist
   (`youtube.com`, `googlevideo.com`, `ytimg.com`, `googleusercontent.com`), the
   redirect target is re-checked, and the body is capped at 8 MiB.
4. Terminal output strips C0/C1 control characters from titles, channels,
   snippets, errors and yt-dlp diagnostics.
5. CSV exports prefix `=`, `+`, `-`, `@` with an apostrophe.
6. No network activity other than `yt-dlp` and the caption fetch; no telemetry,
   no account, no update check at startup.
7. Browser cookies, when `--cookies-from-browser` is used, are handed to `yt-dlp`
   as a flag and never copied, logged or stored by `yts`.

## Verifying a release

```bash
# port listenant : loopback uniquement, et rien pendant une recherche
ss -tlnp | grep yts

# droits des donnees
stat -c '%a %n' ~/.local/share/yt-word-search ~/.local/share/yt-word-search/index.db

# aucune ressource externe dans le depot
grep -rn "https\?://" --include='*.py' src/ | grep -v youtube
```

Reports that contradict one of these points are especially welcome.
