"""mining-6 Track A — freeze countdown button (cycle-5 §3.6 derivative).

【背景】cycle-5 §3.6 close ``auto_resubmit: once`` as not-borrow，但
derivative idea 是：让用户在 web UI 单击 freeze 一个 task 的倒计时。
比 server-side once enforcement 干净 —— task 已支持 ``auto_resubmit_timeout
<= 0`` = 禁用语义，freeze 操作只是新增 endpoint + UI button。

【测试覆盖】
  - ``Task.freeze_deadline`` 单元行为 + 边界（completed / already-frozen）
  - ``TaskQueue.freeze_task_deadline`` facade（write lock + error code）
  - ``POST /api/tasks/<id>/freeze`` 路由（happy path / 404 / 400 / 409）
  - frontend ``updateFreezeCountdownButton`` + ``handleFreezeCountdownClick``
    helper 函数存在 + 关键代码路径有 i18n keys
  - HTML template ``countdown-freeze-btn`` 元素
  - CSS ``.countdown-freeze-btn`` 类 + light theme
  - i18n keys (en + zh-CN) 5 keys
  - watchdog label set 包含 ``freeze_task_deadline``
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
JS_PATH = SRC / "static" / "js" / "multi_task.js"
CSS_PATH = SRC / "static" / "css" / "main.css"
HTML_PATH = SRC / "templates" / "web_ui.html"
TASK_PY_PATH = SRC / "task_queue.py"
ROUTE_PY_PATH = SRC / "web_ui_routes" / "task.py"
EN_LOCALE = SRC / "static" / "locales" / "en.json"
ZH_LOCALE = SRC / "static" / "locales" / "zh-CN.json"


class TestTaskFreezeDeadlineUnit(unittest.TestCase):
    """Direct ``Task.freeze_deadline`` invocation — 独立于 TaskQueue."""

    def _make_task(self, timeout: int = 60, status: str = "active"):
        from ai_intervention_agent.task_queue import Task

        return Task(
            task_id="t-freeze-unit",
            prompt="freeze test",
            auto_resubmit_timeout=timeout,
            status=status,
        )

    def test_freeze_active_task_sets_timeout_to_zero(self) -> None:
        t = self._make_task(timeout=120)
        success, error_code = t.freeze_deadline()
        self.assertTrue(success)
        self.assertIsNone(error_code)
        self.assertEqual(t.auto_resubmit_timeout, 0)

    def test_freeze_already_frozen_returns_error(self) -> None:
        t = self._make_task(timeout=0)
        success, error_code = t.freeze_deadline()
        self.assertFalse(success)
        self.assertEqual(error_code, "already_frozen")

    def test_freeze_completed_task_returns_error(self) -> None:
        t = self._make_task(timeout=60, status="completed")
        success, error_code = t.freeze_deadline()
        self.assertFalse(success)
        self.assertEqual(error_code, "task_completed")

    def test_freeze_makes_is_expired_false(self) -> None:
        """frozen task 不应 expire（auto_resubmit_timeout <= 0 已禁用）."""
        t = self._make_task(timeout=60)
        t.freeze_deadline()
        self.assertFalse(t.is_expired())

    def test_freeze_makes_remaining_time_zero(self) -> None:
        t = self._make_task(timeout=60)
        t.freeze_deadline()
        self.assertEqual(t.get_remaining_time(), 0)


class TestTaskQueueFreezeFacade(unittest.TestCase):
    def _make_queue(self):
        from ai_intervention_agent.task_queue import Task, TaskQueue

        tq = TaskQueue()
        task = Task(
            task_id="t-freeze-facade",
            prompt="facade test",
            auto_resubmit_timeout=120,
        )
        tq._tasks[task.task_id] = task
        return tq, task

    def test_facade_freeze_returns_success_tuple(self) -> None:
        tq, task = self._make_queue()
        success, error_code, timeout_after = tq.freeze_task_deadline(task.task_id)
        self.assertTrue(success)
        self.assertIsNone(error_code)
        self.assertEqual(timeout_after, 0)
        self.assertEqual(task.auto_resubmit_timeout, 0)

    def test_facade_freeze_missing_task(self) -> None:
        tq, _ = self._make_queue()
        success, error_code, timeout_after = tq.freeze_task_deadline("does-not-exist")
        self.assertFalse(success)
        self.assertEqual(error_code, "task_not_found")
        self.assertEqual(timeout_after, 0)

    def test_facade_freeze_already_frozen(self) -> None:
        tq, task = self._make_queue()
        tq.freeze_task_deadline(task.task_id)
        success, error_code, _ = tq.freeze_task_deadline(task.task_id)
        self.assertFalse(success)
        self.assertEqual(error_code, "already_frozen")


class TestRouteContent(unittest.TestCase):
    """Text-level checks on the route source to avoid TaskQueue-singleton
    shared-state pollution (lesson from cr40 health-fix sweep #2)."""

    def setUp(self) -> None:
        self.src = ROUTE_PY_PATH.read_text(encoding="utf-8")

    def test_route_decorated_with_freeze_path(self) -> None:
        self.assertIn('"/api/tasks/<task_id>/freeze", methods=["POST"]', self.src)

    def test_route_calls_freeze_task_deadline_facade(self) -> None:
        self.assertIn("task_queue.freeze_task_deadline(", self.src)

    def test_route_handles_task_not_found_404(self) -> None:
        self.assertIn('"task_not_found"', self.src)
        self.assertIn(", 404", self.src)

    def test_route_handles_already_frozen_409(self) -> None:
        self.assertIn('"already_frozen"', self.src)
        self.assertIn("409", self.src)

    def test_route_returns_new_timeout_field(self) -> None:
        self.assertIn('"new_auto_resubmit_timeout"', self.src)

    def test_route_has_rate_limit(self) -> None:
        self.assertIn('@self.limiter.limit("10 per minute")', self.src)


class TestHtmlButton(unittest.TestCase):
    def setUp(self) -> None:
        self.html = HTML_PATH.read_text(encoding="utf-8")

    def test_freeze_button_id_present(self) -> None:
        self.assertIn('id="countdown-freeze-btn"', self.html)

    def test_freeze_button_class_and_hidden_default(self) -> None:
        self.assertIn('class="countdown-freeze-btn hidden"', self.html)

    def test_freeze_button_has_aria_attrs(self) -> None:
        self.assertIn(
            'data-i18n-aria-label="page.freezeCountdown.ariaLabel"', self.html
        )
        self.assertIn('data-i18n-title="page.freezeCountdown.title"', self.html)

    def test_freeze_button_default_disabled(self) -> None:
        # disabled attribute 在 hidden 状态下避免被键盘 tabbed-to
        idx = self.html.find('id="countdown-freeze-btn"')
        self.assertGreater(idx, 0)
        snippet = self.html[idx : idx + 600]
        self.assertIn("disabled", snippet)

    def test_freeze_label_uses_i18n(self) -> None:
        self.assertIn('data-i18n="page.freezeCountdown.label"', self.html)


class TestJsHelpers(unittest.TestCase):
    def setUp(self) -> None:
        self.js = JS_PATH.read_text(encoding="utf-8")

    def test_update_freeze_button_helper_defined(self) -> None:
        self.assertIn("function updateFreezeCountdownButton(task)", self.js)

    def test_handle_freeze_click_handler_defined(self) -> None:
        self.assertIn("function handleFreezeCountdownClick()", self.js)

    def test_handler_posts_to_freeze_endpoint(self) -> None:
        self.assertIn('"/api/tasks/" + encodeURIComponent(taskId) + "/freeze"', self.js)

    def test_helper_called_in_update_tasks_path(self) -> None:
        # confirm helper is called inside updateTasksList path (after extend
        # button update)
        self.assertIn("updateFreezeCountdownButton(_activeTask)", self.js)

    def test_helper_called_after_extend_success(self) -> None:
        """extend 成功路径之后 freeze button 也应 sync（task 仍 active
        timeout > 0）.

        ``task.extends_used = data.extends_used`` 是 extend handler 成功
        路径的唯一标识（失败路径只读 extends_used 不写 data.extends_used）。
        定位之后向下扫描 freeze sync 调用。
        """
        idx = self.js.find("task.extends_used = data.extends_used;")
        self.assertGreater(idx, 0, "extend success path identifier missing")
        snippet = self.js[idx : idx + 600]
        self.assertIn("updateFreezeCountdownButton(task)", snippet)

    def test_i18n_keys_resolved(self) -> None:
        for key in (
            "page.freezeCountdown.label",
            "page.freezeCountdown.title",
            "page.freezeCountdown.ariaLabel",
            "page.freezeCountdown.alreadyFrozen",
            "page.freezeCountdown.networkError",
        ):
            self.assertIn(f'"{key}"', self.js)

    def test_idempotent_binding_guard(self) -> None:
        self.assertIn("__aiiaFreezeBtnBound", self.js)


class TestCssClass(unittest.TestCase):
    def setUp(self) -> None:
        self.css = CSS_PATH.read_text(encoding="utf-8")

    def test_freeze_class_defined(self) -> None:
        self.assertIn(".countdown-freeze-btn {", self.css)

    def test_freeze_hidden_helper(self) -> None:
        self.assertIn(".countdown-freeze-btn.hidden {", self.css)

    def test_freeze_disabled_state(self) -> None:
        self.assertIn(".countdown-freeze-btn:disabled {", self.css)

    def test_freeze_light_theme_override(self) -> None:
        self.assertIn('[data-theme="light"] .countdown-freeze-btn {', self.css)

    def test_tick_zero_guard_keeps_task_alive_while_typing_r699(self) -> None:
        """R699：倒计时归零但用户仍在输入时，tick 不得触发自动提交。

        typing-hold（R689）只在 extend 配额内自动延长；配额耗尽后本守卫
        兜底——保持 timer 存活并跳过提交，直到用户停止输入。
        """
        js = JS_PATH.read_text(encoding="utf-8")
        idx = js.find("// 倒计时结束")
        self.assertGreater(idx, 0)
        snippet = js[idx : idx + 800]
        self.assertIn(
            "taskId === activeTaskId && isUserActivelyTyping()",
            snippet,
            "tick 归零分支必须带「输入中不提交」守卫（R699）",
        )

    def test_freeze_button_visually_retired_r699(self) -> None:
        """R699：+60s / 冻结按钮按用户决策下线可见入口（display:none）。

        typing-hold（R689）在用户输入时自动调用 extend 端点保证不中断，
        手动按钮不再需要；DOM 与 JS 逻辑保留（多端兼容 + 端点复用），
        仅视觉隐藏。本断言锁定「视觉下线」状态，防止按钮悄悄回归。
        """
        pattern = re.compile(
            r"\.countdown-extend-btn,\s*\n\.countdown-freeze-btn\s*\{[^}]*"
            r"display:\s*none\s*!important",
        )
        self.assertTrue(
            pattern.search(self.css),
            "R699 要求 .countdown-extend-btn / .countdown-freeze-btn "
            "以 display:none !important 下线可见入口",
        )


class TestI18nKeysExist(unittest.TestCase):
    EXPECTED_KEYS = {
        "label",
        "title",
        "ariaLabel",
        "alreadyFrozen",
        "networkError",
    }

    def _load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_en_locale_has_freeze_countdown_block(self) -> None:
        data = self._load(EN_LOCALE)
        self.assertIn("freezeCountdown", data.get("page", {}))
        block = data["page"]["freezeCountdown"]
        self.assertEqual(set(block.keys()), self.EXPECTED_KEYS)

    def test_zh_cn_locale_has_freeze_countdown_block(self) -> None:
        data = self._load(ZH_LOCALE)
        self.assertIn("freezeCountdown", data.get("page", {}))
        block = data["page"]["freezeCountdown"]
        self.assertEqual(set(block.keys()), self.EXPECTED_KEYS)

    def test_en_and_zh_values_distinct(self) -> None:
        en = self._load(EN_LOCALE)["page"]["freezeCountdown"]
        zh = self._load(ZH_LOCALE)["page"]["freezeCountdown"]
        for key in self.EXPECTED_KEYS:
            self.assertNotEqual(
                en[key],
                zh[key],
                f"en/zh-CN 对 freezeCountdown.{key} 翻译不应相同",
            )


class TestWatchdogLabel(unittest.TestCase):
    """新增的 ``freeze_task_deadline`` 必须出现在 watchdog label 期望集中
    （cr40 health-fix #3 lesson — extend_task_deadline 当年漏加导致破测）."""

    def test_label_in_expected_set(self) -> None:
        watchdog_test = REPO_ROOT / "tests" / "test_lock_watchdog_full_coverage_r52a.py"
        src = watchdog_test.read_text(encoding="utf-8")
        self.assertIn('"freeze_task_deadline": "freeze_task_deadline"', src)


if __name__ == "__main__":
    unittest.main()
