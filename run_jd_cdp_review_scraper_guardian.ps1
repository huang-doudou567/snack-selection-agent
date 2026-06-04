param(
    [string]$RepoRoot = 'C:\Users\HUAWEI\Documents\New project 2',
    [int]$RestartDelaySeconds = 3600,
    [int]$RetryDelaySeconds = 300,
    [int]$MaxConsecutiveRiskRuns = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path $RepoRoot).Path
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$guardianLog = Join-Path $logDir 'jd_cdp_review_guardian.log'
$python = (Get-Command python).Source

$runStateFile = Join-Path $root 'jd_cdp_review_scraper_state.json'

function Write-GuardianLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $guardianLog -Value $line -Encoding UTF8
    Write-Output $line
}

function Get-ScraperProcesses {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match 'jd_cdp_review_scraper\.py'
        } |
        Select-Object ProcessId, CommandLine
}

# ── 时间窗口: 主窗口 20:00-23:00 + 辅窗口 00:00-06:00 ──
function Test-InCrawlWindow {
    $now = Get-Date
    $h = $now.Hour
    # 主窗口: 20:00-23:00
    if ($h -ge 20 -and $h -lt 23) { return $true }
    # 辅窗口: 00:00-06:00
    if ($h -ge 0 -and $h -lt 6) { return $true }
    return $false
}

function Get-NextWindowStart {
    $now = Get-Date
    $h = $now.Hour
    # 00:00-06:00 → 已在窗口中
    if ($h -ge 0 -and $h -lt 6) { return $now }
    # 06:00-20:00 → 下一个是今晚 20:00
    if ($h -ge 6 -and $h -lt 20) {
        return Get-Date -Hour 20 -Minute 0 -Second 0
    }
    # 20:00-23:59 → 已在窗口中
    return $now
}

# ── 日运行追踪（读取爬虫自身的状态文件） ──
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

function Test-RunForRiskSignals {
    param(
        [Parameter(Mandatory = $true)][string]$OutLog,
        [Parameter(Mandatory = $true)][string]$ErrLog
    )

    $patterns = 'CAPTCHA|access_blocked|403|访问受限|验证码|风控|verification|verify|manual verification|blocked'
    $hits = @()
    foreach ($path in @($OutLog, $ErrLog)) {
        if (Test-Path $path) {
            $hits += @(Select-String -Path $path -Pattern $patterns -AllMatches -ErrorAction SilentlyContinue)
        }
    }
    return $hits.Count -gt 0
}

Write-GuardianLog "Guardian started. RepoRoot=$root RestartDelaySeconds=$RestartDelaySeconds RetryDelaySeconds=$RetryDelaySeconds"
Write-GuardianLog "Crawl windows: 20:00-23:00 (primary) + 00:00-06:00 (secondary), max 1 run/day"

$consecutiveRiskRuns = 0

while ($true) {
    # ── 窗口检查 ──
    if (-not (Test-InCrawlWindow)) {
        $nextStart = Get-NextWindowStart
        $sleepSeconds = [Math]::Min($RetryDelaySeconds, [Math]::Max(1, [int][Math]::Ceiling(($nextStart - (Get-Date)).TotalSeconds)))
        Write-GuardianLog "Outside crawl window. Next start=$($nextStart.ToString('HH:mm')). Waiting $sleepSeconds seconds."
        Start-Sleep -Seconds $sleepSeconds
        continue
    }

    # ── 日运行检查（同一天不重复启动） ──
    if (Test-AlreadyRanToday) {
        Write-GuardianLog "Already ran today. Waiting $RestartDelaySeconds seconds until next check."
        Start-Sleep -Seconds $RestartDelaySeconds
        continue
    }

    # ── 进程冲突检查 ──
    $running = @(Get-ScraperProcesses)
    if ($running.Count -gt 0) {
        $pids = ($running | ForEach-Object { $_.ProcessId }) -join ', '
        Write-GuardianLog "Scraper already running (PIDs: $pids). Waiting $RetryDelaySeconds seconds."
        Start-Sleep -Seconds $RetryDelaySeconds
        continue
    }

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $outLog = Join-Path $logDir "jd_cdp_review_scraper_$stamp.out.log"
    $errLog = Join-Path $logDir "jd_cdp_review_scraper_$stamp.err.log"

    $env:PYTHONUNBUFFERED = '1'

    Write-GuardianLog "Starting scraper run $stamp"

    try {
        $proc = Start-Process -FilePath $python `
            -ArgumentList @('jd_cdp_review_scraper.py') `
            -WorkingDirectory $root `
            -RedirectStandardOutput $outLog `
            -RedirectStandardError $errLog `
            -PassThru
        $proc.WaitForExit()
        $exitCode = $proc.ExitCode
        $riskHit = Test-RunForRiskSignals -OutLog $outLog -ErrLog $errLog
        if ($riskHit) {
            $consecutiveRiskRuns++
            Write-GuardianLog "Scraper exited with code $exitCode and risk-control text was detected. Consecutive risk runs: $consecutiveRiskRuns"
        } else {
            $consecutiveRiskRuns = 0
            Write-GuardianLog "Scraper exited with code $exitCode."
        }
    } catch {
        $consecutiveRiskRuns = 0
        Write-GuardianLog "Failed to start or wait for scraper run ${stamp}: $($_.Exception.Message)"
    }

    if ($consecutiveRiskRuns -ge $MaxConsecutiveRiskRuns) {
        Write-GuardianLog "Stopping guardian because risk-control text appeared in $consecutiveRiskRuns consecutive runs."
        break
    }

    Write-GuardianLog "Sleeping $RestartDelaySeconds seconds before next restart."
    Start-Sleep -Seconds $RestartDelaySeconds
}

Write-GuardianLog "Guardian exiting."
