"""R64：浅色模式按钮文字颜色 + hover 视觉回归测试。

历史背景
--------

修复前 ``static/css/main.css`` 的「全局浅色覆盖」规则（line 6890-6920）使用了
``[data-theme='light'] span { color: var(--text-primary) }``——这是一个
*element selector*，**会直接命中按钮内部的** ``<span data-i18n=...>`` 文字
节点，把所有 11 个 ``.btn / .btn-secondary / .btn-primary`` 内的中文文字
强制设为深色 ``#141413``，与按钮自身 ``color: #fff``、SVG 图标 stroke
``currentColor`` 解析出的白色形成「图标白 + 文字黑」的反差。

同时 ``.btn:hover`` 默认 rule 用了 iOS 蓝色阴影 ``rgba(0, 122, 255, 0.3)``
+ ``transform: translateY(-1px)``，在浅色模式（Anthropic Orange 主题）下
极其突兀；``.btn::after`` 白色发光层在棕红背景上变成「褪色」。

R64 修复（``static/css/main.css`` 新增规则区域）：

1. ``[data-theme='light'] .btn span`` / ``.btn-secondary span`` /
   ``.btn-primary span`` → ``color: inherit``，让按钮内文字回到从按钮本身
   继承颜色（白色），与图标对齐。
2. ``[data-theme='light'] .btn:hover`` / 同系列 → ``transform: none`` +
   ``box-shadow: 0 2px 6px rgba(217, 119, 87, 0.25)``（Orange 阴影）。
3. ``[data-theme='light'] .btn:hover::after`` → ``opacity: 0``，关闭
   白色发光层。

测试策略
--------

* 解析 ``static/css/main.css`` 提取规则块，断言三类修复同时存在；
* 解析 ``templates/web_ui.html`` 抽出所有 ``.btn`` 系列按钮，确认它们
  仍然使用 ``<span data-i18n=...>`` 模式（避免未来重构静默规避修复）；
* 颜色字面量做「容忍空白/单双引号差异」的正则匹配，避免成为另一种
  brittle assertion（参考 R63 教训）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CSS_FILE = REPO_ROOT / "static" / "css" / "main.css"
TEMPLATE_FILE = REPO_ROOT / "templates" / "web_ui.html"

# 容忍 single/double quote、theme attr 内随意空白
_THEME_LIGHT_PREFIX = r"\[data-theme=['\"]light['\"]\]"


def _read_css() -> str:
    if not CSS_FILE.exists():
        raise FileNotFoundError(f"main.css 不存在：{CSS_FILE}")
    return CSS_FILE.read_text(encoding="utf-8")


def _read_template() -> str:
    if not TEMPLATE_FILE.exists():
        raise FileNotFoundError(f"web_ui.html 不存在：{TEMPLATE_FILE}")
    return TEMPLATE_FILE.read_text(encoding="utf-8")


class TestR64ButtonSpanInheritsLightColor(unittest.TestCase):
    """R64 修复 1：浅色模式按钮内 span 必须 ``color: inherit``。"""

    def setUp(self) -> None:
        self.css = _read_css()

    def test_btn_span_color_inherit_rule_exists(self) -> None:
        """``[data-theme='light'] .btn span`` 必须 ``color: inherit``。

        允许 ``.btn`` / ``.btn-secondary`` / ``.btn-primary`` 三系列任一
        以逗号分隔同时出现，只要修复规则块整体存在即可。
        """
        # 匹配整个规则块，规则的选择器列表可包含多个并列项
        pattern = re.compile(
            _THEME_LIGHT_PREFIX
            + r"\s+\.btn(?:-(?:primary|secondary))?\s+span[^{]*\{[^}]*color\s*:\s*inherit\s*[;}]",
            re.DOTALL,
        )
        self.assertRegex(
            self.css,
            pattern,
            "未找到 R64 修复规则 ``[data-theme='light'] .btn span "
            "{ color: inherit }``。修改 main.css 后需要保持该规则。",
        )

    def test_all_three_btn_variants_covered(self) -> None:
        """三种 .btn 变体必须都被覆盖（btn / btn-primary / btn-secondary）。"""
        for variant in ("btn", "btn-primary", "btn-secondary"):
            with self.subTest(variant=variant):
                pattern = re.compile(
                    _THEME_LIGHT_PREFIX + r"\s+\." + re.escape(variant) + r"\s+span",
                    re.IGNORECASE,
                )
                self.assertRegex(
                    self.css,
                    pattern,
                    f"R64 必须显式覆盖 .{variant} span 选择器（找到的规则缺失）。",
                )


class TestR64HoverEffectsLightMode(unittest.TestCase):
    """R64 修复 2 & 3：浅色模式 hover 效果回归。"""

    def setUp(self) -> None:
        self.css = _read_css()

    def test_hover_disables_translate_transform(self) -> None:
        """浅色模式 ``.btn:hover`` 必须显式 ``transform: none``。

        防止 ``.btn:hover { transform: translateY(-1px) }`` 默认规则在浅
        色模式下 leak。
        """
        pattern = re.compile(
            _THEME_LIGHT_PREFIX
            + r"\s+\.btn(?:-(?:primary|secondary))?:hover[^{]*\{[^}]*transform\s*:\s*none\s*[;}]",
            re.DOTALL,
        )
        self.assertRegex(
            self.css,
            pattern,
            "R64 修复缺失：浅色模式 .btn:hover 应 ``transform: none``。",
        )

    def test_hover_uses_orange_box_shadow_not_blue(self) -> None:
        """浅色模式 hover 阴影必须是 Anthropic Orange（217, 119, 87），不是 iOS 蓝。"""
        pattern = re.compile(
            _THEME_LIGHT_PREFIX
            + r"\s+\.btn(?:-(?:primary|secondary))?:hover[^{]*\{[^}]*"
            r"box-shadow\s*:[^;}]*rgba\s*\(\s*217\s*,\s*119\s*,\s*87",
            re.DOTALL,
        )
        self.assertRegex(
            self.css,
            pattern,
            "R64 修复缺失：浅色模式 .btn:hover 阴影应使用 Orange (217,119,87)，"
            "而不是默认的 iOS 蓝色 (0,122,255)。",
        )

    def test_hover_disables_after_pseudo_glow(self) -> None:
        """浅色模式 ``.btn:hover::after`` 必须 ``opacity: 0`` 关闭白色发光层。"""
        pattern = re.compile(
            _THEME_LIGHT_PREFIX
            + r"\s+\.btn:hover::after[^{]*\{[^}]*opacity\s*:\s*0\s*[;}]",
            re.DOTALL,
        )
        self.assertRegex(
            self.css,
            pattern,
            "R64 修复缺失：浅色模式 .btn:hover::after 应 ``opacity: 0``，"
            "关闭白色发光层避免在棕红背景上「褪色」。",
        )


class TestR64TemplateButtonsStillUseSpanI18n(unittest.TestCase):
    """守护：R64 修复假设按钮文本嵌套在 ``<span data-i18n=...>``。

    若未来某次重构把按钮文本直接写在 ``<button>`` 里、或换成
    ``<div data-i18n>`` 等其它结构，R64 的 CSS 规则就会失效但浏览器
    端仍然显示「正确颜色」（因为新结构不再被 [data-theme='light'] span
    命中）——单测无法发现回归。所以这里把模板结构当成 R64 的隐式契约
    锁住，结构变化时强制开发者重新评估 CSS 修复范围。
    """

    # 用户最初报告的 5 个 + chrome-devtools 实测发现的 6 个，共 11 个 .btn 按钮
    EXPECTED_BTN_IDS = (
        "close-btn",
        "test-bark-notification-btn",
        "test-notification-btn",
        "reset-settings-btn",
        "reset-feedback-config-btn",
        "insert-code-btn",
        "upload-image-btn",
        "submit-btn",
        "bark-base-url-copy-btn",
        "bark-base-url-recheck-btn",
        "open-config-file-btn",
    )

    def setUp(self) -> None:
        self.html = _read_template()

    def test_all_known_btns_have_data_i18n_span_child(self) -> None:
        """11 个 .btn 系列按钮都应包含 ``<span data-i18n=...>`` 子元素。"""
        # 简单解析：抓出 <button ... id="X"> ... </button> 块（贪婪 + 跨行）
        # web_ui.html 没有嵌套 <button>，所以非贪婪到下一个 </button> 即可。
        for btn_id in self.EXPECTED_BTN_IDS:
            with self.subTest(btn_id=btn_id):
                # 仅断言 <button id="X" ...> 与 </button> 之间存在 <span data-i18n
                pattern = re.compile(
                    r'<button\b[^>]*\bid="' + re.escape(btn_id) + r'"[^>]*>'
                    r"(.*?)"
                    r"</button>",
                    re.DOTALL,
                )
                m = pattern.search(self.html)
                self.assertIsNotNone(
                    m,
                    f"模板中未找到 id={btn_id!r} 的 <button>。"
                    "若已重命名/移除，请同步更新 R64 测试列表。",
                )
                assert m is not None
                inner = m.group(1)
                self.assertIn(
                    "data-i18n",
                    inner,
                    f"按钮 id={btn_id!r} 内不再嵌套 data-i18n 元素，"
                    "R64 的 CSS 修复（``.btn span { color: inherit }``）"
                    "可能不再覆盖该按钮的文字节点。"
                    "请重新评估并更新修复范围/测试。",
                )


if __name__ == "__main__":
    unittest.main()
