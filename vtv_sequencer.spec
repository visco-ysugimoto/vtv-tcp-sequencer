# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 設定: dist/VTV_TCP_Sequencer/ にフォルダ配布用ビルドを出力する。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project = Path(SPECPATH)

datas = [
    (str(project / "frontend"), "frontend"),
    (str(project / "backend" / "catalog"), "backend/catalog"),
]

binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "backend.main",
    "backend.catalog",
    "backend.engine",
    "backend.models",
    "backend.paths",
    "backend.protocol",
]

for package in ("uvicorn", "fastapi", "starlette", "anyio", "pydantic"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["run_app.py"],
    pathex=[str(project)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VTV_TCP_Sequencer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VTV_TCP_Sequencer",
)
