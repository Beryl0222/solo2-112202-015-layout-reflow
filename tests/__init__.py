"""资料包测试。

支持用隔离模式运行（``python3 -I -m unittest discover -s tests``）：
隔离模式不自动把当前目录加入 sys.path，这里显式加入仓库根。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
