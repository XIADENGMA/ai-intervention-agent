"""R508 - TaskQueue persistence writes compact machine JSON."""

from __future__ import annotations

import inspect
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ai_intervention_agent.task_queue import TaskQueue


class TestTaskQueuePersistCompactJson(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="r508_"))
        self._persist_path = self._tmp_dir / "tasks.json"
        self._queues: list[TaskQueue] = []

    def tearDown(self) -> None:
        for queue in self._queues:
            queue.stop_cleanup()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _queue(self) -> TaskQueue:
        queue = TaskQueue(persist_path=str(self._persist_path))
        self._queues.append(queue)
        return queue

    def test_persist_uses_compact_json_separators(self) -> None:
        source = inspect.getsource(TaskQueue._persist)

        self.assertIn("separators=_COMPACT_JSON_SEPARATORS", source)
        self.assertNotIn("indent=2", source)

    def test_persisted_json_is_compact_and_restore_compatible(self) -> None:
        queue = self._queue()
        self.assertTrue(
            queue.add_task(
                "task-r508",
                "需要保留中文原文",
                predefined_options=["同意", "拒绝"],
            )
        )

        raw = self._persist_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

        self.assertEqual(raw, compact)
        self.assertLess(len(raw), len(pretty))
        self.assertNotIn("\n", raw)
        self.assertNotIn(": ", raw)
        self.assertIn("需要保留中文原文", raw)
        self.assertEqual(data["tasks"][0]["task_id"], "task-r508")

        restored_queue = self._queue()
        restored = restored_queue.get_task("task-r508")
        assert restored is not None
        self.assertEqual(restored.prompt, "需要保留中文原文")


if __name__ == "__main__":
    unittest.main()
