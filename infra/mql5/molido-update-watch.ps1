# molido-update-watch.ps1
# Polls the MT5 Common Files folder for a confirmed update request from
# Molido_Master, verifies sha256 + backtest gate PASS, replaces sources,
# compiles, and rolls back on failure. Settings (AccountProfile) stay on
# the chart; a .set snapshot is written for reattach if the terminal
# does not hot-reload the new .ex5.
param(
  [string]$Branch = "agents/stage-17-demo-scalper",
  [string]$Repo = "hidooch980/Molido-Traed-Ai"
)

$ErrorActionPreference = "Stop"
$CommonFiles = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
$Experts = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Experts"
$MetaEditor = "C:\Program Files\MetaTrader 5\MetaEditor64.exe"
$ReqPath = Join-Path $CommonFiles "molido_update_request.json"
$ResPath = Join-Path $CommonFiles "molido_update_result.json"
$LogPath = Join-Path $CommonFiles "molido_update_watch.log"

function Log($m) { $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m; Add-Content -Path $LogPath -Value $line; Write-Output $line }

function Write-Result($ok, $msg, $ver) {
  $json = "{{""ok"":{0},""message"":""{1}"",""version"":""{2}"",""at"":""{3}""}}" -f ($(if($ok){"true"}else{"false"}), ($msg -replace '"','\"'), $ver, (Get-Date -Format "yyyy-MM-ddTHH:mm:ss"))
  Set-Content -Path $ResPath -Value $json -Encoding ASCII
}

if (-not (Test-Path $ReqPath)) { exit 0 }
$raw = Get-Content -Raw $ReqPath
if ($raw -notmatch '"confirmed"\s*:\s*true') { Log "request present but not confirmed"; exit 0 }
if ($raw -notmatch '"gate"\s*:\s*"PASS"') { Log "request missing gate PASS"; Write-Result $false "gate not PASS" ""; exit 0 }

$to = [regex]::Match($raw, '"to_version"\s*:\s*"([^"]+)"').Groups[1].Value
$sha = [regex]::Match($raw, '"sha256"\s*:\s*"([^"]+)"').Groups[1].Value
$ea  = [regex]::Match($raw, '"ea"\s*:\s*"([^"]+)"').Groups[1].Value
if (-not $ea) { $ea = "Molido_Master" }
$mq5 = "$ea.mq5"
if ([string]::IsNullOrWhiteSpace($to) -or $sha.Length -ne 64) { Log "bad request fields"; Write-Result $false "bad request" $to; exit 1 }

Log "request $ea -> $to sha=$sha"
$base = "https://raw.githubusercontent.com/$Repo/$Branch/infra/mql5"
$work = Join-Path $env:TEMP "molido-update"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$backup = Join-Path $work "backup"
New-Item -ItemType Directory -Force -Path $backup | Out-Null

$files = @(
  "MolidoShared.mqh","MolidoRuntime.mqh","MolidoDemoScalper.mqh","MolidoNews.mqh",
  "MolidoSmart.mqh","MolidoProtect.mqh","MolidoUniverse.mqh","MolidoDashboard.mqh",
  $mq5, "Molido_Master.gate.json"
)

try {
  foreach ($f in $files) {
    $dest = Join-Path $work $f
    Invoke-WebRequest -Uri "$base/$f" -OutFile $dest -UseBasicParsing -TimeoutSec 60
  }
  $gate = Get-Content -Raw (Join-Path $work "Molido_Master.gate.json")
  if ($gate -notmatch '"backtest"\s*:\s*"PASS"') { throw "published gate is not PASS" }
  $pubSha = [regex]::Match($gate, '"sha256"\s*:\s*"([0-9a-fA-F]{64})"').Groups[1].Value.ToLower()
  $fileSha = (Get-FileHash -Path (Join-Path $work $mq5) -Algorithm SHA256).Hash.ToLower()
  if ($fileSha -ne $sha.ToLower() -or $fileSha -ne $pubSha) {
    throw "sha256 mismatch request=$sha published=$pubSha file=$fileSha"
  }
  $sumUrl = "$base/$mq5.sha256"
  try {
    $sumLine = (Invoke-WebRequest -Uri $sumUrl -UseBasicParsing -TimeoutSec 30).Content
    $published = (($sumLine.ToString().Trim()) -split '\s+')[0].ToLower()
    if ($published -ne $fileSha) { throw "checksum file mismatch $published vs $fileSha" }
  } catch { Log "sha256 sidecar warning: $_" }

  foreach ($f in $files) {
    $cur = Join-Path $Experts $f
    if (Test-Path $cur) { Copy-Item $cur (Join-Path $backup $f) -Force }
  }
  $ex5 = Join-Path $Experts ($ea + ".ex5")
  if (Test-Path $ex5) { Copy-Item $ex5 (Join-Path $backup ($ea + ".ex5")) -Force }

  foreach ($f in $files) {
    if ($f -like "*.gate.json") { continue }
    Copy-Item (Join-Path $work $f) (Join-Path $Experts $f) -Force
  }

  $target = Join-Path $Experts $mq5
  $eaLog = [IO.Path]::ChangeExtension($target, ".log")
  if (Test-Path $eaLog) { Remove-Item $eaLog -Force }
  $p = Start-Process -FilePath $MetaEditor -ArgumentList "/compile:`"$target`"","/log" -Wait -PassThru -WindowStyle Hidden
  $txt = ""
  if (Test-Path $eaLog) { $txt = Get-Content -Raw $eaLog }
  if ($txt -notmatch "Result: 0 errors") { throw "compile failed: $txt" }

  # Preserve settings snapshot as a .set the terminal can reload if needed.
  $setSrc = Join-Path $CommonFiles "molido_master_settings.json"
  $setDst = Join-Path $Experts "Molido_Master.set"
  if (Test-Path $setSrc) {
    $s = Get-Content -Raw $setSrc
    $lines = @()
    foreach ($key in @("AccountProfile","AllowTrading","AllowRealAccount","RehearsalMode","UseScalper","UseNews","UseTrend","UseAutoSymbol","UseFibo")) {
      $m = [regex]::Match($s, '"' + $key + '"\s*:\s*([^,}]+)')
      if ($m.Success) { $lines += ($key + "=" + $m.Groups[1].Value.Trim().Trim('"')) }
    }
    $login = [regex]::Match($s, '"AllowedLogins"\s*:\s*"([^"]*)"').Groups[1].Value
    if ($login -ne "") { $lines += "AllowedLogins=$login" }
    if ($lines.Count -gt 0) { Set-Content -Path $setDst -Value ($lines -join "`r`n") -Encoding ASCII }
  }

  Remove-Item $ReqPath -Force -ErrorAction SilentlyContinue
  Write-Result $true "compiled 0 errors, settings preserved" $to
  Log "update $to applied"
  exit 0
}
catch {
  Log "FAIL $($_.Exception.Message) - rolling back"
  Get-ChildItem $backup -File -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $Experts $_.Name) -Force
  }
  $old = Join-Path $Experts $mq5
  if ((Test-Path $old) -and (Test-Path $MetaEditor)) {
    Start-Process -FilePath $MetaEditor -ArgumentList "/compile:`"$old`"","/log" -Wait -WindowStyle Hidden | Out-Null
  }
  Write-Result $false $_.Exception.Message $to
  exit 2
}
