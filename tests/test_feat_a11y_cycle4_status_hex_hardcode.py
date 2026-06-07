"""a11y-audit-cycle-4 Track A (R259) · 防止 status color hex 在组件 CSS 里硬编码。

背景
----

cycle-2 Track B 把 status colors (success/warning/error/info) 升级到
WCAG AA-normal。但 cr48 §5 follow-up #3 指出：如果某个组件用
``color: #ef4444`` 这种 **硬编码 hex** 而不是 ``color: var(--error-500)``，
它会绕过 cycle-2 升级，仍然显示旧的不合规颜色。

本测试守住"所有 status color 必须通过 token 引用"语义，防止：

1. 新组件作者复制旧 hex 值
2. 第三方贡献者不知道 token 系统
3. 临时 hotfix 留下 hex 漂移

允许的硬编码场景：
- ``--success-500: #...;`` 等 token **定义本身**（in :root / [data-theme] /
  @media block）
- 注释里讨论旧值（如 ``/* old: #ef4444 → #f87171 R257b */``）
- 历史 baseline 测试已 lock 的硬编码（如 R66/R109 iOS 蓝家族）

不允许：
- 在 ``.foo { color: #ef4444; }`` 这种**规则体内**直接出现

回归契约（共 5 cases）
----------------------

针对 cycle-2 升级前的 4 个旧 hex 值（success-500, warning-500,
error-500, info-500 in dark 默认 :root），断言**没有** CSS 规则体
直接引用旧 hex（必须走 token）。

加 1 个 anti-regression：升级后的新 hex 值在 :root 之外不应出现
硬编码（确保 token 是唯一源）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

CSS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "css"
    / "main.css"
)

# cycle-2 R257b 升级**之前**的 status color hex 值（必须从 codebase 里清除）
OLD_STATUS_HEXES = {
    "dark-error": "#ef4444",  # → #f87171
    "dark-info": "#3b82f6",  # → #60a5fa
    "light-success": "#788c5d",  # → #506840
    "light-warning": "#f59e0b",  # → #825005
    "light-error": "#c54d47",  # → #b03d38
    "light-info": "#6a9bcc",  # → #2e5e8c
}

# cycle-2 R257b 升级**之后**的新 hex 值（只允许在 token 定义内出现）
NEW_STATUS_HEXES = {
    "dark-error": "#f87171",
    "dark-info": "#60a5fa",
    "light-success": "#506840",
    "light-warning": "#825005",
    "light-error": "#b03d38",
    "light-info": "#2e5e8c",
}


def _hex_to_rgb(hex_value: str) -> tuple[int, int, int]:
    """``#ef4444`` → (239, 68, 68)"""
    h = hex_value.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _strip_comments(css: str) -> str:
    """剥 ``/* ... */`` 注释，避免误命中。"""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _hex_outside_token_defs(css: str, hex_value: str) -> list[str]:
    r"""返回 ``hex_value`` 在 CSS 中**非** ``--xxx: HEX;`` token 定义行的
    所有引用上下文。

    Strategy：
    1. 剥注释
    2. 用 regex 切分所有"行"
    3. 过滤掉匹配 ``--token:\s*HEX`` 的 token 定义行
    4. 返回剩下含 HEX 的行（这些是潜在 hardcode 泄漏）

    case-insensitive 匹配。
    """
    stripped = _strip_comments(css)
    pattern = re.compile(re.escape(hex_value), re.IGNORECASE)
    token_def_pattern = re.compile(
        r"--[a-zA-Z0-9_-]+:\s*" + re.escape(hex_value),
        re.IGNORECASE,
    )
    # rgba(rgb) 形式也是合法的间接引用（如 --error-bg: rgba(248, 113, 113, 0.15)）
    # 但 rgba 不含 ``#``，所以不会被这里捕获
    offenders: list[str] = []
    for line_num, line in enumerate(stripped.split("\n"), start=1):
        if pattern.search(line) and not token_def_pattern.search(line):
            offenders.append(f"line {line_num}: {line.strip()}")
    return offenders


class TestNoOldStatusHexHardcoded(unittest.TestCase):
    """R259 · cycle-2 升级**前**的 status hex 不应再出现在 codebase 中。

    若新组件作者复制旧 hex 即触发 fail。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_old_dark_error_hex_not_hardcoded(self) -> None:
        offenders = _hex_outside_token_defs(self.css, OLD_STATUS_HEXES["dark-error"])
        self.assertEqual(
            offenders,
            [],
            f"旧 dark error hex {OLD_STATUS_HEXES['dark-error']} 不应再有硬编码"
            f"（cycle-2 R257b 升级为 {NEW_STATUS_HEXES['dark-error']}）；"
            f"用 var(--error-500) 替换：\n  " + "\n  ".join(offenders),
        )

    def test_old_dark_info_hex_not_hardcoded(self) -> None:
        offenders = _hex_outside_token_defs(self.css, OLD_STATUS_HEXES["dark-info"])
        self.assertEqual(
            offenders,
            [],
            f"旧 dark info hex {OLD_STATUS_HEXES['dark-info']} 不应再有硬编码"
            f"（cycle-2 R257b 升级为 {NEW_STATUS_HEXES['dark-info']}）；"
            f"用 var(--info-500) 替换：\n  " + "\n  ".join(offenders),
        )

    def test_old_light_warning_hex_not_hardcoded(self) -> None:
        offenders = _hex_outside_token_defs(self.css, OLD_STATUS_HEXES["light-warning"])
        # warning 旧值 #f59e0b 同时是 dark 主题的 warning（dark 没升级），
        # 所以 :root 内有 1 处合法 token 定义。_hex_outside_token_defs
        # 已过滤 token 行，offenders 应为空。
        self.assertEqual(
            offenders,
            [],
            f"旧 light warning hex {OLD_STATUS_HEXES['light-warning']} 不应再有"
            f"硬编码（cycle-2 R257b 升级 light 为 {NEW_STATUS_HEXES['light-warning']}）；"
            f"\n  " + "\n  ".join(offenders),
        )

    def test_old_light_error_hex_not_hardcoded(self) -> None:
        offenders = _hex_outside_token_defs(self.css, OLD_STATUS_HEXES["light-error"])
        self.assertEqual(
            offenders,
            [],
            f"旧 light error hex {OLD_STATUS_HEXES['light-error']} 不应再有硬编码"
            f"（cycle-2 R257b 升级 light 为 {NEW_STATUS_HEXES['light-error']}）；"
            f"\n  " + "\n  ".join(offenders),
        )


class TestNewStatusHexOnlyInTokenDefs(unittest.TestCase):
    """R259 · 升级后的新 hex 只允许在 token 定义里出现，不在组件 CSS 中。

    保证 token 是 single source of truth。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_new_status_hexes_only_in_token_defs(self) -> None:
        """每个新 hex 只允许出现在 ``--token: HEX;`` 形式中。"""
        for name, hex_value in NEW_STATUS_HEXES.items():
            offenders = _hex_outside_token_defs(self.css, hex_value)
            self.assertEqual(
                offenders,
                [],
                f"新 status hex {hex_value} ({name}) 在 token 定义外硬编码 = "
                f"漂移源。请用 var(--xxx-500) 替换：\n  " + "\n  ".join(offenders),
            )


# ============================================================================
# a11y-audit-cycle-5 Track A 扩展 (R259e)：rgba(R, G, B, 1) alpha=1 等价形式
#
# 背景：cycle-4 Track A 抓到 main.css L7475 / L7485 的 ``rgba(239, 68, 68, 1)``
# 漂移时，是**人工**通过"hex 与 rgba 互译"思维找的，不是测试直接捕获的。
# cycle-5 Track A 把 alpha=1 的 rgba 等价形式补进 invariant，未来类似漂移
# 测试可以直接发现。
#
# 严格只检测 alpha=1（包括 ``1`` 与 ``1.0``），因为 alpha < 1 的 rgba 大多
# 数情况下是"透明叠加色"语义，可能合法。alpha=1 的 rgba 几乎一定等价于
# 直接写 hex，是设计上的回避或漂移。
# ============================================================================


def _rgba_alpha_one_outside_token_defs(css: str, hex_value: str) -> list[str]:
    """搜索 ``rgba(R, G, B, 1)`` / ``rgba(R, G, B, 1.0)`` 形式（alpha=1，
    等价于 hex_value），但**排除** token 定义行（保持与 hex 检测一致语义）。

    返回潜在 hardcode 泄漏行（含行号 + 内容）。
    """
    r, g, b = _hex_to_rgb(hex_value)
    stripped = _strip_comments(css)
    pattern = re.compile(
        rf"rgba\(\s*{r}\s*,\s*{g}\s*,\s*{b}\s*,\s*1(?:\.0+)?\s*\)",
        re.IGNORECASE,
    )
    token_def_pattern = re.compile(
        rf"--[a-zA-Z0-9_-]+:\s*rgba\(\s*{r}\s*,\s*{g}\s*,\s*{b}\s*,\s*1(?:\.0+)?\s*\)",
        re.IGNORECASE,
    )
    offenders: list[str] = []
    for line_num, line in enumerate(stripped.split("\n"), start=1):
        if pattern.search(line) and not token_def_pattern.search(line):
            offenders.append(f"line {line_num}: {line.strip()}")
    return offenders


class TestNoOldStatusRgbaAlphaOneHardcoded(unittest.TestCase):
    """R259e (cycle-5 Track A) · cycle-2 R257b 升级**之前**的 hex 对应的
    ``rgba(R, G, B, 1)`` alpha=1 等价形式也不应硬编码。

    比 R259 hex 检测多一层：alpha=1 的 rgba 与 ``#RRGGBB`` 完全等价，
    应当被视作同一种漂移。alpha < 1 的 rgba（透明叠加色）排除在外。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_old_dark_error_rgba_alpha_one_not_hardcoded(self) -> None:
        offenders = _rgba_alpha_one_outside_token_defs(
            self.css, OLD_STATUS_HEXES["dark-error"]
        )
        self.assertEqual(
            offenders,
            [],
            "旧 dark error rgba(239, 68, 68, 1) 不应再硬编码（=旧 #ef4444 漂移）；"
            "用 var(--error-500) 替换：\n  " + "\n  ".join(offenders),
        )

    def test_old_dark_info_rgba_alpha_one_not_hardcoded(self) -> None:
        offenders = _rgba_alpha_one_outside_token_defs(
            self.css, OLD_STATUS_HEXES["dark-info"]
        )
        self.assertEqual(
            offenders,
            [],
            "旧 dark info rgba(59, 130, 246, 1) 不应再硬编码；\n  "
            + "\n  ".join(offenders),
        )

    def test_old_light_warning_rgba_alpha_one_not_hardcoded(self) -> None:
        offenders = _rgba_alpha_one_outside_token_defs(
            self.css, OLD_STATUS_HEXES["light-warning"]
        )
        self.assertEqual(
            offenders,
            [],
            "旧 light warning rgba(245, 158, 11, 1) 不应再硬编码；\n  "
            + "\n  ".join(offenders),
        )

    def test_old_light_error_rgba_alpha_one_not_hardcoded(self) -> None:
        offenders = _rgba_alpha_one_outside_token_defs(
            self.css, OLD_STATUS_HEXES["light-error"]
        )
        self.assertEqual(
            offenders,
            [],
            "旧 light error rgba(197, 77, 71, 1) 不应再硬编码；\n  "
            + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
