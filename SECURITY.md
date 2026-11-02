# Security

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's private
[Report a vulnerability](https://github.com/viki22uied/Deepworkai/security/advisories/new) form.
You'll get a reply within 7 days, and a fix or mitigation plan within 30 days for confirmed issues.
Only the latest release receives security fixes.

## How Deep Work AI protects you

Deep Work AI runs entirely on your PC. There is no Deep Work AI server, account or telemetry.
The controls below are mapped to the [OWASP Application Security Verification Standard (ASVS) 4.0](https://owasp.org/www-project-application-security-verification-standard/)
and the [OWASP Desktop App Security Top 10](https://owasp.org/www-project-desktop-app-security-top-10/).

| Area | Control | Standard |
|---|---|---|
| Authentication | Local service requires a random 192-bit session key (regenerated every start, compared in constant time); only `PING` is unauthenticated | ASVS V2, V3 |
| Access control | Service listens on 127.0.0.1 only; `data/` and the key file are restricted to the current Windows user | ASVS V4, DA-Top10 DA2 |
| Input validation | Command allow-list, 4 KB line limit, numeric/ID validation, parameterised SQL everywhere, `GITHUB_REPO` and branch names validated/encoded before use in API URLs | ASVS V5, CWE-89, CWE-20 |
| Injection | No shell execution of user data; `cmd.exe` metacharacters rejected before calling editor CLIs; PowerShell fallback only accepts plain executable names; browser restore only passes `http(s)` URLs (no flag injection) | ASVS V5.3, CWE-78, CWE-88 |
| Untrusted content | Notification text rendered as plain text (no HTML); "Open" only follows `http(s)` links; Slack opener only `slack://` | ASVS V5.3, CWE-79, CWE-601 |
| Secrets | API tokens encrypted at rest with Windows DPAPI (current-user scope); never logged; startup warning if any are left in plain text in `.env` | ASVS V6, V8.1, CWE-312 |
| Cryptography | OS-provided primitives only (`secrets`, DPAPI); no custom crypto | ASVS V6.2 |
| Logging | Logs record command names and outcomes only — never message text, senders, notes, file names, URLs or tokens | ASVS V7.1, CWE-532 |
| Data protection | Window titles and URLs redacted before storage (emails, tokens, query secrets); secret URL parameters stripped from snapshots; automatic deletion after `DEEPWORKAI_RETENTION_DAYS` (default 14) | ASVS V8.3, GDPR data minimisation |
| Availability | Max 32 concurrent clients, 2 s read timeout, bounded queries and caches | ASVS V11, CWE-400 |
| Network | Offline by default; optional GitHub/Jira/Slack calls use HTTPS with certificate verification; `DEEPWORKAI_OFFLINE=1` disables all of them | ASVS V9, DA-Top10 DA8 |
| Side effects | Focus Shield never closes windows or kills apps unless `DEEPWORKAI_BLOCK_DISTRACTIONS=1`; debugger keys are only sent when VS Code/Cursor is in front; nothing restores or launches apps without a key press or dial turn | CWE-1188 |
| Test isolation | The test suite cannot start programs, open browsers or press keys on the machine running it (enforced for every test, with a test proving the guard works) | — |
| Dependencies | Runtime dependencies scanned (`pip-audit`, `npm audit --omit=dev`): 0 known vulnerabilities at release | ASVS V14.2, DA-Top10 DA9 |
| Code analysis | `bandit` static analysis: 0 medium/high findings (justified exceptions are annotated `# nosec` with a reason) | ASVS V14 |

Automated tests in `tests/test_security.py` cover authentication, injection guards, URL handling,
log hygiene, secret stripping and denial-of-service limits.

## Known limitations

- **Databases are not encrypted at rest.** They are protected by Windows file permissions. Use
  BitLocker (or another full-disk encryption) on shared or portable machines.
- **Same-user malware is out of scope.** Software running as your Windows user can read your files,
  just like it can read your browser profile.
- **DPAPI vault is Windows-only.** On other systems, supply tokens through environment variables.
- **Python is located through `PATH`** when no explicit interpreter is configured.

## Checking a release yourself

```bash
pip install bandit pip-audit
```
```bash
bandit -r deepworkai -ll
```
```bash
pip-audit -r requirements.txt
```
```bash
cd deepworkai/plugin && npm audit --omit=dev
```
