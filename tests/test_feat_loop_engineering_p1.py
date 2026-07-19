"""Loop engineering P1+P2 契约测试（docs/loop-engineering-design-notes.zh-CN.md）。

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

P2（Web UI 展示面，静态断言模式跟随 test_feat_mining3_header_chip.py）：

7. **前端 helper**：updateLoopContext 定义 + 两个调用站点（任务切换
   cache 路径 + 异步详情路径，与 updateHeaderChip 同步）。
8. **HTML anchor**：#task-loop-context 及子元素 + data-i18n 标签。
9. **CSS**：.task-loop-context / .loop-chip / .task-tab-iter。
10. **tab 轮次徽标**：createTaskTab 渲染 iteration_label。
11. **i18n key**：5 个 loop key 在 en / zh-CN / zh-TW 三个 locale 全存在。

P4（VS Code webview 对齐，模式跟随 test_webview_task_fields_parity_r691.py）：

12. **webview helper**：updateLoopContext 定义 + updateUI 调用 +
    tab 轮次徽标渲染。
13. **webview HTML**：taskLoopContext 及子元素锚点（webview.ts）。
14. **webview CSS**：.task-loop-context / .loop-chip / .task-tab-iter。
15. **webview i18n**：ui.loop.* 5 key 在扩展三个 locale 全存在。

P3（完成轮次台账 —— metadata 保留策略）：

16. **台账捕获**：complete_task 记录 loop 成员轮次（verdict 截断、
    图片只记数量、无 prompt 大字段）；非 loop 任务零记录。
17. **核心语义**：cleanup 删除任务本体后台账仍可回看（P3 的存在意义）。
18. **有界性**：每 loop 最多 50 轮（丢最旧）；最多 20 个 loop
    （驱逐最久未更新）。
19. **loop 级属性**：objective / success_criteria 最后一个非空值胜出。
20. **持久化**：台账随快照 round-trip；旧快照缺 key → 空台账兼容；
    clear_all_tasks 全量重置。
21. **HTTP API**：GET /api/loops 返回台账 + live_tasks 投影。
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
# P2：Web UI 展示面（静态断言，模式跟随 test_feat_mining3_header_chip.py）
# ---------------------------------------------------------------------------

MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"

LOOP_I18N_KEYS = (
    "loopIdTitle",
    "loopPhaseTitle",
    "loopIterTitle",
    "loopObjectiveLabel",
    "loopCriteriaLabel",
    # Loop 视图（历史轮次折叠面板）
    "loopHistoryToggle",
    "loopHistoryEmpty",
    "loopHistoryError",
)


class TestFrontendLoopContext(unittest.TestCase):
    """P2-7/10：multi_task.js 的 helper 定义、调用站点、tab 徽标。"""

    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_helper_defined(self) -> None:
        self.assertIn("function updateLoopContext(task)", self.src)

    def test_switch_task_cache_path_calls_helper(self) -> None:
        self.assertIn("updateLoopContext(cachedTask)", self.src)

    def test_load_task_details_calls_helper(self) -> None:
        self.assertIn("updateLoopContext(task)", self.src)

    def test_helper_uses_textcontent_only(self) -> None:
        """XSS 边界：helper 主体禁止 innerHTML 赋值。"""
        start = self.src.index("function updateLoopContext(task)")
        end = self.src.index("\n}\n", start)
        body = self.src[start:end]
        self.assertNotIn("innerHTML", body)
        self.assertIn("textContent", body)

    def test_tab_iteration_badge_rendered(self) -> None:
        self.assertIn("task-tab-iter", self.src)
        self.assertIn("task.iteration_label", self.src)


class TestHtmlLoopAnchor(unittest.TestCase):
    """P2-8：模板锚点 + i18n 标签。"""

    src = WEB_UI_HTML.read_text(encoding="utf-8")

    def test_container_anchor(self) -> None:
        self.assertIn('id="task-loop-context"', self.src)

    def test_chip_anchors(self) -> None:
        for element_id in ("loop-chip-id", "loop-chip-phase", "loop-chip-iter"):
            self.assertIn(f'id="{element_id}"', self.src)

    def test_line_anchors(self) -> None:
        for element_id in (
            "loop-objective-line",
            "loop-objective-value",
            "loop-criteria-line",
            "loop-criteria-value",
        ):
            self.assertIn(f'id="{element_id}"', self.src)

    def test_i18n_attributes(self) -> None:
        self.assertIn('data-i18n="page.loopObjectiveLabel"', self.src)
        self.assertIn('data-i18n="page.loopCriteriaLabel"', self.src)
        self.assertIn('data-i18n-title="page.loopIdTitle"', self.src)


class TestCssLoopStyles(unittest.TestCase):
    """P2-9：CSS class 定义。"""

    src = MAIN_CSS.read_text(encoding="utf-8")

    def test_classes_defined(self) -> None:
        for cls in (
            ".task-loop-context",
            ".loop-context-chips",
            ".loop-chip",
            ".loop-context-line",
            ".loop-context-label",
            ".loop-context-value",
            ".task-tab-iter",
        ):
            self.assertIn(cls, self.src)


class TestLocaleLoopKeys(unittest.TestCase):
    """P2-11：三个 locale 都要有 5 个 loop key（parity 由 CI 脚本双保险）。"""

    def test_all_locales_have_loop_keys(self) -> None:
        for locale in ("en", "zh-CN", "zh-TW"):
            data = json.loads(
                (LOCALES_DIR / f"{locale}.json").read_text(encoding="utf-8")
            )
            page = data.get("page", {})
            for key in LOOP_I18N_KEYS:
                self.assertIn(key, page, f"{locale}.json 缺少 page.{key}")
                self.assertTrue(
                    isinstance(page[key], str) and page[key].strip(),
                    f"{locale}.json page.{key} 必须是非空字符串",
                )


# ---------------------------------------------------------------------------
# P4：VS Code webview 对齐（模式跟随 test_webview_task_fields_parity_r691.py）
# ---------------------------------------------------------------------------

VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
WEBVIEW_UI_JS = VSCODE_DIR / "webview-ui.js"
WEBVIEW_TS = VSCODE_DIR / "webview.ts"
WEBVIEW_CSS = VSCODE_DIR / "webview.css"

VSCODE_LOOP_I18N_KEYS = (
    "idTitle",
    "phaseTitle",
    "iterTitle",
    "objectiveLabel",
    "criteriaLabel",
    # Loop 视图（历史轮次折叠面板）
    "historyToggle",
    "historyEmpty",
    "historyError",
)


class TestWebviewLoopContext(unittest.TestCase):
    """P4-12：webview-ui.js 的 helper、updateUI 调用、tab 徽标。"""

    src = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    def test_helper_defined(self) -> None:
        self.assertIn("function updateLoopContext(task)", self.src)

    def test_update_ui_calls_helper(self) -> None:
        self.assertIn("updateLoopContext(config)", self.src)

    def test_helper_uses_textcontent_only(self) -> None:
        start = self.src.index("function updateLoopContext(task)")
        end = self.src.index("\n  }\n", start)
        body = self.src[start:end]
        self.assertNotIn("innerHTML", body)
        self.assertIn("textContent", body)

    def test_tab_iteration_badge_rendered(self) -> None:
        self.assertIn("task-tab-iter", self.src)
        self.assertIn("task.iteration_label", self.src)


class TestWebviewLoopAnchor(unittest.TestCase):
    """P4-13：webview.ts 模板锚点。"""

    src = WEBVIEW_TS.read_text(encoding="utf-8")

    def test_anchors_exist(self) -> None:
        for element_id in (
            "taskLoopContext",
            "loopChipId",
            "loopChipPhase",
            "loopChipIter",
            "loopObjectiveLine",
            "loopObjectiveValue",
            "loopCriteriaLine",
            "loopCriteriaValue",
        ):
            self.assertIn(f'id="{element_id}"', self.src)

    def test_i18n_attributes(self) -> None:
        self.assertIn('data-i18n="ui.loop.objectiveLabel"', self.src)
        self.assertIn('data-i18n="ui.loop.criteriaLabel"', self.src)
        self.assertIn('data-i18n-title="ui.loop.idTitle"', self.src)


class TestWebviewLoopCss(unittest.TestCase):
    """P4-14：webview.css class 定义。"""

    src = WEBVIEW_CSS.read_text(encoding="utf-8")

    def test_classes_defined(self) -> None:
        for cls in (
            ".task-loop-context",
            ".loop-context-chips",
            ".loop-chip",
            ".loop-context-line",
            ".loop-context-label",
            ".loop-context-value",
            ".task-tab-iter",
        ):
            self.assertIn(cls, self.src)


class TestWebviewLocaleLoopKeys(unittest.TestCase):
    """P4-15：扩展三个 locale 的 ui.loop.* 5 key。"""

    def test_all_locales_have_loop_namespace(self) -> None:
        for locale in ("en", "zh-CN", "zh-TW"):
            data = json.loads(
                (VSCODE_DIR / "locales" / f"{locale}.json").read_text(encoding="utf-8")
            )
            loop = data.get("ui", {}).get("loop", {})
            for key in VSCODE_LOOP_I18N_KEYS:
                self.assertIn(key, loop, f"vscode {locale}.json 缺少 ui.loop.{key}")
                self.assertTrue(
                    isinstance(loop[key], str) and loop[key].strip(),
                    f"vscode {locale}.json ui.loop.{key} 必须是非空字符串",
                )


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


class TestLoopHistoryView(unittest.TestCase):
    """Loop 视图（历史轮次折叠面板）：web + webview 双端静态契约。

    设计笔记 §3.3 的分组折叠初版：loop 任务的上下文条内提供「历史轮次」
    toggle，展开时拉取 GET /api/loops 渲染已完成轮次时间线。
    """

    web_js = MULTI_TASK_JS.read_text(encoding="utf-8")
    web_html = WEB_UI_HTML.read_text(encoding="utf-8")
    web_css = MAIN_CSS.read_text(encoding="utf-8")
    vs_js = WEBVIEW_UI_JS.read_text(encoding="utf-8")
    vs_ts = WEBVIEW_TS.read_text(encoding="utf-8")
    vs_css = WEBVIEW_CSS.read_text(encoding="utf-8")

    def test_web_helpers_defined(self) -> None:
        for symbol in (
            "function updateLoopHistoryToggle(loopId)",
            "function collapseLoopHistory()",
            "async function toggleLoopHistory()",
            "function buildLoopHistoryRow(round)",
        ):
            self.assertIn(symbol, self.web_js)

    def test_web_fetches_loops_endpoint(self) -> None:
        self.assertIn('"/api/loops"', self.web_js)

    def test_web_stale_render_guard(self) -> None:
        """await 期间任务切换 → 丢弃过期渲染（loop_id 一致性守卫）。"""
        self.assertIn("window.__aiiaCurrentLoopId !== loopId", self.web_js)

    def test_web_template_anchors(self) -> None:
        self.assertIn('id="loop-history-toggle"', self.web_html)
        self.assertIn('id="loop-history-list"', self.web_html)
        self.assertIn('data-i18n="page.loopHistoryToggle"', self.web_html)

    def test_web_css_classes(self) -> None:
        for cls in (
            ".loop-history-toggle",
            ".loop-history-list",
            ".loop-history-row",
            ".loop-history-verdict",
            ".loop-history-empty",
        ):
            self.assertIn(cls, self.web_css)

    def test_web_history_builder_uses_textcontent_only(self) -> None:
        start = self.web_js.index("function buildLoopHistoryRow(round)")
        end = self.web_js.index("\n}\n", start)
        body = self.web_js[start:end]
        self.assertNotIn("innerHTML", body)
        self.assertIn("textContent", body)

    def test_webview_helpers_defined(self) -> None:
        for symbol in (
            "function updateLoopHistoryToggle(loopId)",
            "function collapseLoopHistory()",
            "async function toggleLoopHistory()",
            "function buildLoopHistoryRow(round)",
        ):
            self.assertIn(symbol, self.vs_js)

    def test_webview_fetches_loops_endpoint(self) -> None:
        self.assertIn("SERVER_URL + '/api/loops'", self.vs_js)

    def test_webview_template_anchors(self) -> None:
        self.assertIn('id="loopHistoryToggle"', self.vs_ts)
        self.assertIn('id="loopHistoryList"', self.vs_ts)
        self.assertIn('data-i18n="ui.loop.historyToggle"', self.vs_ts)

    def test_webview_css_classes(self) -> None:
        for cls in (
            ".loop-history-toggle",
            ".loop-history-list",
            ".loop-history-row",
            ".loop-history-verdict",
        ):
            self.assertIn(cls, self.vs_css)


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
