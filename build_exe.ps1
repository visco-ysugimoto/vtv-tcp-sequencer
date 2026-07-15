# VTV TCP Sequencer の Windows 配布用ビルド
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = if (Test-Path ".\.venv\Scripts\python.exe") {
    ".\.venv\Scripts\python.exe"
} else {
    "python"
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "仮想環境を作成しています..."
    python -m venv .venv
    $python = ".\.venv\Scripts\python.exe"
}

& $python -m pip install -r requirements.txt
& $python -m pip install -r requirements-dev.txt

Write-Host "PyInstaller でビルドしています..."
& $python -m PyInstaller --noconfirm --clean vtv_sequencer.spec

Write-Host "配布用 ZIP を作成しています..."
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
Write-Host "完了: dist\VTV_TCP_Sequencer.zip を配布してください。"
Write-Host "受け取り側は ZIP を展開し、VTV_TCP_Sequencer\VTV_TCP_Sequencer.exe を起動します。"
