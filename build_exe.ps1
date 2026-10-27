# VTV TCP Sequencer Windows distribution build
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = if (Test-Path ".\.venv\Scripts\python.exe") {
    ".\.venv\Scripts\python.exe"
} else {
    "python"
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
    $python = ".\.venv\Scripts\python.exe"
}

& $python -m pip install -r requirements.txt
& $python -m pip install -r requirements-dev.txt

Write-Host "Building with PyInstaller..."
& $python -m PyInstaller --noconfirm --clean vtv_sequencer.spec

$distDir = Join-Path $PSScriptRoot "dist\VTV_TCP_Sequencer"
$exePath = Join-Path $distDir "VTV_TCP_Sequencer.exe"
if (-not (Test-Path $exePath)) {
    throw "Build output not found: $exePath"
}

Copy-Item -Force ".\packaging\NOTICE_JA.txt" (Join-Path $distDir "NOTICE_JA.txt")
$packagingOut = Join-Path $distDir "packaging"
New-Item -ItemType Directory -Force -Path $packagingOut | Out-Null
Copy-Item -Force ".\packaging\Add-DefenderExclusion.ps1" (Join-Path $packagingOut "Add-DefenderExclusion.ps1")

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $roots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "${env:ProgramFiles}\Windows Kits\10\bin"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        $found = Get-ChildItem -Path $root -Recurse -Filter "signtool.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

if ($env:VTV_CODESIGN_PFX) {
    if (-not (Test-Path $env:VTV_CODESIGN_PFX)) {
        throw "VTV_CODESIGN_PFX not found: $($env:VTV_CODESIGN_PFX)"
    }
    $signTool = Find-SignTool
    if (-not $signTool) {
        throw "signtool.exe not found. Install Windows SDK or add it to PATH."
    }
    if ($env:VTV_CODESIGN_TIMESTAMP) {
        $timestamp = $env:VTV_CODESIGN_TIMESTAMP
    } else {
        $timestamp = 'http://timestamp.digicert.com'
    }
    Write-Host "Code signing..."
    $signArgs = @(
        "sign",
        "/fd", "SHA256",
        "/td", "SHA256",
        "/tr", $timestamp,
        "/f", $env:VTV_CODESIGN_PFX
    )
    if ($env:VTV_CODESIGN_PASSWORD) {
        $signArgs += @("/p", $env:VTV_CODESIGN_PASSWORD)
    }
    $signArgs += $exePath
    & $signTool @signArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Code signing failed (exit=$LASTEXITCODE)"
    }
    & $signTool verify /pa $exePath
    if ($LASTEXITCODE -ne 0) {
        throw "Signature verification failed (exit=$LASTEXITCODE)"
    }
    Write-Host "Code signing completed."
} else {
    Write-Host "Code signing skipped (VTV_CODESIGN_PFX not set)."
    Write-Host "For fewer AV false positives on recipients, sign with a company Authenticode certificate."
}

$hash = (Get-FileHash -Algorithm SHA256 -Path $exePath).Hash.ToLowerInvariant()
@(
    "VTV_TCP_Sequencer.exe",
    "SHA256=$hash",
    "Generated=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
) | Set-Content -Encoding utf8 (Join-Path $distDir "SHA256.txt")
Write-Host "SHA256: $hash"

Write-Host "Creating distribution ZIP..."
& $python -c @"
import shutil, zipfile
from pathlib import Path
src = Path('dist/VTV_TCP_Sequencer')
zip_path = Path('dist/VTV_TCP_Sequencer.zip')
staging = Path('dist/_zip_staging')
if staging.exists():
    shutil.rmtree(staging, ignore_errors=True)
if zip_path.exists():
    zip_path.unlink()
staging.mkdir(parents=True)
copied = staging / 'VTV_TCP_Sequencer'
shutil.copytree(src, copied)
with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for path in copied.rglob('*'):
        if path.is_file():
            zf.write(path, path.relative_to(staging).as_posix())
shutil.rmtree(staging, ignore_errors=True)
print(f'{zip_path.resolve()} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)')
"@

Write-Host ""
Write-Host "Done: dist\VTV_TCP_Sequencer.zip"
Write-Host "Recipients: extract ZIP, then run VTV_TCP_Sequencer\VTV_TCP_Sequencer.exe"
Write-Host "Bundle includes NOTICE_JA.txt and SHA256.txt for AV false-positive handling."
