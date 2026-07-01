<#
.SYNOPSIS
  Frees up TCP listener ports used by the F8 dashboard (FastAPI + Vite).

.DESCRIPTION
  Kills any process that currently owns a LISTEN socket on the API port
  (default 9001) or the Vite dev-server port range (default 5173-5179).
  Only listener sockets are touched; established connections are left alone.
  Output is a summary of the PIDs that were stopped.

.PARAMETER ApiPort
  API port to free. Defaults to 9001 (or $env:API_SERVER_PORT if set).

.PARAMETER VitePortStart
  First Vite dev-server port to free. Defaults to 5173.

.PARAMETER VitePortEnd
  Last Vite dev-server port to free. Defaults to 5179.

.PARAMETER ExtraPorts
  Additional ports to free (e.g. legacy Streamlit 8501/8502, fallback 3000).
  Defaults to 8501, 8502, 3000.

.PARAMETER DryRun
  List the processes that would be stopped without actually stopping them.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\_free_ports.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\_free_ports.ps1 -DryRun
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\_free_ports.ps1 -ApiPort 9001 -ExtraPorts 8501,8502
#>
[CmdletBinding()]
param(
  [int]$ApiPort       = $(if ($env:API_SERVER_PORT) { [int]$env:API_SERVER_PORT } else { 9001 }),
  [int]$VitePortStart = 5173,
  [int]$VitePortEnd   = 5179,
  [int[]]$ExtraPorts  = @(8501, 8502, 3000),
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$ports = @($ApiPort)
$ports += ($VitePortStart..$VitePortEnd)
if ($ExtraPorts) { $ports += $ExtraPorts }
$ports = $ports | Select-Object -Unique

$killedPids = @{}

foreach ($port in $ports) {
  $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if (-not $conns) { continue }

  foreach ($conn in $conns) {
    $ownerPid = $conn.OwningProcess
    if (-not $ownerPid) { continue }
    if ($killedPids.ContainsKey($ownerPid)) { continue }

    $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
    $name = if ($proc) { $proc.ProcessName } else { '<unknown>' }
    $label = if ($DryRun) { 'DRY-RUN' } else { 'STOPPED' }
    Write-Host ("[{0}] port={1} pid={2} name={3}" -f $label, $port, $ownerPid, $name)

    if (-not $DryRun) {
      Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
    }
    $killedPids[$ownerPid] = $true
  }
}

if ($killedPids.Count -eq 0) {
  Write-Host "[ok] no listeners on ports $($ports -join ', ')"
}
