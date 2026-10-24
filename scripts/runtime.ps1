# Shared runtime configuration. Paths in runtime.json are relative to this repository.
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeConfig = Get-Content -LiteralPath (Join-Path $repositoryRoot 'runtime.json') -Raw | ConvertFrom-Json
$runtimeRoot = if ($env:SUBJECTS_LEARNING_RUNTIME) { [IO.Path]::GetFullPath($env:SUBJECTS_LEARNING_RUNTIME) } else { [IO.Path]::GetFullPath((Join-Path $repositoryRoot $runtimeConfig.root)) }
$python = Join-Path $runtimeRoot $runtimeConfig.python
if (!(Test-Path -LiteralPath $python) -and (Test-Path -LiteralPath (Join-Path $runtimeRoot 'python/Scripts/python.exe'))) {
    $python = Join-Path $runtimeRoot 'python/Scripts/python.exe'
}
$packages = Join-Path $runtimeRoot $runtimeConfig.packages
$env:SUBJECTS_LEARNING_RUNTIME = $runtimeRoot
$env:PYTHONPATH = $packages
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = Join-Path $runtimeRoot 'tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $runtimeRoot 'cache/pip'
$env:RUFF_CACHE_DIR = Join-Path $runtimeRoot 'cache/ruff'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
# Repair only the legacy shared frontend junctions; fresh npm installations remain
# ordinary per-project directories. Never traverse or delete the linked target.
$sharedNodeModules = Join-Path $runtimeRoot 'node_modules'
if (Test-Path -LiteralPath $sharedNodeModules) {
    foreach ($project in @('subjects-learning-1', 'subjects-learning-2')) {
        $linkPath = Join-Path $repositoryRoot "$project/frontend/node_modules"
        $link = Get-Item -LiteralPath $linkPath -Force -ErrorAction SilentlyContinue
        if ($link -and $link.LinkType -eq 'Junction' -and [string]$link.Target -ne $sharedNodeModules) {
            $fullLinkPath = [IO.Path]::GetFullPath($linkPath)
            if (!$fullLinkPath.StartsWith($repositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected frontend link path.' }
            [IO.Directory]::Delete($fullLinkPath)
            New-Item -ItemType Junction -Path $fullLinkPath -Target $sharedNodeModules | Out-Null
        }
    }
}
