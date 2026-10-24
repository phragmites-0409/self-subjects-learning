param([switch]$NoBrowser, [int]$Port=0)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path (Split-Path -Parent $projectRoot) 'scripts/runtime.ps1')
if (Test-Path -LiteralPath $python) {
    & $python (Join-Path $repositoryRoot 'scripts/repair-runtime.py')
    if ($LASTEXITCODE -ne 0) { throw 'Runtime relocation repair failed.' }
}
Set-Location -LiteralPath $projectRoot
$version=Get-Content -LiteralPath (Join-Path $projectRoot 'version.json') -Raw | ConvertFrom-Json
if (!$Port) { $Port=[int]$version.port }
$env:PORT=[string]$Port
$env:DATA_DIR=Join-Path $projectRoot 'data'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH=$packages
$env:TEMP=Join-Path $runtimeRoot 'tmp'; $env:TMP=$env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$serviceUrl="http://127.0.0.1:$Port"
try {
    $health=Invoke-RestMethod "$serviceUrl/api/v1/health" -TimeoutSec 2
    if ($health.application_id -ne 'subjects-learning' -or $health.version -ne $version.version) { throw 'This port belongs to another project version.' }
    if (!$NoBrowser) { Start-Process $serviceUrl }; exit 0
} catch {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $Port is occupied; do not replace its service." }
}
if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'frontend/dist/index.html'))) { throw 'Frontend build missing. Run scripts/build.ps1.' }
$logs=Join-Path $projectRoot 'data/logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$arguments='-m uvicorn app.main:app --app-dir "'+(Join-Path $projectRoot 'backend')+'" --host 127.0.0.1 --port '+$Port
$server=Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'server-output.log') -RedirectStandardError (Join-Path $logs 'server-error.log') -PassThru
Set-Content -LiteralPath (Join-Path $logs 'server.pid') -Value $server.Id -Encoding ascii
for ($attempt=0;$attempt -lt 60;$attempt++) {
    Start-Sleep -Milliseconds 500
    try { $health=Invoke-RestMethod "$serviceUrl/api/v1/health" -TimeoutSec 1; if ($health.version -ne $version.version) { throw 'Unexpected version' }; if (!$NoBrowser) { Start-Process $serviceUrl }; exit 0 } catch { }
}
throw 'Server startup failed; see data/logs/server-error.log.'
