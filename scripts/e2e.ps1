# Playwright smoke test against a throwaway e2e instance under %TEMP% (never Dummy data).
# Ports: kiosk 8112, delivery 8114 (bound to 127.0.0.1), vite preview 5192.
[CmdletBinding()]
param([switch] $SkipBuild)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-DummyLayout
$null = Use-Node24
$python = Get-VenvPython

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
    Invoke-Native $python @('-m', 'photobooth', 'db-upgrade', '--env-file', $envFile)

    if (-not $SkipBuild) {
        $env:PHOTOBOOTH_INSTANCE = 'dummy'
        Invoke-Native 'npm.cmd' @('run', 'build') $frontend
    }

    $env:PHOTOBOOTH_E2E_ENV_FILE = $envFile
    $env:PHOTOBOOTH_E2E_PYTHON = $python
    $env:PHOTOBOOTH_E2E_FRONTEND_DIR = $frontend
    $env:PHOTOBOOTH_E2E_INSTANCE_ROOT = $root
    Push-Location $e2eDir
    $ErrorActionPreference = 'Continue'
    try {
        & npx.cmd playwright test
        $exitCode = $LASTEXITCODE
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
