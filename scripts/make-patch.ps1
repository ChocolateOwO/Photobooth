# Milestone patch artifacts. Run ONLY after explicit user approval of the exact commit
# (except -DryRun). See Project_Docs\PROJECT_RULES.md "Milestone sequence".
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidatePattern('^\d{3}$')] [string] $Number,
    [Parameter(Mandatory)] [ValidatePattern('^[a-z0-9]+(-[a-z0-9]+)*$')] [string] $Slug,
    [Parameter(Mandatory)] [string] $Commit,
    [switch] $DryRun,
    [switch] $Resume,
    [string] $Approval = 'pending',
    [ValidateSet('passed', 'not_required', 'pending')] [string] $ManualTest = 'pending',
    [string] $Purpose = ''
)

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-DummyLayout
$python = Get-VenvPython
if ($DryRun -and $Resume) { throw 'Use -DryRun or -Resume, not both' }

$fullCommit = (& git -C $script:AppRoot rev-parse --verify "$Commit^{commit}").Trim()
if ($LASTEXITCODE -ne 0) { throw "Unknown commit $Commit" }
$record = Join-Path $script:InstanceRoot "data\verify\$fullCommit.json"

$arguments = @(
    (Join-Path $PSScriptRoot 'patchtool\make_patch.py'),
    '--repo', $script:AppRoot,
    '--patches-dir', (Join-Path $script:ProjectRoot 'patches'),
    '--index-file', (Join-Path $script:ProjectRoot 'Project_Docs\PATCH_INDEX.md'),
    '--number', $Number, '--slug', $Slug, '--commit', $fullCommit,
    '--verify-record', $record,
    '--approval', $Approval, '--manual-test', $ManualTest, '--purpose', $Purpose
)
if ($DryRun) { $arguments += '--dry-run' }
if ($Resume) { $arguments += '--resume' }
& $python @arguments
exit $LASTEXITCODE
