# Photobooth (Dummy)

Local-first event photobooth. This repository is the **Dummy** development source (branch `dummy`).
Main is a separate clone created only after explicit approval (see `Project_Docs\PROJECT_RULES.md`).

## Layout

```
Dummy\
  app\        this repo (backend, frontend, e2e, scripts)
  data\       runtime only: db, storage, backups, logs, verify records (never in git)
  config\     photobooth.env + runtime\pairing.code (never in git)
  tools\node24\   portable Node 24 LTS used by all scripts
```

## Toolchain

- Python 3.13 venv from the exact lock (from `backend\`):
  `py -3.13 -m venv .venv`, `.venv\Scripts\python.exe -m pip install -r requirements-dev.lock`,
  `.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .`.
  `verify.ps1` fails on any drift (`scripts\guards\python_lock.py check`). After an intentional
  dependency change, install it and regenerate with `python_lock.py write`.
- Frontend/e2e: `npm ci` (package-lock.json) with Node 24.
- Node 24 LTS only (`.nvmrc`, `engines`, `engine-strict`). Scripts put `Dummy\tools\node24` first on PATH.
- `git config --local core.hooksPath .githooks` enables the staged-content guard.

## Commands (PowerShell, from `Dummy\app`)

| Purpose | Command |
|---|---|
| Start Dummy + pair browser | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-dummy.ps1` |
| Re-pair browser | `... -File scripts\run-dummy.ps1 -PairOnly` |
| Stop Dummy | `... -File scripts\stop-dummy.ps1` |
| Full gate | `... -File scripts\verify.ps1` |
| E2E only | `... -File scripts\e2e.ps1` |
| Secret guard | `... -File scripts\check-staged.ps1 -Tracked` |
| Patch dry run | `... -File scripts\make-patch.ps1 -Number 001 -Slug project-foundation -Commit <sha> -DryRun` |

## Ports

| Instance | Kiosk API (127.0.0.1) | Delivery (LAN) | UI |
|---|---|---|---|
| Dummy dev | 8111 | 8113 | Vite 5191 |
| Dummy e2e (temp instance) | 8112 | 8114 (127.0.0.1) | preview 5192 |
| Main | 8121 | 8123 | served by kiosk |

## Security groundwork

- Kiosk listener binds loopback only and rejects non-allowlisted `Host` headers.
- Delivery listener exposes only delivery routes (Phase 1: `/d/_alive`); everything else is a uniform 404.
- Every `/api/booth/*` and `/api/admin/*` route requires the kiosk device cookie, obtained by consuming a
  single-use 60-second pairing code from `config\runtime\pairing.code`.
- Pairing-code rotation is launcher-only: the caller sends `X-Photobooth-Launcher` with the per-process
  token from `config\runtime\launcher.token` (both runtime files are cleared when the backend stops).
- `db-upgrade` / `db-downgrade` refuse a database stamped for another instance before any schema change.
- The env file is authoritative: process environment variables are never read for settings; launchers
  also clear inherited `PHOTOBOOTH_*` variables and pass `--expect-root` / `--expect-profile`.
- Booth/admin mutations require the device cookie **and** an exact allowed `Origin` (this instance's kiosk
  and UI ports) **and** the `X-Photobooth-CSRF` token from a same-origin read of `/api/kiosk/status`.
- Playwright browsers are installed only into `Dummy\data\playwright-browsers`
  (`PLAYWRIGHT_BROWSERS_PATH`); the shared user browser cache is never used or modified.
- Logs redact delivery tokens, pairing codes, device cookies and secret assignments.
