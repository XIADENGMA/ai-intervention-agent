"""R125 · ``GET /api/tasks/export?format={json,markdown}`` 后端导出端点契约测试。

背景
----
项目此前没有任何"会话历史 / 任务存档"导出能力。``GET /api/tasks`` 给的是
prompt 截断 100 字 + 当前可见任务的轻量列表，``GET /api/tasks/<id>`` 给
单任务详情但需要 task_id 列表，``/api/feedback`` 是 read-once 的活的反馈
通道——三者都不适合用户用于"备份这次会话的所有任务交互"。

R125 落地：

- ``GET /api/tasks/export?format=json`` → 完整字段 JSON 快照，含
  ``schema_version=1`` 用于未来迁移；
- ``GET /api/tasks/export?format=markdown`` → 人类可读"会话日志"，
  栅栏代码块包裹 prompt / result，带 GitHub Flavored Markdown 4-tilde
  外层避免 ``` 干扰；
- 默认 ``format=json``；其它值返回 400；
- 响应含 ``Content-Disposition: attachment; filename=...``，浏览器自动
  下载而不是 inline 渲染（避免 URL 渲染干扰 + 与项目"AI 反馈快照"语
  义对齐）；
- 文件名带 ``YYYYMMDDTHHMMSSZ`` 时间戳，让用户机器上多次导出按时间
  排序，避免覆盖；
- 限速 30/min（与 ``/api/update-feedback-config`` 同档），允许人为
  批量备份但拒绝爬虫式高频抓取。

本测试覆盖五个层面：

1.  **JSON 模式契约** — 端点存在 / 200 响应 / 字段完整性 /
    ``schema_version`` 锚定 / Content-Disposition + JSON mimetype。
2.  **Markdown 模式契约** — 200 响应 / Markdown mimetype / GitHub
    Flavored 栅栏 / 任务字段格式。
3.  **format 参数处理** — 默认 json / 非法值 400 / 大小写归一。
4.  **隐私 + 完整性边界** — 完成的任务的 ``result`` 字段（含 base64
    images）必须出现在 JSON 导出里（否则 export 没有备份价值），但
    Markdown 模式中 ``images`` 字段以 JSON 内嵌而非 inline，避免巨型
    base64 撑爆 Markdown viewer。
5.  **空快照** — 任务队列为空时仍返回 200 + 完整结构 + 友好提示，
    不能崩溃或返回 204/404。
"""

from __future__ import annotations

import re
import unittest
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch


class _ExportTestBase(unittest.TestCase):
    """共享基类：延迟创建 WebFeedbackUI + 临时 TaskQueue + Flask test client。"""

    _port: int = 19510
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="r125 export base", task_id="r125-base", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def setUp(self) -> None:
        # 每个测试前清空 TaskQueue，保证独立性
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        get_task_queue().clear_all_tasks()

    def _add_task(
        self,
        task_id: str,
        prompt: str = "Hello",
        options: list[str] | None = None,
        defaults: list[bool] | None = None,
        timeout: int = 240,
    ) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        get_task_queue().add_task(
            task_id=task_id,
            prompt=prompt,
            predefined_options=options,
            auto_resubmit_timeout=timeout,
            predefined_options_defaults=defaults,
        )

    def _complete_task_with_result(
        self, task_id: str, feedback_text: str = "用户回复"
    ) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        result = {
            "user_input": feedback_text,
            "selected_options": [],
            "images": [],
        }
        get_task_queue().complete_task(task_id, result)


# ---------------------------------------------------------------------------
# 1. JSON 模式契约
# ---------------------------------------------------------------------------


class TestJsonFormatContract(_ExportTestBase):
    _port = 19511

    def test_endpoint_exists(self) -> None:
        resp = self._client.get("/api/tasks/export")
        self.assertNotEqual(
            resp.status_code,
            404,
            "GET /api/tasks/export 必须存在（R125 后端契约）",
        )

    def test_default_format_is_json(self) -> None:
        """不传 format 参数时默认走 JSON 路径。"""
        resp = self._client.get("/api/tasks/export")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            "application/json",
            resp.headers.get("Content-Type", ""),
            "默认 format=json 必须返回 application/json mimetype",
        )

    def test_explicit_format_json(self) -> None:
        resp = self._client.get("/api/tasks/export?format=json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))

    def test_json_payload_has_schema_version(self) -> None:
        """``schema_version`` 必须存在以便未来 export schema 迁移可识别。"""
        resp = self._client.get("/api/tasks/export?format=json")
        data = resp.get_json()
        self.assertIsInstance(data, dict)
        self.assertEqual(
            data.get("schema_version"),
            1,
            "首版 export schema 必须是 schema_version=1（locked-by-test，"
            "未来 breaking change 必须显式 bump 并更新本测试）",
        )

    def test_json_payload_has_top_level_fields(self) -> None:
        resp = self._client.get("/api/tasks/export?format=json")
        data = resp.get_json()
        for field in (
            "success",
            "schema_version",
            "exported_at",
            "server_time",
            "stats",
            "tasks",
        ):
            self.assertIn(field, data, f"JSON 导出顶层缺少字段: {field}")
        self.assertTrue(data["success"])
        self.assertIsInstance(data["tasks"], list)
        self.assertIsInstance(data["stats"], dict)

    def test_content_disposition_attachment(self) -> None:
        """Content-Disposition 必须是 attachment 触发下载。"""
        resp = self._client.get("/api/tasks/export?format=json")
        cd = resp.headers.get("Content-Disposition", "")
        self.assertIn("attachment", cd, "Content-Disposition 必须含 attachment")
        # 文件名必须含 ISO8601-like 时间戳，避免覆盖
        self.assertRegex(
            cd,
            r"filename=\"ai-intervention-agent-tasks-\d{8}T\d{6}Z\.json\"",
            f"文件名必须形如 ai-intervention-agent-tasks-YYYYMMDDTHHMMSSZ.json"
            f"（实际: {cd!r}）",
        )

    def test_json_filename_and_exported_at_share_one_clock_snapshot(self) -> None:
        """R466: filename stamp 和 payload exported_at 必须来自同一次 now。"""
        fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        calls: list[object] = []

        class FixedDatetime:
            @staticmethod
            def now(tz: object = None) -> datetime:
                calls.append(tz)
                return fixed

        with patch("ai_intervention_agent.web_ui_routes.task._dt", FixedDatetime):
            resp = self._client.get("/api/tasks/export?format=json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(calls, [UTC])
        self.assertEqual(resp.get_json()["exported_at"], fixed.isoformat())
        self.assertIn(
            'filename="ai-intervention-agent-tasks-20260102T030405Z.json"',
            resp.headers.get("Content-Disposition", ""),
        )

    def test_task_full_fields_in_json(self) -> None:
        """JSON 模式必须给完整字段（不像 ``/api/tasks`` 只给 prompt[:100]）。"""
        full_prompt = "x" * 500  # 超过 /api/tasks 截断的 100
        self._add_task("r125-full-prompt", prompt=full_prompt)
        resp = self._client.get("/api/tasks/export?format=json")
        data = resp.get_json()
        self.assertEqual(len(data["tasks"]), 1)
        t = data["tasks"][0]
        self.assertEqual(
            t["prompt"],
            full_prompt,
            "JSON 导出必须给完整 prompt（不能像 /api/tasks 截断到 100 字）",
        )
        for f in (
            "task_id",
            "status",
            "prompt",
            "predefined_options",
            "predefined_options_defaults",
            "auto_resubmit_timeout",
            "remaining_time",
            "deadline",
            "created_at",
            "completed_at",
            "result",
        ):
            self.assertIn(f, t, f"导出 task 缺字段: {f}")

    def test_json_includes_completed_task_result(self) -> None:
        """完成的任务的 ``result`` 字段（含图片 base64）必须出现在导出里。"""
        self._add_task("r125-completed")
        self._complete_task_with_result("r125-completed", feedback_text="hello")
        resp = self._client.get("/api/tasks/export?format=json")
        data = resp.get_json()
        # 由于 cleanup 节流，completed 任务还会留在内存 ~10s
        target = next(
            (x for x in data["tasks"] if x["task_id"] == "r125-completed"), None
        )
        self.assertIsNotNone(target, "completed 任务必须出现在导出快照里")
        assert target is not None
        self.assertIsNotNone(target["result"], "completed 任务的 result 不应为 None")
        self.assertEqual(target["result"]["user_input"], "hello")


# ---------------------------------------------------------------------------
# 2. Markdown 模式契约
# ---------------------------------------------------------------------------


class TestMarkdownFormatContract(_ExportTestBase):
    _port = 19512

    def test_explicit_format_markdown(self) -> None:
        resp = self._client.get("/api/tasks/export?format=markdown")
        self.assertEqual(resp.status_code, 200)
        ct = resp.headers.get("Content-Type", "")
        self.assertIn(
            "text/markdown", ct, f"必须返回 text/markdown mimetype（实际 {ct}）"
        )

    def test_markdown_filename_md_ext(self) -> None:
        resp = self._client.get("/api/tasks/export?format=markdown")
        cd = resp.headers.get("Content-Disposition", "")
        self.assertRegex(
            cd,
            r"filename=\"ai-intervention-agent-tasks-\d{8}T\d{6}Z\.md\"",
            f"Markdown 导出文件名必须以 .md 结尾（实际 {cd}）",
        )

    def test_markdown_filename_and_exported_at_share_one_clock_snapshot(self) -> None:
        """R466: Markdown header 和下载文件名必须来自同一次 now。"""
        fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        calls: list[object] = []

        class FixedDatetime:
            @staticmethod
            def now(tz: object = None) -> datetime:
                calls.append(tz)
                return fixed

        with patch("ai_intervention_agent.web_ui_routes.task._dt", FixedDatetime):
            resp = self._client.get("/api/tasks/export?format=markdown")

        body = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(calls, [UTC])
        self.assertIn(f"- Exported at: `{fixed.isoformat()}`", body)
        self.assertIn(
            'filename="ai-intervention-agent-tasks-20260102T030405Z.md"',
            resp.headers.get("Content-Disposition", ""),
        )

    def test_markdown_has_header_and_stats(self) -> None:
        body = self._client.get("/api/tasks/export?format=markdown").get_data(
            as_text=True
        )
        self.assertIn(
            "# AI Intervention Agent · Task Export",
            body,
            "Markdown 必须有 H1 标题",
        )
        self.assertIn("Stats:", body, "Markdown 头部必须显示 stats 摘要")

    def test_markdown_uses_4_tilde_fences_for_prompt(self) -> None:
        """Prompt 用 4 backticks 栅栏避免 prompt 自身含 ``` 破坏渲染。"""
        # 加一个含 ``` 的 prompt
        self._add_task("r125-fenced", prompt="some\n```js\ncode\n```\nmore")
        body = self._client.get("/api/tasks/export?format=markdown").get_data(
            as_text=True
        )
        # 至少应该出现一对 4-tick 栅栏
        self.assertIn(
            "````markdown",
            body,
            "Markdown 必须用 4 反引号栅栏 ````markdown 包裹 prompt（防止 prompt 内 ``` 破坏渲染）",
        )

    def test_markdown_renders_options_with_checkboxes(self) -> None:
        self._add_task(
            "r125-opts",
            prompt="pick one",
            options=["A", "B", "C"],
            defaults=[True, False, False],
        )
        body = self._client.get("/api/tasks/export?format=markdown").get_data(
            as_text=True
        )
        self.assertIn("- [x] A", body, "默认选中的选项必须显示为 [x]")
        self.assertIn("- [ ] B", body, "非默认选项必须显示为 [ ]")
        self.assertIn("- [ ] C", body, "非默认选项必须显示为 [ ]")

    def test_markdown_renders_completed_result_block(self) -> None:
        self._add_task("r125-md-result")
        self._complete_task_with_result("r125-md-result", feedback_text="OK")
        body = self._client.get("/api/tasks/export?format=markdown").get_data(
            as_text=True
        )
        self.assertIn("Result (feedback)", body)
        self.assertIn(
            '"user_input": "OK"',
            body,
            "Markdown 模式下 result 应以 JSON 内嵌（栅栏块）渲染",
        )


# ---------------------------------------------------------------------------
# 3. format 参数处理
# ---------------------------------------------------------------------------


class TestFormatParamHandling(_ExportTestBase):
    _port = 19513

    def test_unsupported_format_returns_400(self) -> None:
        resp = self._client.get("/api/tasks/export?format=xml")
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("success"), False)
        self.assertEqual(data.get("error"), "unsupported_format")

    def test_format_case_insensitive(self) -> None:
        resp = self._client.get("/api/tasks/export?format=JSON")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))

    def test_format_with_whitespace_normalised(self) -> None:
        resp = self._client.get("/api/tasks/export?format=%20markdown%20")
        self.assertEqual(resp.status_code, 200, "format 周围空白必须被 strip 掉")
        self.assertIn("text/markdown", resp.headers.get("Content-Type", ""))


# ---------------------------------------------------------------------------
# 4. 空快照 + 边界
# ---------------------------------------------------------------------------


class TestEmptySnapshotAndBoundaries(_ExportTestBase):
    _port = 19514

    def test_empty_queue_returns_200_with_friendly_marker(self) -> None:
        """无任务时不应崩溃，应返回 200 + 空数组 + Markdown 友好提示。"""
        body = self._client.get("/api/tasks/export?format=markdown").get_data(
            as_text=True
        )
        self.assertIn("(No tasks in queue.)", body)

        data = self._client.get("/api/tasks/export?format=json").get_json()
        self.assertEqual(data["tasks"], [])
        # stats 仍应有结构，所有 count = 0
        self.assertEqual(data["stats"].get("total", 0), 0)

    def test_export_does_not_modify_queue(self) -> None:
        """导出是纯读快照——不应改变任务状态或数量。"""
        self._add_task("r125-noop-1")
        self._add_task("r125-noop-2")

        before = self._client.get("/api/tasks").get_json()
        self._client.get("/api/tasks/export?format=json")
        self._client.get("/api/tasks/export?format=markdown")
        after = self._client.get("/api/tasks").get_json()

        before_ids = sorted(t["task_id"] for t in before["tasks"])
        after_ids = sorted(t["task_id"] for t in after["tasks"])
        self.assertEqual(
            before_ids,
            after_ids,
            "/api/tasks/export 必须是纯读路径——不能改变任务列表",
        )


# ---------------------------------------------------------------------------
# 5. 文件名时间戳唯一性
# ---------------------------------------------------------------------------


class TestFilenameTimestamp(_ExportTestBase):
    _port = 19515

    def test_filename_iso_format(self) -> None:
        cd = self._client.get("/api/tasks/export?format=json").headers.get(
            "Content-Disposition", ""
        )
        m = re.search(r"(\d{8}T\d{6}Z)", cd)
        self.assertIsNotNone(m, f"文件名必须含 ISO8601 时间戳（实际 CD={cd}）")
        assert m is not None
        # 验证戳本身格式合法
        stamp = m.group(1)
        self.assertEqual(len(stamp), 16)  # YYYYMMDDTHHMMSSZ = 16 chars
        self.assertEqual(stamp[8], "T")
        self.assertTrue(stamp.endswith("Z"))


if __name__ == "__main__":
    unittest.main()
