"""mining-cycle-3 §2.1 borrow #3 (gemini-cli ``ask_user.placeholder``)
回归测试。

设计回顾：per-task ``feedback_placeholder`` 让 agent 在调
``interactive_feedback`` 工具时为单次任务提示用户具体应该填什么内
容，覆盖默认 i18n 占位符 ``page.feedbackPlaceholder``。

测试范围：
1. ``Task`` model 持有字段（默认 None）
2. ``TaskQueue.add_task`` 接收新参数 + 200-char clamp
3. ``server_feedback.interactive_feedback`` MCP schema 增字段
4. ``POST /api/tasks`` 路由接收 + 传递
5. ``GET /api/tasks`` + ``GET /api/tasks/<id>`` 返回字段
6. 前端 ``updateFeedbackPlaceholder`` helper + ``switchTask`` /
   ``loadTaskDetails`` 调用点
7. 持久化 round-trip（snapshot + restore）
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_QUEUE_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "task_queue.py"
SERVER_FEEDBACK_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "server_feedback.py"
TASK_ROUTES_PY = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
)
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _import_task_module():
    import importlib

    return importlib.import_module("ai_intervention_agent.task_queue")


class TestTaskModelField(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_task_module()

    def test_task_has_feedback_placeholder_default_none(self) -> None:
        Task = self.mod.Task
        t = Task(task_id="t1", prompt="hi")
        self.assertTrue(hasattr(t, "feedback_placeholder"))
        self.assertIsNone(t.feedback_placeholder)

    def test_task_accepts_string_placeholder(self) -> None:
        Task = self.mod.Task
        t = Task(
            task_id="t2",
            prompt="hi",
            feedback_placeholder="Paste the error trace",
        )
        self.assertEqual(t.feedback_placeholder, "Paste the error trace")


class TestAddTaskClamp(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_task_module()
        # 用独立 queue 避免污染单例
        self.q = self.mod.TaskQueue(persist_path=None)

    def test_short_placeholder_is_kept(self) -> None:
        ok = self.q.add_task(
            task_id="t-short", prompt="hi", feedback_placeholder="short hint"
        )
        self.assertTrue(ok)
        t = self.q.get_task("t-short")
        assert t is not None
        self.assertEqual(t.feedback_placeholder, "short hint")

    def test_empty_placeholder_becomes_none(self) -> None:
        ok = self.q.add_task(task_id="t-empty", prompt="hi", feedback_placeholder="")
        self.assertTrue(ok)
        t = self.q.get_task("t-empty")
        assert t is not None
        self.assertIsNone(t.feedback_placeholder)

    def test_whitespace_only_placeholder_becomes_none(self) -> None:
        ok = self.q.add_task(
            task_id="t-ws", prompt="hi", feedback_placeholder="   \n\t  "
        )
        self.assertTrue(ok)
        t = self.q.get_task("t-ws")
        assert t is not None
        self.assertIsNone(t.feedback_placeholder)

    def test_long_placeholder_is_clamped_to_200_chars(self) -> None:
        # 300 chars 输入
        long_str = "x" * 300
        ok = self.q.add_task(
            task_id="t-long", prompt="hi", feedback_placeholder=long_str
        )
        self.assertTrue(ok)
        t = self.q.get_task("t-long")
        assert t is not None
        self.assertIsNotNone(t.feedback_placeholder)
        assert t.feedback_placeholder is not None
        self.assertEqual(len(t.feedback_placeholder), 200)

    def test_default_omitted_yields_none(self) -> None:
        ok = self.q.add_task(task_id="t-default", prompt="hi")
        self.assertTrue(ok)
        t = self.q.get_task("t-default")
        assert t is not None
        self.assertIsNone(t.feedback_placeholder)


class TestMcpToolSchema(unittest.TestCase):
    src = SERVER_FEEDBACK_PY.read_text(encoding="utf-8")

    def test_interactive_feedback_has_placeholder_param(self) -> None:
        self.assertRegex(
            self.src,
            r"feedback_placeholder:\s*str\s*\|\s*None\s*=\s*Field\(",
            "interactive_feedback 必须 expose feedback_placeholder MCP 参数",
        )

    def test_schema_mentions_mining_cycle_3(self) -> None:
        """description 里必须提到来源 + 200-char clamp，方便 LLM 用对。"""
        self.assertIn("mining-cycle-3", self.src)
        self.assertIn("200 characters", self.src)
        self.assertIn("gemini-cli", self.src)

    def test_post_task_includes_placeholder_in_json_body(self) -> None:
        """interactive_feedback 调 POST /api/tasks 时必须传 feedback_placeholder。"""
        self.assertIn(
            '"feedback_placeholder": feedback_placeholder',
            self.src,
        )


class TestRouteAcceptsAndReturnsPlaceholder(unittest.TestCase):
    src = TASK_ROUTES_PY.read_text(encoding="utf-8")

    def test_post_accepts_placeholder(self) -> None:
        self.assertIn('data.get("feedback_placeholder")', self.src)

    def test_post_passes_to_add_task(self) -> None:
        self.assertRegex(
            self.src,
            r"feedback_placeholder=feedback_placeholder",
            "POST /api/tasks 必须把 feedback_placeholder 转给 add_task",
        )

    def test_list_get_returns_placeholder(self) -> None:
        # GET /api/tasks (列表) 必须在 task dict 包含此字段
        self.assertRegex(
            self.src,
            r'"feedback_placeholder":\s*task\.feedback_placeholder',
            "task 序列化必须包含 feedback_placeholder",
        )

    def test_detail_get_returns_placeholder(self) -> None:
        # detail 路由（同一文件，独立检测）至少出现 2 次：list + detail
        count = self.src.count('"feedback_placeholder": task.feedback_placeholder')
        self.assertGreaterEqual(
            count, 2, "list 路由 + detail 路由都必须返回 feedback_placeholder"
        )


class TestFrontendHelper(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_helper_defined(self) -> None:
        self.assertRegex(
            self.src,
            r"function\s+updateFeedbackPlaceholder\(placeholder\)\s*\{",
            "必须定义 updateFeedbackPlaceholder helper",
        )

    def test_helper_falls_back_to_i18n_when_empty(self) -> None:
        m = re.search(
            r"function\s+updateFeedbackPlaceholder\(placeholder\)\s*\{([\s\S]*?)\n\}",
            self.src,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(1)
        # 必须有非空 string 分支 + i18n fallback 分支
        self.assertIn('setAttribute("placeholder"', body)
        self.assertIn('window.AIIA_I18N.t("page.feedbackPlaceholder")', body)

    def test_switch_task_calls_helper_from_cache(self) -> None:
        """switchTask cached 路径必须立即调 updateFeedbackPlaceholder。"""
        # 上下文锚点：cachedTask.predefined_options 那块之后必须有
        # updateFeedbackPlaceholder(cachedTask.feedback_placeholder)
        m = re.search(
            r"updateOptionsDisplay\(\s*cachedTask\.predefined_options[\s\S]*?\}",
            self.src,
        )
        self.assertIsNotNone(m)
        # 同一函数体内之后 1000 char 内必须出现 helper 调用
        idx = self.src.find(
            "updateFeedbackPlaceholder(cachedTask.feedback_placeholder)"
        )
        self.assertNotEqual(idx, -1, "cache 路径必须调 updateFeedbackPlaceholder")

    def test_load_task_details_calls_helper(self) -> None:
        """async loadTaskDetails 异步详情回来后也必须 sync placeholder。"""
        self.assertIn(
            "updateFeedbackPlaceholder(task.feedback_placeholder)",
            self.src,
            "loadTaskDetails 必须重新 sync placeholder",
        )


class TestPersistenceRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_task_module()

    def test_snapshot_includes_placeholder(self) -> None:
        src = TASK_QUEUE_PY.read_text(encoding="utf-8")
        # 持久化时序列化必须含 feedback_placeholder
        self.assertIn('"feedback_placeholder": task.feedback_placeholder', src)

    def test_restore_reads_placeholder_with_backward_compat(self) -> None:
        src = TASK_QUEUE_PY.read_text(encoding="utf-8")
        # restore 时 item.get 读取 + 兜底 None；clamp 同样到 200
        self.assertIn('item.get("feedback_placeholder")', src)
        self.assertIn("feedback_placeholder=restored_placeholder", src)


if __name__ == "__main__":
    unittest.main()
