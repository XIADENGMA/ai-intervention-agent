"""mining-cycle-2 §3.4 — one-click copy task_id 回归测试

覆盖：
- ``copyTaskIdToClipboard`` helper 存在 + 双路径 (clipboard API +
  ``document.execCommand`` fallback) 都被引用
- ``createTaskTab`` 内 ``textSpan`` 上挂 ``dblclick`` listener
- ``data-copyable-task-id`` 属性写在 textSpan 上（供 UI 测试 hook 和
  截图回归 grep）
- helper 调 ``status.copied`` / ``status.copyFailed`` i18n key
- i18n key 在 en.json + zh-CN.json 都存在
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
EN_JSON = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
ZH_CN_JSON = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)


class TestHelperExists(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_helper_function_defined(self) -> None:
        self.assertRegex(
            self.src,
            r"async function copyTaskIdToClipboard\(\s*taskId\s*\)",
            "必须定义 async copyTaskIdToClipboard(taskId)",
        )

    def test_helper_uses_clipboard_api(self) -> None:
        self.assertIn(
            "navigator.clipboard.writeText",
            self.src,
            "helper 必须 try clipboard API primary path",
        )

    def test_helper_has_execcommand_fallback(self) -> None:
        self.assertIn(
            'document.execCommand("copy")',
            self.src,
            "helper 必须有 ``document.execCommand('copy')`` legacy fallback",
        )

    def test_helper_uses_status_i18n_keys(self) -> None:
        self.assertIn(
            't("status.copied")', self.src, "helper 成功 path 必须 t('status.copied')"
        )
        self.assertIn(
            't("status.copyFailed")',
            self.src,
            "helper 失败 path 必须 t('status.copyFailed')",
        )

    def test_helper_exposed_on_window(self) -> None:
        self.assertIn(
            "window.copyTaskIdToClipboard = copyTaskIdToClipboard",
            self.src,
            "helper 必须暴露到 window 以便测试和外部调用",
        )


class TestTaskTabWiring(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_textspan_has_copyable_attribute(self) -> None:
        self.assertIn(
            'setAttribute("data-copyable-task-id"',
            self.src,
            "task tab textSpan 必须有 data-copyable-task-id 属性供 UI 测试 hook",
        )

    def test_textspan_has_dblclick_listener(self) -> None:
        self.assertRegex(
            self.src,
            r'textSpan\.addEventListener\(\s*"dblclick"',
            "textSpan 必须有 dblclick 监听器",
        )

    def test_dblclick_handler_calls_helper(self) -> None:
        """dblclick handler 必须调 copyTaskIdToClipboard(task.task_id)。"""
        # 用 multiline 兼容 black/ruff 任何格式
        pattern = r'dblclick"[\s\S]*?copyTaskIdToClipboard\(\s*task\.task_id\s*\)'
        self.assertRegex(self.src, pattern, "dblclick handler 必须调 helper")

    def test_dblclick_handler_stops_propagation(self) -> None:
        """防止双击触发"切换任务"（task tab 上的 click handler）。"""
        pattern = r'dblclick"[\s\S]*?e\.stopPropagation\(\)'
        self.assertRegex(
            self.src, pattern, "dblclick handler 必须 stopPropagation 防止误触发 click"
        )


class TestI18nKeysExist(unittest.TestCase):
    def test_en_has_status_copied_and_failed(self) -> None:
        data = json.loads(EN_JSON.read_text(encoding="utf-8"))
        status = data.get("status") or {}
        self.assertIn(
            "copied", status, "en.json::status.copied 必须存在（helper 复用此 key）"
        )
        self.assertIn(
            "copyFailed",
            status,
            "en.json::status.copyFailed 必须存在（helper 复用此 key）",
        )

    def test_zh_cn_has_status_copied_and_failed(self) -> None:
        data = json.loads(ZH_CN_JSON.read_text(encoding="utf-8"))
        status = data.get("status") or {}
        self.assertIn("copied", status, "zh-CN.json::status.copied 必须存在")
        self.assertIn("copyFailed", status, "zh-CN.json::status.copyFailed 必须存在")


class TestAntiRegression(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_no_single_click_hijack(self) -> None:
        """textSpan 不能挂额外的 ``click`` listener — single click 必须保留
        给 task 切换（task tab 自身的现有 click handler）。

        这条 invariant 防止未来 refactor 把 copy 改成 single-click，
        破坏 task 切换 UX。
        """
        # 在 textSpan 加 dblclick 那段附近 ±10 行，不能有 textSpan.addEventListener("click"
        # 简化判定：全文 textSpan.addEventListener("click" 数量必须为 0
        click_count = len(
            re.findall(r'textSpan\.addEventListener\(\s*"click"', self.src)
        )
        self.assertEqual(
            click_count,
            0,
            "textSpan 不能挂 click 监听器；single click 必须留给 task 切换",
        )


class TestVisualFlashFeedback(unittest.TestCase):
    """cr34 §8 #1 — 复制后给来源 textSpan 加 600ms 视觉反馈。"""

    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_flash_helper_defined(self) -> None:
        self.assertRegex(
            self.src,
            r"function _flashCopyOnSourceElement\(\s*taskId\s*,\s*ok\s*\)",
            "必须定义 _flashCopyOnSourceElement(taskId, ok)",
        )

    def test_flash_helper_called_on_id_copy(self) -> None:
        m = re.search(
            r"async function copyTaskIdToClipboard\(\s*taskId\s*\)\s*\{([\s\S]*?)\n\}",
            self.src,
        )
        self.assertIsNotNone(m)
        assert m is not None
        self.assertIn(
            "_flashCopyOnSourceElement(taskId,",
            m.group(1),
            "copyTaskIdToClipboard 应该调 _flashCopyOnSourceElement",
        )

    def test_flash_helper_called_on_link_copy(self) -> None:
        m = re.search(
            r"async function copyTaskLinkToClipboard\(\s*taskId\s*\)\s*\{([\s\S]*?)\n\}",
            self.src,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(1)
        self.assertGreaterEqual(
            body.count("_flashCopyOnSourceElement"),
            2,
            "copyTaskLinkToClipboard 应在 invalid-url 和 写完后 两个分支调 flash",
        )

    def test_flash_uses_dataset_query(self) -> None:
        self.assertIn(
            "data-copyable-task-id=",
            self.src,
            "_flashCopyOnSourceElement 必须用 data-copyable-task-id 查找来源元素",
        )

    def test_flash_uses_css_escape(self) -> None:
        self.assertIn(
            "CSS.escape(",
            self.src,
            "querySelector 必须用 CSS.escape 防止 task_id 含特殊字符注入 selector",
        )


if __name__ == "__main__":
    unittest.main()
