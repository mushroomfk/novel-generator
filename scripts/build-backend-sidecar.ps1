param(
  [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RootDir ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $RootDir ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $PyInstaller)) {
  Write-Error "Missing .venv\Scripts\pyinstaller.exe. Run .venv\Scripts\python.exe -m pip install pyinstaller first."
}

$OutputPath = Join-Path $RootDir "src-tauri\binaries\novel-backend-$TargetTriple.exe"
$BuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("novel-sidecar-build-" + [System.Guid]::NewGuid().ToString("N"))
$DistDir = Join-Path $BuildRoot "dist"
$WorkDir = Join-Path $BuildRoot "work"
$SpecDir = Join-Path $BuildRoot "spec"
$PyInstallerConfigDir = Join-Path $BuildRoot "config"
$EntryPoint = Join-Path $RootDir "backend\novel_backend\main.py"
$PreviousPyInstallerConfigDir = $env:PYINSTALLER_CONFIG_DIR

try {
  New-Item -ItemType Directory -Force -Path $DistDir, $WorkDir, $SpecDir, $PyInstallerConfigDir | Out-Null
  $env:PYINSTALLER_CONFIG_DIR = $PyInstallerConfigDir

  $PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", "novel-backend",
    "--distpath", $DistDir,
    "--workpath", $WorkDir,
    "--specpath", $SpecDir
  )

  $LocalEmbeddingModels = Join-Path $RootDir "backend\novel_backend\assets\embedding_models"
  if (Test-Path $LocalEmbeddingModels) {
    $PyInstallerArgs += @("--add-data", "$LocalEmbeddingModels;novel_backend\assets\embedding_models")
  }

  if (Test-Path $Python) {
    & $Python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('liteparse') else 1)" *> $null
    if ($LASTEXITCODE -eq 0) {
      $PyInstallerArgs += @("--collect-binaries", "liteparse", "--collect-datas", "liteparse")
    }

    & $Python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('fastembed') else 1)" *> $null
    if ($LASTEXITCODE -eq 0) {
      $PyInstallerArgs += @(
        "--collect-submodules", "fastembed",
        "--collect-binaries", "onnxruntime",
        "--collect-submodules", "onnxruntime",
        "--collect-binaries", "tokenizers"
      )
    }
  }

  $PyInstallerArgs += $EntryPoint
  & $PyInstaller @PyInstallerArgs

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
  if ($null -eq $PreviousPyInstallerConfigDir) {
    Remove-Item Env:PYINSTALLER_CONFIG_DIR -ErrorAction SilentlyContinue
  } else {
    $env:PYINSTALLER_CONFIG_DIR = $PreviousPyInstallerConfigDir
  }
  if (Test-Path $BuildRoot) {
    Remove-Item -Recurse -Force $BuildRoot
  }
}
