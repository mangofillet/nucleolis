param([int]$Port = 8079, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Project virtual environment missing. Install the backend dependencies first.'
}
if (-not $SkipBuild) {
    Push-Location (Join-Path $projectRoot 'ui')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
}
Push-Location $projectRoot
try {
    Write-Host "Nucleolis research workspace: http://127.0.0.1:$Port/"
    & $projectPython -m uvicorn nucleolis.api.main:app --app-dir src --host 127.0.0.1 --port $Port
} finally { Pop-Location }
