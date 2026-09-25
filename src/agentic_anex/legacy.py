"""Import bridge to the unmodified published ANEX source tree."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "source"
ANEX_ROOT = SOURCE_ROOT / "ANEX"

for path in (str(SOURCE_ROOT), str(ANEX_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import ANEX as anex_module  # noqa: E402
from libs import gentopo  # noqa: E402

__all__ = ["anex_module", "gentopo"]

