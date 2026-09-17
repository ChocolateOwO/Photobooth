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
$remaining = Stop-RecordedProcesses -Entries @($record.processes)
$commit = if ($record.PSObject.Properties['commit']) { "$($record.commit)" } else { '' }
Save-ProcessRecord -Path $PidFile -Entries $remaining.ToArray() -Commit $commit

if ($remaining.Count -eq 0) {
    Write-Host 'PHOTOBOOTH DUMMY stopped.'
}
else {
    Write-Warning "$($remaining.Count) process(es) not stopped; record kept at $PidFile"
    exit 1
}
