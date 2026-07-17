"""R691 — /api/config 任务级字段补齐 + 插件 webview 三特性对齐（TODO#5）。

背景
----

MCP ``interactive_feedback`` 支持三个任务级 UI 特性（mining-cycle-3 借自
gemini-cli ``ask_user``）：

- ``feedback_placeholder``：per-task textarea 占位提示；
- ``question_type="yesno"``：一行 Yes/No 按钮替代 textarea；
- ``header_label``：≤16 字符领域 chip。

web 页面（multi_task.js 走 ``/api/tasks/<id>``）三者齐全；插件 webview 走
``/api/config``，而该端点此前**不返回**这三个字段——插件端整套特性静默
失效，两端行为不一致。

R691 修复两层：

1. 后端：``/api/config`` 的 active-task / first-incomplete-task 两个分支
   补齐三个字段；
2. 插件：webview 渲染 header chip / 应用 placeholder / yesno 按钮组，
   与 web 端同构。

本测试锁定后端字段契约（运行时行为）+ 插件端源码契约 + locale 数据。
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

TASK_LEVEL_FIELDS = ("feedback_placeholder", "question_type", "header_label")


class TestApiConfigCarriesTaskLevelFields(unittest.TestCase):
    """运行时行为：/api/config 必须返回三个任务级字段。"""

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(
            prompt="R691 字段契约测试",
            task_id="r691-field-parity",
            port=8981,
        )
        cls.app = cls.ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

        cls.task_queue = get_task_queue()
        cls.task_queue.add_task(
            task_id="r691-task",
            prompt="# R691",
            predefined_options=["A"],
            auto_resubmit_timeout=240,
            feedback_placeholder="Paste the stack trace",
            question_type="yesno",
            header_label="Auth",
        )
        cls.task_queue.set_active_task("r691-task")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.task_queue.remove_task("r691-task")

    def test_active_task_branch_returns_all_three_fields(self) -> None:
        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data.get("task_id"), "r691-task")
        for field in TASK_LEVEL_FIELDS:
            with self.subTest(field=field):
                self.assertIn(
                    field,
                    data,
                    f"/api/config 缺少任务级字段 {field}（R691 契约）",
                )
        self.assertEqual(data.get("feedback_placeholder"), "Paste the stack trace")
        self.assertEqual(data.get("question_type"), "yesno")
        self.assertEqual(data.get("header_label"), "Auth")


class TestWebviewSourceContract(unittest.TestCase):
    """插件端必须消费三个字段（源码契约）。"""

    def setUp(self) -> None:
        self.ts = WEBVIEW_TS.read_text(encoding="utf-8")
        self.js = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    def test_header_chip_element_and_updater(self) -> None:
        self.assertIn('id="taskHeaderChip"', self.ts)
        self.assertIn("function updateHeaderChip(", self.js)
        self.assertIn("updateHeaderChip(config.header_label)", self.js)

    def test_placeholder_updater_wired(self) -> None:
        self.assertIn("function updateFeedbackPlaceholder(", self.js)
        self.assertIn("updateFeedbackPlaceholder(config.feedback_placeholder)", self.js)

    def test_yesno_group_element_and_updater(self) -> None:
        self.assertIn('id="yesnoButtonGroup"', self.ts)
        self.assertIn('id="yesnoYesBtn"', self.ts)
        self.assertIn('id="yesnoNoBtn"', self.ts)
        self.assertIn("function updateYesnoButtonGroup(", self.js)
        self.assertIn("updateYesnoButtonGroup(config.question_type)", self.js)

    def test_yesno_buttons_submit_literal_answers(self) -> None:
        match = re.search(
            r"async function handleYesnoAnswerClick\(.*?\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "未找到 handleYesnoAnswerClick")
        assert match is not None
        body = match.group(0)
        self.assertIn("'yes'", body)
        self.assertIn("'no'", body)
        self.assertIn("submitWithData(", body)

    def test_chip_clamped_to_sixteen_chars(self) -> None:
        match = re.search(r"function updateHeaderChip\(.*?\n  \}", self.js, re.DOTALL)
        assert match is not None
        self.assertIn(
            "slice(0, 16)",
            match.group(0),
            "header chip 必须与后端/web 端一致地截断到 16 字符",
        )

    def test_css_styles_exist(self) -> None:
        css = WEBVIEW_CSS.read_text(encoding="utf-8")
        self.assertIn(".task-header-chip", css)
        self.assertIn(".yesno-button-group", css)
        self.assertIn(".yesno-btn", css)


class TestLocaleKeys(unittest.TestCase):
    def test_yesno_keys_in_all_locales(self) -> None:
        for locale in ("en", "zh-CN", "zh-TW"):
            data = json.loads(
                (LOCALES_DIR / f"{locale}.json").read_text(encoding="utf-8")
            )
            form = data.get("ui", {}).get("form", {})
            for key in ("yesnoYes", "yesnoNo"):
                with self.subTest(locale=locale, key=key):
                    self.assertIn(key, form, f"{locale}.json 缺少 ui.form.{key}")
                    self.assertTrue(str(form[key]).strip())


if __name__ == "__main__":
    unittest.main()
