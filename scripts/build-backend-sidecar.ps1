param(
  [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PyInstaller = Join-Path $RootDir ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $PyInstaller)) {
  Write-Error "Missing .venv\Scripts\pyinstaller.exe. Run .venv\Scripts\python.exe -m pip install pyinstaller first."
}

$OutputPath = Join-Path $RootDir "src-tauri\binaries\novel-backend-$TargetTriple.exe"
$BuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("novel-sidecar-build-" + [System.Guid]::NewGuid().ToString("N"))
$DistDir = Join-Path $BuildRoot "dist"
$WorkDir = Join-Path $BuildRoot "work"
$SpecDir = Join-Path $BuildRoot "spec"
$EntryPoint = Join-Path $RootDir "backend\novel_backend\main.py"

try {
  New-Item -ItemType Directory -Force -Path $DistDir, $WorkDir, $SpecDir | Out-Null

  & $PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name novel-backend `
    $EntryPoint `
    --distpath $DistDir `
    --workpath $WorkDir `
    --specpath $SpecDir

  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }

  $BuiltBinary = Join-Path $DistDir "novel-backend.exe"
  if (-not (Test-Path $BuiltBinary)) {
    Write-Error "PyInstaller finished but did not create $BuiltBinary"
  }

  New-Item -ItemType Directory -Force -Path (Split-Path $OutputPath) | Out-Null
  Move-Item -Force -Path $BuiltBinary -Destination $OutputPath

  Write-Host "Generated $OutputPath"
}
finally {
  if (Test-Path $BuildRoot) {
    Remove-Item -Recurse -Force $BuildRoot
  }
}
