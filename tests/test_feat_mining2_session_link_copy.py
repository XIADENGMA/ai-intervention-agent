"""mining-cycle-2 §3.2 — task deep-link copy 回归测试

覆盖：
- ``buildTaskDeepLink(taskId, base?)`` helper 存在 + 正确构造 URL
- ``copyTaskLinkToClipboard(taskId)`` helper 存在 + 调
  ``buildTaskDeepLink`` + 调 ``_writeToClipboard``
- task tab textSpan dblclick 现在分流：
  - 普通 dblclick → ``copyTaskIdToClipboard``
  - Shift+dblclick → ``copyTaskLinkToClipboard``
- ``window.copyTaskLinkToClipboard`` + ``window.buildTaskDeepLink``
  暴露
- ``_writeToClipboard`` 被抽取为低阶 helper（架构清晰度回归）
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


class TestBuildTaskDeepLinkHelper(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_helper_defined(self) -> None:
        self.assertRegex(
            self.src,
            r"function buildTaskDeepLink\(\s*taskId\s*,\s*base\s*\)",
            "必须定义 buildTaskDeepLink(taskId, base)",
        )

    def test_helper_uses_url_api(self) -> None:
        self.assertIn(
            "new URL(",
            self.src,
            "buildTaskDeepLink 必须用 URL API（不能拼字符串，避免 query 失序）",
        )

    def test_helper_sets_task_id_param(self) -> None:
        self.assertIn(
            'searchParams.set("task_id"',
            self.src,
            "URL 必须含 task_id query param",
        )


class TestCopyLinkHelper(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_helper_defined(self) -> None:
        self.assertRegex(
            self.src,
            r"async function copyTaskLinkToClipboard\(\s*taskId\s*\)",
            "必须定义 async copyTaskLinkToClipboard(taskId)",
        )

    def test_helper_uses_buildTaskDeepLink(self) -> None:
        self.assertIn(
            "buildTaskDeepLink(taskId)",
            self.src,
            "copyTaskLinkToClipboard 必须调 buildTaskDeepLink",
        )

    def test_helper_uses_write_clipboard_helper(self) -> None:
        self.assertIn(
            "_writeToClipboard(url)",
            self.src,
            "必须调用低阶 _writeToClipboard helper（避免代码重复）",
        )

    def test_helper_uses_status_i18n(self) -> None:
        # 不引入新 i18n key；复用 status.copied / status.copyFailed
        self.assertIn('t("status.copied")', self.src)
        self.assertIn('t("status.copyFailed")', self.src)


class TestLowLevelHelperExtracted(unittest.TestCase):
    """mining-2 §3.2 重构 invariant：``_writeToClipboard`` 必须被抽取出来
    作为独立低阶 helper，``copyTaskIdToClipboard`` 与 ``copyTaskLinkToClipboard``
    都通过它写剪贴板，避免双 path 逻辑重复两次。
    """

    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_low_level_helper_defined(self) -> None:
        self.assertRegex(
            self.src,
            r"async function _writeToClipboard\(\s*text\s*\)",
            "必须定义 async _writeToClipboard(text)",
        )

    def test_id_helper_uses_low_level(self) -> None:
        # copyTaskIdToClipboard body 内必须出现 _writeToClipboard(taskId)
        m = re.search(
            r"async function copyTaskIdToClipboard\(\s*taskId\s*\)\s*\{([\s\S]*?)\n\}",
            self.src,
        )
        self.assertIsNotNone(m, "找不到 copyTaskIdToClipboard body")
        assert m is not None
        self.assertIn(
            "_writeToClipboard(taskId)",
            m.group(1),
            "copyTaskIdToClipboard 必须通过 _writeToClipboard 写剪贴板",
        )

    def test_no_duplicated_execcommand(self) -> None:
        """``document.execCommand("copy")`` 在重构后应该**只出现一次**
        （在 ``_writeToClipboard`` 内），不再在每个高层 helper 内重复。
        """
        count = len(re.findall(r'document\.execCommand\("copy"\)', self.src))
        self.assertEqual(
            count,
            1,
            f"document.execCommand('copy') 应该只在 _writeToClipboard 内出现一次，实际 {count} 次",
        )


class TestTaskTabShiftDblclickWiring(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_dblclick_handler_branches_on_shift(self) -> None:
        # 找 dblclick handler body
        m = re.search(
            r'textSpan\.addEventListener\(\s*"dblclick"\s*,\s*function\s*\([^)]+\)\s*\{([\s\S]*?)\n  \}\s*\)',
            self.src,
        )
        self.assertIsNotNone(m, "找不到 textSpan dblclick handler")
        assert m is not None
        body = m.group(1)
        self.assertIn(
            "e.shiftKey",
            body,
            "dblclick handler 必须检查 e.shiftKey 来分流 task_id / task_link",
        )
        self.assertIn(
            "copyTaskLinkToClipboard(task.task_id)",
            body,
            "Shift+dblclick 必须调 copyTaskLinkToClipboard",
        )
        self.assertIn(
            "copyTaskIdToClipboard(task.task_id)",
            body,
            "普通 dblclick 必须调 copyTaskIdToClipboard",
        )


class TestWindowExposure(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_link_helper_on_window(self) -> None:
        self.assertIn(
            "window.copyTaskLinkToClipboard = copyTaskLinkToClipboard",
            self.src,
        )

    def test_build_helper_on_window(self) -> None:
        self.assertIn(
            "window.buildTaskDeepLink = buildTaskDeepLink",
            self.src,
        )


if __name__ == "__main__":
    unittest.main()
