param([switch]$Formula)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
& (Join-Path $repository 'scripts/setup.ps1') -Formula:$Formula
