# First Main install (release-001), run from the Dummy checkout: Dummy\app\scripts\install-main.ps1.
# Builds <project>\Main from one approved Dummy milestone, never from the working tree:
#   1. verify the source: the tag names the commit, its patch folder's checksums and manifest agree,
#      and a passed verify record exists for that exact commit;
#   2. clone Dummy\app into Main\app on branch `main` at that commit (remote `dummy-remote`);
#   3. Python 3.13 venv from the exact lock, frontend from package-lock with the Main badge setting;
#   4. Main env (instance main, profile prod, kiosk 127.0.0.1:8121 serving the built screens,
#      delivery 8123), a new empty database migrated to head and stamped `main`, a new admin
#      password typed by the operator (never copied from Dummy);
#   5. start once, check health, version, the screens, the delivery listener and pairing, stop.
# Nothing of Dummy's data, settings, photos or passwords is copied. Any failure stops the process it
# started and moves the half-built folder aside to Main.failed-<stamp> (nothing else is touched).
#
#   -Rehearsal   the same steps into a folder named Main under the system temp dir, with a random
#                admin password and the delivery listener on 127.0.0.1; the tag is optional so a
#                candidate commit can be rehearsed before it is approved. Never the real Main.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Commit,
    [string] $Tag,
    [string] $MainRoot,
    [switch] $Rehearsal,
    [switch] $KeepRunning
)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-DummyLayout
Clear-PhotoboothEnvironment

$kioskPort = 8121
$deliveryPort = 8123
$dummyApp = $script:AppRoot
$realMain = Join-Path $script:ProjectRoot 'Main'

function Write-Stage { param([string] $Text) Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }

# ---- where Main goes -------------------------------------------------------------------------
if (-not $MainRoot) {
    if ($Rehearsal) { throw '-Rehearsal needs -MainRoot <temp folder>\Main' }
    $MainRoot = $realMain
}
$MainRoot = [System.IO.Path]::GetFullPath($MainRoot)
if ((Split-Path -Leaf $MainRoot) -ne 'Main') { throw "The Main folder must be named Main: $MainRoot" }
$temp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$underTemp = $MainRoot.StartsWith($temp, [System.StringComparison]::OrdinalIgnoreCase)
if ($Rehearsal -and -not $underTemp) { throw "A rehearsal goes under $temp only, not $MainRoot" }
if (-not $Rehearsal) {
    if ($MainRoot -ne [System.IO.Path]::GetFullPath($realMain)) {
        throw "The real install goes to $realMain only"
    }
    if (-not $Tag) { throw 'The real install needs -Tag <approved dummy-patch tag>' }
}
if ((Test-Path -LiteralPath $MainRoot) -and @(Get-ChildItem -LiteralPath $MainRoot -Force).Count -gt 0) {
    throw "$MainRoot exists and is not empty: the first install only goes into an empty folder"
}
foreach ($port in $kioskPort, $deliveryPort) {
    if (-not (Test-PortFree -Port $port)) { throw "Port $port is busy (is Main already running?)" }
}

# ---- 1. the source -----------------------------------------------------------------------------
Write-Stage 'source commit and artifacts'
$full = (& git -C $dummyApp rev-parse --verify --quiet "$Commit^{commit}")
if (-not $full) { throw "Commit $Commit is not in $dummyApp" }
$full = "$full".Trim()
if ($Tag) {
    if ($Tag -notmatch '^dummy-patch-\d{3}-[a-z0-9-]+$') { throw "Not a milestone tag: $Tag" }
    $tagged = "$(& git -C $dummyApp rev-parse --verify --quiet "refs/tags/$Tag^{commit}")".Trim()
    if ($tagged -ne $full) { throw "Tag $Tag names $tagged, not $full" }
    if ("$(& git -C $dummyApp cat-file -t "refs/tags/$Tag")".Trim() -ne 'tag') { throw "$Tag is not an annotated tag" }
    $patchDir = Join-Path $script:ProjectRoot "patches\$Tag"
    $sums = Join-Path $patchDir 'SHA256SUMS.txt'
    if (-not (Test-Path -LiteralPath $sums)) { throw "No published patch folder for $Tag" }
    foreach ($line in [System.IO.File]::ReadAllLines($sums)) {
        if (-not $line.Trim()) { continue }
        $expected, $name = $line -split '\s+', 2
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $patchDir $name.Trim())).Hash
        if ($actual -ne $expected.ToUpperInvariant()) { throw "Checksum mismatch: $name" }
    }
    $manifest = [System.IO.File]::ReadAllText((Join-Path $patchDir 'manifest.json')) | ConvertFrom-Json
    if ($manifest.tag -ne $Tag -or $manifest.resulting_commit -ne $full) {
        throw "manifest.json does not name $Tag at $full"
    }
    $bundle = Join-Path $patchDir "$Tag.bundle"
    Invoke-Native 'git' @('bundle', 'verify', $bundle) $dummyApp
    Write-Host "tag $Tag -> $full; checksums, manifest and bundle verified"
}
$record = Join-Path $script:InstanceRoot "data\verify\$full.json"
if (-not (Test-Path -LiteralPath $record)) { throw "No verify record for $full (run scripts\verify.ps1 on it)" }
$verified = [System.IO.File]::ReadAllText($record) | ConvertFrom-Json
if ($verified.result -ne 'passed' -or $verified.commit -ne $full) { throw "Verify record for $full did not pass" }
$recordHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $record).Hash
Write-Host "verify record passed: $record (sha256 $recordHash)"

$started = $null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
try {
    # ---- 2. the code ---------------------------------------------------------------------------
    Write-Stage "Main code at $full"
    $mainApp = Join-Path $MainRoot 'app'
    New-Item -ItemType Directory -Force -Path $MainRoot | Out-Null
    Invoke-Native 'git' @('clone', '--quiet', '--no-checkout', '--origin', 'dummy-remote', $dummyApp, $mainApp) $MainRoot
    # A --no-checkout clone has an empty index: a forced checkout writes exactly that commit's files.
    Invoke-Native 'git' @('checkout', '--quiet', '--force', '-B', 'main', $full) $mainApp
    $head = "$(& git -C $mainApp rev-parse HEAD)".Trim()
    if ($head -ne $full) { throw "Main\app is at $head, not $full" }
    if (& git -C $mainApp status --porcelain --untracked-files=all) { throw 'Main\app is not clean after checkout' }
    Write-Host "Main\app on branch main at $head (remote dummy-remote = Dummy\app)"

    # ---- 3. dependencies and the screens ---------------------------------------------------------
    Write-Stage 'Python 3.13 environment from the exact lock'
    $backend = Join-Path $mainApp 'backend'
    $venv = Join-Path $backend '.venv'
    Invoke-Native 'py' @('-3.13', '-m', 'venv', $venv) $backend
    $python = Join-Path $venv 'Scripts\python.exe'
    Invoke-Native $python @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--no-deps', '-r', 'requirements-dev.lock') $backend
    Invoke-Native $python @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '--no-deps', '--no-build-isolation', '-e', '.') $backend
    Invoke-Native $python @('-m', 'pip', 'check') $backend
    Invoke-Native $python @((Join-Path $mainApp 'scripts\guards\python_lock.py'), 'check',
        '--pyproject', 'pyproject.toml', '--lock', 'requirements-dev.lock') $backend

    Write-Stage 'screens (npm ci + build, no DUMMY badge)'
    $null = Use-Node24
    $frontend = Join-Path $mainApp 'frontend'
    Invoke-Native 'npm.cmd' @('ci', '--no-audit', '--no-fund') $frontend
    $env:PHOTOBOOTH_INSTANCE = 'main'
    try { Invoke-Native 'npm.cmd' @('run', 'build') $frontend }
    finally { Remove-Item Env:PHOTOBOOTH_INSTANCE -ErrorAction SilentlyContinue }
    $dist = Join-Path $frontend 'dist'
    if (-not (Test-Path -LiteralPath (Join-Path $dist 'index.html'))) { throw 'The build made no index.html' }

    # ---- 4. settings, database, admin --------------------------------------------------------------
    Write-Stage 'Main settings, database and admin'
    New-Item -ItemType Directory -Force -Path (Join-Path $MainRoot 'data\db'), (Join-Path $MainRoot 'data\storage'),
        (Join-Path $MainRoot 'data\backups'), (Join-Path $MainRoot 'data\logs') | Out-Null
    $envFile = Join-Path $MainRoot 'config\photobooth.env'
    $deliveryHost = if ($Rehearsal) { '127.0.0.1' } else { '0.0.0.0' }
    Invoke-Native $python @('-m', 'photobooth', 'init-env', '--instance', 'main', '--profile', 'prod',
        '--instance-root', $MainRoot, '--output', $envFile, '--delivery-host', $deliveryHost,
        '--frontend-dist', $dist) $backend
    $intent = @('--env-file', $envFile, '--expect-root', $MainRoot, '--expect-profile', 'prod')
    Invoke-Native $python (@('-m', 'photobooth', 'db-upgrade') + $intent) $backend
    Invoke-Native $python (@('-m', 'photobooth', 'db-check') + $intent) $backend
    if ($Rehearsal) {
        # A throwaway password, never shown or written down: a rehearsal has no organizer.
        $password = 'rehearsal-' + [guid]::NewGuid().ToString('N')
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $password | & $python -m photobooth admin-set-password @intent --username admin --password-stdin
            if ($LASTEXITCODE -ne 0) { throw "admin-set-password exited with $LASTEXITCODE" }
        }
        finally { $ErrorActionPreference = $previous }
    }
    else {
        Write-Host 'Type the NEW Main admin password (12+ characters; not the Dummy one), twice:'
        Invoke-Native $python (@('-m', 'photobooth', 'admin-set-password') + $intent + @('--username', 'admin')) $backend
    }

    # ---- 5. first start and checks ----------------------------------------------------------------
    Write-Stage 'first start: health, version, screens, delivery, pairing'
    $logs = Join-Path $MainRoot 'data\logs'
    $env:PHOTOBOOTH_GIT_COMMIT = $full
    $started = Start-Process -FilePath $python -WorkingDirectory $mainApp -PassThru -WindowStyle Minimized `
        -ArgumentList (@('-m', 'photobooth', 'serve', '--env-file', "`"$envFile`"", '--expect-root', "`"$MainRoot`"", '--expect-profile', 'prod')) `
        -RedirectStandardOutput (Join-Path $logs 'install-console.out.log') -RedirectStandardError (Join-Path $logs 'install-console.err.log')
    Remove-Item Env:PHOTOBOOTH_GIT_COMMIT
    $kiosk = "http://127.0.0.1:$kioskPort"
    Wait-HttpOk -Url "$kiosk/api/health" -TimeoutSeconds 90
    $version = Invoke-RestMethod -Uri "$kiosk/api/version" -UseBasicParsing
    if ($version.instance -ne 'main') { throw "The server says instance $($version.instance)" }
    if ($version.git_commit -ne $full) { throw "The server runs $($version.git_commit), not $full" }
    if (-not $version.schema_revision) { throw 'The server reports no database revision' }
    foreach ($path in '/', '/booth', '/admin') {
        $page = Invoke-WebRequest -Uri "$kiosk$path" -UseBasicParsing
        if ($page.StatusCode -ne 200 -or $page.Content -notmatch '<div id="root">') { throw "$path did not serve the screens" }
    }
    $delivery = "http://127.0.0.1:$deliveryPort"
    try {
        Invoke-WebRequest -Uri "$delivery/api/health" -UseBasicParsing | Out-Null
        throw 'The guest-phone listener answers /api/health; it must serve /d/ links only'
    }
    catch [System.Net.WebException] {
        if ([int]$_.Exception.Response.StatusCode -ne 404) { throw }
    }
    $launcher = [System.IO.File]::ReadAllText((Join-Path $MainRoot 'config\runtime\launcher.token')).Trim()
    $rotated = Invoke-WebRequest -Uri "$kiosk/kiosk/pairing-code/rotate" -Method Post -UseBasicParsing `
        -Headers @{ 'X-Photobooth-Launcher' = $launcher }
    if ($rotated.StatusCode -ne 204) { throw "Pairing code rotation answered $($rotated.StatusCode)" }
    Write-Host "Main $($version.app_version) (API $($version.api_version)) answers at $kiosk; database $($version.schema_revision); code $full"
}
catch {
    $failure = $_
    if ($started) { & taskkill.exe /PID $started.Id /T /F 2>$null | Out-Null }
    Start-Sleep -Seconds 1
    if (Test-Path -LiteralPath $MainRoot) {
        $aside = "$MainRoot.failed-$stamp"
        try { Move-Item -LiteralPath $MainRoot -Destination $aside; Write-Warning "Moved the half-built Main to $aside" }
        catch { Write-Warning "Could not move $MainRoot aside: $_" }
    }
    throw "Main install failed: $failure"
}

if ($KeepRunning) {
    Write-Host "Main left running (PID $($started.Id)); stop it with taskkill /PID $($started.Id) /T /F or, after a restart, Main\app\scripts\stop-main.ps1"
}
else {
    & taskkill.exe /PID $started.Id /T /F | Out-Null
    Write-Host 'Main stopped after its first-start checks.'
}
Write-Host ''
Write-Host "MAIN INSTALLED at $MainRoot from $full$(if ($Tag) { " ($Tag)" })"
Write-Host '  Start:  Main\app\scripts\run-main.ps1      Stop: Main\app\scripts\stop-main.ps1'
Write-Host '  Next:   check Main yourself; only then tag main-release-001 (see Project_Docs\MAIN_INSTALL.md)'
