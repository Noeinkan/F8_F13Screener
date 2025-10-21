# Script per visualizzare il log in tempo reale
# Uso: .\watch_log.ps1

Write-Host "=== 13F Alert System - Monitor Log ===" -ForegroundColor Cyan
Write-Host "Visualizzazione in tempo reale di: 13f_alerts.log" -ForegroundColor Yellow
Write-Host "Premi Ctrl+C per uscire`n" -ForegroundColor Gray

Get-Content -Path "13f_alerts.log" -Wait -Tail 20
