#!/usr/bin/env python3
"""V30 backtest entrypoint safe from any working directory."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ict_full_backtest import main  # noqa: E402

if __name__ == "__main__":
    main()
