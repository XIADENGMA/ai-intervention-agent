"""R690 — VSCode webview 倒计时控制行与 web 端功能对齐（TODO#5）。

背景
----

web 端（``templates/web_ui.html`` + ``multi_task.js``）提供 +60s 延长与
冻结两个倒计时控制按钮；插件 webview 此前只有任务标签上的倒计时圆环，
没有任何控制入口——同一后端能力在两个客户端的可达性不一致。

R690 在插件 webview 补齐同构控制行：

1. ``webview.ts`` 渲染 ``#countdownControls``（含 ``#countdownExtendBtn`` /
   ``#countdownFreezeBtn``），默认 hidden；
2. ``webview-ui.js`` 的 ``updateCountdownControls`` 按 active 任务的
   ``auto_resubmit_timeout`` / ``extends_used`` / ``extends_max`` 切换
   可见性与置灰状态；点击分别调用服务端 ``/extend`` 与 ``/freeze``；
3. i18n 键 ``ui.countdown.extend*`` / ``ui.countdown.freeze*`` 在
   en / zh-CN / zh-TW 三个 locale 全量存在（parity 由既有脚本约束）。

本测试锁定上述源码契约与 locale 数据完整性。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
WEBVIEW_CSS = REPO_ROOT / "packages" / "vscode" / "webview.css"
LOCALES_DIR = REPO_ROOT / "packages" / "vscode" / "locales"

EXPECTED_KEYS = (
    "extendLabel",
    "extendTitle",
    "extendAriaLabel",
    "extendLimitReached",
    "extendFailed",
    "freezeLabel",
    "freezeTitle",
    "freezeAriaLabel",
    "freezeAlreadyFrozen",
    "freezeFailed",
)


class TestWebviewHtmlContract(unittest.TestCase):
    def setUp(self) -> None:
        self.source = WEBVIEW_TS.read_text(encoding="utf-8")

    def test_controls_row_exists_with_both_buttons(self) -> None:
        self.assertIn('id="countdownControls"', self.source)
        self.assertIn('id="countdownExtendBtn"', self.source)
        self.assertIn('id="countdownFreezeBtn"', self.source)

    def test_controls_hidden_by_default(self) -> None:
        match = re.search(r'<div class="([^"]*)" id="countdownControls"', self.source)
        self.assertIsNotNone(match, "未找到 countdownControls 容器")
        assert match is not None
        self.assertIn(
            "hidden", match.group(1), "控制行必须默认 hidden，由 JS 按任务状态显示"
        )

    def test_buttons_use_i18n_keys(self) -> None:
        self.assertIn('data-i18n="ui.countdown.extendLabel"', self.source)
        self.assertIn('data-i18n="ui.countdown.freezeLabel"', self.source)
        self.assertIn('data-i18n-title="ui.countdown.extendTitle"', self.source)
        self.assertIn('data-i18n-title="ui.countdown.freezeTitle"', self.source)


class TestWebviewUiWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.source = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    def test_update_countdown_controls_defined_and_called(self) -> None:
        self.assertIn("function updateCountdownControls(", self.source)
        # 至少在任务列表刷新 + 空队列 + /api/config 三条路径被调用
        self.assertGreaterEqual(
            self.source.count("updateCountdownControls("),
            4,
            "updateCountdownControls 必须在任务刷新/清空/config 路径均被调用",
        )

    def test_extend_click_posts_extend_endpoint(self) -> None:
        match = re.search(
            r"function handleCountdownExtendClick\(\) \{.*?\n  \}",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "未找到 handleCountdownExtendClick")
        assert match is not None
        self.assertIn("/extend", match.group(0))
        self.assertIn("seconds: 60", match.group(0))

    def test_freeze_click_posts_freeze_endpoint(self) -> None:
        match = re.search(
            r"function handleCountdownFreezeClick\(\) \{.*?\n  \}",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "未找到 handleCountdownFreezeClick")
        assert match is not None
        self.assertIn("/freeze", match.group(0))

    def test_buttons_are_bound_on_init(self) -> None:
        self.assertIn(
            "countdownExtendBtn.addEventListener('click', handleCountdownExtendClick)",
            self.source,
        )
        self.assertIn(
            "countdownFreezeBtn.addEventListener('click', handleCountdownFreezeClick)",
            self.source,
        )

    def test_extend_disabled_at_quota_limit(self) -> None:
        match = re.search(
            r"function updateCountdownControls\(.*?\n  \}",
            self.source,
            re.DOTALL,
        )
        assert match is not None
        body = match.group(0)
        self.assertIn("extends_used", body)
        self.assertIn("extends_max", body)
        self.assertIn("extendLimitReached", body)


class TestCssContract(unittest.TestCase):
    def test_controls_styles_exist(self) -> None:
        css = WEBVIEW_CSS.read_text(encoding="utf-8")
        self.assertIn(".countdown-controls", css)
        self.assertIn(".countdown-ctrl-btn", css)

    def test_controls_visually_retired_r700(self) -> None:
        """R700（与 web 端 R699 对齐）：+60s/冻结按钮行有意下线。

        typing-hold 自动延长取代手动操作；DOM/JS 保留，仅视觉隐藏。
        隐藏规则必须带 R700 标记，防止被当作事故误"修复"。
        """
        css = WEBVIEW_CSS.read_text(encoding="utf-8")
        match = re.search(r"\.countdown-controls\s*\{([^}]*)\}", css)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertIn("display: none", match.group(1))
        self.assertIn("R700", match.group(1))


class TestTickTypingGuardR700(unittest.TestCase):
    """R700：倒计时归零但用户仍在输入时，webview tick 不得触发 autoSubmit。"""

    def test_tick_zero_guard_present(self) -> None:
        js = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        idx = js.find("if (remainingSeconds <= 0) {")
        self.assertGreater(idx, 0)
        snippet = js[idx : idx + 600]
        self.assertIn("isUserActivelyTyping()", snippet)
        self.assertIn("autoSubmit()", snippet)


class TestTabLabelPrefersHeaderLabelR700(unittest.TestCase):
    """R700：任务标签优先显示 header_label，机器 ID 仅兜底（tooltip 保留全 ID）。"""

    def test_tab_label_logic(self) -> None:
        js = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        idx = js.find("const tabLabel =")
        self.assertGreater(idx, 0)
        snippet = js[idx : idx + 400]
        self.assertIn("task.header_label", snippet)
        self.assertIn("task.task_id", snippet)
        self.assertIn("taskId.title = task.task_id", snippet)


class TestLocaleKeys(unittest.TestCase):
    def test_all_locales_contain_countdown_control_keys(self) -> None:
        for locale in ("en", "zh-CN", "zh-TW"):
            data = json.loads(
                (LOCALES_DIR / f"{locale}.json").read_text(encoding="utf-8")
            )
            countdown = data.get("ui", {}).get("countdown", {})
            for key in EXPECTED_KEYS:
                with self.subTest(locale=locale, key=key):
                    self.assertIn(
                        key,
                        countdown,
                        f"{locale}.json 缺少 ui.countdown.{key}",
                    )
                    self.assertTrue(
                        str(countdown[key]).strip(),
                        f"{locale}.json 的 ui.countdown.{key} 不能为空",
                    )


if __name__ == "__main__":
    unittest.main()
