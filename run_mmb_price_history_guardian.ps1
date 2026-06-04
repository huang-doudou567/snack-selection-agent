param(
    [string]$RepoRoot = 'C:\Users\HUAWEI\Documents\New project 2',
    [int]$RetryDelaySeconds = 300,
    [int]$MaxConsecutiveRiskRuns = 2,
    [string]$StopAt = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path $RepoRoot).Path
$logDir = Join-Path $root 'logs'
$guardianLog = Join-Path $logDir 'mmb_price_history_guardian.log'
$runnerScript = Join-Path $root 'run_mmb_price_history_batch_hourly.ps1'
$lockPath = Join-Path $root 'mmb_price_history_active.lock.json'
$runStateFile = Join-Path $root 'mmb_cdp_price_history_state.json'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-GuardianLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $guardianLog -Value $line -Encoding UTF8
    Write-Output $line
}

function Get-StopTime {
    param([string]$StopAtInput)
    if ($StopAtInput) {
        return [datetime]::Parse($StopAtInput)
    }
    $now = Get-Date
    $stop = Get-Date -Hour 10 -Minute 0 -Second 0
    if ($now -ge $stop) {
        $stop = $stop.AddDays(1)
    }
    return $stop
}

# Crawl window: 23:00-06:00 (overnight, lowest risk-control)
function Test-InCrawlWindow {
    $now = Get-Date
    $h = $now.Hour
    return ($h -ge 23 -or $h -lt 6)
}

function Get-NextWindowStart {
    $now = Get-Date
    $h = $now.Hour
    if ($h -ge 23 -or $h -lt 6) {
        return $now
    }
    $todayStart = Get-Date -Hour 23 -Minute 0 -Second 0
    return $todayStart
}

# Daily run tracking
function Test-AlreadyRanToday {
    if (-not (Test-Path $runStateFile)) { return $false }
    try {
        $state = Get-Content -Raw $runStateFile | ConvertFrom-Json
        $today = (Get-Date).ToString('yyyy-MM-dd')
        return ($state.run_date -eq $today)
    } catch {
        return $false
    }
}

function Get-ActiveLockState {
    if (-not (Test-Path $lockPath)) {
        return $null
    }
    try {
        return Get-Content -Raw $lockPath | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Test-LockAlive {
    param($LockState)
    if (-not $LockState -or -not $LockState.pid) {
        return $false
    }
    return $null -ne (Get-Process -Id ([int]$LockState.pid) -ErrorAction SilentlyContinue)
}

function Get-LatestRunLogs {
    $outLog = Get-ChildItem $logDir -Filter 'mmb_price_history_batch_*.out.log' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    $errLog = Get-ChildItem $logDir -Filter 'mmb_price_history_batch_*.err.log' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    return @{
        OutLog = $outLog
        ErrLog = $errLog
    }
}

function Test-RunForRiskSignals {
    $patterns = 'CAPTCHA|access_blocked|403|402|verification|verify|blocked|risk-control'
    $hits = @()
    $logs = Get-LatestRunLogs
    foreach ($path in @($logs.OutLog.FullName, $logs.ErrLog.FullName)) {
        if ($path -and (Test-Path $path)) {
            $hits += @(Select-String -Path $path -Pattern $patterns -AllMatches -ErrorAction SilentlyContinue)
        }
    }
    return $hits.Count -gt 0
}

$stopTime = Get-StopTime -StopAtInput $StopAt
Write-GuardianLog "Guardian started. RepoRoot=$root CrawlWindow=23:00-06:00 RetryDelaySeconds=$RetryDelaySeconds StopAt=$($stopTime.ToString('o'))"

$consecutiveRiskRuns = 0

while ((Get-Date) -lt $stopTime) {
    if (-not (Test-InCrawlWindow)) {
        $nextStart = Get-NextWindowStart
        $sleepSeconds = [Math]::Min($RetryDelaySeconds, [Math]::Max(1, [int][Math]::Ceiling(($nextStart - (Get-Date)).TotalSeconds)))
        Write-GuardianLog "Outside crawl window (23:00-06:00). Next start=$($nextStart.ToString('o')). Waiting $sleepSeconds seconds."
        Start-Sleep -Seconds $sleepSeconds
        continue
    }

    if (Test-AlreadyRanToday) {
        Write-GuardianLog "Already ran today. Waiting $RetryDelaySeconds seconds until next check."
        Start-Sleep -Seconds $RetryDelaySeconds
        continue
    }

    $lock = Get-ActiveLockState
    if (Test-LockAlive -LockState $lock) {
        Write-GuardianLog "Crawler active via lock. pid=$($lock.pid) heartbeat_at=$($lock.heartbeat_at). Waiting $RetryDelaySeconds seconds."
        Start-Sleep -Seconds $RetryDelaySeconds
        continue
    }

    Write-GuardianLog "Starting price-history runner."
    try {
        $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerScript`" -RepoRoot `"$root`""
        $proc = Start-Process -FilePath 'powershell.exe' `
            -ArgumentList $argLine `
            -WorkingDirectory $root `
            -WindowStyle Hidden `
            -PassThru
        $proc.WaitForExit()
        $exitCode = $proc.ExitCode
        $riskHit = Test-RunForRiskSignals
        if ($riskHit) {
            $consecutiveRiskRuns++
            Write-GuardianLog "Runner exited with code $exitCode and risk-control text was detected. Consecutive risk runs: $consecutiveRiskRuns"
        } else {
            $consecutiveRiskRuns = 0
            Write-GuardianLog "Runner exited with code $exitCode."
        }
    } catch {
        $consecutiveRiskRuns = 0
        Write-GuardianLog "Failed to start or wait for runner: $($_.Exception.Message)"
    }

    if ($consecutiveRiskRuns -ge $MaxConsecutiveRiskRuns) {
        Write-GuardianLog "Stopping guardian because risk-control text appeared in $consecutiveRiskRuns consecutive runs."
        break
    }

    if ((Get-Date) -lt $stopTime) {
        Write-GuardianLog "Sleeping $RetryDelaySeconds seconds before next check."
        Start-Sleep -Seconds $RetryDelaySeconds
    }
}

Write-GuardianLog "Guardian exiting."
