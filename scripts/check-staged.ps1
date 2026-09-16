# Staged-content guard wrapper. -Staged for pre-commit, -Tracked for verify.
[CmdletBinding()]
param([switch] $Staged, [switch] $Tracked)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
if ($Staged -eq $Tracked) { throw 'Use exactly one of -Staged or -Tracked' }
$python = Join-Path $script:AppRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'py'; $prefix = @('-3.13') } else { $prefix = @() }
$mode = if ($Staged) { '--staged' } else { '--tracked' }
& $python @prefix (Join-Path $PSScriptRoot 'guards\check_staged.py') '--repo' $script:AppRoot $mode
exit $LASTEXITCODE
