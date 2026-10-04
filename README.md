# Photobooth

A local-first event photobooth for Windows: guests choose a frame, take photos with the booth's
camera, decorate them with stickers and a filter, and take them home by scanning a QR code with a
phone on the same Wi-Fi. Organizers prepare events (profiles, frames, themes, retention) in Admin.
Everything runs on the booth PC; nothing is sent to the internet.

## Install on Windows (from GitHub)

Tested on Windows 11 with Windows PowerShell 5.1. The first install downloads the locked Python and
Node packages, so it needs internet access once; it takes about 5 to 10 minutes.

### Prerequisites

- Windows 10 or 11 (64-bit), a webcam, and Chrome or Edge.
- Git and Python 3.13 with the `py` launcher. If you do not have them (in PowerShell):

  ```powershell
  winget install --id Git.Git -e
  winget install --id Python.Python.3.13 -e
  ```

  Open a new PowerShell window afterwards so both are on `PATH` (`git --version`, `py -3.13 --version`).

### Install

Copy and paste into PowerShell. `C:\Photobooth` can be any folder without special characters; the
`Dummy\app` and `Dummy\tools\node24` names inside it are required by the scripts.

```powershell
$root = 'C:\Photobooth'
New-Item -ItemType Directory -Force "$root\Dummy\tools" | Out-Null
git clone https://github.com/ChocolateOwO/Photobooth.git "$root\Dummy\app"

# Node.js 24 (portable copy used only by the Photobooth scripts)
$node = 'v24.21.0'
Invoke-WebRequest "https://nodejs.org/dist/$node/node-$node-win-x64.zip" -OutFile "$env:TEMP\node-$node.zip"
Expand-Archive "$env:TEMP\node-$node.zip" "$root\Dummy\tools" -Force
Rename-Item "$root\Dummy\tools\node-$node-win-x64" node24

# Install the published release into C:\Photobooth\Main
Set-Location "$root\Dummy\app"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-main.ps1 -Release dummy-patch-008-sticker-corner-handles
```

The installer checks the release tag (approved commit, approval and test records), builds the booth
into `C:\Photobooth\Main`, creates an empty database, and **asks you for a new admin password**
(at least 12 characters, typed twice). It then starts the booth once, checks it, and stops it.
It never overwrites an existing `Main` folder; if anything fails it moves the half-built folder
aside to `Main.failed-<date>` and says why.

### Start, stop and pair

```powershell
# Start (opens the browser and pairs it as the booth screen)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Photobooth\Main\app\scripts\run-main.ps1

# Stop
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Photobooth\Main\app\scripts\stop-main.ps1

# Pair the browser again (for example after a restart)
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Photobooth\Main\app\scripts\run-main.ps1 -PairOnly
```

| Screen | Address (on the booth PC) |
|---|---|
| Booth (guests) | http://127.0.0.1:8121/booth |
| Admin (organizers; user `admin`, your password) | http://127.0.0.1:8121/admin |
| Start page (version and health) | http://127.0.0.1:8121/ |

First steps in Admin: Event Profiles → New profile (title, colours, photo sizes, countdown,
retakes, retention policy) → Activate; Frames → upload your event's transparent PNG frames;
Test booth → try the camera. Then open the Booth address in the paired browser and tap once for
fullscreen.

To change the admin password later, stop the booth first, then:

```powershell
C:\Photobooth\Main\app\backend\.venv\Scripts\python.exe -m photobooth admin-set-password --env-file C:\Photobooth\Main\config\photobooth.env --expect-root C:\Photobooth\Main --expect-profile prod
```

### Phones and the QR code (LAN only)

- Guests' phones must be on the **same Wi-Fi** as the booth PC, and that Wi-Fi must not isolate
  clients from each other (many guest and hotel networks do; a phone hotspot or your own router works).
- The phones reach the booth on port **8123**. When Windows asks on the first start, allow
  Python on **Private** networks (set the Wi-Fi to Private in Windows settings).
- Admin → System shows the address the phones use. The link in each QR code works for the
  number of days the event's retention policy allows (7 by default).

### Where the data is

| What | Where |
|---|---|
| Database (events, visits, history) | `C:\Photobooth\Main\data\db\photobooth.sqlite` |
| Photos, finished photos, uploaded frames and images | `C:\Photobooth\Main\data\storage\` |
| Database backups | `C:\Photobooth\Main\data\backups\` |
| Logs | `C:\Photobooth\Main\data\logs\` |
| Settings | `C:\Photobooth\Main\config\photobooth.env` |
| Pairing code and launcher token (while running) | `C:\Photobooth\Main\config\runtime\` |

Guests' photos are deleted automatically when the event's retention policy says (Admin →
Retention; defaults: original photos 7 days, finished photos 30 days). A safe backup of the
database at any time:

```powershell
C:\Photobooth\Main\app\backend\.venv\Scripts\python.exe -m photobooth backup --env-file C:\Photobooth\Main\config\photobooth.env --expect-root C:\Photobooth\Main --expect-profile prod
```

No data, password or photo is part of this repository.

## For developers (the Dummy instance)

The `dummy` branch is the development source. A development instance ("Dummy", with a DUMMY badge,
Vite on port 5191 and its own data) runs from `<folder>\Dummy\app`; Main is a separate clone made by
`scripts\install-main.ps1` from an approved milestone tag (see `Project_Docs\PROJECT_RULES.md`).
### Layout

```
Dummy\
  app\        this repo (backend, frontend, e2e, scripts)
  data\       runtime only: db, storage, backups, logs, verify records (never in git)
  config\     photobooth.env + runtime\pairing.code (never in git)
  tools\node24\   portable Node 24 LTS used by all scripts
```

### Toolchain

- Python 3.13 venv from the exact lock (from `backend\`):
  `py -3.13 -m venv .venv`, `.venv\Scripts\python.exe -m pip install -r requirements-dev.lock`,
  `.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .`.
  `verify.ps1` fails on any drift (`scripts\guards\python_lock.py check`). After an intentional
  dependency change, install it and regenerate with `python_lock.py write`.
- Frontend/e2e: `npm ci` (package-lock.json) with Node 24.
- Node 24 LTS only (`.nvmrc`, `engines`, `engine-strict`). Scripts put `Dummy\tools\node24` first on PATH.
- `git config --local core.hooksPath .githooks` enables the staged-content guard.

### Commands (PowerShell, from `Dummy\app`)

| Purpose | Command |
|---|---|
| Start Dummy + pair browser | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-dummy.ps1` |
| Re-pair browser | `... -File scripts\run-dummy.ps1 -PairOnly` |
| Stop Dummy | `... -File scripts\stop-dummy.ps1` |
| Full gate | `... -File scripts\verify.ps1` |
| E2E only | `... -File scripts\e2e.ps1` |
| Secret guard | `... -File scripts\check-staged.ps1 -Tracked` |
| Set admin password (booth stopped) | `backend\.venv\Scripts\python.exe -m photobooth admin-set-password --env-file ..\config\photobooth.env --expect-root <Dummy root> --expect-profile dev` |
| Patch dry run | `... -File scripts\make-patch.ps1 -Number 001 -Slug project-foundation -Commit <sha> -DryRun` |

### Ports

| Instance | Kiosk API (127.0.0.1) | Delivery (LAN) | UI |
|---|---|---|---|
| Dummy dev | 8111 | 8113 | Vite 5191 |
| Dummy e2e (temp instance) | 8112 | 8114 (127.0.0.1) | preview 5192 |
| Main | 8121 | 8123 | served by kiosk |

### Photo templates (Phase 2)

Code-defined, versioned, read-only JSON in `backend/src/photobooth/templates_data/<key>.v<N>.json`.
Spec API, blank PNG, guide PNG, renderer and (later) frame validator all read the same definition.

| Template | Physical | Canvas @ 300 DPI | Photos per output | Captures / outputs |
|---|---|---|---|---|
| `strip_2x6` v1 | 2 x 6 in | 600 x 1800 | 3 (4:3) | 6 captures -> 2 strips (1-3, 4-6), no reuse |
| `print_3x4` v1 | 3 x 4 in | 900 x 1200 | 2 (3:2) | 2 -> 1 |
| `print_4x6` v1 | 4 x 6 in | 1200 x 1800 | 4 (3:4, 2x2) | 4 -> 1 |

| Endpoint (kiosk listener, GET only) | Returns |
|---|---|
| `/api/templates` | all latest templates with links |
| `/api/templates/{key}?version=N` | full spec: slots, safe area, branding area, frame rules, frame requirements text |
| `/api/templates/{key}/blank.png` | transparent RGBA canvas at exact size and DPI (frame starting point) |
| `/api/templates/{key}/guide.png` | labeled guide: slots with x/y/w/h, safe area, branding area |
| `/api/render/samples/{key}/{n}.jpg` | output n rendered server-side with numbered placeholder photos |

Renderer: each capture is center cover-cropped into its slot, optional RGBA frame composited on top,
exported as sRGB JPEG q95 with 300 DPI metadata. A session must supply exactly the template's captures;
a capture is never placed twice.

### Admin and Event Profiles (Phase 3, backend only)

All routes need the paired device and an admin session; mutations also need Origin, the device key and
`X-Photobooth-Admin-CSRF` (returned by login and `GET /api/admin/auth/session`).

| Endpoint | Purpose |
|---|---|
| `POST /api/admin/auth/login`, `GET .../session`, `POST .../logout` | Argon2id login, device-bound session cookie |
| `POST /api/admin/assets` (multipart `kind`=logo/background, `file`) | validated PNG/JPEG upload |
| `GET /api/admin/assets/{id}`, `GET /api/admin/assets/{id}/content` | metadata, image bytes |
| `GET/POST /api/admin/profiles` (`?include_deleted=true`) | list, create |
| `GET/PUT/DELETE /api/admin/profiles/{id}` (PUT body and DELETE query carry `revision`) | read, edit, soft delete |
| `POST /api/admin/profiles/{id}/duplicate`, `/activate`, `/restore` | copy, make the only active profile, undelete |

Frames are not uploaded here: organizers make finished transparent PNG frames outside the app (Phase 5).

### Admin UI (Phase 4)

Open `/admin` on the paired kiosk browser (Dummy dev: `http://127.0.0.1:5191/admin`). Create the admin
account first with `admin-set-password` while the booth is stopped.

- Sign in / sign out; an expired session returns to the sign-in form without showing data.
- Event Profiles list: create, edit, duplicate, activate (one active), soft delete with confirmation, restore.
- Editor: preparation-screen title, subtitle, start-button text, colors, logo and background upload with
  preview, enabled layouts, mirror, inactivity timeout, retakes; fixed 5 s countdown and LAN QR delivery shown
  read-only; live 16:9 preparation-screen preview; stale edits are refused with "Reload latest".
- All data access goes through `frontend/src/shared/api/adminClient.ts` (generated OpenAPI types) and the hooks
  in `frontend/src/features/admin/api/`.

UI pages in `frontend/src/features/admin/{pages,components}` were produced by Antigravity running as the
restricted Windows account `pb-ui-agent` (write access only to `Dummy\ui-work\frontend\src` and `public`),
then reviewed and integrated by Claude. See `Project_Docs\DECISIONS.md` (P4 rows).

### Security groundwork

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
  and UI ports) **and** the `X-Photobooth-Device-Key` issued at pairing (delivered only in the redirect
  fragment, kept in the UI origin's storage, never returned by any endpoint).
- Playwright browsers are installed only into `Dummy\data\playwright-browsers`
  (`PLAYWRIGHT_BROWSERS_PATH`); the shared user browser cache is never used or modified.
- Logs redact delivery tokens, pairing codes, device cookies and secret assignments.
