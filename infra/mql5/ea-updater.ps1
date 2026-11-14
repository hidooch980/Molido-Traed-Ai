<#
.SYNOPSIS
  Molido EA updater: download a newer MolidoBridge.mq5, verify its SHA-256,
  back up the current one, compile with MetaEditor, roll back on failure.

.NOTES
  - Holds no secrets. Downloads from a public URL only.
  - Installs only when the downloaded MOLIDO_EA_VERSION is newer (or -Force).
  - The checksum comes from the same place as the file: it catches corruption
    and partial downloads. Pin -ExpectedSha256 to also guard against a changed
    source.
  - The running EA reloads by itself when MetaTrader sees the new .ex5.
#>
[CmdletBinding()]
param(
  [string]$Repo = "hidooch980/Molido-Traed-Ai",
  [string]$Branch = "agents/stage-17-demo-scalper",
  [string]$SourceUrl = "",
  [string]$ChecksumUrl = "",
  [string]$ExpectedSha256 = "",
  [string]$ExpertsDir = "",
  [string]$MetaEditor = "",
  [string]$WorkDir = "$env:ProgramData\MolidoEA",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$name = "MolidoBridge.mq5"
if (-not $SourceUrl) { $SourceUrl = "https://raw.githubusercontent.com/$Repo/$Branch/infra/mql5/$name" }
if (-not $ChecksumUrl) { $ChecksumUrl = "$SourceUrl.sha256" }

New-Item -ItemType Directory -Force -Path $WorkDir, "$WorkDir\backup" | Out-Null
$logFile = Join-Path $WorkDir "updater.log"
function Log($msg) {
  $line = "{0:u}  {1}" -f (Get-Date).ToUniversalTime(), $msg
  Add-Content -Path $logFile -Value $line
  Write-Host $line
}

function Get-EaVersion([string]$path) {
  if (-not (Test-Path $path)) { return $null }
  $m = Select-String -Path $path -Pattern '#define MOLIDO_EA_VERSION "([0-9.]+)"' | Select-Object -First 1
  if ($m) { return [version]$m.Matches[0].Groups[1].Value }
  $p = Select-String -Path $path -Pattern '#property version\s+"([0-9.]+)"' | Select-Object -First 1
  if ($p) { return [version]$p.Matches[0].Groups[1].Value }
  return $null
}

function Find-ExpertsDir {
  $root = Join-Path $env:APPDATA "MetaQuotes\Terminal"
  $hits = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "MQL5\Experts\$name") } |
    ForEach-Object { Join-Path $_.FullName "MQL5\Experts" }
  if (@($hits).Count -eq 1) { return @($hits)[0] }
  throw "Found $(@($hits).Count) terminals with $name. Pass -ExpertsDir. Candidates: $($hits -join '; ')"
}

function Find-MetaEditor {
  $hits = Get-ChildItem -Path "C:\Program Files\*\metaeditor64.exe" -ErrorAction SilentlyContinue
  if (@($hits).Count -ge 1) { return @($hits)[0].FullName }
  throw "metaeditor64.exe not found. Pass -MetaEditor 'C:\Program Files\<terminal>\metaeditor64.exe'."
}

function Compile([string]$target) {
  $clog = Join-Path $WorkDir "compile.log"
  if (Test-Path $clog) { Remove-Item $clog -Force }
  Start-Process -FilePath $MetaEditor -ArgumentList "/compile:`"$target`"", "/log:`"$clog`"" -Wait -WindowStyle Hidden
  if (-not (Test-Path $clog)) { return $false }
  $text = Get-Content -Path $clog -Raw -Encoding Unicode
  Log ("compile: " + (($text -split "`r?`n" | Where-Object { $_ -match "Result:" }) -join " "))
  return ($text -match "Result:\s*0 errors?")
}

try {
  if (-not $ExpertsDir) { $ExpertsDir = Find-ExpertsDir }
  if (-not $MetaEditor) { $MetaEditor = Find-MetaEditor }
  $target = Join-Path $ExpertsDir $name
  $tmp = Join-Path $WorkDir "download.mq5"

  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $SourceUrl -OutFile $tmp -UseBasicParsing
  $sumLine = (Invoke-WebRequest -Uri $ChecksumUrl -UseBasicParsing).Content
  if ($sumLine -is [byte[]]) { $sumLine = [Text.Encoding]::ASCII.GetString($sumLine) }
  $published = ($sumLine.Trim() -split '\s+')[0].ToLower()
  $actual = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToLower()
  if ($actual -ne $published) { throw "checksum mismatch: file $actual, published $published" }
  if ($ExpectedSha256 -and $actual -ne $ExpectedSha256.ToLower()) { throw "checksum is not the pinned -ExpectedSha256" }

  $new = Get-EaVersion $tmp
  $cur = Get-EaVersion $target
  Log "installed: $cur  available: $new  ($SourceUrl)"
  if (-not $new) { throw "downloaded file carries no version" }
  if (-not $Force -and $cur -and $new -le $cur) { Log "up to date"; exit 0 }

  $backup = $null
  if (Test-Path $target) {
    $backup = Join-Path "$WorkDir\backup" ("MolidoBridge-{0}-{1:yyyyMMdd-HHmmss}.mq5" -f $cur, (Get-Date))
    Copy-Item $target $backup -Force
    Log "backup: $backup"
  }
  Copy-Item $tmp $target -Force

  $includes = @("MolidoShared.mqh","MolidoI18n.mqh","MolidoRuntime.mqh","MolidoDemoScalper.mqh","MolidoNews.mqh","MolidoSmart.mqh","MolidoProtect.mqh","MolidoUniverse.mqh","MolidoFibo.mqh","MolidoDashboard.mqh","MolidoExpertBridge.mqh","MolidoExpertRisk.mqh","MolidoExpertReport.mqh","MolidoExpertExec.mqh","MolidoExpertUI.mqh","Molido_Expert.gate.json","molido-update-watch.ps1","Molido_Master.gate.json")
  $incBackups = @()
  foreach ($incName in $includes) {
    $incUrl = $SourceUrl -replace [regex]::Escape($name), $incName
    $incSumUrl = $incUrl + ".sha256"
    $incTarget = Join-Path $ExpertsDir $incName
    $incTmp = Join-Path $WorkDir ("download-" + $incName)
    Invoke-WebRequest -Uri $incUrl -OutFile $incTmp -UseBasicParsing
    $incSumLine = (Invoke-WebRequest -Uri $incSumUrl -UseBasicParsing).Content
    if ($incSumLine -is [byte[]]) { $incSumLine = [Text.Encoding]::ASCII.GetString($incSumLine) }
    $incPublished = ($incSumLine.Trim() -split '\s+')[0].ToLower()
    $incActual = (Get-FileHash -Path $incTmp -Algorithm SHA256).Hash.ToLower()
    if ($incActual -ne $incPublished) { throw "include checksum mismatch for $incName : file $incActual, published $incPublished" }
    if (Test-Path $incTarget) {
      $incBackup = Join-Path "$WorkDir\backup" ("{0}-{1:yyyyMMdd-HHmmss}" -f $incName, (Get-Date))
      Copy-Item $incTarget $incBackup -Force
      $incBackups += @{target=$incTarget; backup=$incBackup}
    }
    Copy-Item $incTmp $incTarget -Force
  }

  $experts = @("Molido_Expert.mq5","Molido_Master.mq5","MolidoBridge.mq5","Molido_Demo.mq5","Molido_Prop.mq5","Molido_Live.mq5","Molido_Scalper.mq5","Molido_News.mq5","Molido_Trend.mq5","Molido_AutoPortfolio.mq5")
  foreach ($eaName in $experts) {
    if ($eaName -eq $name) { continue }
    $eaUrl = $SourceUrl -replace [regex]::Escape($name), $eaName
    $eaSumUrl = $eaUrl + ".sha256"
    $eaTarget = Join-Path $ExpertsDir $eaName
    $eaTmp = Join-Path $WorkDir ("download-" + $eaName)
    Invoke-WebRequest -Uri $eaUrl -OutFile $eaTmp -UseBasicParsing
    $eaSumLine = (Invoke-WebRequest -Uri $eaSumUrl -UseBasicParsing).Content
    if ($eaSumLine -is [byte[]]) { $eaSumLine = [Text.Encoding]::ASCII.GetString($eaSumLine) }
    $eaPublished = ($eaSumLine.Trim() -split '\s+')[0].ToLower()
    $eaActual = (Get-FileHash -Path $eaTmp -Algorithm SHA256).Hash.ToLower()
    if ($eaActual -ne $eaPublished) { throw "EA checksum mismatch for $eaName : file $eaActual, published $eaPublished" }
    Copy-Item $eaTmp $eaTarget -Force
  }

  $allOk = $true
  foreach ($eaName in $experts) {
    $eaTarget = Join-Path $ExpertsDir $eaName
    if (-not (Compile $eaTarget)) { Log "compile failed: $eaName"; $allOk = $false }
  }
  if ($allOk) { Log "installed $new"; exit 0 }

  Log "compile failed - restoring the previous version"
  if ($backup) { Copy-Item $backup $target -Force }
  foreach ($item in $incBackups) { Copy-Item $item.backup $item.target -Force }
  if ($backup) { [void](Compile $target) }
  exit 2
}
catch {
  Log "ERROR: $($_.Exception.Message)"
  exit 1
}
