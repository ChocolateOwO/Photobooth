# First Main install (release-001), run from the Dummy checkout: Dummy\app\scripts\install-main.ps1.
# Builds <project>\Main from one approved Dummy milestone, never from the working tree:
#   1. verify the source: the annotated tag records the approval, the manual test and the hash of
#      the passed verify record of that exact commit; the patch folder's checksum list is complete
#      and matches; the manifest and the bundle name the same tag and commit;
#   2. clone Dummy\app into Main\app on branch `main` at that commit (remote `dummy-remote`);
#   3. Python 3.13 venv from the exact lock, frontend from package-lock with the Main badge setting;
#   4. Main env (instance main, profile prod, kiosk 127.0.0.1:8121 serving the built screens,
#      delivery 8123), a new empty database migrated to head and stamped `main`, a new admin
#      password typed by the operator (never copied from Dummy);
#   5. start once (recorded like run-main.ps1), check health, version, the screens, the delivery
#      listener and pairing, and stop it again by its recorded identity.
# Nothing of Dummy's data, settings, photos or passwords is copied. Any failure stops the process it
# started and moves the half-built folder aside to Main.failed-<stamp> (nothing is deleted, nothing
# else is touched); if the process can not be stopped, the folder stays and the report says why.
#
#   -Rehearsal   the same steps into a folder named Main under the system temp dir, outside the
#                project, with a random admin password and the delivery listener on 127.0.0.1; the
#                tag is optional so a candidate commit can be rehearsed before it is approved.
#                Never the real Main, whatever TEMP or TMP say (P13-R1).
#   -Release <tag>  install a published milestone from a fresh clone of the public repository
#                (README): the annotated tag must record the approved commit, an approval date and
#                a passed (or not required) manual test. The owner's local evidence (the verify
#                record, whose hash the tag carries, and the patch folder) is not part of a clone
#                and is not asked for. Everything else is the same as the real install.
#   -AdminPasswordStdin  read the new admin password from the first line of standard input instead
#                of asking twice at the keyboard (for unattended rehearsals; never stored).
[CmdletBinding()]
param(
    [string] $Commit,
    [string] $Tag,
    [string] $Release,
    [string] $MainRoot,
    [switch] $Rehearsal,
    [switch] $KeepRunning,
    [switch] $AdminPasswordStdin
)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-DummyLayout
Clear-PhotoboothEnvironment
Clear-GitEnvironment

$kioskPort = 8121
$deliveryPort = 8123
$dummyApp = $script:AppRoot
$project = $script:ProjectRoot
$realMain = [System.IO.Path]::GetFullPath((Join-Path $project 'Main'))
$marker = '-m photobooth serve --env-file'

function Write-Stage { param([string] $Text) Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }

function Invoke-Git {
    # git, always told which repository it works in (never an inherited GIT_DIR/GIT_WORK_TREE).
    param([Parameter(Mandatory)] [string] $Repo, [Parameter(Mandatory)] [string[]] $Arguments)
    $out = & git -C $Repo @Arguments
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed in $Repo ($LASTEXITCODE)" }
    return $out
}

if ($Release -and ($Rehearsal -or $Tag)) { throw '-Release installs a published tag for real: not with -Rehearsal or -Tag' }
if (-not $Release -and -not $Commit) { throw 'Name the source: -Commit <sha> (with -Tag or -Rehearsal), or -Release <tag>' }
# Read before anything else, so a piped password is never left waiting in the pipe.
$stdinPassword = if ($AdminPasswordStdin) { Read-StdinLineUtf8 } else { $null }
if ($AdminPasswordStdin -and -not $stdinPassword) { throw '-AdminPasswordStdin: no password on the first line of standard input' }

# ---- where Main goes (checked before anything is written) ----------------------------------------
if ($Rehearsal) {
    if (-not $MainRoot) { throw '-Rehearsal needs -MainRoot <temp folder>\Main' }
}
elseif (-not $MainRoot) {
    $MainRoot = $realMain
}
$MainRoot = Assert-PlainPath -Path $MainRoot
$null = Assert-PlainPath -Path $project
if ((Split-Path -Leaf $MainRoot) -cne 'Main') { throw "The Main folder must be named Main: $MainRoot" }
if ($Rehearsal) {
    $temp = Assert-PlainPath -Path ([System.IO.Path]::GetTempPath())
    if (-not (Test-PathInside -Path $MainRoot -Folder $temp)) { throw "A rehearsal goes under $temp only, not $MainRoot" }
    # TEMP and TMP come from the caller: the project (and with it the real Main) is refused
    # whatever they say.
    if ((Test-PathInside -Path $MainRoot -Folder $project) -or (Test-PathInside -Path $temp -Folder $project)) {
        throw "A rehearsal never goes inside the project ($project), not $MainRoot"
    }
    if ($MainRoot.Equals($realMain, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'A rehearsal never targets the real Main' }
}
else {
    if (-not $MainRoot.Equals($realMain, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The real install goes to $realMain only"
    }
    if (-not $Tag -and -not $Release) { throw 'The real install needs -Tag <approved dummy-patch tag>' }
}
if ((Test-Path -LiteralPath $MainRoot) -and @(Get-ChildItem -LiteralPath $MainRoot -Force).Count -gt 0) {
    throw "$MainRoot exists and is not empty: the first install only goes into an empty folder"
}
foreach ($port in $kioskPort, $deliveryPort) {
    if (-not (Test-PortFree -Port $port)) { throw "Port $port is busy (is Main already running?)" }
}

# ---- 1. the source -----------------------------------------------------------------------------
Write-Stage 'source commit and artifacts'
if ($Release) {
    # A published release: the annotated tag in this clone is the evidence (the README install).
    if ($Release -notmatch '^dummy-patch-\d{3}-[a-z0-9-]+$') { throw "Not a milestone tag: $Release" }
    $releaseObject = "$(& git -C $dummyApp rev-parse --verify --quiet "refs/tags/$Release")".Trim()
    if (-not $releaseObject) { throw "Tag $Release is not in this clone (git fetch --tags)" }
    if ("$(Invoke-Git $dummyApp @('cat-file', '-t', $releaseObject))".Trim() -ne 'tag') { throw "$Release is not an annotated tag" }
    $releaseCommit = "$(Invoke-Git $dummyApp @('rev-parse', '--verify', "refs/tags/$Release^{commit}"))".Trim()
    if ($Commit) {
        $named = "$(& git -C $dummyApp rev-parse --verify --quiet "$Commit^{commit}")".Trim()
        if ($named -ne $releaseCommit) { throw "-Commit $Commit is not the commit of $Release" }
    }
    $evidence = @{}
    foreach ($line in @(Invoke-Git $dummyApp @('tag', '-l', '--format=%(contents)', $Release))) {
        if ("$line" -match '^(approved-commit|approval|manual-test|verify-record-sha256):\s*(.+)$') { $evidence[$Matches[1]] = $Matches[2].Trim() }
    }
    if ($evidence['approved-commit'] -ne $releaseCommit) { throw "$Release does not record $releaseCommit as the approved commit" }
    if ("$($evidence['approval'])" -notmatch '^approved \d{4}-\d{2}-\d{2}$') { throw "$Release records no approval" }
    if ($evidence['manual-test'] -notin @('passed', 'not_required')) { throw "$Release records the manual test as '$($evidence['manual-test'])'" }
    if ("$($evidence['verify-record-sha256'])" -notmatch '^[0-9a-f]{64}$') { throw "$Release records no verify record" }
    $Commit = $releaseCommit
    $Tag = $Release
    Write-Host "release $Release -> $releaseCommit ($($evidence['approval']); manual test $($evidence['manual-test']); verify record sha256 $($evidence['verify-record-sha256']))"
}
$full = & git -C $dummyApp rev-parse --verify --quiet "$Commit^{commit}"
if ($LASTEXITCODE -ne 0 -or -not $full) { throw "Commit $Commit is not in $dummyApp" }
$full = "$full".Trim()
if (-not $Release) {
    $record = Join-Path $script:InstanceRoot "data\verify\$full.json"
    if (-not (Test-Path -LiteralPath $record)) { throw "No verify record for $full (run scripts\verify.ps1 on it)" }
    $verified = [System.IO.File]::ReadAllText($record) | ConvertFrom-Json
    if ($verified.result -ne 'passed' -or $verified.commit -ne $full) { throw "Verify record for $full did not pass" }
    $recordHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $record).Hash.ToLowerInvariant()
    Write-Host "verify record passed: $record (sha256 $recordHash)"
}
if ($Tag -and -not $Release) {
    if ($Tag -notmatch '^dummy-patch-\d{3}-[a-z0-9-]+$') { throw "Not a milestone tag: $Tag" }
    $tagObject = "$(Invoke-Git $dummyApp @('rev-parse', '--verify', "refs/tags/$Tag"))".Trim()
    if ("$(Invoke-Git $dummyApp @('cat-file', '-t', $tagObject))".Trim() -ne 'tag') { throw "$Tag is not an annotated tag" }
    $tagged = "$(Invoke-Git $dummyApp @('rev-parse', '--verify', "refs/tags/$Tag^{commit}"))".Trim()
    if ($tagged -ne $full) { throw "Tag $Tag names $tagged, not $full" }
    # The approval evidence make-patch.ps1 writes into the tag (P13-R4).
    $evidence = @{}
    foreach ($line in @(Invoke-Git $dummyApp @('tag', '-l', '--format=%(contents)', $Tag))) {
        if ("$line" -match '^(approved-commit|approval|manual-test|verify-record-sha256):\s*(.+)$') { $evidence[$Matches[1]] = $Matches[2].Trim() }
    }
    if ($evidence['approved-commit'] -ne $full) { throw "$Tag does not record $full as the approved commit" }
    if ("$($evidence['approval'])" -notmatch '^approved \d{4}-\d{2}-\d{2}$') { throw "$Tag records no approval" }
    if ($evidence['manual-test'] -notin @('passed', 'not_required')) { throw "$Tag records the manual test as '$($evidence['manual-test'])'" }
    if ("$($evidence['verify-record-sha256'])".ToLowerInvariant() -ne $recordHash) { throw "$Tag names another verify record than $record" }
    # The published patch folder: every artifact listed, every checksum right, nothing else.
    $patchDir = Assert-PlainPath -Path (Join-Path $project "patches\$Tag")
    $sums = Join-Path $patchDir 'SHA256SUMS.txt'
    if (-not (Test-Path -LiteralPath $sums)) { throw "No published patch folder for $Tag" }
    $expected = @("$Tag.bundle", "$Tag.patch", 'manifest.json', 'MANIFEST.md')
    $listed = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($sums)) {
        if (-not $line.Trim()) { continue }
        if ($line -notmatch '^([0-9a-fA-F]{64})\s+\*?(\S+)$') { throw "Unreadable checksum line in $sums" }
        $name = $Matches[2]
        if ($name -notin $expected -or $listed.ContainsKey($name)) { throw "Unexpected entry in $sums`: $name" }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $patchDir $name)).Hash
        if ($actual -ne $Matches[1].ToUpperInvariant()) { throw "Checksum mismatch: $name" }
        $listed[$name] = $true
    }
    $missing = @($expected | Where-Object { -not $listed.ContainsKey($_) })
    if ($missing.Count) { throw "$sums does not list: $($missing -join ', ')" }
    $manifest = [System.IO.File]::ReadAllText((Join-Path $patchDir 'manifest.json')) | ConvertFrom-Json
    if ($manifest.tag -ne $Tag -or $manifest.resulting_commit -ne $full) { throw "manifest.json does not name $Tag at $full" }
    if ("$($manifest.user_approval)" -notmatch '^approved \d{4}-\d{2}-\d{2}$') { throw 'manifest.json records no approval' }
    $bundle = Join-Path $patchDir "$Tag.bundle"
    $null = Invoke-Git $dummyApp @('bundle', 'verify', $bundle)
    $heads = @(Invoke-Git $dummyApp @('bundle', 'list-heads', $bundle, "refs/tags/$Tag"))
    if (-not ($heads | Where-Object { "$_" -eq "$tagObject refs/tags/$Tag" })) { throw "The bundle does not carry $Tag as $tagObject" }
    Write-Host "tag $Tag -> $full; approval, manual test, verify record, checksums, manifest and bundle verified"
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runRecord = Join-Path $MainRoot 'data\run\main-processes.json'
$started = $null
$created = $false

function Stop-Started {
    # Stops what this install started, by its recorded identity; returns what is still running.
    $left = @()
    if (Test-Path -LiteralPath $runRecord) {
        $entries = @(([System.IO.File]::ReadAllText($runRecord) | ConvertFrom-Json).processes)
        $left = @((Stop-RecordedProcesses -Entries $entries).ToArray())
        Save-ProcessRecord -Path $runRecord -Entries $left -Instance 'main'
    }
    elseif ($script:started -and -not $script:started.HasExited) {
        # Started but not yet recorded: only the very process this install launched.
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $($script:started.Id)" -ErrorAction SilentlyContinue
        if ($cim -and ("$($cim.CommandLine)").Contains($marker)) {
            $previous = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try { & taskkill.exe /PID $script:started.Id /T /F | Out-Null } finally { $ErrorActionPreference = $previous }
            Start-Sleep -Milliseconds 500
        }
        if (-not $script:started.HasExited) { $left = @($script:started.Id) }
    }
    return , $left
}

try {
    # ---- 2. the code ---------------------------------------------------------------------------
    Write-Stage "Main code at $full"
    $mainApp = Join-Path $MainRoot 'app'
    New-Item -ItemType Directory -Force -Path $MainRoot | Out-Null
    $created = $true
    $null = Assert-PlainPath -Path $MainRoot  # what was just made (or found empty) is a plain folder
    # A full copy (no hard links into Dummy's object store), checked out explicitly into Main\app.
    Invoke-Native 'git' @('clone', '--quiet', '--no-checkout', '--no-hardlinks', '--origin', 'dummy-remote', $dummyApp, $mainApp) $MainRoot
    $null = Assert-PlainPath -Path $mainApp
    # Main\app is the top of its own work tree with its own .git (relative answers: git prints
    # absolute Thai paths in a code page PowerShell 5.1 does not read back).
    $gitDirName = "$(Invoke-Git $mainApp @('rev-parse', '--git-dir'))".Trim()
    $cdup = "$(Invoke-Git $mainApp @('rev-parse', '--show-cdup'))".Trim()
    if ($gitDirName -ne '.git' -or $cdup) { throw "Main\app is not its own repository (git dir '$gitDirName', up '$cdup')" }
    $gitDir = Join-Path $mainApp '.git'
    $null = Invoke-Git $mainApp @("--git-dir=$gitDir", "--work-tree=$mainApp", 'checkout', '--quiet', '--force', '-B', 'main', $full)
    $head = "$(Invoke-Git $mainApp @('rev-parse', 'HEAD'))".Trim()
    if ($head -ne $full) { throw "Main\app is at $head, not $full" }
    if (Invoke-Git $mainApp @('status', '--porcelain', '--untracked-files=all')) { throw 'Main\app is not clean after checkout' }
    Write-Host "Main\app on branch main at $head (remote dummy-remote = Dummy\app)"

    # ---- 3. dependencies and the screens ---------------------------------------------------------
    Write-Stage 'Python 3.13 environment from the exact lock'
    $null = Assert-PlainPath -Path $mainApp
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
    $null = Assert-PlainPath -Path $MainRoot
    foreach ($dir in 'data\db', 'data\storage', 'data\backups', 'data\logs', 'data\run', 'config') {
        $path = Join-Path $MainRoot $dir
        New-Item -ItemType Directory -Force -Path $path | Out-Null
        $null = Assert-PlainPath -Path $path
    }
    $envFile = Join-Path $MainRoot 'config\photobooth.env'
    $deliveryHost = if ($Rehearsal) { '127.0.0.1' } else { '0.0.0.0' }
    Invoke-Native $python @('-m', 'photobooth', 'init-env', '--instance', 'main', '--profile', 'prod',
        '--instance-root', $MainRoot, '--output', $envFile, '--delivery-host', $deliveryHost,
        '--frontend-dist', $dist) $backend
    $intent = @('--env-file', $envFile, '--expect-root', $MainRoot, '--expect-profile', 'prod')
    Invoke-Native $python (@('-m', 'photobooth', 'db-upgrade') + $intent) $backend
    Invoke-Native $python (@('-m', 'photobooth', 'db-check') + $intent) $backend
    if ($Rehearsal -or $stdinPassword) {
        # A rehearsal's throwaway password (never shown or written down), or the one piped in.
        $password = if ($stdinPassword) { $stdinPassword } else { 'rehearsal-' + [guid]::NewGuid().ToString('N') }
        # UTF-8 end to end, so a password with characters outside ASCII arrives as typed.
        Invoke-NativeWithLine -FilePath $python -Line $password -Arguments (@('-m', 'photobooth', 'admin-set-password') + $intent + @('--username', 'admin', '--password-stdin'))
    }
    else {
        Write-Host 'Type the NEW Main admin password (12+ characters; not the Dummy one), twice:'
        Invoke-Native $python (@('-m', 'photobooth', 'admin-set-password') + $intent + @('--username', 'admin')) $backend
    }

    # ---- 5. first start and checks ----------------------------------------------------------------
    Write-Stage 'first start: health, version, screens, delivery, pairing'
    $logs = Join-Path $MainRoot 'data\logs'
    $env:PHOTOBOOTH_GIT_COMMIT = $full
    try {
        $script:started = Start-Process -FilePath $python -WorkingDirectory $mainApp -PassThru -WindowStyle Minimized `
            -ArgumentList (@('-m', 'photobooth', 'serve', '--env-file', "`"$envFile`"", '--expect-root', "`"$MainRoot`"", '--expect-profile', 'prod')) `
            -RedirectStandardOutput (Join-Path $logs 'install-console.out.log') -RedirectStandardError (Join-Path $logs 'install-console.err.log')
    }
    finally { Remove-Item Env:PHOTOBOOTH_GIT_COMMIT -ErrorAction SilentlyContinue }
    # Recorded at once, as run-main.ps1 does: stop-main.ps1 (or this script) stops exactly it.
    Save-ProcessRecord -Path $runRecord -Entries @(Get-ProcessIdentity -Process $script:started -Role 'backend' -Marker $marker) -Commit $full -Instance 'main'
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
    $refused = $false
    try { Invoke-WebRequest -Uri "$delivery/api/health" -UseBasicParsing | Out-Null }
    catch [System.Net.WebException] {
        $answer = $_.Exception.Response
        $refused = $answer -and [int]$answer.StatusCode -eq 404
    }
    if (-not $refused) { throw 'The guest-phone listener must answer /api/health with 404 (it serves /d/ links only)' }
    $launcher = [System.IO.File]::ReadAllText((Join-Path $MainRoot 'config\runtime\launcher.token')).Trim()
    $rotated = Invoke-WebRequest -Uri "$kiosk/kiosk/pairing-code/rotate" -Method Post -UseBasicParsing `
        -Headers @{ 'X-Photobooth-Launcher' = $launcher }
    if ($rotated.StatusCode -ne 204) { throw "Pairing code rotation answered $($rotated.StatusCode)" }
    Write-Host "Main $($version.app_version) (API $($version.api_version)) answers at $kiosk; database $($version.schema_revision); code $full"

    if (-not $KeepRunning) {
        $left = Stop-Started
        if ($left.Count) { throw "Main could not be stopped after its checks; see $runRecord" }
        Write-Host 'Main stopped after its first-start checks.'
    }
}
catch {
    $failure = $_
    $problems = New-Object System.Collections.Generic.List[string]
    $problems.Add("$failure")
    $left = @()
    try { $left = Stop-Started } catch { $problems.Add("stopping: $_"); $left = @('unknown') }
    if (-not $created) {
        # Nothing was written: nothing to move.
    }
    elseif ($left.Count) {
        $problems.Add("a process this install started may still run ($runRecord); $MainRoot was left in place")
    }
    else {
        try {
            $null = Assert-PlainPath -Path $MainRoot
            Start-Sleep -Seconds 1
            $aside = "$MainRoot.failed-$stamp"
            if (Test-Path -LiteralPath $MainRoot) {
                Move-Item -LiteralPath $MainRoot -Destination $aside
                Write-Warning "Moved the half-built Main to $aside"
            }
        }
        catch { $problems.Add("moving aside: $_; $MainRoot was left in place") }
    }
    throw "Main install failed: $($problems -join ' | ')"
}

if ($KeepRunning) {
    Write-Host "Main left running (PID $($script:started.Id), recorded in $runRecord); stop it with Main\app\scripts\stop-main.ps1"
}
Write-Host ''
Write-Host "MAIN INSTALLED at $MainRoot from $full$(if ($Tag) { " ($Tag)" })"
Write-Host '  Start:  Main\app\scripts\run-main.ps1      Stop: Main\app\scripts\stop-main.ps1'
Write-Host '  Next:   check Main yourself; only then tag main-release-001 (see Project_Docs\MAIN_INSTALL.md)'
