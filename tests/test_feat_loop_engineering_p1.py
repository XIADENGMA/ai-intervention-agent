"""Loop engineering 契约测试（docs/loop-engineering-design-notes.zh-CN.md）。

覆盖面：

P1（数据面）：

1. **Task 模型**：5 个可选字段存在、默认 None（旧客户端零破坏）。
2. **add_task normalize**：strip → 空归 None → 超长截断（与
   feedback_placeholder / header_label 同模式）；非 str 静默归 None。
3. **持久化 round-trip**：_persist 落盘 5 字段；_restore 回灌；
   **旧快照缺 key 时兼容**（与 R702 explicit 标记同一兼容模式）。
4. **HTTP API**：POST /api/tasks 透传；GET /api/tasks（列表）、
   GET /api/tasks/<id>（详情）、GET /api/tasks/export（导出）返回。
5. **/api/config**：active 任务分支返回 loop 上下文。
6. **MCP 工具**：interactive_feedback 签名含 5 个可选参数，且
   payload 透传代码存在（静态断言，不起真实 server）。

界面（R896 精简）：

7. **tab 轮次徽标**：Web 的 createTaskTab 与 VS Code webview 的 tab 渲染
   iteration_label（``.task-tab-iter``）——loop 字段如今留在界面上的唯一
   位置。标签栏下方的「循环信息卡片」（loop id / 阶段 / 轮次芯片、循环目标、
   完成标准、「历史轮次」折叠面板）连同它的 i18n 键、样式、脚本已在 R896
   整体移除，「它不再出现」由 test_loop_card_and_code_hover_gone_r896.py 守护。

P3（完成轮次台账 —— metadata 保留策略）：

8. **台账捕获**：complete_task 记录 loop 成员轮次（verdict 截断、
   图片只记数量、无 prompt 大字段）；非 loop 任务零记录。
9. **核心语义**：cleanup 删除任务本体后台账仍可回看（P3 的存在意义）。
10. **有界性**：每 loop 最多 50 轮（丢最旧）；最多 20 个 loop
    （驱逐最久未更新）。
11. **loop 级属性**：objective / success_criteria 最后一个非空值胜出。
12. **持久化**：台账随快照 round-trip；旧快照缺 key → 空台账兼容；
    clear_all_tasks 全量重置。
13. **HTTP API**：GET /api/loops 返回台账 + live_tasks 投影。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from ai_intervention_agent.task_constants import (
    LOOP_HISTORY_MAX_LOOPS,
    LOOP_HISTORY_MAX_ROUNDS,
    LOOP_ID_MAX_LENGTH,
    LOOP_LABEL_MAX_LENGTH,
    LOOP_TEXT_MAX_LENGTH,
    LOOP_VERDICT_MAX_LENGTH,
)
from ai_intervention_agent.task_queue import Task, TaskQueue

REPO_ROOT = Path(__file__).resolve().parent.parent

LOOP_FIELDS = (
    "loop_id",
    "loop_objective",
    "loop_phase",
    "success_criteria",
    "iteration_label",
)


class TestTaskModelLoopFields(unittest.TestCase):
    """Layer 1：Task 模型字段存在 + 默认 None。"""

    def test_fields_exist_with_none_default(self) -> None:
        task = Task(task_id="t1", prompt="p")
        for field in LOOP_FIELDS:
            self.assertIn(field, Task.model_fields)
            self.assertIsNone(getattr(task, field))

    def test_fields_accept_strings(self) -> None:
        task = Task(
            task_id="t1",
            prompt="p",
            loop_id="auth-refactor",
            loop_objective="migrate to PyJWT 2.x",
            loop_phase="verify",
            success_criteria="pytest green",
            iteration_label="iter-3",
        )
        self.assertEqual(task.loop_id, "auth-refactor")
        self.assertEqual(task.loop_objective, "migrate to PyJWT 2.x")
        self.assertEqual(task.loop_phase, "verify")
        self.assertEqual(task.success_criteria, "pytest green")
        self.assertEqual(task.iteration_label, "iter-3")


class TestAddTaskNormalization(unittest.TestCase):
    """Layer 2：add_task 的 strip / clamp / 非 str 归 None。"""

    def _fresh_queue(self) -> TaskQueue:
        return TaskQueue(persist_path=None)

    def test_strip_and_clamp(self) -> None:
        q = self._fresh_queue()
        ok = q.add_task(
            task_id="t1",
            prompt="p",
            loop_id="  " + "x" * (LOOP_ID_MAX_LENGTH + 10) + "  ",
            loop_objective=" o " + "y" * LOOP_TEXT_MAX_LENGTH,
            loop_phase="  verify  ",
            success_criteria="z" * (LOOP_TEXT_MAX_LENGTH + 1),
            iteration_label="  iter-1  ",
        )
        self.assertTrue(ok)
        task = q.get_task("t1")
        assert task is not None
        self.assertEqual(task.loop_id, "x" * LOOP_ID_MAX_LENGTH)
        self.assertEqual(len(task.loop_objective or ""), LOOP_TEXT_MAX_LENGTH)
        self.assertEqual(task.loop_phase, "verify")
        self.assertEqual(len(task.success_criteria or ""), LOOP_TEXT_MAX_LENGTH)
        self.assertEqual(task.iteration_label, "iter-1")
        self.assertLessEqual(len(task.loop_phase or ""), LOOP_LABEL_MAX_LENGTH)

    def test_empty_and_non_str_become_none(self) -> None:
        from typing import Any, cast

        q = self._fresh_queue()
        # cast(Any, ...) 显式让 ty 接受非 str 输入——运行时契约是
        # _normalize_optional_text 把非 str 静默归 None
        ok = q.add_task(
            task_id="t2",
            prompt="p",
            loop_id="   ",
            loop_objective=cast(Any, 12345),
            loop_phase=None,
            success_criteria="",
            iteration_label=cast(Any, ["not", "str"]),
        )
        self.assertTrue(ok)
        task = q.get_task("t2")
        assert task is not None
        for field in LOOP_FIELDS:
            self.assertIsNone(getattr(task, field), field)

    def test_omitted_defaults_none(self) -> None:
        """旧调用方（不传 loop 参数）行为逐字节不变。"""
        q = self._fresh_queue()
        self.assertTrue(q.add_task(task_id="t3", prompt="p"))
        task = q.get_task("t3")
        assert task is not None
        for field in LOOP_FIELDS:
            self.assertIsNone(getattr(task, field), field)


class TestPersistRestoreRoundTrip(unittest.TestCase):
    """Layer 3：持久化 round-trip + 旧快照兼容。"""

    def test_round_trip(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            persist = Path(td) / "tasks.json"
            q1 = TaskQueue(persist_path=str(persist))
            q1.add_task(
                task_id="t1",
                prompt="p",
                loop_id="loop-a",
                loop_objective="objective",
                loop_phase="implement",
                success_criteria="criteria",
                iteration_label="iter-2",
            )
            self.assertTrue(persist.exists())
            snapshot = json.loads(persist.read_text(encoding="utf-8"))
            entry = snapshot["tasks"][0]
            for field in LOOP_FIELDS:
                self.assertIn(field, entry)

            q2 = TaskQueue(persist_path=str(persist))
            restored = q2.get_task("t1")
            assert restored is not None
            self.assertEqual(restored.loop_id, "loop-a")
            self.assertEqual(restored.loop_objective, "objective")
            self.assertEqual(restored.loop_phase, "implement")
            self.assertEqual(restored.success_criteria, "criteria")
            self.assertEqual(restored.iteration_label, "iter-2")

    def test_legacy_snapshot_without_loop_keys(self) -> None:
        """旧快照（无 loop key）恢复后字段全 None，不抛错。"""
        import tempfile
        from datetime import UTC, datetime

        with tempfile.TemporaryDirectory() as td:
            persist = Path(td) / "tasks.json"
            legacy = {
                "version": 1,
                "active_task_id": "t-legacy",
                "saved_at": datetime.now(UTC).isoformat(),
                "tasks": [
                    {
                        "task_id": "t-legacy",
                        "prompt": "legacy prompt",
                        "predefined_options": None,
                        "auto_resubmit_timeout": 240,
                        "created_at": datetime.now(UTC).isoformat(),
                        "status": "pending",
                    }
                ],
            }
            persist.write_text(json.dumps(legacy), encoding="utf-8")
            q = TaskQueue(persist_path=str(persist))
            task = q.get_task("t-legacy")
            assert task is not None
            for field in LOOP_FIELDS:
                self.assertIsNone(getattr(task, field), field)


class TestHttpApiPassthrough(unittest.TestCase):
    """Layer 4：POST 透传 + 3 个 GET 返回（Flask test client）。

    跟随 R125 export 测试的既定模式：真实 TaskQueue 单例 + 每个测试
    前 ``clear_all_tasks()``，不 patch。
    """

    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="loop p1 base", task_id="loop-p1-base", port=19620
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def setUp(self) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        get_task_queue().clear_all_tasks()

    @classmethod
    def tearDownClass(cls) -> None:
        # 不给共享单例（真实 persist 路径）留下任务/台账残留
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        get_task_queue().clear_all_tasks()

    def test_post_get_config_export_round_trip(self) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        client = self._client
        queue = get_task_queue()
        payload = {
            "task_id": "loop-task-1",
            "prompt": "round 3 evidence",
            "loop_id": "auth-refactor",
            "loop_objective": "migrate auth to PyJWT 2.x",
            "loop_phase": "verify",
            "success_criteria": "pytest all green",
            "iteration_label": "iter-3",
        }
        resp = client.post("/api/tasks", json=payload)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))

        stored = queue.get_task("loop-task-1")
        assert stored is not None
        self.assertEqual(stored.loop_id, "auth-refactor")

        # GET /api/tasks（列表）
        listing = client.get("/api/tasks").get_json()
        task_row = listing["tasks"][0]
        for field in LOOP_FIELDS:
            self.assertIn(field, task_row)
        self.assertEqual(task_row["loop_id"], "auth-refactor")
        self.assertEqual(task_row["iteration_label"], "iter-3")

        # GET /api/tasks/<id>（详情）
        detail = client.get("/api/tasks/loop-task-1").get_json()
        for field in LOOP_FIELDS:
            self.assertIn(field, detail["task"])
        self.assertEqual(detail["task"]["loop_phase"], "verify")

        # GET /api/config（active 任务分支）
        config = client.get("/api/config").get_json()
        for field in LOOP_FIELDS:
            self.assertIn(field, config)
        self.assertEqual(config["loop_objective"], "migrate auth to PyJWT 2.x")

        # GET /api/tasks/export（JSON 导出）
        export = client.get("/api/tasks/export?format=json")
        self.assertEqual(export.status_code, 200)
        exported = json.loads(export.get_data(as_text=True))
        exported_task = exported["tasks"][0]
        for field in LOOP_FIELDS:
            self.assertIn(field, exported_task)
        self.assertEqual(exported_task["success_criteria"], "pytest all green")

    def test_post_without_loop_fields_keeps_none(self) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        client = self._client
        resp = client.post(
            "/api/tasks", json={"task_id": "plain-1", "prompt": "no loop"}
        )
        self.assertEqual(resp.status_code, 200)
        stored = get_task_queue().get_task("plain-1")
        assert stored is not None
        for field in LOOP_FIELDS:
            self.assertIsNone(getattr(stored, field), field)


class TestMcpToolSurface(unittest.TestCase):
    """Layer 5：interactive_feedback 签名 + payload 透传（静态断言）。"""

    def test_tool_signature_has_loop_params(self) -> None:
        import inspect

        from ai_intervention_agent.server_feedback import interactive_feedback

        params = set(inspect.signature(interactive_feedback).parameters)
        for field in LOOP_FIELDS:
            self.assertIn(field, params)

    def test_payload_passthrough_source(self) -> None:
        src = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "server_feedback.py"
        ).read_text(encoding="utf-8")
        for field in LOOP_FIELDS:
            self.assertIn(f'"{field}": {field}', src)


# ---------------------------------------------------------------------------
# 界面：tab 上的轮次徽标（标签栏下方的循环信息卡片已在 R896 移除）
# ---------------------------------------------------------------------------

MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
WEBVIEW_UI_JS = VSCODE_DIR / "webview-ui.js"
WEBVIEW_CSS = VSCODE_DIR / "webview.css"


class TestTabIterationBadge(unittest.TestCase):
    """tab 上的 ``iteration_label`` 徽标：Web 与 VS Code 各一份，仍然存在。"""

    def test_web_tab_renders_the_iteration_label(self) -> None:
        src = MULTI_TASK_JS.read_text(encoding="utf-8")
        self.assertIn("task-tab-iter", src)
        self.assertIn("task.iteration_label", src)

    def test_web_badge_style_defined(self) -> None:
        self.assertIn(".task-tab-iter", MAIN_CSS.read_text(encoding="utf-8"))

    def test_webview_tab_renders_the_iteration_label(self) -> None:
        src = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        self.assertIn("task-tab-iter", src)
        self.assertIn("task.iteration_label", src)

    def test_webview_badge_style_defined(self) -> None:
        self.assertIn(".task-tab-iter", WEBVIEW_CSS.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# P3：完成轮次台账（metadata 保留策略）
# ---------------------------------------------------------------------------


def _result(
    text: str = "ok", options: list[str] | None = None, images: int = 0
) -> dict[str, Any]:
    return {
        "user_input": text,
        "selected_options": options or [],
        "images": [{"data": "x" * 10}] * images,
    }


class TestLoopLedgerCapture(unittest.TestCase):
    """P3-16/17/19：台账捕获、cleanup 后可回看、loop 级属性语义。"""

    def setUp(self) -> None:
        self.q = TaskQueue(persist_path=None)
        self.addCleanup(self.q.stop_cleanup)

    def test_completed_loop_round_recorded_with_compact_verdict(self) -> None:
        self.q.add_task(
            task_id="r1",
            prompt="p" * 5000,  # prompt 大字段绝不进台账
            loop_id="lp",
            loop_objective="obj",
            loop_phase="verify",
            success_criteria="crit",
            iteration_label="iter-1",
            header_label="Auth",
        )
        long_text = "v" * (LOOP_VERDICT_MAX_LENGTH + 50)
        self.q.complete_task("r1", _result(long_text, ["approve"], images=3))

        loops = self.q.get_loops_snapshot()
        self.assertEqual(len(loops), 1)
        loop = loops[0]
        self.assertEqual(loop["loop_id"], "lp")
        self.assertEqual(loop["objective"], "obj")
        self.assertEqual(loop["success_criteria"], "crit")
        self.assertEqual(len(loop["rounds"]), 1)
        entry = loop["rounds"][0]
        self.assertEqual(entry["task_id"], "r1")
        self.assertEqual(entry["iteration_label"], "iter-1")
        self.assertEqual(entry["loop_phase"], "verify")
        self.assertEqual(entry["header_label"], "Auth")
        verdict = entry["verdict"]
        self.assertEqual(len(verdict["user_input"]), LOOP_VERDICT_MAX_LENGTH)
        self.assertEqual(verdict["selected_options"], ["approve"])
        self.assertEqual(verdict["image_count"], 3)
        # 台账条目绝不携带 prompt / base64 图片
        self.assertNotIn("prompt", entry)
        self.assertNotIn("images", verdict)

    def test_non_loop_task_records_nothing(self) -> None:
        self.q.add_task(task_id="plain", prompt="p")
        self.q.complete_task("plain", _result())
        self.assertEqual(self.q.get_loops_snapshot(), [])

    def test_double_complete_records_single_round(self) -> None:
        """completed 任务在 10s 清理窗口内被再次 complete（用户提交与
        自动重提并发）时，台账只保留首次轮次，不产生重复条目。"""
        self.q.add_task(task_id="r1", prompt="p", loop_id="lp")
        self.q.complete_task("r1", _result("first verdict"))
        self.q.complete_task("r1", _result("second verdict"))

        loop = self.q.get_loops_snapshot()[0]
        self.assertEqual(len(loop["rounds"]), 1)
        self.assertEqual(loop["rounds"][0]["verdict"]["user_input"], "first verdict")

    def test_ledger_survives_cleanup(self) -> None:
        """P3 核心：任务本体被清理后历史轮次仍可回看。"""
        self.q.add_task(task_id="r1", prompt="p", loop_id="lp")
        self.q.complete_task("r1", _result("round 1 verdict"))
        removed = self.q.cleanup_completed_tasks(age_seconds=0)
        self.assertEqual(removed, 1)
        self.assertIsNone(self.q.get_task("r1"))

        loops = self.q.get_loops_snapshot()
        self.assertEqual(len(loops), 1)
        self.assertEqual(
            loops[0]["rounds"][0]["verdict"]["user_input"], "round 1 verdict"
        )
        self.assertEqual(loops[0]["live_tasks"], [])

    def test_objective_criteria_last_non_empty_wins(self) -> None:
        self.q.add_task(task_id="r1", prompt="p", loop_id="lp", loop_objective="obj-v1")
        self.q.complete_task("r1", _result())
        # 第二轮省略 objective → 保留旧值；显式更新 criteria → 跟进
        self.q.add_task(
            task_id="r2", prompt="p", loop_id="lp", success_criteria="crit-v2"
        )
        self.q.complete_task("r2", _result())

        loop = self.q.get_loops_snapshot()[0]
        self.assertEqual(loop["objective"], "obj-v1")
        self.assertEqual(loop["success_criteria"], "crit-v2")
        self.assertEqual(len(loop["rounds"]), 2)

    def test_live_tasks_projection(self) -> None:
        """进行中的轮次出现在 live_tasks（首轮未完成也能看到 loop）。"""
        self.q.add_task(
            task_id="r1",
            prompt="p",
            loop_id="lp",
            loop_objective="obj",
            iteration_label="iter-1",
        )
        loops = self.q.get_loops_snapshot()
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]["rounds"], [])
        self.assertEqual(loops[0]["objective"], "obj")
        self.assertEqual(len(loops[0]["live_tasks"]), 1)
        self.assertEqual(loops[0]["live_tasks"][0]["task_id"], "r1")
        self.assertEqual(loops[0]["live_tasks"][0]["iteration_label"], "iter-1")


class TestLoopLedgerBounds(unittest.TestCase):
    """P3-18：rounds / loops 双重有界。"""

    def setUp(self) -> None:
        self.q = TaskQueue(max_tasks=200, persist_path=None)
        self.addCleanup(self.q.stop_cleanup)

    def test_rounds_bounded_keep_newest(self) -> None:
        for i in range(LOOP_HISTORY_MAX_ROUNDS + 5):
            tid = f"r{i}"
            self.q.add_task(
                task_id=tid, prompt="p", loop_id="lp", iteration_label=f"iter-{i}"
            )
            self.q.complete_task(tid, _result(f"verdict-{i}"))
            self.q.cleanup_completed_tasks(age_seconds=0)

        loop = self.q.get_loops_snapshot()[0]
        rounds = loop["rounds"]
        self.assertEqual(len(rounds), LOOP_HISTORY_MAX_ROUNDS)
        # 丢最旧：第一条应是 iter-5，最后一条是 iter-54
        self.assertEqual(rounds[0]["iteration_label"], "iter-5")
        self.assertEqual(
            rounds[-1]["iteration_label"],
            f"iter-{LOOP_HISTORY_MAX_ROUNDS + 4}",
        )

    def test_loops_bounded_evict_stalest(self) -> None:
        for i in range(LOOP_HISTORY_MAX_LOOPS + 3):
            tid = f"t{i}"
            self.q.add_task(task_id=tid, prompt="p", loop_id=f"lp-{i}")
            self.q.complete_task(tid, _result())
            self.q.cleanup_completed_tasks(age_seconds=0)

        loops = self.q.get_loops_snapshot()
        self.assertEqual(len(loops), LOOP_HISTORY_MAX_LOOPS)
        ids = {loop["loop_id"] for loop in loops}
        # 最早的 3 个被驱逐
        for evicted in ("lp-0", "lp-1", "lp-2"):
            self.assertNotIn(evicted, ids)
        self.assertIn(f"lp-{LOOP_HISTORY_MAX_LOOPS + 2}", ids)

    def test_snapshot_most_recent_first(self) -> None:
        for i in range(3):
            tid = f"t{i}"
            self.q.add_task(task_id=tid, prompt="p", loop_id=f"lp-{i}")
            self.q.complete_task(tid, _result())
        loops = self.q.get_loops_snapshot()
        self.assertEqual([lp["loop_id"] for lp in loops], ["lp-2", "lp-1", "lp-0"])


class TestLoopLedgerPersistence(unittest.TestCase):
    """P3-20：持久化 round-trip + 旧快照兼容 + clear_all_tasks 重置。"""

    def test_round_trip_across_restart(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            persist = Path(td) / "tasks.json"
            q1 = TaskQueue(persist_path=str(persist))
            try:
                q1.add_task(task_id="r1", prompt="p", loop_id="lp")
                q1.complete_task("r1", _result("verdict-1"))
                q1.cleanup_completed_tasks(age_seconds=0)
            finally:
                q1.stop_cleanup()

            # 任务本体已清理，但 loop_history 让文件保留
            self.assertTrue(persist.exists())
            snapshot = json.loads(persist.read_text(encoding="utf-8"))
            self.assertIn("loop_history", snapshot)
            self.assertIn("lp", snapshot["loop_history"])

            q2 = TaskQueue(persist_path=str(persist))
            try:
                loops = q2.get_loops_snapshot()
                self.assertEqual(len(loops), 1)
                self.assertEqual(
                    loops[0]["rounds"][0]["verdict"]["user_input"], "verdict-1"
                )
            finally:
                q2.stop_cleanup()

    def test_legacy_snapshot_without_loop_history(self) -> None:
        import tempfile
        from datetime import UTC, datetime

        with tempfile.TemporaryDirectory() as td:
            persist = Path(td) / "tasks.json"
            legacy = {
                "version": 1,
                "active_task_id": "t1",
                "saved_at": datetime.now(UTC).isoformat(),
                "tasks": [
                    {
                        "task_id": "t1",
                        "prompt": "legacy",
                        "created_at": datetime.now(UTC).isoformat(),
                        "status": "pending",
                    }
                ],
            }
            persist.write_text(json.dumps(legacy), encoding="utf-8")
            q = TaskQueue(persist_path=str(persist))
            try:
                self.assertIsNotNone(q.get_task("t1"))
                self.assertEqual(q.get_loops_snapshot(), [])
            finally:
                q.stop_cleanup()

    def test_clear_all_tasks_resets_ledger(self) -> None:
        q = TaskQueue(persist_path=None)
        try:
            q.add_task(task_id="r1", prompt="p", loop_id="lp")
            q.complete_task("r1", _result())
            self.assertEqual(len(q.get_loops_snapshot()), 1)
            q.clear_all_tasks()
            self.assertEqual(q.get_loops_snapshot(), [])
        finally:
            q.stop_cleanup()


class TestLoopsHttpApi(unittest.TestCase):
    """P3-21：GET /api/loops 契约（真实 TaskQueue 单例，模式同 Layer 4）。"""

    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="loop p3 base", task_id="loop-p3-base", port=19621
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def setUp(self) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        get_task_queue().clear_all_tasks()

    @classmethod
    def tearDownClass(cls) -> None:
        # 台账跨重启持久化，测试残留会漂进开发者的真实 tasks.json——
        # 类级兜底清一次（每个测试的 setUp 已保证独立性）
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        get_task_queue().clear_all_tasks()

    def test_endpoint_returns_ledger_and_live_tasks(self) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        queue = get_task_queue()
        # 一轮已完成 + 一轮进行中
        queue.add_task(
            task_id="lr1",
            prompt="p",
            loop_id="api-loop",
            loop_objective="obj",
            iteration_label="iter-1",
        )
        queue.complete_task("lr1", _result("approve it", ["approve"]))
        queue.cleanup_completed_tasks(age_seconds=0)
        queue.add_task(
            task_id="lr2", prompt="p", loop_id="api-loop", iteration_label="iter-2"
        )

        resp = self._client.get("/api/loops")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("server_time", data)
        self.assertEqual(len(data["loops"]), 1)
        loop = data["loops"][0]
        self.assertEqual(loop["loop_id"], "api-loop")
        self.assertEqual(loop["objective"], "obj")
        self.assertEqual(len(loop["rounds"]), 1)
        self.assertEqual(loop["rounds"][0]["verdict"]["selected_options"], ["approve"])
        self.assertEqual(len(loop["live_tasks"]), 1)
        self.assertEqual(loop["live_tasks"][0]["task_id"], "lr2")

    def test_empty_state_returns_empty_list(self) -> None:
        resp = self._client.get("/api/loops")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["loops"], [])


if __name__ == "__main__":
    unittest.main()
