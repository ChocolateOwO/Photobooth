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

Clear-PhotoboothEnvironment
$nodeVersion = Use-Node24
$python = Get-VenvPython
New-Item -ItemType Directory -Force -Path $runDir, $logsDir | Out-Null

if (Test-Path $pidFile) {
    throw "Dummy appears to be running ($pidFile exists). Use scripts\stop-dummy.ps1 first."
}
foreach ($port in $kioskPort, $deliveryPort, $uiPort) {
    if (-not (Test-PortFree -Port $port)) { throw "Port $port is busy; Dummy not started" }
}

$intent = @('--expect-root', $script:InstanceRoot, '--expect-profile', 'dev')
if (-not (Test-Path $envFile)) {
    Invoke-Native $python @('-m', 'photobooth', 'init-env', '--instance', 'dummy', '--profile', 'dev',
        '--instance-root', $script:InstanceRoot, '--output', $envFile)
}
Invoke-Native $python (@('-m', 'photobooth', 'db-upgrade', '--env-file', $envFile) + $intent)

$commit = (& git -C $script:AppRoot rev-parse HEAD).Trim()
$env:PHOTOBOOTH_GIT_COMMIT = $commit
$env:PHOTOBOOTH_INSTANCE = 'dummy'
$env:PHOTOBOOTH_KIOSK_PORT = "$kioskPort"

$frontend = Join-Path $script:AppRoot 'frontend'
$viteJs = Join-Path $frontend 'node_modules\vite\bin\vite.js'
$node = Join-Path $script:InstanceRoot 'tools\node24\node.exe'

Invoke-TrackedStartup -RecordPath $pidFile -Commit $commit -Body {
    param($start)
    $script:backend = & $start 'backend' '-m photobooth serve --env-file' $python `
        (@('-m', 'photobooth', 'serve', '--env-file', "`"$envFile`"", '--expect-root', "`"$($script:InstanceRoot)`"", '--expect-profile', 'dev')) `
        $script:AppRoot (Join-Path $logsDir 'backend-console.out.log') (Join-Path $logsDir 'backend-console.err.log')
    $script:vite = & $start 'vite' 'vite\bin\vite.js' $node `
        (@("`"$viteJs`"", '--host', '127.0.0.1', '--port', "$uiPort", '--strictPort')) `
        $frontend (Join-Path $logsDir 'vite-console.out.log') (Join-Path $logsDir 'vite-console.err.log')
    Wait-HttpOk -Url "http://127.0.0.1:$kioskPort/api/health" -TimeoutSeconds 90
    Wait-HttpOk -Url "http://127.0.0.1:$uiPort/" -TimeoutSeconds 90
}

Open-Pairing
Write-Host ''
Write-Host "PHOTOBOOTH DUMMY running  (node $nodeVersion, commit $commit)"
Write-Host "  UI:        http://127.0.0.1:$uiPort/"
Write-Host "  Kiosk API: http://127.0.0.1:$kioskPort/api/health"
Write-Host "  Delivery:  port $deliveryPort (LAN), /d/_alive only"
Write-Host "  PIDs:      backend $($script:backend.Id), vite $($script:vite.Id)"
Write-Host '  Stop:      scripts\stop-dummy.ps1'
