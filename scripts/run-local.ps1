$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not (Test-Path (Join-Path $resolvedRoot ".venv"))) {
  python -m venv (Join-Path $resolvedRoot ".venv")
  & (Join-Path $resolvedRoot ".venv\Scripts\python.exe") -m pip install -r (Join-Path $resolvedRoot "backend\requirements-runtime.txt")
}
Start-Process -FilePath (Join-Path $resolvedRoot ".venv\Scripts\python.exe") -ArgumentList "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--reload", "--port", "8000" -WorkingDirectory $resolvedRoot -WindowStyle Hidden
Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory (Join-Path $resolvedRoot "frontend") -WindowStyle Hidden
Write-Output "TraceOS API: http://localhost:8000/docs"
Write-Output "TraceOS console: http://localhost:3000"
