"""feat-sse-status-indicator (§3.1) 回归契约

对标 mcp-feedback-enhanced 的 Connection Monitoring 特性，把项目原本
仅作为内部 boolean (``_sseConnected``) 的 SSE 连接状态 surface 到 UI：
顶部一个 3 态胶囊 (connected / reconnecting / disconnected)，配合 i18n
+ a11y。

设计原则（必须 lock 住，避免回归）
----------------------------------
1. **非侵入式**：``connected`` 状态 UI 完全隐藏（避免对健康路径添加
   视觉噪声）；仅在异常状态显示，符合 "Don't make me think" 原则。
2. **CSS-driven**：JS 仅写 ``data-sse-state`` 属性；样式 / 可见性 /
   动画全部由 CSS 根据属性切换。这让 JS 模块未加载时 fallback 完美
   （DOM 元素静默隐藏，不影响 init 路径）。
3. **i18n + a11y**：每个状态都有 ``title`` (hover tooltip) + ``aria-label``
   双覆盖，``role="status"`` + ``aria-live="polite"`` 让屏幕阅读器
   可感知状态切换。
4. **3 个 SSE state machine hook 点**：``onopen`` 触发 ``connected``，
   ``onerror`` 区分 reconnecting vs disconnected（用 ``_sseReconnectDelay``
   是否退到 30s 上限判定），``_disconnectSSE`` (主动关闭) 回到 connected
   隐藏态。
5. **不引入新计时器**：复用既有 ``_sseReconnectDelay`` 状态，避免
   并行 timer 链导致的复杂度增加。
6. **reduce-motion 友好**：呼吸动画在 ``prefers-reduced-motion: reduce``
   下被禁用（a11y 必备）。

锁定的不变量
------------
A. HTML 元素 + 必备属性
B. CSS 3 状态 selector + 默认隐藏 + reduce-motion override
C. JS state machine 在正确 hook 点切换状态
D. i18n keys 双语完整
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
EN_JSON = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
ZH_JSON = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ============================================================
# A. HTML
# ============================================================
class TestHtmlStructure(unittest.TestCase):
    def setUp(self) -> None:
        self.html = WEB_UI_HTML.read_text(encoding="utf-8")

    def test_indicator_element_present(self) -> None:
        self.assertIn(
            'id="sse-status-indicator"',
            self.html,
            "web_ui.html 必须含 ``#sse-status-indicator`` 元素",
        )

    def test_indicator_has_class(self) -> None:
        self.assertIn(
            'class="sse-status-indicator"',
            self.html,
            "元素必须带 ``.sse-status-indicator`` class 才能匹配 CSS 状态规则",
        )

    def test_indicator_has_initial_connected_state(self) -> None:
        """初始 ``data-sse-state="connected"`` 必须存在，否则 CSS 默认
        样式不会隐藏元素，会一直显示。"""
        self.assertRegex(
            self.html,
            r'id="sse-status-indicator"[^>]*data-sse-state="connected"',
            "初始 data-sse-state 必须是 connected（隐藏态）",
        )

    def test_indicator_has_aria_live(self) -> None:
        """屏幕阅读器必须能感知状态切换。"""
        m = re.search(
            r'id="sse-status-indicator"([^>]*)>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 #sse-status-indicator opening tag")
        assert m is not None
        attrs = m.group(1)
        self.assertIn('role="status"', attrs, "必须 role=status")
        self.assertIn('aria-live="polite"', attrs, "必须 aria-live=polite")

    def test_indicator_has_i18n_attributes(self) -> None:
        """``data-i18n-title`` / ``data-i18n-aria-label`` 必须挂上，初始
        渲染就走 i18n（不依赖 JS 加载顺序）。"""
        m = re.search(
            r'id="sse-status-indicator"([^>]*)>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        attrs = m.group(1)
        self.assertIn(
            'data-i18n-title="page.sseStatus.connected"',
            attrs,
            "初始 title 必须走 page.sseStatus.connected key",
        )
        self.assertIn(
            'data-i18n-aria-label="page.sseStatus.connected"',
            attrs,
            "初始 aria-label 必须走 page.sseStatus.connected key",
        )

    def test_indicator_has_dot_and_label_children(self) -> None:
        # 圆点 + label 两个子元素，让 CSS 能独立 style
        self.assertIn(
            'class="sse-status-dot"',
            self.html,
            "必须有 .sse-status-dot 子元素",
        )
        self.assertIn(
            'class="sse-status-label"',
            self.html,
            "必须有 .sse-status-label 子元素",
        )

    def test_indicator_inside_header_actions(self) -> None:
        """元素位置：必须在 ``.header-actions`` 容器内（顶部右侧操作区），
        而不是 footer / 任务列表里 —— 视觉信息架构。"""
        header_match = re.search(
            r'class="header-actions"(.*?)</div>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(header_match, "未找到 .header-actions 容器")
        assert header_match is not None
        self.assertIn(
            "sse-status-indicator",
            header_match.group(1),
            "SSE 指示器必须放在 .header-actions 内（视觉一致性）",
        )


# ============================================================
# B. CSS
# ============================================================
class TestCssRules(unittest.TestCase):
    def setUp(self) -> None:
        self.css = MAIN_CSS.read_text(encoding="utf-8")

    def test_base_class_present(self) -> None:
        self.assertIn(".sse-status-indicator {", self.css)

    def test_base_class_hidden_by_default(self) -> None:
        # 用 regex 抓 .sse-status-indicator { ... } 整块，确认 display: none
        m = re.search(
            r"\.sse-status-indicator\s*\{([^}]+)\}",
            self.css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 .sse-status-indicator 基础规则块")
        assert m is not None
        self.assertIn(
            "display: none",
            m.group(1),
            "基础规则必须 display:none（默认 connected 状态隐藏）",
        )

    def test_three_state_selectors_present(self) -> None:
        for state in ("connected", "reconnecting", "disconnected"):
            self.assertRegex(
                self.css,
                rf'\[data-sse-state="{state}"\]',
                f"必须有 [data-sse-state={state!r}] 状态规则",
            )

    def test_reconnecting_and_disconnected_show_inline_flex(self) -> None:
        """异常态规则必须把 display 翻成 inline-flex，否则 connected 的
        display:none 会覆盖整个元素。"""
        m = re.search(
            r'\.sse-status-indicator\[data-sse-state="reconnecting"\][^{]*,[\s\n]*\.sse-status-indicator\[data-sse-state="disconnected"\]\s*\{([^}]+)\}',
            self.css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "必须有合并的 reconnecting + disconnected 显示规则",
        )
        assert m is not None
        self.assertIn("display: inline-flex", m.group(1))

    def test_reconnecting_has_pulse_animation(self) -> None:
        self.assertRegex(
            self.css,
            r"animation:\s*sseStatusPulse",
            "reconnecting 状态必须有 sseStatusPulse 呼吸动画",
        )
        self.assertIn(
            "@keyframes sseStatusPulse",
            self.css,
            "必须定义 @keyframes sseStatusPulse",
        )

    def test_reduce_motion_disables_animation(self) -> None:
        """a11y：用户偏好减少动画时必须关闭呼吸效果。"""
        m = re.search(
            r"@media \(prefers-reduced-motion: reduce\)\s*\{([^@]+?)\.sse-status-indicator\[data-sse-state=\"reconnecting\"\]\s*\.sse-status-dot\s*\{([^}]+)\}",
            self.css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "prefers-reduced-motion: reduce 媒体查询里必须 override "
            ".sse-status-dot 动画",
        )
        assert m is not None
        self.assertIn("animation: none", m.group(2))


# ============================================================
# C. JS state machine
# ============================================================
class TestJsStateMachine(unittest.TestCase):
    def setUp(self) -> None:
        self.full = MULTI_TASK_JS.read_text(encoding="utf-8")
        self.code = _strip_js_comments(self.full)

    def test_setter_function_defined(self) -> None:
        self.assertRegex(
            self.code,
            r"function\s+_setSseStatus\s*\(",
            "必须定义 _setSseStatus(state) 函数把状态写到 DOM 属性",
        )

    def test_setter_writes_data_attribute(self) -> None:
        m = re.search(
            r"function\s+_setSseStatus\s*\([^)]*\)\s*\{(.*?)\n\}",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 _setSseStatus 函数体")
        assert m is not None
        body = m.group(1)
        self.assertIn("getElementById", body, "_setSseStatus 必须查 DOM")
        self.assertIn(
            'setAttribute("data-sse-state"',
            body,
            "_setSseStatus 必须写 data-sse-state 属性",
        )

    def test_constants_defined(self) -> None:
        for const, val in (
            ("SSE_STATUS_CONNECTED", "connected"),
            ("SSE_STATUS_RECONNECTING", "reconnecting"),
            ("SSE_STATUS_DISCONNECTED", "disconnected"),
        ):
            self.assertRegex(
                self.code,
                rf'var\s+{const}\s*=\s*"{val}"',
                f"必须定义常量 {const} = '{val}'",
            )

    def test_onopen_sets_connected(self) -> None:
        """onopen 必须调用 _setSseStatus(SSE_STATUS_CONNECTED)。"""
        m = re.search(
            r"source\.onopen\s*=\s*function\s*\(\)\s*\{(.*?)\n\s*\};",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 source.onopen handler")
        assert m is not None
        body = m.group(1)
        self.assertIn(
            "_setSseStatus(SSE_STATUS_CONNECTED)",
            body,
            "onopen 必须切换到 connected 状态（隐藏 UI）",
        )

    def test_onerror_picks_state_by_reconnect_delay(self) -> None:
        """onerror 必须根据 _sseReconnectDelay 选 reconnecting / disconnected。"""
        m = re.search(
            r"source\.onerror\s*=\s*function\s*\(\)\s*\{(.*?)\n\s*\};",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 source.onerror handler")
        assert m is not None
        body = m.group(1)
        self.assertIn(
            "SSE_STATUS_RECONNECTING",
            body,
            "onerror 路径必须可能切换到 reconnecting",
        )
        self.assertIn(
            "SSE_STATUS_DISCONNECTED",
            body,
            "onerror 路径必须可能切换到 disconnected",
        )

    def test_disconnect_resets_to_connected(self) -> None:
        """主动 disconnect（页面 hidden / unload）不应留下黄色/红色焦虑 UI。"""
        m = re.search(
            r"function\s+_disconnectSSE\s*\(\)\s*\{(.*?)\n\}",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(1)
        self.assertIn(
            "_setSseStatus(SSE_STATUS_CONNECTED)",
            body,
            "_disconnectSSE 必须重置到 connected（即隐藏 UI），避免主动关闭"
            "时残留焦虑指示器",
        )

    def test_disconnect_threshold_constant_matches_backoff_cap(self) -> None:
        """``SSE_STATUS_DISCONNECTED_DELAY_MS`` 必须 = 30000，与 onerror
        里 ``Math.min(30000, ...)`` 的 backoff 上限一致。"""
        self.assertRegex(
            self.code,
            r"SSE_STATUS_DISCONNECTED_DELAY_MS\s*=\s*30000",
            "阈值必须与既有 backoff cap (30000) 一致",
        )
        self.assertRegex(
            self.code,
            r"Math\.min\(30000,\s*_sseReconnectDelay\s*\*\s*2\)",
            "既有 backoff cap 仍为 30000（同步 review）",
        )


# ============================================================
# D. i18n
# ============================================================
class TestI18nKeys(unittest.TestCase):
    REQUIRED_KEYS = ["label", "connected", "reconnecting", "disconnected"]

    def _load(self, p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    def test_en_has_all_keys(self) -> None:
        en = self._load(EN_JSON)
        sse = en.get("page", {}).get("sseStatus")
        self.assertIsInstance(
            sse,
            dict,
            "en.json 必须有 page.sseStatus 命名空间",
        )
        for key in self.REQUIRED_KEYS:
            self.assertIn(
                key,
                sse,
                f"en.json page.sseStatus 缺 {key}",
            )
            self.assertIsInstance(sse[key], str)
            self.assertGreater(len(sse[key].strip()), 0)

    def test_zh_has_all_keys(self) -> None:
        zh = self._load(ZH_JSON)
        sse = zh.get("page", {}).get("sseStatus")
        self.assertIsInstance(
            sse,
            dict,
            "zh-CN.json 必须有 page.sseStatus 命名空间",
        )
        for key in self.REQUIRED_KEYS:
            self.assertIn(
                key,
                sse,
                f"zh-CN.json page.sseStatus 缺 {key}",
            )
            self.assertIsInstance(sse[key], str)
            self.assertGreater(len(sse[key].strip()), 0)

    def test_zh_distinct_from_en(self) -> None:
        """zh-CN 翻译不能照抄英文（防止 placeholder 漏译）。"""
        en = self._load(EN_JSON).get("page", {}).get("sseStatus", {})
        zh = self._load(ZH_JSON).get("page", {}).get("sseStatus", {})
        for key in self.REQUIRED_KEYS:
            self.assertNotEqual(
                en.get(key),
                zh.get(key),
                f"page.sseStatus.{key} 中英文必须不同（防 placeholder 漏译）",
            )


# ============================================================
# E. 设计文档锚点（feature mining backlog 引用）
# ============================================================
class TestDesignAnchors(unittest.TestCase):
    def test_html_has_feat_anchor_comment(self) -> None:
        self.assertIn(
            "feat-sse-status-indicator",
            WEB_UI_HTML.read_text(encoding="utf-8"),
            "HTML 应有 feat-sse-status-indicator 注释锚点便于 grep / blame",
        )

    def test_css_has_feat_anchor_comment(self) -> None:
        self.assertIn(
            "feat-sse-status-indicator",
            MAIN_CSS.read_text(encoding="utf-8"),
            "CSS 应有 feat-sse-status-indicator 锚点",
        )

    def test_js_has_feat_anchor_comment(self) -> None:
        self.assertIn(
            "feat-sse-status-indicator",
            MULTI_TASK_JS.read_text(encoding="utf-8"),
            "JS 应有 feat-sse-status-indicator 锚点",
        )


if __name__ == "__main__":
    unittest.main()
