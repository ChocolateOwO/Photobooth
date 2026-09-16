# Phase gate: every automated check. Exit 0 only if all pass.
# Writes Dummy\data\verify\<commit>.json (result=passed) only when the tree is clean and all steps pass.
[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'lib\common.ps1')
Assert-DummyLayout

$results = New-Object System.Collections.Generic.List[object]
$app = $script:AppRoot
$backend = Join-Path $app 'backend'
$frontend = Join-Path $app 'frontend'
$e2e = Join-Path $app 'e2e'

function Step {
    param([string] $Name, [scriptblock] $Body)
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    $started = Get-Date
    $output = & $Body | ForEach-Object { "$_" } | Tee-Object -Variable captured
    $output | Out-Host
    $text = ($captured -join "`n")
    $results.Add([pscustomobject]@{
            suite   = $Name
            result  = 'passed'
            seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
            counts  = (Get-Counts $text)
        })
}

function Get-Counts {
    param([string] $Text)
    $patterns = @(
        '(\d+ passed(?:, \d+ \w+)*)(?: in [\d\.]+s)?',
        'Tests\s+(\d+ passed(?: \| \d+ \w+)*)',
        'Contracts: (\d+ kept, \d+ broken)',
        '(Success: no issues found in \d+ source files)',
        '(All checks passed!)'
    )
    foreach ($p in $patterns) {
        $m = [regex]::Matches($Text, $p)
        if ($m.Count -gt 0) { return $m[$m.Count - 1].Groups[1].Value }
    }
    return ''
}

$overall = 'failed'
try {
    $nodeVersion = Use-Node24
    $python = Get-VenvPython

    Step 'toolchain' {
        $pyVersion = (& $python --version).Trim()
        if (-not $pyVersion.StartsWith('Python 3.13')) { throw "Python 3.13 required, found $pyVersion" }
        "node $nodeVersion; npm $((& npm.cmd --version).Trim()); $pyVersion"
    }
    Step 'backend dependencies (pip check)' { Invoke-Native $python @('-m', 'pip', 'check') $backend }
    Step 'ruff' {
        Invoke-Native $python @('-m', 'ruff', 'check', 'src', 'tests', 'alembic', '..\scripts') $backend
        Invoke-Native $python @('-m', 'ruff', 'format', '--check', 'src', 'tests', 'alembic', '..\scripts') $backend
    }
    Step 'mypy (strict)' { Invoke-Native $python @('-m', 'mypy') $backend }
    Step 'import architecture (import-linter)' {
        Invoke-Native (Join-Path $backend '.venv\Scripts\lint-imports.exe') @() $backend
    }
    Step 'pytest (backend + scripts: config, guard, lock, listeners, pairing, backup, migrations, gitignore, staged guard, make-patch)' {
        Invoke-Native $python @('-m', 'pytest', '-q', '-p', 'no:warnings') $backend
    }
    Step 'alembic upgrade/downgrade proof (CLI, Thai temp instance)' {
        $root = Get-ThaiTempRoot -Prefix 'pb-verify'
        try {
            $envFile = Join-Path $root 'config\photobooth.env'
            Invoke-Native $python @('-m', 'photobooth', 'init-env', '--instance', 'dummy', '--profile', 'test',
                '--instance-root', $root, '--output', $envFile, '--kiosk-port', '18111',
                '--delivery-port', '18113', '--delivery-host', '127.0.0.1')
            Invoke-Native $python @('-m', 'photobooth', 'db-upgrade', '--env-file', $envFile)
            Invoke-Native $python @('-m', 'photobooth', 'db-check', '--env-file', $envFile)
            Invoke-Native $python @('-m', 'photobooth', 'backup', '--env-file', $envFile)
            Invoke-Native $python @('-m', 'photobooth', 'db-downgrade', '--env-file', $envFile, '--revision', 'base')
            Invoke-Native $python @('-m', 'photobooth', 'db-upgrade', '--env-file', $envFile)
            Invoke-Native $python @('-m', 'photobooth', 'db-check', '--env-file', $envFile)
            'alembic: upgrade head -> backup -> downgrade base -> upgrade head passed'
        }
        finally {
            Remove-TempRoot -Path $root -Prefix 'pb-verify'
        }
    }
    Step 'OpenAPI contract + generated TS types are current' {
        $tmp = [System.IO.Path]::GetTempFileName()
        $tmpTs = "$tmp.d.ts"
        try {
            Invoke-Native $python @('-m', 'photobooth', 'export-openapi', '--output', $tmp) $backend
            if ((Get-FileHash $tmp).Hash -ne (Get-FileHash (Join-Path $backend 'openapi.json')).Hash) {
                throw 'backend\openapi.json is stale: run photobooth export-openapi and npm run gen:api'
            }
            Invoke-Native 'npx.cmd' @('openapi-typescript', '..\backend\openapi.json', '-o', $tmpTs) $frontend
            $expected = (Get-Content -Raw $tmpTs) -replace "`r`n", "`n"
            $actual = (Get-Content -Raw (Join-Path $frontend 'src\shared\api\schema.d.ts')) -replace "`r`n", "`n"
            if ($expected -ne $actual) { throw 'frontend schema.d.ts is stale: run npm run gen:api' }
            'openapi.json and schema.d.ts are current'
        }
        finally {
            Remove-Item $tmp, $tmpTs -ErrorAction SilentlyContinue
        }
    }
    Step 'frontend dependencies (npm ls)' {
        Invoke-Native 'npm.cmd' @('ls', '--depth=0') $frontend
        Invoke-Native 'npm.cmd' @('ls', '--depth=0') $e2e
    }
    Step 'frontend typecheck (tsc strict)' { Invoke-Native 'npm.cmd' @('run', 'typecheck') $frontend }
    Step 'frontend eslint' { Invoke-Native 'npm.cmd' @('run', 'lint') $frontend }
    Step 'frontend vitest' { Invoke-Native 'npm.cmd' @('test') $frontend }
    Step 'frontend vite production build' {
        $env:PHOTOBOOTH_INSTANCE = 'dummy'
        Invoke-Native 'npm.cmd' @('run', 'build') $frontend
    }
    Step 'playwright smoke (e2e instance)' {
        & (Join-Path $PSScriptRoot 'e2e.ps1') -SkipBuild
    }
    Step 'staged-file guard (all tracked files)' {
        Invoke-Native $python @((Join-Path $PSScriptRoot 'guards\check_staged.py'), '--repo', $app, '--tracked')
    }

    $dirty = (& git -C $app status --porcelain --untracked-files=all)
    $commit = (& git -C $app rev-parse HEAD).Trim()
    if ($dirty) {
        Write-Warning 'Working tree is dirty: make-patch dry run against this repository and the verify record require a clean committed tree.'
        $overall = 'passed-uncommitted'
    }
    else {
        Step 'make-patch dry run (this repository, no tag, nothing published)' {
            Invoke-Native $python @((Join-Path $PSScriptRoot 'patchtool\make_patch.py'), '--repo', $app,
                '--patches-dir', (Join-Path $script:ProjectRoot 'patches'),
                '--index-file', (Join-Path $script:ProjectRoot 'Project_Docs\PATCH_INDEX.md'),
                '--number', '001', '--slug', 'project-foundation', '--commit', $commit, '--dry-run')
        }
        $overall = 'passed'
    }
}
catch {
    $results.Add([pscustomobject]@{ suite = 'FAILURE'; result = 'failed'; seconds = 0; counts = "$_" })
    Write-Host "VERIFY FAILED: $_" -ForegroundColor Red
}

Write-Host ''
Write-Host '==================== VERIFY SUMMARY ====================' -ForegroundColor Cyan
$results | Format-Table -AutoSize suite, result, counts, seconds | Out-Host
Write-Host "RESULT: $overall"

if ($overall -eq 'passed') {
    $commit = (& git -C $app rev-parse HEAD).Trim()
    $recordDir = Join-Path $script:InstanceRoot 'data\verify'
    New-Item -ItemType Directory -Force -Path $recordDir | Out-Null
    [ordered]@{
        commit      = $commit
        result      = 'passed'
        finished_at = (Get-Date).ToString('o')
        tests       = $results
    } | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $recordDir "$commit.json") -Encoding UTF8
    Write-Host "Verify record: $recordDir\$commit.json"
    exit 0
}
if ($overall -eq 'passed-uncommitted') { exit 0 }
exit 1
