from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    """開発時はリポジトリ根、exe 化時は展開先ルートを返す。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def frontend_dir() -> Path:
    return project_root() / "frontend"


def catalog_dir() -> Path:
    return project_root() / "backend" / "catalog"
