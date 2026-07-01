<#
.SYNOPSIS
  Avvia la dashboard F8 in locale (FastAPI + Vite).

.PARAMETER SkipFreePorts
  Skip the pre-launch step that frees the API and Vite ports from stale
  listeners. Useful if you want to keep another dashboard session running.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\dev.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\dev.ps1 -SkipFreePorts
#>
param(
  [switch]$SkipFreePorts
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$apiPort = if ($env:API_SERVER_PORT) { $env:API_SERVER_PORT } else { "9001" }
$webPort = "5173"

Write-Host "F8 13F Screener - Local Dashboard"
Write-Host "API: http://127.0.0.1:$apiPort"
Write-Host "Web: http://127.0.0.1:$webPort"
Write-Host "Premi Ctrl+C per fermare entrambi."
Write-Host ""

if (-not $SkipFreePorts) {
  $freeScript = Join-Path $PSScriptRoot "scripts\_free_ports.ps1"
  if (Test-Path $freeScript) {
    Write-Host "[setup] Freeing ports 9001, 5173-5179, 8501, 8502, 3000 from stale listeners..."
    & $freeScript -ApiPort ([int]$apiPort)
  }
}

if (-not (Test-Path "frontend\node_modules")) {
  Write-Host "[setup] Installing frontend dependencies..."
  Push-Location frontend
  npm install
  Pop-Location
}

$apiProc = Start-Process `
  -FilePath "python" `
  -ArgumentList @("-m", "src.api") `
  -WorkingDirectory $PSScriptRoot `
  -PassThru `
  -NoNewWindow

$webProc = Start-Process `
  -FilePath "npm.cmd" `
  -ArgumentList @("run", "dev") `
  -WorkingDirectory (Join-Path $PSScriptRoot "frontend") `
  -PassThru `
  -NoNewWindow

try {
  while ($true) {
    if ($apiProc.HasExited -or $webProc.HasExited) { break }
    Start-Sleep -Seconds 1
  }
}
finally {
  foreach ($proc in @($apiProc, $webProc)) {
    if ($proc -and -not $proc.HasExited) {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
  }
}
