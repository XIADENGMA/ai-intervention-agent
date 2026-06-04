"""BUG1 回归契约：Web 设置页主动保存配置时，禁止 SSE config_changed 回显 toast。

背景：用户在 Web 设置页保存反馈/通知/语言配置后，后端写 config.toml →
file watcher 检测到 mtime 变化 → 通过 ``_emit_config_changed_to_sse_bus``
广播 ``config_changed`` SSE 事件。如果不做任何抑制，发起者会同时看到
两条 toast 提示：

  1. API 200 OK → ``showStatus("反馈配置已保存", "success")`` 一条 toast
  2. SSE config_changed → "Configuration file changed. Reload the page..." 又一条

第 2 条对发起者是冗余且误导的（用户被告诉 reload，但热更新已生效）。

修复策略（前端静音窗口）：
- ``multi_task.js`` 暴露 ``window.suppressLocalConfigChangedEcho(ms)``，
  写入未来时间戳到 ``_suppressConfigChangedToastUntilMs``；
- 同文件的 SSE ``config_changed`` handler 在显示 toast 前先调用
  ``_isConfigChangedToastSuppressed()``，命中静音窗口则只 debug log；
- ``settings-manager.js`` 在所有主动写配置（feedback / notification /
  language / reset）的 fetch 之前调用 ``_suppressConfigChangedEchoIfAvailable()``
  从而设置短期静音窗口。

本测试通过静态扫描 JS 源码锁住这套契约，避免后续重构无意中破坏。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"
SETTINGS_MANAGER_JS = STATIC_JS / "settings-manager.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestMultiTaskExposesSuppressionHelper(unittest.TestCase):
    """``multi_task.js`` 必须暴露 ``window.suppressLocalConfigChangedEcho``
    并在 SSE ``config_changed`` handler 中检查静音窗口。"""

    def setUp(self) -> None:
        self.source = _read(MULTI_TASK_JS)

    def test_module_level_state_variable_exists(self) -> None:
        """``_suppressConfigChangedToastUntilMs`` 模块级变量必须存在。"""
        self.assertIn(
            "_suppressConfigChangedToastUntilMs",
            self.source,
            "multi_task.js 必须有 _suppressConfigChangedToastUntilMs 模块级"
            "变量来记录静音窗口截止时间",
        )

    def test_predicate_helper_exists(self) -> None:
        """``_isConfigChangedToastSuppressed`` 谓词必须存在。"""
        self.assertIn(
            "function _isConfigChangedToastSuppressed()",
            self.source,
            "multi_task.js 必须有 _isConfigChangedToastSuppressed 谓词",
        )

    def test_window_helper_exposed(self) -> None:
        """``window.suppressLocalConfigChangedEcho`` 必须被暴露。"""
        # 同时接受单/双引号字面量。
        self.assertRegex(
            self.source,
            r"window\.suppressLocalConfigChangedEcho\s*=",
            "multi_task.js 必须暴露 window.suppressLocalConfigChangedEcho "
            "供 settings-manager.js 调用",
        )

    def test_sse_handler_checks_suppression_before_toast(self) -> None:
        """SSE ``config_changed`` handler 必须在调用 ``_showToast`` 前检查静音。"""
        # 提取 config_changed handler 的完整 body：
        # source.addEventListener("config_changed", function (e) { ... });
        match = re.search(
            r"addEventListener\(['\"]config_changed['\"]\s*,\s*function\s*\([^)]*\)\s*\{(?P<body>.*?)\}\s*\);",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "无法定位 config_changed SSE handler；测试需要更新")
        body = match.group("body")
        self.assertIn(
            "_isConfigChangedToastSuppressed()",
            body,
            "config_changed SSE handler 必须调用 _isConfigChangedToastSuppressed() "
            "检查是否处于本地保存静音窗口",
        )
        # 静音判断必须出现在 _showToast 调用之前（否则形同虚设）
        suppress_idx = body.find("_isConfigChangedToastSuppressed()")
        toast_idx = body.find("_showToast(")
        self.assertGreaterEqual(suppress_idx, 0)
        self.assertGreaterEqual(toast_idx, 0)
        self.assertLess(
            suppress_idx,
            toast_idx,
            "_isConfigChangedToastSuppressed() 必须在 _showToast 之前调用，"
            "否则即便命中静音窗口 toast 仍会显示",
        )

    def test_suppression_uses_max_window_semantics(self) -> None:
        """多次调用 ``suppressLocalConfigChangedEcho`` 应保留更大的窗口。

        防御性回归：连续两次保存（间隔 < 5s）不应让第二次缩短第一次
        留下的静音窗口。实现里通过 ``Math.max`` 或显式比较保证。
        """
        # 抓取 helper 函数 body
        match = re.search(
            r"window\.suppressLocalConfigChangedEcho\s*=\s*function\s*\([^)]*\)\s*\{(?P<body>.*?)\n\s*\};",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertTrue(
            "Math.max" in body or "until > _suppressConfigChangedToastUntilMs" in body,
            "suppressLocalConfigChangedEcho 必须确保新窗口截止时间 ≥ 旧值（用 "
            "Math.max 或显式比较），不能因为后调用而缩短窗口",
        )


class TestSettingsManagerSuppressionInvocations(unittest.TestCase):
    """``settings-manager.js`` 在所有主动写配置 fetch 前必须先调用静音 helper。"""

    def setUp(self) -> None:
        self.source = _read(SETTINGS_MANAGER_JS)

    def test_helper_defined(self) -> None:
        """``_suppressConfigChangedEchoIfAvailable`` 模块内 helper 必须存在。"""
        self.assertIn(
            "function _suppressConfigChangedEchoIfAvailable(",
            self.source,
            "settings-manager.js 必须定义 _suppressConfigChangedEchoIfAvailable helper",
        )
        # helper 必须做 typeof 兜底，避免 multi_task.js 未加载时崩溃
        self.assertIn(
            'typeof window.suppressLocalConfigChangedEcho === "function"',
            self.source,
            "helper 必须用 typeof 兜底 window.suppressLocalConfigChangedEcho 的存在性",
        )

    def _assert_suppression_before_endpoint(self, endpoint: str) -> None:
        """断言对应 endpoint 的 fetch 调用之前，必有 _suppressConfigChangedEchoIfAvailable()。"""
        # 找到所有 fetch("<endpoint>", ...) 调用
        pattern = rf"fetch\([\"']{re.escape(endpoint)}[\"']"
        matches = list(re.finditer(pattern, self.source))
        self.assertGreater(
            len(matches),
            0,
            f"settings-manager.js 应该有 fetch('{endpoint}', ...) 调用",
        )
        for m in matches:
            # 在 fetch 调用之前 400 字符内必须出现 helper 调用
            # （400 字符够覆盖正常的 method/headers/body 结构）
            window_start = max(0, m.start() - 400)
            preceding = self.source[window_start : m.start()]
            self.assertIn(
                "_suppressConfigChangedEchoIfAvailable()",
                preceding,
                f"endpoint {endpoint!r} 的 fetch 调用之前必须先调用 "
                f"_suppressConfigChangedEchoIfAvailable()，避免 SSE config_changed "
                f"回显 toast 与 API 成功提示重复",
            )

    def test_update_notification_config_has_suppression(self) -> None:
        self._assert_suppression_before_endpoint("/api/update-notification-config")

    def test_update_feedback_config_has_suppression(self) -> None:
        self._assert_suppression_before_endpoint("/api/update-feedback-config")

    def test_reset_feedback_config_has_suppression(self) -> None:
        self._assert_suppression_before_endpoint("/api/reset-feedback-config")

    def test_update_language_has_suppression(self) -> None:
        self._assert_suppression_before_endpoint("/api/update-language")


class TestSuppressionDocsAndIntent(unittest.TestCase):
    """文档化注释必须明确说明 BUG1 的修复意图，便于后续维护者快速理解。"""

    def test_multi_task_documents_bug1(self) -> None:
        source = _read(MULTI_TASK_JS)
        self.assertIn(
            "BUG1",
            source,
            "multi_task.js 应在 _suppressConfigChangedToastUntilMs 附近注释中"
            "标注 'BUG1' 锚点，让后续阅读者能追溯设计动机",
        )

    def test_settings_manager_documents_bug1(self) -> None:
        source = _read(SETTINGS_MANAGER_JS)
        self.assertIn(
            "BUG1",
            source,
            "settings-manager.js 应在 _suppressConfigChangedEchoIfAvailable 附近"
            "注释中标注 'BUG1' 锚点",
        )


if __name__ == "__main__":
    unittest.main()
