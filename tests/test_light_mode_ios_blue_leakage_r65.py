"""R65：浅色模式 — iOS 蓝硬编码 leakage 修复测试。

历史背景
--------

main.css 内大量组件（``.btn``、``.feedback-textarea:focus``、
``.description``、``.setting-input:focus`` 等）的默认（深色模式）规则
硬编码 ``rgba(0, 122, 255, X)``（iOS system blue），早期与黑色背景搭配
没有视觉问题。后来引入 light/dark 主题变量时只覆盖了高频按钮（btn 系列、
option-item、scrollbar 等），R64 进一步补全了 ``.btn:hover`` 的浅色覆盖，
但 7 个 high-traffic 组件在浅色模式下仍然漏出 iOS 蓝，与 Anthropic
Orange (#d97757) 主调不和谐：

1. ``.feedback-textarea:focus``  — 反馈文本框聚焦
2. ``.btn:active`` / ``.btn-primary:active`` / ``.btn-secondary:active``
3. ``.description`` / ``.description::before``  — LLM prompt 容器
4. ``.textarea-drag-over``       — 拖图到文本框
5. ``.drag-overlay-content``     — 拖图到页面
6. ``.setting-input:focus``      — 设置面板输入框
7. ``.settings-btn:focus``       — 设置按钮 focus

R65 修复策略与 R64 一致 —— 仅添加 ``[data-theme='light']`` override，
深色模式 100% 不变；颜色统一替换为 Anthropic Orange ``#d97757`` /
``rgba(217, 119, 87, X)``。

测试策略
--------

* 解析 ``static/css/main.css``，对每条 R65 规则用容忍空白/单双引号的
  正则匹配选择器 + 关键属性；
* 显式断言「不能再出现 iOS 蓝 (0,122,255)」于这些 light-mode 规则块内
  （regression guard）；
* 与 R64 同样避免 brittle 字面量比较：用 RGB 数字三元组 + 任意空白匹配。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CSS_FILE = REPO_ROOT / "static" / "css" / "main.css"

_THEME_LIGHT_PREFIX = r"\[data-theme=['\"]light['\"]\]"
_ORANGE_RGB = r"rgba?\s*\(\s*217\s*,\s*119\s*,\s*87"
_IOS_BLUE_RGB = r"rgba?\s*\(\s*0\s*,\s*122\s*,\s*255"


def _read_css() -> str:
    if not CSS_FILE.exists():
        raise FileNotFoundError(f"main.css 不存在：{CSS_FILE}")
    return CSS_FILE.read_text(encoding="utf-8")


def _extract_rule_block(css: str, selector_regex: str) -> str | None:
    """从 css 中抽出第一个匹配 selector 的规则块（不含外层花括号）。

    用于把单条规则隔离出来后再做属性断言（避免跨规则误匹配）。
    """
    pattern = re.compile(selector_regex + r"[^{]*\{([^}]*)\}", re.DOTALL)
    m = pattern.search(css)
    return m.group(1) if m else None


class TestR65FeedbackTextareaFocus(unittest.TestCase):
    """R65-1：反馈文本框 :focus 在浅色模式下用 Orange 边框 / 阴影。"""

    def setUp(self) -> None:
        self.css = _read_css()

    def test_feedback_textarea_focus_has_light_override(self) -> None:
        block = _extract_rule_block(
            self.css,
            _THEME_LIGHT_PREFIX + r"\s+\.feedback-textarea:focus",
        )
        self.assertIsNotNone(
            block,
            "R65-1 缺失：未找到 [data-theme='light'] .feedback-textarea:focus 规则。",
        )
        assert block is not None
        self.assertRegex(
            block,
            _ORANGE_RGB,
            "R65-1：反馈文本框 :focus 浅色规则应包含 Orange RGB(217,119,87)。",
        )
        self.assertNotRegex(
            block,
            _IOS_BLUE_RGB,
            "R65-1 regression：浅色规则块内不应再出现 iOS 蓝 RGB(0,122,255)。",
        )


class TestR65BtnActive(unittest.TestCase):
    """R65-2：按钮 :active 浅色模式不再闪 iOS 蓝。"""

    def setUp(self) -> None:
        self.css = _read_css()

    def test_btn_active_has_light_override(self) -> None:
        pattern = re.compile(
            _THEME_LIGHT_PREFIX + r"\s+\.btn(?:-(?:primary|secondary))?:active",
            re.DOTALL,
        )
        self.assertRegex(
            self.css,
            pattern,
            "R65-2 缺失：未找到 [data-theme='light'] .btn(*):active 规则。",
        )

    def test_btn_active_uses_orange_background(self) -> None:
        """``.btn:active`` 浅色规则的 background 必须是 Orange/Deep Orange。

        允许 ``#c56a4c`` / ``#d97757`` 字面量或 ``rgba(217,119,87,X)``。
        """
        block_pattern = re.compile(
            _THEME_LIGHT_PREFIX + r"\s+\.btn(?:[^{]*:active)[^{]*\{([^}]+)\}",
            re.DOTALL,
        )
        m = block_pattern.search(self.css)
        self.assertIsNotNone(
            m,
            "R65-2：未找到 [data-theme='light'] .btn(...):active { ... } 规则块。",
        )
        assert m is not None
        block = m.group(1)
        orange_hex = re.compile(r"#(?:d97757|c56a4c)", re.IGNORECASE)
        self.assertTrue(
            orange_hex.search(block) or re.search(_ORANGE_RGB, block),
            "R65-2：.btn:active 浅色规则应使用 Orange (#d97757/#c56a4c) "
            "或 Orange RGB；当前规则未包含。",
        )


class TestR65Description(unittest.TestCase):
    """R65-3：``.description`` 浅色模式不再蓝紫渐变。"""

    def setUp(self) -> None:
        self.css = _read_css()

    def test_description_has_light_override(self) -> None:
        block = _extract_rule_block(
            self.css,
            _THEME_LIGHT_PREFIX + r"\s+\.description(?![:.\w-])",
        )
        self.assertIsNotNone(
            block,
            "R65-3 缺失：未找到 [data-theme='light'] .description 规则。",
        )

    def test_description_uses_orange_border_or_shadow(self) -> None:
        block = _extract_rule_block(
            self.css,
            _THEME_LIGHT_PREFIX + r"\s+\.description(?![:.\w-])",
        )
        assert block is not None
        self.assertRegex(
            block,
            _ORANGE_RGB,
            "R65-3：.description 浅色规则应至少有一处 Orange RGB（边框/阴影/背景）。",
        )

    def test_description_no_pure_ios_blue_in_light_block(self) -> None:
        """description 浅色块内不应再出现纯蓝 (0,122,255)。

        允许把 Anthropic Cloud Blue (106,155,204) 作为渐变中段保留，
        因为它属于品牌色板。
        """
        block = _extract_rule_block(
            self.css,
            _THEME_LIGHT_PREFIX + r"\s+\.description(?![:.\w-])",
        )
        assert block is not None
        self.assertNotRegex(
            block,
            _IOS_BLUE_RGB,
            "R65-3 regression：description 浅色规则不应再出现 iOS 蓝 (0,122,255)。",
        )


class TestR65DragOverlays(unittest.TestCase):
    """R65-4 / R65-5：拖图状态浅色模式不再蓝色发光。"""

    def setUp(self) -> None:
        self.css = _read_css()

    def test_textarea_drag_over_has_light_override(self) -> None:
        block = _extract_rule_block(
            self.css,
            _THEME_LIGHT_PREFIX + r"\s+\.textarea-drag-over",
        )
        self.assertIsNotNone(
            block,
            "R65-4 缺失：未找到 [data-theme='light'] .textarea-drag-over 规则。",
        )
        assert block is not None
        self.assertRegex(
            block,
            _ORANGE_RGB,
            "R65-4：textarea-drag-over 浅色规则应使用 Orange RGB。",
        )
        self.assertNotRegex(
            block,
            _IOS_BLUE_RGB,
            "R65-4 regression：浅色规则块内不应再出现 iOS 蓝。",
        )

    def test_drag_overlay_content_has_light_override(self) -> None:
        block = _extract_rule_block(
            self.css,
            _THEME_LIGHT_PREFIX + r"\s+\.drag-overlay-content",
        )
        self.assertIsNotNone(
            block,
            "R65-5 缺失：未找到 [data-theme='light'] .drag-overlay-content 规则。",
        )
        assert block is not None
        self.assertRegex(
            block,
            _ORANGE_RGB,
            "R65-5：drag-overlay-content 浅色规则应使用 Orange RGB。",
        )
        self.assertNotRegex(
            block,
            _IOS_BLUE_RGB,
            "R65-5 regression：浅色规则块内不应再出现 iOS 蓝。",
        )


class TestR65SettingInputAndSettingsBtnFocus(unittest.TestCase):
    """R65-6 / R65-7：设置输入框 + 设置按钮 focus 在浅色模式下用 Orange。"""

    def setUp(self) -> None:
        self.css = _read_css()

    def test_setting_input_focus_has_light_override(self) -> None:
        block = _extract_rule_block(
            self.css,
            _THEME_LIGHT_PREFIX + r"\s+\.setting-input:focus",
        )
        self.assertIsNotNone(
            block,
            "R65-6 缺失：未找到 [data-theme='light'] .setting-input:focus 规则。",
        )
        assert block is not None
        # 允许 #d97757 hex 字面量也算 Orange
        self.assertTrue(
            re.search(r"#d97757", block, re.IGNORECASE)
            or re.search(_ORANGE_RGB, block),
            "R65-6：setting-input:focus 浅色规则应使用 Orange (#d97757 或 RGB)。",
        )
        self.assertNotRegex(
            block,
            _IOS_BLUE_RGB,
            "R65-6 regression：浅色规则块内不应再出现 iOS 蓝。",
        )

    def test_settings_btn_focus_has_light_override(self) -> None:
        block = _extract_rule_block(
            self.css,
            _THEME_LIGHT_PREFIX + r"\s+\.settings-btn:focus",
        )
        self.assertIsNotNone(
            block,
            "R65-7 缺失：未找到 [data-theme='light'] .settings-btn:focus 规则。",
        )
        assert block is not None
        self.assertRegex(
            block,
            _ORANGE_RGB,
            "R65-7：settings-btn:focus 浅色规则应包含 Orange RGB box-shadow。",
        )
        self.assertNotRegex(
            block,
            _IOS_BLUE_RGB,
            "R65-7 regression：浅色规则块内不应再出现 iOS 蓝。",
        )


class TestR65SourceRulesStillExist(unittest.TestCase):
    """守护：R65 是 override 修复，必须有「源规则」存在它才有意义。

    若未来某次重构把源规则（深色默认）重写或删除，R65 的 override 可能
    成为「孤儿规则」。这里把源规则作为隐式契约锁住，结构变化时强制
    开发者重新评估 R65 修复范围。
    """

    EXPECTED_DEFAULT_SELECTORS = (
        r"\.feedback-textarea:focus",
        r"\.btn:active",
        r"\.description(?![-:.\w])",
        r"\.textarea-drag-over",
        r"\.drag-overlay-content",
        r"\.setting-input:focus",
        r"\.settings-btn:focus",
    )

    def setUp(self) -> None:
        self.css = _read_css()

    def test_all_default_rules_still_exist(self) -> None:
        for selector in self.EXPECTED_DEFAULT_SELECTORS:
            with self.subTest(selector=selector):
                # 排除带 [data-theme=...] 前缀的浅色 override 行
                pattern = re.compile(
                    r"(?<!\])(?<!\s)" + r"\n" + selector + r"\b",
                    re.MULTILINE,
                )
                self.assertRegex(
                    self.css,
                    pattern,
                    f"R65 守护：未找到默认（深色）规则 {selector}，"
                    "R65 的 [data-theme='light'] override 失去了源规则的"
                    "对照，可能导致深色模式回归。请检查重构。",
                )


if __name__ == "__main__":
    unittest.main()
