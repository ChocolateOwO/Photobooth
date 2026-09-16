# Shared helpers for Photobooth Dummy scripts (Windows PowerShell 5.1 compatible, ASCII only).
# Paths are derived from this file's location, so Thai characters in the checkout path are never typed.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:AppRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:InstanceRoot = Split-Path -Parent $script:AppRoot
$script:ProjectRoot = Split-Path -Parent $script:InstanceRoot

function Assert-DummyLayout {
    if ((Split-Path -Leaf $script:InstanceRoot) -ne 'Dummy') {
        throw "Refusing to run: expected <project>\Dummy\app layout, got $($script:AppRoot)"
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
