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

- Python 3.13 venv: `backend\.venv` (`py -3.13 -m venv backend\.venv`, then `backend\.venv\Scripts\python.exe -m pip install -e "backend[dev]"`)
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
- Logs redact delivery tokens, pairing codes, device cookies and secret assignments.
