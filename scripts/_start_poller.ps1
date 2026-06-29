$ErrorActionPreference = 'Stop'
$root = 'C:\Users\andre\Downloads\F8_F13Screener'
$py   = Join-Path $root '.venv\Scripts\python.exe'
$out  = Join-Path $root 'logs\13f_alerts_freshtry.log.out'
$err  = Join-Path $root 'logs\13f_alerts_freshtry.log.err'

if (-not (Test-Path $py)) { throw "python.exe not found: $py" }
$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

$argList = @('-m','src.main','alerts')
$proc = Start-Process -FilePath $py -ArgumentList $argList `
    -WorkingDirectory $root `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -PassThru -WindowStyle Hidden

Write-Host ("STARTED PID={0} at {1:yyyy-MM-dd HH:mm:ss}" -f $proc.Id, (Get-Date))
Write-Host ("stdout: {0}" -f $out)
Write-Host ("stderr: {0}" -f $err)