"""R262 · `fastmcp>=3.0.0` baseline lock (mining-12 cycle-8 corrigendum).

背景
----

mining-12 §3.2 #1 (cr50 §5 follow-up #5) 原本提议 "FastMCP 3.x compatibility
评估" 当作 cycle-13 candidate，错把 AIIA 当 fastmcp 2.x。

cycle-8 corrigendum audit (cr50 follow-up 落地时) 复核发现：

- ``pyproject.toml`` 已 pin ``fastmcp>=3.0.0``
- 实际安装 ``fastmcp==3.2.4`` (2025 H2 GA)
- AIIA 在 FastMCP 3.x 跟随上 **比 upstream mcp-feedback-enhanced
  (still 2.x) + fork mcp-feedback-enhanced-pro (3.0.0b2) 都早**

为防未来 dep 升级回退（或 ``pyproject.toml`` 误改），本 invariant 锁住
``fastmcp>=3.0.0`` baseline。

回归契约
--------

1. ``pyproject.toml`` 必包含 ``fastmcp>=3.0.0`` (或更高 ``major``)
2. 实际安装版本 ``major >= 3``
"""

from __future__ import annotations

import importlib.metadata
import re
import unittest
from pathlib import Path

PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _read_fastmcp_pin() -> str | None:
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    m = re.search(r'"fastmcp([><=!~][^"]+)"', text)
    return m.group(1) if m else None


def _read_fastmcp_major() -> int:
    """返回当前安装 fastmcp 的 major 版本号。"""
    raw = importlib.metadata.version("fastmcp")
    # PEP 440: major.minor.patch[.postN][.devN][.aN][bN][rcN]
    m = re.match(r"^(\d+)", raw)
    assert m is not None, f"无法解析 fastmcp 版本号: {raw!r}"
    return int(m.group(1))


class TestFastmcpBaselinePin(unittest.TestCase):
    """R262 · pyproject.toml 必 pin fastmcp>=3.0.0。"""

    def test_pyproject_has_fastmcp_3_pin(self) -> None:
        pin = _read_fastmcp_pin()
        self.assertIsNotNone(
            pin,
            "pyproject.toml 找不到 fastmcp 依赖 — mining-12 §3.2 R262 baseline",
        )
        assert pin is not None
        m = re.match(r">=(\d+)\.", pin)
        self.assertIsNotNone(
            m,
            f"fastmcp pin {pin!r} 不是 '>=X.Y.Z' 形式，"
            f"R262 要求至少 '>=3.x.y' (避免无意义放宽到 ~=3.0 等)",
        )
        assert m is not None
        self.assertGreaterEqual(
            int(m.group(1)),
            3,
            f"fastmcp pin {pin!r} major 低于 3 — R262 baseline (cycle-8 "
            f"corrigendum) 要求 >=3.0.0，AIIA 已先于 upstream 3+ 个 minor "
            f"采用，禁止回退",
        )


class TestFastmcpRuntimeMajor(unittest.TestCase):
    """R262 · 实际安装 fastmcp major >= 3。"""

    def test_installed_major_is_3_or_higher(self) -> None:
        major = _read_fastmcp_major()
        self.assertGreaterEqual(
            major,
            3,
            f"实际安装 fastmcp major={major} < 3 — 与 pyproject.toml pin 不一致，"
            f"可能是 venv 出问题或 lockfile 漂移",
        )


if __name__ == "__main__":
    unittest.main()
