$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildLogDir = Join-Path ([System.IO.Path]::GetTempPath()) ("novel-windows-release-" + [System.Guid]::NewGuid().ToString("N"))
$SidecarPath = Join-Path $RootDir "src-tauri\binaries\novel-backend-x86_64-pc-windows-msvc.exe"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $Message"
}

function Require-Path {
  param([string]$Path)
  if (-not (Test-Path $Path)) {
    throw "Missing file: $Path"
  }
}

function Get-FreePort {
  $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), 0)
  $Listener.Start()
  try {
    return $Listener.LocalEndpoint.Port
  }
  finally {
    $Listener.Stop()
  }
}

function Invoke-BackendSmoke {
  param(
    [string]$Binary,
    [string]$Label
  )

  Require-Path $Binary

  $Port = Get-FreePort
  $DataDir = Join-Path ([System.IO.Path]::GetTempPath()) ("novel-backend-smoke-" + [System.Guid]::NewGuid().ToString("N"))
  $StdoutLog = Join-Path $BuildLogDir "$Label.stdout.log"
  $StderrLog = Join-Path $BuildLogDir "$Label.stderr.log"

  New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

  $Process = Start-Process `
    -FilePath $Binary `
    -ArgumentList @("--host", "127.0.0.1", "--port", "$Port", "--data-dir", $DataDir) `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -PassThru `
    -WindowStyle Hidden

  try {
    $HealthUrl = "http://127.0.0.1:$Port/api/app/health"
    $Healthy = $false

    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
      try {
        Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2 | Out-File -Encoding utf8 (Join-Path $BuildLogDir "$Label.health.json")
        $Healthy = $true
        break
      }
      catch {
        Start-Sleep -Milliseconds 500
      }
    }

    if (-not $Healthy) {
      if (Test-Path $StdoutLog) { Get-Content $StdoutLog | Write-Host }
      if (Test-Path $StderrLog) { Get-Content $StderrLog | Write-Host }
      throw "$Label failed health check"
    }

    Invoke-RestMethod `
      -Method Post `
      -Uri "http://127.0.0.1:$Port/api/app/shutdown" `
      -ContentType "application/json" `
      -Body "{}" `
      -TimeoutSec 5 | Out-Null

    try {
      Wait-Process -Id $Process.Id -Timeout 15
    }
    catch {
      Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
      throw "$Label did not exit after shutdown"
    }

    if ($null -ne $Process.ExitCode -and $Process.ExitCode -notin @(0, 143)) {
      if (Test-Path $StdoutLog) { Get-Content $StdoutLog | Write-Host }
      if (Test-Path $StderrLog) { Get-Content $StderrLog | Write-Host }
      throw "$Label exited with code $($Process.ExitCode)"
    }
  }
  finally {
    if (-not $Process.HasExited) {
      Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $DataDir) {
      Remove-Item -Recurse -Force $DataDir
    }
  }
}

try {
  New-Item -ItemType Directory -Force -Path $BuildLogDir | Out-Null

  Write-Step "Run backend tests"
  Push-Location $RootDir
  try {
    & npm run backend:test:windows
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Step "Run frontend build"
    & npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Step "Build Windows Python sidecar"
    & npm run backend:bundle:windows
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Step "Check Windows sidecar health"
    Invoke-BackendSmoke $SidecarPath "sidecar"

    Write-Step "Build Tauri Windows installer"
    & npm run tauri -- build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
  finally {
    Pop-Location
  }

  $MsiDir = Join-Path $RootDir "src-tauri\target\release\bundle\msi"
  $NsisDir = Join-Path $RootDir "src-tauri\target\release\bundle\nsis"
  $Msi = Get-ChildItem -Path $MsiDir -Filter "*.msi" -File -ErrorAction SilentlyContinue | Select-Object -First 1
  $Nsis = Get-ChildItem -Path $NsisDir -Filter "*.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1

  if ($null -eq $Msi -and $null -eq $Nsis) {
    throw "No Windows installer found under $MsiDir or $NsisDir"
  }

  Write-Step "Windows release check finished"
  Write-Host "sidecar=$SidecarPath"
  if ($null -ne $Msi) { Write-Host "msi=$($Msi.FullName)" }
  if ($null -ne $Nsis) { Write-Host "nsis=$($Nsis.FullName)" }
}
finally {
  if (Test-Path $BuildLogDir) {
    Remove-Item -Recurse -Force $BuildLogDir
  }
}
