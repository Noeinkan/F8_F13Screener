$ErrorActionPreference = 'SilentlyContinue'
$procs = Get-Process python
foreach ($p in $procs) {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $p.Id)
    $cmd = $proc.CommandLine
    $short = if ($cmd.Length -gt 220) { $cmd.Substring(0, 220) + "..." } else { $cmd }
    $memMB = [math]::Round($p.WorkingSet64 / 1MB, 1)
    $cpu  = [math]::Round($p.CPU, 1)
    Write-Host ("PID {0,-6} started {1:HH:mm:ss} cpu={2}s rss={3}MB :: {4}" -f $p.Id, $p.StartTime, $cpu, $memMB, $short)
}