param(
    [int]$Port = 8502,
    [string]$ListenAddress = "127.0.0.1",
    [int]$StartupTimeoutSeconds = 45,
    [switch]$RebuildDb,
    [switch]$FullRefresh,
    [int]$Workers = 1
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$dashboardUrl = "http://localhost:$Port"
$healthUrl = "http://${ListenAddress}:$Port/_stcore/health"
$dashboardPattern = 'streamlit\s+run\s+src[\\/]+web[\\/]+dashboard\.py'

function Get-PythonLauncher {
    $rtkCommand = Get-Command rtk -ErrorAction SilentlyContinue
    if ($rtkCommand) {
        return @{
            FilePath = $rtkCommand.Source
            PrefixArgs = @("python")
        }
    }

    $pythonCommand = Get-Command python -ErrorAction Stop
    return @{
        FilePath = $pythonCommand.Source
        PrefixArgs = @()
    }
}

function Invoke-ProjectPython {
    param(
        [string[]]$Arguments
    )

    $allArgs = @($script:pythonLauncher.PrefixArgs + $Arguments)
    & $script:pythonLauncher.FilePath @allArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $($allArgs -join ' ')"
    }
}

function Stop-DashboardProcessByCommandLine {
    $running = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -match $dashboardPattern
    }

    foreach ($process in $running) {
        if ($process.ProcessId -ne $PID) {
            Write-Host "Stopping existing dashboard process PID $($process.ProcessId)..."
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-ProcessOnDashboardPort {
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $connections) {
        return
    }

    $owningProcesses = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($owningProcessId in $owningProcesses) {
        if (-not $owningProcessId -or $owningProcessId -eq $PID) {
            continue
        }

        $process = Get-Process -Id $owningProcessId -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "Stopping process on port ${Port}: PID $owningProcessId ($($process.ProcessName))..."
            Stop-Process -Id $owningProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

Set-Location $repoRoot
$env:PYTHONPATH = $repoRoot

$pythonLauncher = Get-PythonLauncher

if ($RebuildDb) {
    $refreshArgs = @(
        "-m",
        "src.cli.process_historical_13f",
        "full",
        "--yes",
        "--save-db",
        "--workers",
        "$Workers"
    )
    if ($FullRefresh) {
        $refreshArgs += "--full-refresh"
    }

    Write-Host "Refreshing historical 13F data for the dashboard DB..."
    Invoke-ProjectPython -Arguments $refreshArgs
}

Stop-DashboardProcessByCommandLine
Stop-ProcessOnDashboardPort

$launcher = $pythonLauncher.FilePath
$launcherArgs = @(
    $pythonLauncher.PrefixArgs + @(
        "-m",
        "streamlit",
        "run",
        "src/web/dashboard.py",
        "--server.port",
        $Port,
        "--server.address",
        $ListenAddress,
        "--server.headless",
        "true"
    )
)

Write-Host "Starting dashboard on $dashboardUrl ..."
$startedProcess = Start-Process -FilePath $launcher -ArgumentList $launcherArgs -WorkingDirectory $repoRoot -PassThru

for ($attempt = 0; $attempt -lt $StartupTimeoutSeconds; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            Write-Host "Dashboard is ready. Opening browser..."
            Start-Process $dashboardUrl
            Write-Host "Dashboard PID: $($startedProcess.Id)"
            exit 0
        }
    } catch {
        # Wait for Streamlit to finish booting.
    }

    Start-Sleep -Seconds 1
}

Write-Error "Dashboard did not become ready within $StartupTimeoutSeconds seconds. Check the new console window for errors."
exit 1
