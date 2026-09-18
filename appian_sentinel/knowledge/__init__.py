"""Access to shipped Appian Sentinel ground-truth files."""

from __future__ import annotations

import sys
from pathlib import Path


def resolve_ground_truth_path(filename: str) -> Path:
    """Resolve a bundled data file in source and PyInstaller builds."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    root = Path(bundle_root) if bundle_root is not None else Path(__file__).resolve().parents[2]
    return root / filename
