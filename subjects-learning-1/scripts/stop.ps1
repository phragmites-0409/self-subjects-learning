$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot 'data/logs/server.pid'
if (Test-Path -LiteralPath $pidFile) {
    $serverPid = [int](Get-Content -LiteralPath $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine.Contains('uvicorn app.main:app') -and $process.CommandLine.Contains((Join-Path $projectRoot 'backend'))) {
        # Windows' venv launcher can own a child interpreter. Stop only children
        # carrying this project's verified server command, before the launcher.
        $serverChildren = Get-CimInstance Win32_Process -Filter "ParentProcessId=$serverPid" -ErrorAction SilentlyContinue
        foreach ($child in $serverChildren) {
            if ($child.CommandLine -and $child.CommandLine.Contains('uvicorn app.main:app') -and $child.CommandLine.Contains((Join-Path $projectRoot 'backend'))) {
                Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
            }
        }
        Stop-Process -Id $serverPid
        Remove-Item -LiteralPath $pidFile
    }
}
