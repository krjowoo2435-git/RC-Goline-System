"""실행: python -m desktop (프로젝트 루트에서)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop.ui.main_monitor import run


if __name__ == "__main__":
    run()
