# Stop only the process started by run-main.ps1.
# Each recorded process must match PID + creation time + exact executable + role marker in its
# command line; mismatches are refused and kept in the record. -PidFile exists for tests.
[CmdletBinding()]
param([string] $PidFile)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
if (-not $PidFile) {
    Assert-MainLayout
    $PidFile = Join-Path $script:InstanceRoot 'data\run\main-processes.json'
}
if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host 'Main is not running (no PID file).'
    return
}
$record = [System.IO.File]::ReadAllText($PidFile) | ConvertFrom-Json
$remaining = Stop-RecordedProcesses -Entries @($record.processes)
$commit = if ($record.PSObject.Properties['commit']) { "$($record.commit)" } else { '' }
Save-ProcessRecord -Path $PidFile -Entries $remaining.ToArray() -Commit $commit -Instance 'main'

if ($remaining.Count -eq 0) {
    Write-Host 'PHOTOBOOTH MAIN stopped.'
}
else {
    Write-Warning "$($remaining.Count) process(es) not stopped; record kept at $PidFile"
    exit 1
}
