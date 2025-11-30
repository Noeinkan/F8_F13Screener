# Script per visualizzare il log in tempo reale
# Uso: .\watch_log.ps1

$logPath = Join-Path $PSScriptRoot "..\logs\13f_alerts.log"

Write-Host "=== 13F Alert System - Monitor Log ===" -ForegroundColor Cyan
Write-Host "Visualizzazione in tempo reale di: $logPath" -ForegroundColor Yellow
Write-Host "Premi Ctrl+C per uscire`n" -ForegroundColor Gray

if (Test-Path $logPath) {
    Get-Content -Path $logPath -Wait -Tail 20
} else {
    Write-Host "Log file not found: $logPath" -ForegroundColor Red
    Write-Host "Run 13f_alert.py first to create the log file." -ForegroundColor Yellow
}
