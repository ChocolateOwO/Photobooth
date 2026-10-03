# Shared helpers for Photobooth Dummy scripts (Windows PowerShell 5.1 compatible, ASCII only).
# Paths are derived from this file's location, so Thai characters in the checkout path are never typed.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:AppRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:InstanceRoot = Split-Path -Parent $script:AppRoot
$script:ProjectRoot = Split-Path -Parent $script:InstanceRoot

function Clear-PhotoboothEnvironment {
    # Inherited PHOTOBOOTH_* / Playwright variables from the calling shell must never steer a script.
    # (The backend also ignores process environment for settings; this is defence in depth.)
    foreach ($name in @(Get-ChildItem Env: | Where-Object {
                $_.Name -like 'PHOTOBOOTH_*' -or $_.Name -eq 'PLAYWRIGHT_BROWSERS_PATH' } |
            ForEach-Object Name)) {
        Remove-Item -LiteralPath "Env:$name"
    }
}

function Use-IsolatedPlaywrightBrowsers {
    # Photobooth's Playwright browsers live in Dummy runtime storage, never in the shared user cache.
    $path = Join-Path $script:InstanceRoot 'data\playwright-browsers'
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    $env:PLAYWRIGHT_BROWSERS_PATH = $path
    return $path
}

function Assert-DummyLayout {
    if ((Split-Path -Leaf $script:InstanceRoot) -ne 'Dummy') {
        throw "Refusing to run: expected <project>\Dummy\app layout, got $($script:AppRoot)"
    }
}

function Assert-MainLayout {
    if ((Split-Path -Leaf $script:InstanceRoot) -ne 'Main') {
        throw "Refusing to run: expected <project>\Main\app layout, got $($script:AppRoot)"
    }
}

function Use-Node24 {
    $nodeDir = Join-Path $script:InstanceRoot 'tools\node24'
    if (-not (Test-Path (Join-Path $nodeDir 'node.exe'))) {
        throw "Node 24 not found at $nodeDir"
    }
    $env:Path = "$nodeDir;" + (($env:Path -split ';' | Where-Object { $_ -and ($_ -notmatch '\\nodejs\\?$') }) -join ';')
    $version = (& (Join-Path $nodeDir 'node.exe') --version).Trim()
    if (-not $version.StartsWith('v24.')) {
        throw "Node 24 required, found $version"
    }
    return $version
}

function Get-VenvPython {
    $python = Join-Path $script:AppRoot 'backend\.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        throw "Backend venv missing: run 'py -3.13 -m venv backend\.venv' and install backend[dev]"
    }
    return $python
}

function Invoke-Native {
    # Runs a native command, streams output, throws on non-zero exit.
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [string[]] $Arguments = @(),
        [string] $WorkingDirectory = $script:AppRoot
    )
    Push-Location $WorkingDirectory
    $previous = $ErrorActionPreference
    # Native tools write progress to stderr; only the exit code decides success.
    $ErrorActionPreference = 'Continue'
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath $($Arguments -join ' ') exited with $LASTEXITCODE"
        }
    }
    finally {
        $ErrorActionPreference = $previous
        Pop-Location
    }
}

function Test-PortFree {
    param([Parameter(Mandatory)] [int] $Port)
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($listener) { $listener.Stop() }
    }
}

function Wait-HttpOk {
    param([Parameter(Mandatory)] [string] $Url, [int] $TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Timed out waiting for $Url"
}

function Get-NextMilestoneNumber {
    # Next unused dummy-patch number as a three-digit string. Integer arithmetic only:
    # Measure-Object -Maximum returns a Double, which the D3 format specifier rejects.
    param([Parameter(Mandatory)] [string] $Repo)
    [int] $max = 0
    foreach ($tag in @(& git -C $Repo tag --list 'dummy-patch-*')) {
        if ($tag -match '^dummy-patch-(\d{3})-') {
            [int] $n = [int] $Matches[1]
            if ($n -gt $max) { $max = $n }
        }
    }
    return ([int]($max + 1)).ToString('D3')
}

function Get-ProcessIdentity {
    # Identity recorded so a recycled PID or an unrelated process is never killed.
    # Executable path comes from the same source stop-time verification uses (Win32_Process), polled
    # until available: immediately after launch Process.Path can still be empty.
    param([System.Diagnostics.Process] $Process, [string] $Role, [string] $Marker)
    $deadline = (Get-Date).AddSeconds(10)
    $executable = $null
    while (-not $executable) {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $($Process.Id)" -ErrorAction SilentlyContinue
        if ($cim -and $cim.ExecutablePath) { $executable = $cim.ExecutablePath; break }
        if ((Get-Date) -gt $deadline) { throw "executable path unavailable for PID $($Process.Id)" }
        Start-Sleep -Milliseconds 100
    }
    $Process.Refresh()
    return [pscustomobject][ordered]@{
        role       = $Role
        pid        = $Process.Id
        start_time = $Process.StartTime.ToUniversalTime().ToString('o')
        executable = $executable
        marker     = $Marker
    }
}

function Stop-RecordedProcesses {
    # Stops exact identity matches. Returns entries that could not be verified or stopped.
    param([object[]] $Entries)
    $remaining = New-Object System.Collections.Generic.List[object]
    foreach ($entry in @($Entries)) {
        if ($null -eq $entry) { continue }
        $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
        if (-not $process) {
            Write-Host "$($entry.role) PID $($entry.pid) already exited."
            continue
        }
        if ($entry.start_time -eq 'unknown') {
            Write-Warning "$($entry.role) PID $($entry.pid) has no verified identity; not stopped, record kept."
            $remaining.Add($entry)
            continue
        }
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)" -ErrorAction SilentlyContinue
        $sameStart = $process.StartTime.ToUniversalTime().ToString('o') -eq $entry.start_time
        if (-not $sameStart) {
            Write-Warning "$($entry.role) PID $($entry.pid) now belongs to another process (start time differs); not stopped."
            continue
        }
        $sameExe = ("$($cim.ExecutablePath)").ToLowerInvariant() -eq ("$($entry.executable)").ToLowerInvariant()
        $hasMarker = ("$($cim.CommandLine)").ToLowerInvariant().Contains(("$($entry.marker)").ToLowerInvariant())
        if (-not ($sameExe -and $hasMarker)) {
            Write-Warning "$($entry.role) PID $($entry.pid) identity mismatch (exe=$sameExe marker=$hasMarker); not stopped."
            $remaining.Add($entry)
            continue
        }
        & taskkill.exe /PID $entry.pid /T /F | Out-Null
        $killExit = $LASTEXITCODE
        if ($killExit -ne 0) {
            # A venv python.exe launcher exits by itself once its child interpreter is killed, so
            # taskkill can report "no running instance" for a tree that is in fact gone. Only a
            # process still running with the recorded identity keeps the record.
            Start-Sleep -Milliseconds 300
            $still = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
            if ($still -and $still.StartTime.ToUniversalTime().ToString('o') -eq $entry.start_time) {
                Write-Warning "taskkill failed for $($entry.role) PID $($entry.pid) (exit $killExit); record kept."
                $remaining.Add($entry)
                continue
            }
        }
        Write-Host "Stopped $($entry.role) PID $($entry.pid)."
    }
    return , $remaining
}

function Save-ProcessRecord {
    # Publishes the record atomically; an empty list removes it.
    param([Parameter(Mandatory)] [string] $Path, [object[]] $Entries, [string] $Commit = '', [string] $Instance = 'dummy')
    $list = @($Entries | Where-Object { $null -ne $_ })
    if ($list.Count -eq 0) {
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path }
        return
    }
    $record = [ordered]@{
        instance   = $Instance
        updated_at = (Get-Date).ToString('o')
        commit     = $Commit
        processes  = $list
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $tmp = "$Path.$([guid]::NewGuid().ToString('N')).tmp"
    [System.IO.File]::WriteAllText($tmp, ($record | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding $false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Invoke-TrackedStartup {
    # Runs $Body with a $start scriptblock that launches and immediately records each child.
    # Any failure (launch, identity, record write, readiness) stops every verified child started so
    # far; unverifiable survivors stay in the record for stop-dummy.ps1.
    param(
        [Parameter(Mandatory)] [string] $RecordPath,
        [Parameter(Mandatory)] [scriptblock] $Body,
        [string] $Commit = '',
        [string] $Instance = 'dummy'
    )
    $tracked = New-Object System.Collections.Generic.List[object]
    $start = {
        param([string] $Role, [string] $Marker, [string] $FilePath, [string[]] $ArgumentList,
            [string] $WorkingDirectory, [string] $StdOut, [string] $StdErr)
        $startArgs = @{
            FilePath         = $FilePath
            ArgumentList     = $ArgumentList
            WorkingDirectory = $WorkingDirectory
            PassThru         = $true
            WindowStyle      = 'Minimized'
        }
        if ($StdOut) { $startArgs.RedirectStandardOutput = $StdOut }
        if ($StdErr) { $startArgs.RedirectStandardError = $StdErr }
        $process = Start-Process @startArgs
        try {
            $tracked.Add((Get-ProcessIdentity -Process $process -Role $Role -Marker $Marker))
        }
        catch {
            # Identity unreadable: record the bare PID with an impossible start time so it is never
            # killed blindly, then fail the startup.
            $tracked.Add([pscustomobject]@{ role = $Role; pid = $process.Id; start_time = 'unknown'; executable = $FilePath; marker = $Marker })
            throw "could not record identity of $Role (PID $($process.Id)): $_"
        }
        Save-ProcessRecord -Path $RecordPath -Entries $tracked.ToArray() -Commit $Commit -Instance $Instance
        return $process
    }  # no GetNewClosure: resolves $tracked/$RecordPath dynamically from this function's scope

    try {
        & $Body $start
    }
    catch {
        $failure = $_
        Write-Warning "Startup failed: $failure. Stopping started processes."
        $remaining = Stop-RecordedProcesses -Entries $tracked.ToArray()
        Save-ProcessRecord -Path $RecordPath -Entries $remaining.ToArray() -Commit $Commit -Instance $Instance
        throw $failure
    }
}

function Get-ThaiTempRoot {
    param([Parameter(Mandatory)] [string] $Prefix)
    # Thai segment built from code points so this file stays ASCII: "thotsop" (test).
    $thai = -join ([char]0x0E17, [char]0x0E14, [char]0x0E2A, [char]0x0E2D, [char]0x0E1A)
    $name = '{0}-{1}-{2}' -f $Prefix, $thai, ([guid]::NewGuid().ToString('N').Substring(0, 8))
    $root = Join-Path ([System.IO.Path]::GetTempPath()) $name
    New-Item -ItemType Directory -Path $root | Out-Null
    return $root
}

function Remove-TempRoot {
    param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] [string] $Prefix)
    $temp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($temp, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Leaf $full).StartsWith("$Prefix-")) {
        throw "Refusing to delete non-temp path: $full"
    }
    if (Test-Path -LiteralPath $full) {
        Remove-Item -LiteralPath $full -Recurse -Force
    }
}
