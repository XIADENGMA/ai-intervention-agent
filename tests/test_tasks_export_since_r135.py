"""R135 · ``GET /api/tasks/export?since=<ISO>`` 增量导出过滤器契约测试。

背景
----
R125 / R125c 的导出端点全量导出整个 ``TaskQueue`` 快照。在 CI / 备份脚本
周期性拉 ``/api/tasks/export`` 的真实场景里，绝大多数任务自上次同步后
没动过——全量传输是 O(N×content) 的浪费（含 base64 image data 时尤
甚）。R135 引入 ``?since=<ISO>`` 把过滤交给服务端：downstream 只拿真
正变化的 tasks，传输量落到 O(M×content)，M ≤ N。

设计契约（5 个 invariant class，共 18 cases）：

1. **`_parse_since_iso` helper** — None / 空 / 合法 / 非法 ISO 解析。

2. **`_task_modified_since` helper** — created_at / completed_at 联合判断。

3. **HTTP 默认行为不变** — `?since` 缺省时与 R125c 全量导出行为一致。

4. **HTTP `?since` 增量路径** — 仅返回过滤后的 tasks；JSON payload
   `since` / `incremental` 字段；Markdown header `Filtered since:` 行。

5. **HTTP `?since` 错误路径与组合用法** — 非法 ISO 返回 400；空字符串
   走全量；与 `format` / `include_images` 三参数组合。
"""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _iso_for_query(dt: datetime) -> str:
    """把 ``datetime`` 转成 query-safe 的 ISO 字符串。

    ``datetime.isoformat()`` 输出形如 ``2024-01-15T08:00:00+00:00``，
    里面 ``+`` 在 URL query 里会被解析成空格 → server 收到
    ``2024-01-15T08:00:00 00:00`` 解析失败。``quote(safe="")`` 把
    ``+`` / ``:`` 全部 percent-encode（``%2B`` / ``%3A``），server
    侧 Flask 会自动解码回去。
    """
    return quote(dt.isoformat(), safe="")


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from ai_intervention_agent.web_ui_routes.task import (
    _parse_since_iso,
    _task_modified_since,
)

# ----------------------------------------------------------------------------
# 1. _parse_since_iso helper
# ----------------------------------------------------------------------------


class TestParseSinceIso(unittest.TestCase):
    def test_none_returns_none_no_error(self) -> None:
        dt, err = _parse_since_iso(None)
        self.assertIsNone(dt)
        self.assertIsNone(err)

    def test_empty_string_returns_none_no_error(self) -> None:
        dt, err = _parse_since_iso("")
        self.assertIsNone(dt)
        self.assertIsNone(err)
        # 仅空白也按 None 处理
        dt, err = _parse_since_iso("   ")
        self.assertIsNone(dt)
        self.assertIsNone(err)

    def test_iso_with_explicit_utc_offset(self) -> None:
        dt, err = _parse_since_iso("2024-01-15T08:00:00+00:00")
        self.assertIsNone(err)
        assert dt is not None
        self.assertEqual(dt.tzinfo, UTC)
        self.assertEqual(dt.year, 2024)
        self.assertEqual(dt.month, 1)
        self.assertEqual(dt.day, 15)
        self.assertEqual(dt.hour, 8)

    def test_iso_with_z_suffix(self) -> None:
        # ``Z`` 后缀必须被识别为 UTC（无论 Python 版本）
        dt, err = _parse_since_iso("2024-01-15T08:00:00Z")
        self.assertIsNone(err)
        assert dt is not None
        self.assertEqual(dt.tzinfo, UTC)
        self.assertEqual(dt.hour, 8)

    def test_naive_iso_treated_as_utc(self) -> None:
        # 不带时区的 ISO 字符串按 UTC 处理（与 Task.created_at 全 UTC-aware
        # 的契约保持一致）
        dt, err = _parse_since_iso("2024-01-15T08:00:00")
        self.assertIsNone(err)
        assert dt is not None
        self.assertEqual(dt.tzinfo, UTC)

    def test_invalid_iso_returns_error_msg(self) -> None:
        for bad in ("not an iso", "2024/01/15", "2024-13-99T99:99:99"):
            dt, err = _parse_since_iso(bad)
            self.assertIsNone(dt, f"{bad!r} 解析后应当为 None")
            self.assertIsNotNone(err, f"{bad!r} 应返回 human msg")
            assert err is not None
            self.assertIn("ISO", err)


# ----------------------------------------------------------------------------
# 2. _task_modified_since helper
# ----------------------------------------------------------------------------


class _FakeTask:
    """轻量 task 桩——仅暴露 ``created_at`` / ``completed_at`` 两字段。

    实际 ``Task`` 是 ``BaseModel``，但 ``_task_modified_since`` 只用
    ``getattr``，所以 duck-typing 即可。"""

    def __init__(
        self, created_at: datetime, completed_at: datetime | None = None
    ) -> None:
        self.created_at = created_at
        self.completed_at = completed_at


class TestTaskModifiedSince(unittest.TestCase):
    def setUp(self) -> None:
        self.since = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

    def test_created_at_after_since_is_modified(self) -> None:
        task = _FakeTask(created_at=self.since + timedelta(seconds=1))
        self.assertTrue(_task_modified_since(task, self.since))

    def test_created_at_equal_to_since_is_modified(self) -> None:
        # 边界：created_at == since 视为 modified（>=）
        task = _FakeTask(created_at=self.since)
        self.assertTrue(_task_modified_since(task, self.since))

    def test_completed_at_after_since_is_modified_even_if_created_before(
        self,
    ) -> None:
        # task 早就创建，但刚完成——也是变化
        task = _FakeTask(
            created_at=self.since - timedelta(hours=2),
            completed_at=self.since + timedelta(seconds=30),
        )
        self.assertTrue(_task_modified_since(task, self.since))

    def test_created_before_no_completed_is_not_modified(self) -> None:
        task = _FakeTask(
            created_at=self.since - timedelta(hours=2),
            completed_at=None,
        )
        self.assertFalse(_task_modified_since(task, self.since))

    def test_created_before_completed_before_is_not_modified(self) -> None:
        task = _FakeTask(
            created_at=self.since - timedelta(hours=2),
            completed_at=self.since - timedelta(hours=1),
        )
        self.assertFalse(_task_modified_since(task, self.since))


# ----------------------------------------------------------------------------
# 3-5. HTTP-level integration
# ----------------------------------------------------------------------------


class _HttpExportSinceBase(unittest.TestCase):
    """共享 fixtures：真实 WebFeedbackUI + Flask test client + 干净 TaskQueue。"""

    _port: int = 19612
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(prompt="r135 base", task_id="r135-base", port=cls._port)
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def setUp(self) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        get_task_queue().clear_all_tasks()

    def _add_two_tasks_with_known_times(self) -> tuple[datetime, datetime]:
        """添加两个任务：一个老（created 1h ago）、一个新（刚刚 created）。

        返回 ``(old_created_at, new_created_at)`` 给 caller 写 since 边界。"""
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        tq = get_task_queue()
        # 先加新 task
        tq.add_task(task_id="t-new", prompt="recent", auto_resubmit_timeout=240)
        # 再加 old task 后手动 backdate created_at 到 1 小时前
        tq.add_task(task_id="t-old", prompt="long ago", auto_resubmit_timeout=240)
        old_task = tq.get_task("t-old")
        new_task = tq.get_task("t-new")
        assert old_task is not None
        assert new_task is not None
        old_task.created_at = datetime.now(UTC) - timedelta(hours=1)
        return old_task.created_at, new_task.created_at


class TestExportSinceDefaultBehavior(_HttpExportSinceBase):
    def test_no_since_returns_full_export(self) -> None:
        # R125 兼容性回归保护：since 缺省时全量
        old_at, new_at = self._add_two_tasks_with_known_times()
        resp = self._client.get("/api/tasks/export?format=json")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(len(body["tasks"]), 2)
        self.assertIsNone(body.get("since"))
        self.assertFalse(body.get("incremental"))

    def test_empty_since_treated_as_no_since(self) -> None:
        old_at, new_at = self._add_two_tasks_with_known_times()
        resp = self._client.get("/api/tasks/export?format=json&since=")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(len(body["tasks"]), 2)
        self.assertIsNone(body.get("since"))
        self.assertFalse(body.get("incremental"))


class TestExportSinceIncremental(_HttpExportSinceBase):
    def test_since_filters_old_tasks(self) -> None:
        self._add_two_tasks_with_known_times()
        # 取一个介于 old / new 之间的时间戳：30min ago
        midpoint_dt = datetime.now(UTC) - timedelta(minutes=30)
        midpoint_q = _iso_for_query(midpoint_dt)
        resp = self._client.get(f"/api/tasks/export?format=json&since={midpoint_q}")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(len(body["tasks"]), 1)
        self.assertEqual(body["tasks"][0]["task_id"], "t-new")
        self.assertTrue(body["incremental"])
        # echo 必带时区（aware datetime.isoformat 总有时区段）
        self.assertIn("+00:00", body["since"])

    def test_since_with_z_suffix_works(self) -> None:
        self._add_two_tasks_with_known_times()
        # ISO + Z（UTC）— Z 字符不需要 percent-encode
        midpoint = (
            (datetime.now(UTC) - timedelta(minutes=30))
            .replace(microsecond=0)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        resp = self._client.get(f"/api/tasks/export?format=json&since={midpoint}")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(len(body["tasks"]), 1)
        self.assertTrue(body["incremental"])
        # echo back 时 Z 已被规范化成 +00:00 形式
        self.assertIn("+00:00", body["since"])

    def test_since_in_future_returns_empty_tasks(self) -> None:
        self._add_two_tasks_with_known_times()
        future_q = _iso_for_query(datetime.now(UTC) + timedelta(hours=1))
        resp = self._client.get(f"/api/tasks/export?format=json&since={future_q}")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["tasks"], [])
        self.assertTrue(body["incremental"])

    def test_stats_remain_global_not_localized(self) -> None:
        self._add_two_tasks_with_known_times()
        midpoint_q = _iso_for_query(datetime.now(UTC) - timedelta(minutes=30))
        resp = self._client.get(f"/api/tasks/export?format=json&since={midpoint_q}")
        body = resp.get_json()
        stats = body["stats"]
        self.assertEqual(
            stats.get("total"),
            2,
            "stats 必须是全局 baseline，不应被 since 局部化",
        )


class TestExportSinceMarkdown(_HttpExportSinceBase):
    def test_markdown_header_has_filtered_since_line(self) -> None:
        self._add_two_tasks_with_known_times()
        midpoint_q = _iso_for_query(datetime.now(UTC) - timedelta(minutes=30))
        resp = self._client.get(f"/api/tasks/export?format=markdown&since={midpoint_q}")
        self.assertEqual(resp.status_code, 200)
        text = resp.get_data(as_text=True)
        self.assertIn("Filtered since:", text)
        # Markdown body 应只含 t-new task header
        self.assertIn("Task `t-new`", text)
        self.assertNotIn("Task `t-old`", text)

    def test_markdown_no_since_no_filtered_line(self) -> None:
        # since 缺省时 Markdown header 不应有 ``Filtered since:`` 行
        old_at, new_at = self._add_two_tasks_with_known_times()
        resp = self._client.get("/api/tasks/export?format=markdown")
        self.assertEqual(resp.status_code, 200)
        text = resp.get_data(as_text=True)
        self.assertNotIn("Filtered since:", text)


class TestExportSinceErrorPathAndCombos(_HttpExportSinceBase):
    def test_invalid_since_returns_400(self) -> None:
        resp = self._client.get("/api/tasks/export?format=json&since=not-an-iso")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "invalid_since")
        self.assertIn("ISO", body["message"])

    def test_invalid_since_returns_400_with_format_markdown(self) -> None:
        # 即便用户传 format=markdown 也应当返回 400 JSON 而非半态 markdown
        resp = self._client.get("/api/tasks/export?format=markdown&since=2024-13-99")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["error"], "invalid_since")

    def test_since_combines_with_include_images_false(self) -> None:
        # 三参数组合：since + format=json + include_images=false
        self._add_two_tasks_with_known_times()
        midpoint_q = _iso_for_query(datetime.now(UTC) - timedelta(minutes=30))
        resp = self._client.get(
            f"/api/tasks/export?format=json&since={midpoint_q}&include_images=false"
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(len(body["tasks"]), 1)
        self.assertTrue(body["incremental"])
        self.assertFalse(body["include_images"])


if __name__ == "__main__":
    unittest.main()
