#!/usr/bin/env python3
"""Compatibility shim for the HulunGuard CLI."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hulun_guard.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
