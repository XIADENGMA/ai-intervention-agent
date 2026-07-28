"""mining-cycle-3 §2.1 borrow #2 (gemini-cli ``ask_user.yesno``)
回归测试。

设计回顾（TODO#41 重设计后）：``question_type='yesno'`` 让前端在
textarea 上方渲染 1 行 Yes/No 2-button。点击只登记"选中态"（再点
取消、点另一按钮切换），textarea 保持可见供补充说明（可选），用户
点「提交反馈」时发送 ``"yes"`` / ``"no"``（有补充时
``"yes\\n\\n<补充>"``）。

测试范围：
1. ``Task`` model 字段（默认 None；接受 "yesno"）
2. ``add_task`` 白名单 normalization（"yesno" / 大小写 / 未知值
   静默 None）
3. ``server_feedback`` MCP schema 新参数
4. POST /api/tasks 路由接收 + GET 返回
5. 前端 ``updateYesnoButtonGroup`` helper + 选中态登记/合并提交链路
6. CSS rules + i18n keys
7. 持久化 round-trip
"""

from __future__ import annotations

import json
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
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
EN_JSON = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
ZH_CN_JSON = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)


def _import_task_module():
    import importlib

    return importlib.import_module("ai_intervention_agent.task_queue")


class TestTaskModelField(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_task_module()

    def test_field_defaults_to_none(self) -> None:
        Task = self.mod.Task
        t = Task(task_id="t1", prompt="hi")
        self.assertTrue(hasattr(t, "question_type"))
        self.assertIsNone(t.question_type)

    def test_field_accepts_yesno(self) -> None:
        Task = self.mod.Task
        t = Task(task_id="t2", prompt="hi", question_type="yesno")
        self.assertEqual(t.question_type, "yesno")


class TestAddTaskNormalization(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_task_module()
        self.q = self.mod.TaskQueue(persist_path=None)

    def test_yesno_accepted(self) -> None:
        ok = self.q.add_task(task_id="t-y", prompt="ok?", question_type="yesno")
        self.assertTrue(ok)
        t = self.q.get_task("t-y")
        assert t is not None
        self.assertEqual(t.question_type, "yesno")

    def test_unknown_type_silently_none(self) -> None:
        """未知 type（"rating"/"choice"/任意字符串）静默归 None，向前兼容。"""
        for bad in ("rating", "choice", "YESNO", "Yes", "yes-no", "boolean"):
            ok = self.q.add_task(task_id=f"t-bad-{bad}", prompt="hi", question_type=bad)
            self.assertTrue(ok)
            t = self.q.get_task(f"t-bad-{bad}")
            assert t is not None
            self.assertIsNone(t.question_type, f"unknown type {bad!r} 应归 None")

    def test_none_omitted_defaults_to_none(self) -> None:
        ok = self.q.add_task(task_id="t-omit", prompt="hi")
        self.assertTrue(ok)
        t = self.q.get_task("t-omit")
        assert t is not None
        self.assertIsNone(t.question_type)

    def test_whitespace_yesno_normalized(self) -> None:
        """``"  yesno  "`` strip 后等价 yesno。"""
        ok = self.q.add_task(task_id="t-ws", prompt="hi", question_type="  yesno  ")
        self.assertTrue(ok)
        t = self.q.get_task("t-ws")
        assert t is not None
        self.assertEqual(t.question_type, "yesno")


class TestMcpToolSchema(unittest.TestCase):
    src = SERVER_FEEDBACK_PY.read_text(encoding="utf-8")

    def test_question_type_field(self) -> None:
        self.assertRegex(
            self.src,
            r"question_type:\s*str\s*\|\s*None\s*=\s*Field\(",
            "interactive_feedback 必须 expose question_type 参数",
        )

    def test_description_explains_yesno(self) -> None:
        self.assertIn("yesno", self.src)
        self.assertIn("Yes/No button", self.src)
        self.assertIn("mining-cycle-3", self.src)

    def test_post_includes_question_type(self) -> None:
        self.assertIn('"question_type": question_type', self.src)


class TestRoute(unittest.TestCase):
    src = TASK_ROUTES_PY.read_text(encoding="utf-8")

    def test_post_accepts_question_type(self) -> None:
        self.assertIn('data.get("question_type")', self.src)

    def test_post_passes_to_add_task(self) -> None:
        self.assertIn("question_type=question_type", self.src)

    def test_list_get_returns_question_type(self) -> None:
        self.assertRegex(self.src, r'"question_type":\s*task\.question_type')

    def test_detail_get_returns_question_type(self) -> None:
        count = self.src.count('"question_type": task.question_type')
        self.assertGreaterEqual(
            count, 2, "list + detail + persistence-snapshot 都该返回 question_type"
        )


class TestFrontend(unittest.TestCase):
    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_helper_defined(self) -> None:
        self.assertRegex(
            self.src,
            r"function\s+updateYesnoButtonGroup\(questionType\)\s*\{",
        )

    def test_helper_uses_i18n_with_fallback(self) -> None:
        m = re.search(
            r"function\s+updateYesnoButtonGroup\(questionType\)\s*\{([\s\S]*?)\n\}\n",
            self.src,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(1)
        # helper 把 ``window.AIIA_I18N.t`` bind 到本地 ``t``，再调
        # ``t("page.yesnoYes")`` —— 验证 i18n key 字面值出现
        self.assertIn('"page.yesnoYes"', body)
        self.assertIn('"page.yesnoNo"', body)
        # 英文 fallback：i18n 失败仍渲染
        self.assertIn('|| "Yes"', body)
        self.assertIn('|| "No"', body)

    def test_helper_keeps_textarea_visible_on_yesno(self) -> None:
        """TODO#41 关键 invariant：yesno 模式 textarea **保持可见**
        （供补充说明），不允许出现 display="none" 隐藏路径。"""
        m = re.search(
            r"function\s+updateYesnoButtonGroup\(questionType\)\s*\{([\s\S]*?)\n\}\n",
            self.src,
        )
        assert m is not None
        body = m.group(1)
        self.assertNotIn('feedbackTextarea.style.display = "none"', body)
        self.assertIn('feedbackTextarea.style.display = ""', body)

    def test_helper_sets_supplement_placeholder(self) -> None:
        """yesno 模式把默认占位符换成"可补充说明"提示（仅当任务未
        提供自定义 feedback_placeholder 时）。"""
        m = re.search(
            r"function\s+updateYesnoButtonGroup\(questionType\)\s*\{([\s\S]*?)\n\}\n",
            self.src,
        )
        assert m is not None
        body = m.group(1)
        self.assertIn('"page.yesnoSupplementPlaceholder"', body)

    def test_click_registers_selection_instead_of_submitting(self) -> None:
        """TODO#41：Yes/No 点击只登记选择（toggleYesnoSelection），
        不得直接触发表单提交。"""
        m = re.search(
            r"function\s+updateYesnoButtonGroup\(questionType\)\s*\{([\s\S]*?)\n\}\n",
            self.src,
        )
        assert m is not None
        body = m.group(1)
        self.assertIn('toggleYesnoSelection("yes")', body)
        self.assertIn('toggleYesnoSelection("no")', body)
        # 旧"一击直发"路径必须移除
        self.assertNotIn("requestSubmit", body)
        self.assertNotIn('_submit("yes")', body)

    def test_toggle_and_sync_helpers_defined(self) -> None:
        self.assertRegex(self.src, r"function\s+toggleYesnoSelection\(value\)\s*\{")
        self.assertRegex(self.src, r"function\s+syncYesnoSelectedStyles\(\)\s*\{")

    def test_toggle_supports_unselect_and_switch(self) -> None:
        """再点同一按钮取消（delete）、点另一按钮切换（赋值）。"""
        m = re.search(
            r"function\s+toggleYesnoSelection\(value\)\s*\{([\s\S]*?)\n\}\n",
            self.src,
        )
        assert m is not None
        body = m.group(1)
        self.assertIn("delete taskYesnoSelections[taskId]", body)
        self.assertIn("taskYesnoSelections[taskId] = value", body)

    def test_selected_state_uses_aria_pressed(self) -> None:
        """选中态必须同步 aria-pressed（toggle button a11y 语义）。"""
        self.assertIn('setAttribute("aria-pressed"', self.src)

    def test_global_getter_and_clear_exposed(self) -> None:
        """app.js 依赖的两个全局桥接函数必须暴露在 window 上。"""
        self.assertIn("window.getActiveYesnoSelection = function", self.src)
        self.assertIn("window.clearYesnoSelection = function", self.src)

    def test_task_state_registered_and_cleaned(self) -> None:
        """任务级选中态 map 注册 + 任务关闭/提交成功两条清理路径。"""
        self.assertIn("window.taskYesnoSelections", self.src)
        self.assertRegex(
            self.src,
            r"function\s+clearTaskLocalState[\s\S]{0,900}"
            r"delete taskYesnoSelections\[normalizedTaskId\]",
        )

    def test_auto_submit_merges_yesno_selection(self) -> None:
        """倒计时归零自动提交时，已点选未提交的 yes/no 不能丢。"""
        m = re.search(
            r"async function\s+autoSubmitTask\(taskId\)\s*\{([\s\S]*?)\n\}\n",
            self.src,
        )
        assert m is not None
        body = m.group(1)
        self.assertIn("yesnoSelection", body)
        self.assertIn("combinedText", body)

    def test_switch_task_calls_helper(self) -> None:
        self.assertIn(
            "updateYesnoButtonGroup(cachedTask.question_type)",
            self.src,
            "switchTask cache 路径必须调 updateYesnoButtonGroup",
        )

    def test_load_task_details_calls_helper(self) -> None:
        self.assertIn("updateYesnoButtonGroup(task.question_type)", self.src)


class TestCss(unittest.TestCase):
    src = MAIN_CSS.read_text(encoding="utf-8")

    def test_button_group_class(self) -> None:
        for cls in (
            ".yesno-button-group",
            ".yesno-btn",
        ):
            self.assertIn(cls, self.src, f"main.css 必须定义 {cls}")

    def test_a11y_touch_target_44px(self) -> None:
        """a11y: WCAG 推荐 button 最小 44x44 px touch target。"""
        m = re.search(r"\.yesno-btn\s*\{([\s\S]*?)\}", self.src)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertIn("44px", m.group(1))

    def test_selected_state_rules(self) -> None:
        """TODO#41：选中态高亮（深色基础 + 浅色主题覆盖两套都要有）。"""
        self.assertIn(".btn.yesno-btn.selected", self.src)
        self.assertIn('[data-theme="light"] .btn.yesno-btn.selected', self.src)


class TestAppJsSubmitMerge(unittest.TestCase):
    """TODO#41：app.js 手动提交链路合并 yes/no 选择。"""

    src = (
        REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")

    def test_submit_reads_selection(self) -> None:
        self.assertIn("window.getActiveYesnoSelection", self.src)

    def test_submit_prefixes_literal(self) -> None:
        """合并格式：选择在前，空行分隔补充说明。"""
        self.assertIn("${yesnoSelection}\\n\\n${feedbackText}", self.src)

    def test_success_cleanup_clears_selection(self) -> None:
        self.assertIn("window.clearYesnoSelection", self.src)


class TestI18nKeys(unittest.TestCase):
    def test_en_has_yes_no(self) -> None:
        data = json.loads(EN_JSON.read_text(encoding="utf-8"))
        page = data.get("page") or {}
        self.assertEqual(page.get("yesnoYes"), "Yes")
        self.assertEqual(page.get("yesnoNo"), "No")

    def test_zh_cn_has_yes_no_translated(self) -> None:
        data = json.loads(ZH_CN_JSON.read_text(encoding="utf-8"))
        page = data.get("page") or {}
        self.assertEqual(page.get("yesnoYes"), "是")
        self.assertEqual(page.get("yesnoNo"), "否")

    def test_supplement_placeholder_keys(self) -> None:
        """TODO#41：三语都要有补充说明占位符。"""
        for path in (EN_JSON, ZH_CN_JSON):
            data = json.loads(path.read_text(encoding="utf-8"))
            page = data.get("page") or {}
            self.assertTrue(
                page.get("yesnoSupplementPlaceholder"),
                f"{path.name} 缺 page.yesnoSupplementPlaceholder",
            )


class TestPersistenceRoundTrip(unittest.TestCase):
    src = TASK_QUEUE_PY.read_text(encoding="utf-8")

    def test_snapshot_contains_question_type(self) -> None:
        self.assertIn('"question_type": task.question_type', self.src)

    def test_restore_reads_question_type(self) -> None:
        self.assertIn('item.get("question_type")', self.src)
        self.assertIn("question_type=restored_qt", self.src)


if __name__ == "__main__":
    unittest.main()
