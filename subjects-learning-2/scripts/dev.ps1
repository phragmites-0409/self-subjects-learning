$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$version = Get-Content -LiteralPath (Join-Path $root 'version.json') -Raw | ConvertFrom-Json
& (Join-Path $PSScriptRoot 'start.ps1') -NoBrowser
$env:API_PROXY_TARGET = "http://127.0.0.1:$($version.port)"
$env:VITE_API_BASE_URL = '/api/v1'
Push-Location (Join-Path $root 'frontend')
try { npm run dev; if ($LASTEXITCODE -ne 0) { throw 'Frontend development server failed' } } finally { Pop-Location }
