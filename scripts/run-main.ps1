# Start the Main instance: one backend process (kiosk 127.0.0.1:8121 serving the API and the built
# screens; delivery 8123 on the LAN for guests' phones), then pair this browser as the kiosk.
# Never touches Dummy. Main never migrates on start: a database behind the code is refused here,
# because Main migrates only during a promotion, after a verified backup.
#   -NoBrowser   start only; print how to pair
#   -PairOnly    rotate the pairing code and open the pairing URL for an already-running Main
[CmdletBinding()]
param([switch] $NoBrowser, [switch] $PairOnly)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-MainLayout
$Host.UI.RawUI.WindowTitle = 'PHOTOBOOTH MAIN'

$kioskPort = 8121
$deliveryPort = 8123
$runDir = Join-Path $script:InstanceRoot 'data\run'
$pidFile = Join-Path $runDir 'main-processes.json'
$logsDir = Join-Path $script:InstanceRoot 'data\logs'
$envFile = Join-Path $script:InstanceRoot 'config\photobooth.env'
$pairingFile = Join-Path $script:InstanceRoot 'config\runtime\pairing.code'
$launcherFile = Join-Path $script:InstanceRoot 'config\runtime\launcher.token'

function Open-Pairing {
    $rotated = $false
    for ($i = 0; $i -lt 5 -and -not $rotated; $i++) {
        try {
            $launcher = [System.IO.File]::ReadAllText($launcherFile).Trim()
            Invoke-WebRequest -Uri "http://127.0.0.1:$kioskPort/kiosk/pairing-code/rotate" -Method Post `
                -Headers @{ 'X-Photobooth-Launcher' = $launcher } -UseBasicParsing | Out-Null
            $rotated = $true
        }
        catch {
            Start-Sleep -Milliseconds 1100
        }
    }
    if (-not $rotated) { throw 'Could not rotate pairing code (is Main running?)' }
    $code = [System.IO.File]::ReadAllText($pairingFile).Trim()
    $url = "http://127.0.0.1:$kioskPort/kiosk/pair?code=$([uri]::EscapeDataString($code))"
    if ($NoBrowser) {
        Write-Host 'Pairing code published. Run scripts\run-main.ps1 -PairOnly within 60 s of use.'
    }
    else {
        Start-Process $url
        Write-Host "Opened browser for kiosk pairing (single-use code, valid 60 s)."
    }
}

if ($PairOnly) {
    Open-Pairing
    return
}

Clear-PhotoboothEnvironment
Clear-GitEnvironment

# Every check comes before the first write: a refused start leaves Main exactly as it was
# (P13-R6). The folders Main writes to are plain folders inside Main, not links elsewhere.
foreach ($path in $envFile, $pidFile, $runDir, $logsDir, (Join-Path $script:InstanceRoot 'data\db')) {
    $null = Assert-PlainPath -Path $path
}
if (-not (Test-Path -LiteralPath $envFile)) { throw "No Main settings at $envFile (install Main first)" }
if (Test-Path -LiteralPath $pidFile) {
    throw "Main appears to be running ($pidFile exists). Use scripts\stop-main.ps1 first."
}
foreach ($port in $kioskPort, $deliveryPort) {
    if (-not (Test-PortFree -Port $port)) { throw "Port $port is busy; Main not started" }
}
$python = Get-VenvPython

# db-check only reads: a missing database is refused, never created (exit 4).
$intent = @('--env-file', $envFile, '--expect-root', $script:InstanceRoot, '--expect-profile', 'prod')
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & $python -m photobooth db-check @intent
    $atHead = $LASTEXITCODE
}
finally { $ErrorActionPreference = $previous }
if ($atHead -eq 4) { throw 'Main has no database. Install Main first (see Project_Docs\MAIN_INSTALL.md).' }
if ($atHead -ne 0) {
    throw "The Main database is not at this code's revision (db-check exit $atHead). Main migrates only during a promotion; see Project_Docs\MAIN_INSTALL.md."
}

New-Item -ItemType Directory -Force -Path $runDir, $logsDir | Out-Null
$commit = (& git -C $script:AppRoot rev-parse HEAD).Trim()
$env:PHOTOBOOTH_GIT_COMMIT = $commit

Invoke-TrackedStartup -RecordPath $pidFile -Commit $commit -Instance 'main' -Body {
    param($start)
    $script:backend = & $start 'backend' '-m photobooth serve --env-file' $python `
        (@('-m', 'photobooth', 'serve', '--env-file', "`"$envFile`"", '--expect-root', "`"$($script:InstanceRoot)`"", '--expect-profile', 'prod')) `
        $script:AppRoot (Join-Path $logsDir 'backend-console.out.log') (Join-Path $logsDir 'backend-console.err.log')
    Wait-HttpOk -Url "http://127.0.0.1:$kioskPort/api/health" -TimeoutSeconds 90
}

Open-Pairing
Write-Host ''
Write-Host "PHOTOBOOTH MAIN running  (commit $commit)"
Write-Host "  Booth:     http://127.0.0.1:$kioskPort/booth"
Write-Host "  Admin:     http://127.0.0.1:$kioskPort/admin"
Write-Host "  Delivery:  port $deliveryPort (LAN), /d/... guest links only"
Write-Host "  PID:       backend $($script:backend.Id)"
Write-Host '  Stop:      scripts\stop-main.ps1'
