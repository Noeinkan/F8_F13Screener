$p = Get-Process -Id 31696 -ErrorAction SilentlyContinue
if ($p) {
    $cpu = [math]::Round($p.CPU, 1)
    $rss = [math]::Round($p.WorkingSet64 / 1MB, 1)
    $start = $p.StartTime.ToString('yyyy-MM-dd HH:mm:ss')
    Write-Host ("ALIVE pid={0} started={1} cpu={2}s rss={3}MB" -f $p.Id, $start, $cpu, $rss)
} else {
    Write-Host 'DEAD'
}