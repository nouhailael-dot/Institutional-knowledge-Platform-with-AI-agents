"""Top-level package compatibility helpers."""

from __future__ import annotations

import sys

from src import ML as ml

sys.modules.setdefault(__name__ + ".ml", ml)
