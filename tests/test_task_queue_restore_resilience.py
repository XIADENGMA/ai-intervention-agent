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


class TestCorruptPersistQuarantine(unittest.TestCase):
    """R17.8：损坏的持久化文件必须被 quarantine（重命名带时间戳后缀），
    避免被下次 ``_persist`` 的 ``os.replace`` 静默覆盖丢失 forensic 数据。

    动机：v1.5.x R17.2 修了 _persist 的 fsync 漏洞，但旧版本写入的损坏
    tasks.json 仍可能留在用户磁盘上。如果重启时 ``_restore`` 顶层 except
    无声地降级到空队列，第一个 ``add_task`` 触发的 ``_persist`` 会用
    ``os.replace`` 原子覆盖原文件 —— 用户的损坏证据永久消失，事后无法
    inspect 当时的字节内容做断电诊断。本测试类锁住"损坏文件被
    quarantine"的不变量。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.persist_path = Path(self._tmp.name) / "tasks.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_queue(self):
        from task_queue import TaskQueue

        return TaskQueue(persist_path=str(self.persist_path))

    def _list_corrupt_files(self) -> list[Path]:
        """枚举目录下所有 ``<orig>.corrupt-*`` 隔离文件。"""
        parent = self.persist_path.parent
        return sorted(parent.glob(f"{self.persist_path.name}.corrupt-*"))

    def test_truncated_json_is_quarantined(self) -> None:
        """JSON 截断（断电常见情形）→ 损坏文件应被 quarantine。"""
        # 写一个被截断的 JSON：大括号没闭合，模拟"fsync 之前断电"
        self.persist_path.write_text(
            '{"version": 1, "tasks": [{"task_id": "trunc"',
            encoding="utf-8",
        )

        q = self._make_queue()
        try:
            # 队列降级为空（不抛异常）
            self.assertEqual(len(q.get_all_tasks()), 0)

            # 原路径已不存在（被 rename 了）
            self.assertFalse(
                self.persist_path.exists(),
                "损坏文件应被 quarantine 出去；原路径不应再有文件",
            )

            # 但隔离副本必须存在
            corrupts = self._list_corrupt_files()
            self.assertEqual(
                len(corrupts),
                1,
                "应恰好产生一个 quarantine 副本",
            )

            # 隔离副本的内容应与原损坏文件完全一致（forensic 完整性）
            self.assertEqual(
                corrupts[0].read_text(encoding="utf-8"),
                '{"version": 1, "tasks": [{"task_id": "trunc"',
                "quarantine 副本的字节必须与原损坏文件完全一致",
            )
        finally:
            q.stop_cleanup()

    def test_quarantine_filename_format(self) -> None:
        """隔离文件名必须为 ``<orig>.corrupt-<ISO>`` 格式且按时间排序。"""
        import re

        self.persist_path.write_text("not-json-at-all", encoding="utf-8")

        q = self._make_queue()
        try:
            corrupts = self._list_corrupt_files()
            self.assertEqual(len(corrupts), 1)

            name = corrupts[0].name
            # 期望格式：tasks.json.corrupt-YYYYMMDDTHHMMSSZ
            pattern = (
                rf"^{re.escape(self.persist_path.name)}\.corrupt-"
                r"\d{8}T\d{6}Z$"
            )
            self.assertRegex(
                name,
                pattern,
                f"quarantine 文件名 {name!r} 应符合 ISO 紧凑时间戳格式（"
                "YYYYMMDDTHHMMSSZ，不含冒号 — Windows 文件名禁止冒号）",
            )
        finally:
            q.stop_cleanup()

    def test_subsequent_persist_does_not_overwrite_quarantine(self) -> None:
        """quarantine 后下次 ``_persist`` 写入新文件，不应覆盖隔离副本。

        这是修复的核心价值：如果 quarantine 副本被覆盖，等于没做隔离。
        """
        self.persist_path.write_text(
            '{"version": 1, "tasks": [{}',  # 截断
            encoding="utf-8",
        )

        q = self._make_queue()
        try:
            corrupts_before = self._list_corrupt_files()
            self.assertEqual(len(corrupts_before), 1)
            quarantine_path = corrupts_before[0]
            quarantine_bytes = quarantine_path.read_bytes()

            # 触发一次 _persist：add_task 后会持久化新文件
            self.assertTrue(
                q.add_task(
                    task_id="new-task-after-corrupt",
                    prompt="正常任务",
                    auto_resubmit_timeout=60,
                )
            )

            # 隔离副本必须仍然在原位、内容不变
            self.assertTrue(
                quarantine_path.exists(),
                "quarantine 副本不应被后续 _persist 覆盖",
            )
            self.assertEqual(
                quarantine_path.read_bytes(),
                quarantine_bytes,
                "quarantine 副本的字节不应被改动",
            )

            # 同时新的 tasks.json 应该写入成功
            self.assertTrue(
                self.persist_path.exists(),
                "_persist 应在原路径创建新文件（不再受损坏文件干扰）",
            )
            new_data = json.loads(self.persist_path.read_text(encoding="utf-8"))
            self.assertEqual(new_data.get("version"), 1)
            new_task_ids = {t["task_id"] for t in new_data.get("tasks", [])}
            self.assertIn("new-task-after-corrupt", new_task_ids)
        finally:
            q.stop_cleanup()

    def test_quarantine_failure_does_not_propagate(self) -> None:
        """quarantine 自身失败（rename 抛 OSError）也不能让 ``_restore`` 抛
        异常 —— 否则 ``__init__`` 会直接挂掉，整个 server 启动失败。

        反向锁：``_quarantine_corrupt_persist_file`` 必须吞 OSError，
        ``_restore`` 必须仍然返回正常（用空队列继续）。
        """
        from unittest.mock import patch

        self.persist_path.write_text("garbage-not-json", encoding="utf-8")

        # 让 os.replace 在 quarantine 路径上抛 OSError（模拟权限不够 /
        # 磁盘满 / 跨设备 rename 失败）
        with patch(
            "task_queue.os.replace",
            side_effect=OSError("simulated quarantine failure"),
        ):
            # 不应抛异常 —— 队列正常构造
            q = self._make_queue()
            try:
                self.assertEqual(len(q.get_all_tasks()), 0)
            finally:
                q.stop_cleanup()

    def test_quarantine_called_from_restore_except(self) -> None:
        """反向锁：``_restore`` 顶层 except 必须调用 ``_quarantine_*``。

        如果未来重构把 quarantine 调用挪到错误位置（比如挪到 try 内部，
        或者删了），损坏文件会被静默覆盖，本测试立即红线。

        实现策略：mock ``_quarantine_corrupt_persist_file``，写一个会触发
        json.loads 失败的文件，断言 quarantine 被调用且接收到的 reason
        参数包含 'JSONDecodeError' 关键字（验证 except 中 reason=str(e)
        逻辑生效）。
        """
        from unittest.mock import patch

        self.persist_path.write_text("not-valid-json", encoding="utf-8")

        with patch("task_queue.TaskQueue._quarantine_corrupt_persist_file") as mock_q:
            q = self._make_queue()
            try:
                # quarantine 必须被调一次
                mock_q.assert_called_once()
                # 检查 reason 参数（kwarg）
                _, kwargs = mock_q.call_args
                self.assertIn("reason", kwargs)
                # JSON 解析错误的 str 表示通常包含 "JSONDecodeError" 或
                # 其错误描述（例如 "Expecting value"）；用宽松匹配。
                self.assertTrue(
                    "JSON" in kwargs["reason"]
                    or "Expecting" in kwargs["reason"]
                    or "expected" in kwargs["reason"].lower(),
                    f"reason 参数 {kwargs['reason']!r} 应反映原始 JSON 解析错误",
                )
            finally:
                q.stop_cleanup()


if __name__ == "__main__":
    unittest.main()
