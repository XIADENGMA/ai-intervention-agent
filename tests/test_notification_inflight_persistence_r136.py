"""R136 · 通知 in-flight 队列断电恢复持久化契约测试。

背景
----
在 R136 之前，``NotificationManager._event_queue`` /
``_finalized_event_ids`` 都在内存里，进程异常退出（崩溃 / SIGKILL /
OOM / 容器被驱逐）时彻底丢——运维侧完全看不到"上次重启时还有 N 条
通知没投递"。R136 落地「inflight 持久化」：
- 入队时把事件 id + 序列化 dump 写到 config dir 的
  ``notification_inflight.json``；
- 事件最终化（成功或失败）时从持久化集合摘除并刷盘；
- 启动时一次性 load 文件，TTL 过滤后暴露给 ``get_status()``——不自动
  重发，避免「重启后用户被旧通知刷屏」尴尬。

设计契约（6 个 invariant class，共 23 cases）：

1. **常量与文件路径** — ``_INFLIGHT_FILE_NAME`` /
   ``_INFLIGHT_SCHEMA_VERSION`` / ``_INFLIGHT_TTL_SECONDS`` 锁定；
   ``_get_inflight_file_dir`` 复用 config dir。

2. **`_load_persisted_inflight_events` 容错** — 缺文件 / JSON 损坏 /
   schema 不匹配 / events 不是 list / 元素不是 dict 都返回 ``[]`` 不
   抛错。

3. **TTL 过滤** — saved_at_ts 距今超 ``_INFLIGHT_TTL_SECONDS`` 的事件
   load 时被过滤掉。

4. **`_persist_inflight_unlocked` 写盘** — 空集合时删除文件；非空时
   atomic write（``.tmp`` → ``os.replace``）。

5. **`_track_event_inflight` / `_untrack_event_inflight`** — 加 id 后
   文件含 event；删 id 后文件不再含 event；最后一个 id 删除后文件被
   主动 unlink。

6. **`get_status()` R136 字段** — ``inflight_persisted_count`` /
   ``inflight_seen_at_startup`` 在 status 顶层暴露；后者是 list 副本
   不直接暴露内部状态。
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_intervention_agent.notification_manager import (
    _INFLIGHT_FILE_NAME,
    _INFLIGHT_SCHEMA_VERSION,
    _INFLIGHT_TTL_SECONDS,
    NotificationManager,
)
from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationPriority,
    NotificationTrigger,
    NotificationType,
)


def _make_event(event_id: str = "test-evt") -> NotificationEvent:
    """构造测试用 NotificationEvent。"""
    return NotificationEvent(
        id=event_id,
        title="hello",
        message="world",
        trigger=NotificationTrigger.IMMEDIATE,
        types=[NotificationType.WEB],
        max_retries=3,
        priority=NotificationPriority.NORMAL,
    )


# ----------------------------------------------------------------------------
# 1. 常量与文件路径
# ----------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    def test_filename_constant(self) -> None:
        self.assertEqual(_INFLIGHT_FILE_NAME, "notification_inflight.json")

    def test_schema_version_constant(self) -> None:
        self.assertEqual(_INFLIGHT_SCHEMA_VERSION, 1)

    def test_ttl_constant(self) -> None:
        # 5 分钟 TTL（300 秒）— 关电脑回家场景的边界
        self.assertEqual(_INFLIGHT_TTL_SECONDS, 300)


class _ManagerWithTmpInflight(unittest.TestCase):
    """给每个用例造一个独立 tmp dir 的 NotificationManager 测试基类。

    - 用 ``patch`` 把 ``_get_inflight_file_dir`` 重定向到 tmp dir，
      保证测试间不互相污染、不影响真实 config dir。
    - NotificationManager 是单例，但 ``_inflight_persisted_ids`` /
      ``_inflight_seen_at_startup`` 字段可以直接 reset。
    """

    def setUp(self) -> None:
        import tempfile

        self._tmp_dir = Path(tempfile.mkdtemp(prefix="r136_"))
        self._patcher = patch(
            "ai_intervention_agent.notification_manager._get_inflight_file_dir",
            return_value=self._tmp_dir,
        )
        self._patcher.start()
        self._manager = NotificationManager()
        # reset state（单例可能携带其他测试副作用）
        self._manager._inflight_persisted_ids = set()
        self._manager._inflight_seen_at_startup = []
        # _event_queue 也清空避免污染
        with self._manager._queue_lock:
            self._manager._event_queue = []

    def tearDown(self) -> None:
        self._patcher.stop()
        # 清理 tmp dir
        import shutil

        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    @property
    def _file_path(self) -> Path:
        return self._tmp_dir / _INFLIGHT_FILE_NAME


# ----------------------------------------------------------------------------
# 2. _load_persisted_inflight_events 容错
# ----------------------------------------------------------------------------


class TestLoadGracefulFailures(_ManagerWithTmpInflight):
    def test_missing_file_returns_empty(self) -> None:
        self.assertFalse(self._file_path.exists())
        result = self._manager._load_persisted_inflight_events()
        self.assertEqual(result, [])

    def test_corrupt_json_returns_empty(self) -> None:
        self._file_path.write_text("{ not valid json")
        result = self._manager._load_persisted_inflight_events()
        self.assertEqual(result, [])

    def test_non_dict_root_returns_empty(self) -> None:
        # 顶层不是 dict（list / str / int）都返回 []
        self._file_path.write_text(json.dumps([]))
        self.assertEqual(self._manager._load_persisted_inflight_events(), [])
        self._file_path.write_text(json.dumps("just a string"))
        self.assertEqual(self._manager._load_persisted_inflight_events(), [])

    def test_schema_version_mismatch_returns_empty(self) -> None:
        self._file_path.write_text(
            json.dumps(
                {
                    "schema_version": 99,
                    "events": [{"id": "x", "saved_at_ts": time.time()}],
                }
            )
        )
        result = self._manager._load_persisted_inflight_events()
        self.assertEqual(result, [])

    def test_events_not_a_list_returns_empty(self) -> None:
        self._file_path.write_text(
            json.dumps(
                {
                    "schema_version": _INFLIGHT_SCHEMA_VERSION,
                    "events": "this should be a list",
                }
            )
        )
        result = self._manager._load_persisted_inflight_events()
        self.assertEqual(result, [])

    def test_non_dict_entry_skipped(self) -> None:
        # 单元素不是 dict 时 skip 该元素，其他 dict 元素保留
        valid_entry = {
            "id": "ok",
            "title": "t",
            "saved_at_ts": time.time(),
        }
        self._file_path.write_text(
            json.dumps(
                {
                    "schema_version": _INFLIGHT_SCHEMA_VERSION,
                    "events": ["string-not-dict", 42, valid_entry],
                }
            )
        )
        result = self._manager._load_persisted_inflight_events()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "ok")


# ----------------------------------------------------------------------------
# 3. TTL 过滤
# ----------------------------------------------------------------------------


class TestTtlFilter(_ManagerWithTmpInflight):
    def test_fresh_event_kept(self) -> None:
        fresh = {"id": "fresh", "saved_at_ts": time.time() - 10}
        self._file_path.write_text(
            json.dumps(
                {
                    "schema_version": _INFLIGHT_SCHEMA_VERSION,
                    "events": [fresh],
                }
            )
        )
        result = self._manager._load_persisted_inflight_events()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "fresh")

    def test_expired_event_dropped(self) -> None:
        expired = {
            "id": "expired",
            "saved_at_ts": time.time() - _INFLIGHT_TTL_SECONDS - 60,
        }
        self._file_path.write_text(
            json.dumps(
                {
                    "schema_version": _INFLIGHT_SCHEMA_VERSION,
                    "events": [expired],
                }
            )
        )
        result = self._manager._load_persisted_inflight_events()
        self.assertEqual(result, [])

    def test_invalid_saved_at_ts_dropped(self) -> None:
        # ``saved_at_ts`` 不是 int/float 时被丢弃，不抛异常
        bad = {"id": "bad", "saved_at_ts": "not a number"}
        self._file_path.write_text(
            json.dumps(
                {
                    "schema_version": _INFLIGHT_SCHEMA_VERSION,
                    "events": [bad],
                }
            )
        )
        result = self._manager._load_persisted_inflight_events()
        self.assertEqual(result, [])


# ----------------------------------------------------------------------------
# 4. _persist_inflight_unlocked 写盘
# ----------------------------------------------------------------------------


class TestPersistWritePath(_ManagerWithTmpInflight):
    def test_empty_set_removes_existing_file(self) -> None:
        # 先写一个文件
        self._file_path.write_text("{}")
        self.assertTrue(self._file_path.exists())
        # 集合空时 persist 应当删文件
        with self._manager._queue_lock:
            self._manager._inflight_persisted_ids = set()
            self._manager._persist_inflight_unlocked()
        self.assertFalse(self._file_path.exists())

    def test_empty_set_no_file_no_op(self) -> None:
        # 集合空且文件原本就不存在 → 静默 no-op
        self.assertFalse(self._file_path.exists())
        with self._manager._queue_lock:
            self._manager._inflight_persisted_ids = set()
            self._manager._persist_inflight_unlocked()
        self.assertFalse(self._file_path.exists())

    def test_non_empty_writes_envelope_with_schema(self) -> None:
        evt = _make_event("evt-write")
        with self._manager._queue_lock:
            self._manager._event_queue.append(evt)
            self._manager._inflight_persisted_ids = {evt.id}
            self._manager._persist_inflight_unlocked()
        self.assertTrue(self._file_path.exists())
        data = json.loads(self._file_path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], _INFLIGHT_SCHEMA_VERSION)
        self.assertIn("saved_at", data)
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["id"], "evt-write")
        self.assertIn("saved_at_ts", data["events"][0])

    def test_atomic_write_no_tmp_left(self) -> None:
        # atomic 写后 .tmp 必须被 os.replace 消化掉，不留尾巴
        evt = _make_event("evt-atomic")
        with self._manager._queue_lock:
            self._manager._event_queue.append(evt)
            self._manager._inflight_persisted_ids = {evt.id}
            self._manager._persist_inflight_unlocked()
        leftover = list(self._tmp_dir.glob("*.tmp"))
        self.assertEqual(leftover, [], "atomic write 后不应残留 .tmp 文件")


# ----------------------------------------------------------------------------
# 5. _track / _untrack 行为
# ----------------------------------------------------------------------------


class TestTrackUntrackBehavior(_ManagerWithTmpInflight):
    def test_track_writes_event_to_disk(self) -> None:
        evt = _make_event("evt-track-1")
        with self._manager._queue_lock:
            self._manager._event_queue.append(evt)
        self._manager._track_event_inflight(evt)
        self.assertIn(evt.id, self._manager._inflight_persisted_ids)
        self.assertTrue(self._file_path.exists())
        data = json.loads(self._file_path.read_text(encoding="utf-8"))
        ids = [e["id"] for e in data["events"]]
        self.assertIn(evt.id, ids)

    def test_untrack_removes_event_from_disk(self) -> None:
        evt_a = _make_event("evt-a")
        evt_b = _make_event("evt-b")
        with self._manager._queue_lock:
            self._manager._event_queue.extend([evt_a, evt_b])
        self._manager._track_event_inflight(evt_a)
        self._manager._track_event_inflight(evt_b)
        self.assertEqual(len(self._manager._inflight_persisted_ids), 2)

        self._manager._untrack_event_inflight(evt_a.id)
        self.assertNotIn(evt_a.id, self._manager._inflight_persisted_ids)
        self.assertIn(evt_b.id, self._manager._inflight_persisted_ids)
        # 文件仍存在（还有 evt_b）
        self.assertTrue(self._file_path.exists())
        data = json.loads(self._file_path.read_text(encoding="utf-8"))
        ids = [e["id"] for e in data["events"]]
        self.assertEqual(ids, ["evt-b"])

    def test_last_untrack_removes_file(self) -> None:
        evt = _make_event("evt-only")
        with self._manager._queue_lock:
            self._manager._event_queue.append(evt)
        self._manager._track_event_inflight(evt)
        self.assertTrue(self._file_path.exists())

        self._manager._untrack_event_inflight(evt.id)
        self.assertEqual(self._manager._inflight_persisted_ids, set())
        self.assertFalse(
            self._file_path.exists(),
            "最后一个 in-flight 事件 untrack 后磁盘文件应当被删除",
        )

    def test_untrack_unknown_id_is_safe(self) -> None:
        # 未知 id 不在集合内 → 静默 no-op，不抛错
        self._manager._untrack_event_inflight("never-tracked")
        self.assertEqual(self._manager._inflight_persisted_ids, set())


# ----------------------------------------------------------------------------
# 6. get_status() R136 字段
# ----------------------------------------------------------------------------


class TestGetStatusFields(_ManagerWithTmpInflight):
    def test_status_contains_inflight_persisted_count(self) -> None:
        status = self._manager.get_status()
        self.assertIn("inflight_persisted_count", status)
        self.assertEqual(status["inflight_persisted_count"], 0)

    def test_inflight_persisted_count_reflects_current_set(self) -> None:
        evt = _make_event("evt-status-count")
        with self._manager._queue_lock:
            self._manager._event_queue.append(evt)
        self._manager._track_event_inflight(evt)
        status = self._manager.get_status()
        self.assertEqual(status["inflight_persisted_count"], 1)

    def test_status_contains_inflight_seen_at_startup_list(self) -> None:
        status = self._manager.get_status()
        self.assertIn("inflight_seen_at_startup", status)
        self.assertIsInstance(status["inflight_seen_at_startup"], list)

    def test_inflight_seen_at_startup_is_copy_not_internal_ref(self) -> None:
        # 内部状态被外部修改不应影响 manager 内部
        self._manager._inflight_seen_at_startup = [{"id": "boot-1"}]
        status = self._manager.get_status()
        seen = status["inflight_seen_at_startup"]
        seen.append({"id": "external-mutation"})
        # 内部仍是 1 条
        self.assertEqual(len(self._manager._inflight_seen_at_startup), 1)


if __name__ == "__main__":
    unittest.main()
