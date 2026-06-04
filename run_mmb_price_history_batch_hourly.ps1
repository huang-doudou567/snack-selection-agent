param(
    [string]$RepoRoot = 'C:\Users\HUAWEI\Documents\New project 2'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Set-Location $RepoRoot
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logDir = Join-Path $RepoRoot 'logs'
$lockPath = Join-Path $RepoRoot 'mmb_price_history_active.lock.json'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir "mmb_price_history_batch_$timestamp.out.log"
$errLog = Join-Path $logDir "mmb_price_history_batch_$timestamp.err.log"

function Write-Line {
    param(
        [string]$Path,
        [string]$Message
    )
    $Message | Out-File -FilePath $Path -Append -Encoding utf8
}

if (Test-Path $lockPath) {
    try {
        $lock = Get-Content -Raw $lockPath | ConvertFrom-Json
        $alive = $false
        if ($lock.pid) {
            $alive = $null -ne (Get-Process -Id ([int]$lock.pid) -ErrorAction SilentlyContinue)
        }
        if ($alive) {
            Write-Line $outLog "[SKIP] Active lock detected for $($lock.script_name) pid=$($lock.pid) heartbeat_at=$($lock.heartbeat_at)"
            exit 0
        }
    } catch {
        Write-Line $errLog "[WARN] Failed to inspect lock file: $($_.Exception.Message)"
    }
}

$python = (Get-Command python).Source
$env:PYTHONUNBUFFERED = '1'

# DrissionPage manages its own browser — no CDP port needed
& $python 'mmb_cdp_price_history_crawler.py' 1> $outLog 2> $errLog
exit $LASTEXITCODE
