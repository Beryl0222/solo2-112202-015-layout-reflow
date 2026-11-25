"""支持 ``python -m training_pack``，实际入口在仓库根的 cli.py。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
