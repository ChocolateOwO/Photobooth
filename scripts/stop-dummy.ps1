# Stop only the processes started by run-dummy.ps1 (verified by PID file + command line).
[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-DummyLayout

$pidFile = Join-Path $script:InstanceRoot 'data\run\dummy-processes.json'
if (-not (Test-Path $pidFile)) {
    Write-Host 'Dummy is not running (no PID file).'
    return
}
$record = Get-Content -Raw -Path $pidFile | ConvertFrom-Json
$appRootLower = $script:AppRoot.ToLowerInvariant()

foreach ($processId in @($record.backend_pid, $record.vite_pid)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if (-not $process) {
        Write-Host "PID $processId already exited."
        continue
    }
    $commandLine = "$($process.CommandLine)".ToLowerInvariant()
    $executable = "$($process.ExecutablePath)".ToLowerInvariant()
    $instanceLower = $script:InstanceRoot.ToLowerInvariant()
    if (-not ($commandLine.Contains($appRootLower) -or $executable.StartsWith($instanceLower))) {
        Write-Warning "PID $processId is not a Dummy process ($($process.Name)); not stopped."
        continue
    }
    & taskkill.exe /PID $processId /T /F | Out-Null
    Write-Host "Stopped PID $processId ($($process.Name))."
}
Remove-Item -LiteralPath $pidFile
Write-Host 'PHOTOBOOTH DUMMY stopped.'
