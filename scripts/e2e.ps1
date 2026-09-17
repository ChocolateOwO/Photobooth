# Playwright smoke test against a throwaway e2e instance under %TEMP% (never Dummy data).
# Ports: kiosk 8112, delivery 8114 (bound to 127.0.0.1), vite preview 5192.
# Playwright browsers are isolated in Dummy\data\playwright-browsers (shared user cache untouched).
[CmdletBinding()]
param([switch] $SkipBuild)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-DummyLayout
Clear-PhotoboothEnvironment
$null = Use-Node24
$python = Get-VenvPython
$browsers = Use-IsolatedPlaywrightBrowsers

foreach ($port in 8112, 8114, 5192) {
    if (-not (Test-PortFree -Port $port)) { throw "E2E port $port is busy" }
}

$frontend = Join-Path $script:AppRoot 'frontend'
$e2eDir = Join-Path $script:AppRoot 'e2e'
$root = Get-ThaiTempRoot -Prefix 'pb-e2e'
$exitCode = 1
try {
    $envFile = Join-Path $root 'config\photobooth.env'
    Invoke-Native $python @('-m', 'photobooth', 'init-env', '--instance', 'dummy', '--profile', 'e2e',
        '--instance-root', $root, '--output', $envFile, '--kiosk-port', '8112',
        '--delivery-port', '8114', '--delivery-host', '127.0.0.1')
    Invoke-Native $python @('-m', 'photobooth', 'db-upgrade', '--env-file', $envFile,
        '--expect-root', $root, '--expect-profile', 'e2e')

    # Throwaway admin account for this e2e instance only (random password, never written to disk).
    $adminPassword = 'e2e-' + [guid]::NewGuid().ToString('N')
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $adminPassword | & $python -m photobooth admin-set-password --env-file $envFile `
            --expect-root $root --expect-profile e2e --username admin --password-stdin
        if ($LASTEXITCODE -ne 0) { throw "admin-set-password exited with $LASTEXITCODE" }
    }
    finally { $ErrorActionPreference = $previousPreference }

    # Upload fixtures: a small transparent PNG logo and a JPEG background.
    $fixtures = Join-Path $root 'fixtures'
    New-Item -ItemType Directory -Force -Path $fixtures | Out-Null
    # Single quotes only: Windows PowerShell 5.1 drops embedded double quotes in native arguments.
    Invoke-Native $python @('-c', 'import sys; from PIL import Image; d=sys.argv[1]; Image.new(''RGBA'',(256,128),(255,176,32,200)).save(d+''/logo.png''); Image.new(''RGB'',(1280,720),(40,90,160)).save(d+''/background.jpg'', quality=90)', $fixtures)

    if (-not $SkipBuild) {
        $env:PHOTOBOOTH_INSTANCE = 'dummy'
        Invoke-Native 'npm.cmd' @('run', 'build') $frontend
    }

    # Installs only into the isolated browsers path (no-op when already present).
    Invoke-Native 'npx.cmd' @('playwright', 'install', 'chromium') $e2eDir
    Write-Host "Playwright browsers: $browsers"

    $env:PHOTOBOOTH_E2E_ENV_FILE = $envFile
    $env:PHOTOBOOTH_E2E_PYTHON = $python
    $env:PHOTOBOOTH_E2E_FRONTEND_DIR = $frontend
    $env:PHOTOBOOTH_E2E_INSTANCE_ROOT = $root
    $env:PHOTOBOOTH_E2E_ADMIN_PASSWORD = $adminPassword
    $env:PHOTOBOOTH_E2E_FIXTURES = $fixtures
    Push-Location $e2eDir
    $ErrorActionPreference = 'Continue'
    try {
        # Phase 1: everything except the restart checks. Playwright stops the backend at the end.
        & npx.cmd playwright test --grep-invert '@after-restart'
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            # Phase 2: a fresh backend process on the same instance data proves persistence.
            & npx.cmd playwright test --grep '@after-restart'
            $exitCode = $LASTEXITCODE
        }
    }
    finally {
        $ErrorActionPreference = 'Stop'
        Pop-Location
    }

    # No pairing code or device cookie value may appear in the instance logs.
    $logs = Join-Path $root 'data\logs'
    if (Test-Path $logs) {
        $leak = Get-ChildItem $logs -File | Select-String -Pattern 'code=(?!\[REDACTED\])[A-Za-z0-9_-]{20,}'
        if ($leak) { throw "Secret material found in e2e logs: $($leak[0])" }
    }
}
finally {
    Remove-Item Env:PHOTOBOOTH_E2E_* -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    try { Remove-TempRoot -Path $root -Prefix 'pb-e2e' } catch { Write-Warning $_ }
}
if ($exitCode -ne 0) { throw "Playwright failed with exit code $exitCode" }
Write-Host 'e2e: passed'
