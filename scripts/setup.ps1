param(
    [string]$PythonCommand = 'python',
    [switch]$Formula,
    [switch]$InkTools,
    [switch]$Frontend,
    [switch]$Renderer,
    [switch]$SkipModels
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'runtime.ps1')
$mainRoot = Join-Path $repositoryRoot 'subjects-learning-2'
if (!(Test-Path -LiteralPath $python)) {
    $savedPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = ''
        & $PythonCommand -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 is required by this Windows lockfile"'
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12, then use -PythonCommand with its path.' }
        & $PythonCommand -m venv (Join-Path $runtimeRoot 'python')
        if ($LASTEXITCODE -ne 0) { throw 'Unable to create local Python environment.' }
    } finally { $env:PYTHONPATH = $savedPythonPath }
}
# A fresh venv uses Scripts/python.exe; the migrated full interpreter uses python.exe.
if (!(Test-Path -LiteralPath $python)) { $python = Join-Path $runtimeRoot 'python/Scripts/python.exe' }
New-Item -ItemType Directory -Force -Path $packages | Out-Null
& $python -m pip install --upgrade --target $packages -r (Join-Path $repositoryRoot 'dependencies/requirements/main.txt')
if ($LASTEXITCODE -ne 0) { throw 'Backend/OCR dependency installation failed.' }
if (!$SkipModels) {
    & $python (Join-Path $mainRoot 'scripts/prepare-local-ocr.py')
    if ($LASTEXITCODE -ne 0) { throw 'OCR model preparation failed.' }
}
if ($Formula) {
    $formula = Join-Path $runtimeRoot 'formula/Scripts/python.exe'
    if (!(Test-Path -LiteralPath $formula)) {
        & $python -m venv (Join-Path $runtimeRoot 'formula')
        if ($LASTEXITCODE -ne 0) { throw 'Formula environment creation failed.' }
    }
    $savedPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = ''
        & $formula -m pip install -r (Join-Path $repositoryRoot 'dependencies/requirements/formula.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Formula dependency installation failed.' }
        if (!$SkipModels) {
            & $formula (Join-Path $mainRoot 'scripts/prepare-local-formula.py')
            if ($LASTEXITCODE -ne 0) { throw 'Formula model preparation failed.' }
        }
    } finally { $env:PYTHONPATH = $savedPythonPath }
}
if ($InkTools) {
    $ink = Join-Path $runtimeRoot 'ink-erase/Scripts/python.exe'
    if (!(Test-Path -LiteralPath $ink)) {
        & $python -m venv (Join-Path $runtimeRoot 'ink-erase')
        if ($LASTEXITCODE -ne 0) { throw 'Ink model tooling environment creation failed.' }
    }
    & $ink -m pip install -r (Join-Path $repositoryRoot 'dependencies/requirements/ink-tools.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Ink model tooling installation failed.' }
    & $python -m pip install --upgrade --target $packages -r (Join-Path $repositoryRoot 'dependencies/requirements/model-tools.txt')
    if ($LASTEXITCODE -ne 0) { throw 'ONNX export tooling installation failed.' }
}
if ($Renderer) { & (Join-Path $mainRoot 'scripts/setup-document-renderer.ps1') }
if ($Frontend) {
    foreach ($project in @('subjects-learning-1', 'subjects-learning-2')) {
        Push-Location (Join-Path $repositoryRoot "$project/frontend")
        try {
            npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed: $project" }
            npm run build
            if ($LASTEXITCODE -ne 0) { throw "Frontend build failed: $project" }
        } finally { Pop-Location }
    }
}
Write-Output "Runtime prepared at $runtimeRoot. Start with start-local.cmd."
