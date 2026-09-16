# Start the Dummy instance: backend (kiosk 127.0.0.1:8111 + delivery 0.0.0.0:8113) and Vite dev UI
# (127.0.0.1:5191), then pair this browser as the kiosk. Never touches Main.
#   -NoBrowser   start only; print how to pair
#   -PairOnly    rotate the pairing code and open the pairing URL for an already-running Dummy
[CmdletBinding()]
param([switch] $NoBrowser, [switch] $PairOnly)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-DummyLayout
$Host.UI.RawUI.WindowTitle = 'PHOTOBOOTH DUMMY'

$kioskPort = 8111
$deliveryPort = 8113
$uiPort = 5191
$runDir = Join-Path $script:InstanceRoot 'data\run'
$pidFile = Join-Path $runDir 'dummy-processes.json'
$logsDir = Join-Path $script:InstanceRoot 'data\logs'
$envFile = Join-Path $script:InstanceRoot 'config\photobooth.env'
$pairingFile = Join-Path $script:InstanceRoot 'config\runtime\pairing.code'

function Open-Pairing {
    $rotated = $false
    for ($i = 0; $i -lt 5 -and -not $rotated; $i++) {
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$kioskPort/kiosk/pairing-code/rotate" -Method Post -UseBasicParsing | Out-Null
            $rotated = $true
        }
        catch {
            Start-Sleep -Milliseconds 1100
        }
    }
    if (-not $rotated) { throw 'Could not rotate pairing code (is Dummy running?)' }
    $code = [System.IO.File]::ReadAllText($pairingFile).Trim()
    $url = "http://127.0.0.1:$uiPort/kiosk/pair?code=$([uri]::EscapeDataString($code))"
    if ($NoBrowser) {
        Write-Host 'Pairing code published. Run scripts\run-dummy.ps1 -PairOnly within 60 s of use.'
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

$nodeVersion = Use-Node24
$python = Get-VenvPython
New-Item -ItemType Directory -Force -Path $runDir, $logsDir | Out-Null

if (Test-Path $pidFile) {
    throw "Dummy appears to be running ($pidFile exists). Use scripts\stop-dummy.ps1 first."
}
foreach ($port in $kioskPort, $deliveryPort, $uiPort) {
    if (-not (Test-PortFree -Port $port)) { throw "Port $port is busy; Dummy not started" }
}

if (-not (Test-Path $envFile)) {
    Invoke-Native $python @('-m', 'photobooth', 'init-env', '--instance', 'dummy', '--profile', 'dev',
        '--instance-root', $script:InstanceRoot, '--output', $envFile)
}
Invoke-Native $python @('-m', 'photobooth', 'db-upgrade', '--env-file', $envFile)

$env:PHOTOBOOTH_GIT_COMMIT = (& git -C $script:AppRoot rev-parse HEAD).Trim()
$env:PHOTOBOOTH_INSTANCE = 'dummy'
$env:PHOTOBOOTH_KIOSK_PORT = "$kioskPort"

$backend = Start-Process -FilePath $python -WorkingDirectory $script:AppRoot -PassThru -WindowStyle Minimized `
    -ArgumentList @('-m', 'photobooth', 'serve', '--env-file', "`"$envFile`"") `
    -RedirectStandardOutput (Join-Path $logsDir 'backend-console.out.log') `
    -RedirectStandardError (Join-Path $logsDir 'backend-console.err.log')

$frontend = Join-Path $script:AppRoot 'frontend'
$viteJs = Join-Path $frontend 'node_modules\vite\bin\vite.js'
$node = Join-Path $script:InstanceRoot 'tools\node24\node.exe'
$vite = Start-Process -FilePath $node -WorkingDirectory $frontend -PassThru -WindowStyle Minimized `
    -ArgumentList @("`"$viteJs`"", '--host', '127.0.0.1', '--port', "$uiPort", '--strictPort') `
    -RedirectStandardOutput (Join-Path $logsDir 'vite-console.out.log') `
    -RedirectStandardError (Join-Path $logsDir 'vite-console.err.log')

@{
    instance    = 'dummy'
    backend_pid = $backend.Id
    vite_pid    = $vite.Id
    started_at  = (Get-Date).ToString('o')
    commit      = $env:PHOTOBOOTH_GIT_COMMIT
} | ConvertTo-Json | Set-Content -Path $pidFile -Encoding ASCII

try {
    Wait-HttpOk -Url "http://127.0.0.1:$kioskPort/api/health" -TimeoutSeconds 60
    Wait-HttpOk -Url "http://127.0.0.1:$uiPort/" -TimeoutSeconds 60
}
catch {
    Write-Warning "Dummy did not become healthy; see $logsDir. Stopping."
    & (Join-Path $PSScriptRoot 'stop-dummy.ps1')
    throw
}

Open-Pairing
Write-Host ''
Write-Host "PHOTOBOOTH DUMMY running  (node $nodeVersion, commit $($env:PHOTOBOOTH_GIT_COMMIT))"
Write-Host "  UI:        http://127.0.0.1:$uiPort/"
Write-Host "  Kiosk API: http://127.0.0.1:$kioskPort/api/health"
Write-Host "  Delivery:  port $deliveryPort (LAN), /d/_alive only"
Write-Host "  PIDs:      backend $($backend.Id), vite $($vite.Id)"
Write-Host '  Stop:      scripts\stop-dummy.ps1'
