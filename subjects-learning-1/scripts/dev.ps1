$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'start.ps1') -NoBrowser
Set-Location (Join-Path $root 'frontend')
npm run dev -- --host 127.0.0.1
