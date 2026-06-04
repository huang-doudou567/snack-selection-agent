param(
    [string]$RepoRoot = 'C:\Users\HUAWEI\Documents\New project 2'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Set-Location $RepoRoot
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logDir = Join-Path $RepoRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir "jd_cdp_review_scraper_$timestamp.out.log"
$errLog = Join-Path $logDir "jd_cdp_review_scraper_$timestamp.err.log"

function Test-RunForRiskSignals {
    param(
        [Parameter(Mandatory = $true)][string]$OutLog,
        [Parameter(Mandatory = $true)][string]$ErrLog
    )

    $patterns = 'CAPTCHA|access_blocked|403|402|verification|verify|manual verification|blocked|risk-control'
    $hits = @()
    foreach ($path in @($OutLog, $ErrLog)) {
        if (Test-Path $path) {
            $hits += @(Select-String -Path $path -Pattern $patterns -AllMatches -ErrorAction SilentlyContinue)
        }
    }
    return $hits.Count -gt 0
}

$active = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match 'jd_cdp_review_scraper\.py' }
if ($active) {
    "[SKIP] jd_cdp_review_scraper.py already running at $(Get-Date -Format o)" | Tee-Object -FilePath $outLog -Append
    exit 0
}

$python = (Get-Command python).Source
$env:PYTHONUNBUFFERED = '1'

& $python 'jd_cdp_review_scraper.py' 1> $outLog 2> $errLog
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0 -and (Test-RunForRiskSignals -OutLog $outLog -ErrLog $errLog)) {
    "[STOP] Verification or risk-control detected; preserving checkpoint and exiting 0." | Tee-Object -FilePath $outLog -Append
    exit 0
}

exit $exitCode
