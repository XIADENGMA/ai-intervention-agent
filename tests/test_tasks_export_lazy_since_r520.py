"""R520 regression coverage for lazy ``/api/tasks/export?since=`` filtering."""

from __future__ import annotations

import inspect
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _iso_for_query(dt: datetime) -> str:
    return quote(dt.isoformat(), safe="")


class TestTasksExportLazySinceFilterSource(unittest.TestCase):
    def test_since_filter_does_not_materialize_intermediate_task_list(self) -> None:
        from ai_intervention_agent.web_ui_routes.task import TaskRoutesMixin

        source = inspect.getsource(TaskRoutesMixin)

        self.assertNotIn(
            "tasks = [t for t in tasks if _task_modified_since(t, since_dt)]",
            source,
            "R520: since filtering must not allocate a second tasks list before export",
        )
        self.assertIn("tasks_iter = iter(tasks)", source)
        self.assertIn("for task in tasks_iter:", source)
        self.assertIn(
            "task for task in tasks if _task_modified_since(task, since_dt)",
            source,
        )


class TestTasksExportLazySinceFilterRuntime(unittest.TestCase):
    _port: int = 19620
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(prompt="r520 base", task_id="r520-base", port=cls._port)
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()

    def setUp(self) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        get_task_queue().clear_all_tasks()

    def _add_old_and_new_tasks(self) -> str:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        tq = get_task_queue()
        tq.add_task(task_id="r520-new", prompt="recent", auto_resubmit_timeout=240)
        tq.add_task(task_id="r520-old", prompt="old", auto_resubmit_timeout=240)
        old_task = tq.get_task("r520-old")
        assert old_task is not None
        old_task.created_at = datetime.now(UTC) - timedelta(hours=1)
        return _iso_for_query(datetime.now(UTC) - timedelta(minutes=30))

    def test_json_since_filter_keeps_existing_payload_contract(self) -> None:
        since_q = self._add_old_and_new_tasks()

        resp = self._client.get(f"/api/tasks/export?format=json&since={since_q}")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["incremental"])
        self.assertEqual([task["task_id"] for task in body["tasks"]], ["r520-new"])
        self.assertEqual(body["stats"].get("total"), 2)

    def test_markdown_since_filter_keeps_existing_payload_contract(self) -> None:
        since_q = self._add_old_and_new_tasks()

        resp = self._client.get(f"/api/tasks/export?format=markdown&since={since_q}")

        self.assertEqual(resp.status_code, 200)
        text = resp.get_data(as_text=True)
        self.assertIn("Filtered since:", text)
        self.assertIn("Task `r520-new`", text)
        self.assertNotIn("Task `r520-old`", text)


if __name__ == "__main__":
    unittest.main()
