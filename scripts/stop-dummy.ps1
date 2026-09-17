# Stop only the processes started by run-dummy.ps1.
# Each recorded process must match PID + creation time + exact executable + role marker in its
# command line; mismatches are refused and kept in the record. -PidFile exists for tests.
[CmdletBinding()]
param([string] $PidFile)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-DummyLayout

if (-not $PidFile) { $PidFile = Join-Path $script:InstanceRoot 'data\run\dummy-processes.json' }
if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host 'Dummy is not running (no PID file).'
    return
}
$record = [System.IO.File]::ReadAllText($PidFile) | ConvertFrom-Json
$remaining = New-Object System.Collections.Generic.List[object]
$failures = 0

foreach ($entry in @($record.processes)) {
    $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if (-not $process) {
        Write-Host "$($entry.role) PID $($entry.pid) already exited."
        continue
    }
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)" -ErrorAction SilentlyContinue
    $startTime = $process.StartTime.ToUniversalTime().ToString('o')
    $sameStart = $startTime -eq $entry.start_time
    $sameExe = ("$($cim.ExecutablePath)").ToLowerInvariant() -eq ("$($entry.executable)").ToLowerInvariant()
    $hasMarker = ("$($cim.CommandLine)").ToLowerInvariant().Contains(("$($entry.marker)").ToLowerInvariant())
    if (-not ($sameStart -and $sameExe -and $hasMarker)) {
        if (-not $sameStart) {
            # Different creation time: the PID was recycled; the recorded process is gone.
            Write-Warning "$($entry.role) PID $($entry.pid) now belongs to another process (start time differs); not stopped."
            continue
        }
        Write-Warning "$($entry.role) PID $($entry.pid) identity mismatch (exe=$sameExe marker=$hasMarker); not stopped."
        $remaining.Add($entry)
        $failures++
        continue
    }
    & taskkill.exe /PID $entry.pid /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "taskkill failed for $($entry.role) PID $($entry.pid) (exit $LASTEXITCODE); record kept."
        $remaining.Add($entry)
        $failures++
        continue
    }
    Write-Host "Stopped $($entry.role) PID $($entry.pid)."
}

if ($remaining.Count -eq 0) {
    Remove-Item -LiteralPath $PidFile
    Write-Host 'PHOTOBOOTH DUMMY stopped.'
}
else {
    $record.processes = @($remaining)
    [System.IO.File]::WriteAllText($PidFile, ($record | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding $false))
    Write-Warning "$failures process(es) not stopped; record kept at $PidFile"
    exit 1
}
