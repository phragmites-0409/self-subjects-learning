$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $repository 'scripts/runtime.ps1')
$rendererRoot = Join-Path $runtimeRoot 'document-renderer'
New-Item -ItemType Directory -Force -Path $rendererRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $repository 'dependencies/renderer/package.json'),(Join-Path $repository 'dependencies/renderer/package-lock.json') -Destination $rendererRoot
npm ci --prefix $rendererRoot --cache (Join-Path $runtimeRoot 'cache/npm') --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Local formula renderer installation failed.' }
