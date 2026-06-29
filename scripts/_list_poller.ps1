$ErrorActionPreference = 'SilentlyContinue'
$targets = @('13f','alerts','main.py','poller','src.main')
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'"
foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if ($cmd -match '13f|F8_F13|F8-F13|src\.main|alerts') {
        $short = if ($cmd.Length -gt 260) { $cmd.Substring(0, 260) + "..." } else { $cmd }
        Write-Host ("PID {0,-6} parent={1,-6} started {2:yyyy-MM-dd HH:mm:ss} :: {3}" -f $p.ProcessId, $p.ParentProcessId, $p.CreationDate, $short)
    }
}