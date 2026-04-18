#!/usr/bin/env python3
"""P6Y-1 回归：_restore 必须逐条容错，单任务损坏不中断整体恢复。

背景：
    历史实现中 _restore 将整个任务列表的解析放在同一个 try/except 块里：
      - 只要某一条 item 的 created_at 不是合法 ISO 时间，
        或 auto_resubmit_timeout 非法，或 Pydantic 构造失败，
        就会直接跳进外层 except，日志一条 "任务恢复失败（将使用空队列）"，
        然后内存完全空——用户看到"所有任务丢失"。
    修复：per-item try/except，跳过坏记录并累加 skipped 计数。

下面的样本覆盖：
  1. 合法记录 + 单条损坏（损坏方式：created_at 不合法）
  2. 合法记录 + 单条 auto_resubmit_timeout 为非法字符串
  3. 全部损坏 → 恢复空队列但不抛异常
  4. tasks 字段不是 list → 退化为空队列
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def _write_persist(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestRestoreResilience(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.persist_path = Path(self._tmp.name) / "tasks.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_queue(self):
        from task_queue import TaskQueue

        return TaskQueue(persist_path=str(self.persist_path))

    def test_skip_invalid_created_at_keep_valid(self) -> None:
        _write_persist(
            self.persist_path,
            {
                "version": 1,
                "saved_at": "2025-01-01T00:00:00+00:00",
                "active_task_id": None,
                "tasks": [
                    {
                        "task_id": "good",
                        "prompt": "ok",
                        "predefined_options": [],
                        "auto_resubmit_timeout": 120,
                        "created_at": "2025-01-01T00:00:00+00:00",
                        "status": "pending",
                    },
                    {
                        "task_id": "bad",
                        "prompt": "corrupt",
                        "predefined_options": [],
                        "auto_resubmit_timeout": 120,
                        "created_at": "not-an-iso-datetime",
                        "status": "pending",
                    },
                ],
            },
        )

        q = self._make_queue()
        try:
            self.assertIsNotNone(q.get_task("good"))
            self.assertIsNone(
                q.get_task("bad"),
                "损坏的任务必须被跳过，不应进入内存",
            )
        finally:
            q.stop_cleanup()

    def test_skip_invalid_auto_resubmit_timeout_type(self) -> None:
        _write_persist(
            self.persist_path,
            {
                "version": 1,
                "saved_at": "2025-01-01T00:00:00+00:00",
                "active_task_id": None,
                "tasks": [
                    {
                        "task_id": "good",
                        "prompt": "ok",
                        "predefined_options": [],
                        "auto_resubmit_timeout": 120,
                        "created_at": "2025-01-01T00:00:00+00:00",
                        "status": "pending",
                    },
                    {
                        "task_id": "bad",
                        "prompt": "corrupt",
                        "predefined_options": [],
                        "auto_resubmit_timeout": "this-is-not-a-number",
                        "created_at": "2025-01-01T00:00:00+00:00",
                        "status": "pending",
                    },
                ],
            },
        )

        q = self._make_queue()
        try:
            self.assertIsNotNone(q.get_task("good"))
            self.assertIsNone(q.get_task("bad"))
        finally:
            q.stop_cleanup()

    def test_all_items_corrupt_returns_empty_queue(self) -> None:
        _write_persist(
            self.persist_path,
            {
                "version": 1,
                "saved_at": "2025-01-01T00:00:00+00:00",
                "active_task_id": None,
                "tasks": [
                    {
                        "task_id": "x",
                        "prompt": "x",
                        "created_at": "not-iso",
                        "status": "pending",
                    },
                    {
                        "task_id": "y",
                        "prompt": "y",
                        "created_at": "also-not-iso",
                        "status": "pending",
                    },
                ],
            },
        )

        q = self._make_queue()
        try:
            self.assertEqual(len(q.get_all_tasks()), 0)
            self.assertIsNone(q.get_active_task())
        finally:
            q.stop_cleanup()

    def test_non_list_tasks_field_falls_back_to_empty(self) -> None:
        _write_persist(
            self.persist_path,
            {
                "version": 1,
                "saved_at": "2025-01-01T00:00:00+00:00",
                "active_task_id": None,
                "tasks": "not-a-list",
            },
        )

        q = self._make_queue()
        try:
            self.assertEqual(len(q.get_all_tasks()), 0)
        finally:
            q.stop_cleanup()

    def test_non_dict_item_is_skipped(self) -> None:
        _write_persist(
            self.persist_path,
            {
                "version": 1,
                "saved_at": "2025-01-01T00:00:00+00:00",
                "active_task_id": None,
                "tasks": [
                    "this-is-a-string-not-a-dict",
                    42,
                    {
                        "task_id": "good",
                        "prompt": "ok",
                        "predefined_options": [],
                        "auto_resubmit_timeout": 120,
                        "created_at": "2025-01-01T00:00:00+00:00",
                        "status": "pending",
                    },
                ],
            },
        )

        q = self._make_queue()
        try:
            self.assertEqual(len(q.get_all_tasks()), 1)
            self.assertIsNotNone(q.get_task("good"))
        finally:
            q.stop_cleanup()


if __name__ == "__main__":
    unittest.main()
