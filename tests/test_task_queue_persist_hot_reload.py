#!/usr/bin/env python3
"""P6R-1 回归：update_auto_resubmit_timeout_for_all 必须触发持久化。

背景：
    web_ui_config_sync 在配置热更新时会调用
    TaskQueue.update_auto_resubmit_timeout_for_all(new_timeout) 修改所有进行中任务。
    历史实现直接改内存但不调用 _persist()，导致：
      1. 进程重启后从快照恢复时 auto_resubmit_timeout 仍是旧值；
      2. 与 add_task/complete_task/remove_task/set_active_task/clear_completed_tasks
         的写盘策略不一致，破坏了"状态变更即持久化"的契约。

这里通过真实持久化文件 + 新进程风格 restore 验证：
  - 有任务被更新 → 文件 mtime / 内容发生变化；
  - 重新实例化 TaskQueue(persist_path=...) → auto_resubmit_timeout 恢复为新值；
  - 没有任务被更新时不触发多余写盘。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class TestUpdateAutoResubmitTimeoutPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.persist_path = Path(self._tmp.name) / "tasks.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_queue(self):
        from task_queue import TaskQueue

        return TaskQueue(persist_path=str(self.persist_path))

    def test_hot_update_is_persisted_to_disk(self) -> None:
        """更新 timeout 后写盘；新进程 restore 可拿到新值。"""
        q = self._make_queue()
        try:
            q.add_task("t1", "p1", auto_resubmit_timeout=60)
            q.add_task("t2", "p2", auto_resubmit_timeout=60)

            updated = q.update_auto_resubmit_timeout_for_all(180)
            self.assertEqual(updated, 2)
        finally:
            q.stop_cleanup()

        self.assertTrue(self.persist_path.exists(), "持久化文件必须存在")
        data = json.loads(self.persist_path.read_text(encoding="utf-8"))
        timeouts = {
            item["task_id"]: item["auto_resubmit_timeout"]
            for item in data.get("tasks", [])
        }
        self.assertEqual(timeouts.get("t1"), 180)
        self.assertEqual(timeouts.get("t2"), 180)

        q2 = self._make_queue()
        try:
            restored_t1 = q2.get_task("t1")
            restored_t2 = q2.get_task("t2")
            self.assertIsNotNone(restored_t1)
            self.assertIsNotNone(restored_t2)
            assert restored_t1 is not None and restored_t2 is not None
            self.assertEqual(restored_t1.auto_resubmit_timeout, 180)
            self.assertEqual(restored_t2.auto_resubmit_timeout, 180)
        finally:
            q2.stop_cleanup()

    def test_no_update_no_extra_write(self) -> None:
        """updated==0 时不应无谓刷盘（不修改 mtime）。"""
        q = self._make_queue()
        try:
            q.add_task("t1", "p1", auto_resubmit_timeout=120)

            self.assertTrue(self.persist_path.exists())
            mtime_before = self.persist_path.stat().st_mtime_ns

            updated = q.update_auto_resubmit_timeout_for_all(120)
            self.assertEqual(updated, 0)

            mtime_after = self.persist_path.stat().st_mtime_ns
            self.assertEqual(
                mtime_before,
                mtime_after,
                "updated=0 时不应触发额外 _persist() 写盘",
            )
        finally:
            q.stop_cleanup()

    def test_completed_tasks_not_affected(self) -> None:
        """已完成任务不应被更新，也不因此导致额外写盘。"""
        q = self._make_queue()
        try:
            q.add_task("t_active", "p1", auto_resubmit_timeout=60)
            q.add_task("t_done", "p2", auto_resubmit_timeout=60)
            q.complete_task("t_done", {"text": "ok"})

            updated = q.update_auto_resubmit_timeout_for_all(300)
            self.assertEqual(updated, 1)
        finally:
            q.stop_cleanup()

        data = json.loads(self.persist_path.read_text(encoding="utf-8"))
        ids = {item["task_id"] for item in data.get("tasks", [])}
        self.assertIn("t_active", ids)
        self.assertNotIn(
            "t_done",
            ids,
            "已完成任务不应出现在持久化快照中（_persist 过滤 COMPLETED）",
        )


if __name__ == "__main__":
    unittest.main()
