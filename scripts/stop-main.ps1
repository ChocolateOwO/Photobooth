# Stop only the process started by run-main.ps1 (or by install-main.ps1 -KeepRunning).
# The record must be Main's own (P13-R7): Main's run folder, or for the tests a record under the
# system temp dir outside the project; either way it must say instance "main". Each recorded process
# must match PID + creation time + exact executable + role marker in its command line; mismatches
# are refused and kept in the record.
[CmdletBinding()]
param([string] $PidFile)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
if ($PidFile) {
    $PidFile = Assert-PlainPath -Path $PidFile
    $temp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if (-not (Test-PathInside -Path $PidFile -Folder $temp) -or (Test-PathInside -Path $PidFile -Folder $script:ProjectRoot)) {
        throw "-PidFile is for isolated tests only (under $temp, outside the project), not $PidFile"
    }
}
else {
    Assert-MainLayout
    $PidFile = Assert-PlainPath -Path (Join-Path $script:InstanceRoot 'data\run\main-processes.json')
}
if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host 'Main is not running (no PID file).'
    return
}
$record = [System.IO.File]::ReadAllText($PidFile) | ConvertFrom-Json
if ("$($record.instance)" -cne 'main') {
    Write-Warning "$PidFile is not a Main process record (instance '$($record.instance)'); nothing stopped."
    exit 2
}
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
