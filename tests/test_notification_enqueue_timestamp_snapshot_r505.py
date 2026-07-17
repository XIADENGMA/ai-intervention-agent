"""R505 - notification enqueue uses one creation timestamp snapshot."""

from __future__ import annotations

import inspect
import re
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from ai_intervention_agent.notification_manager import (
    NotificationConfig,
    NotificationManager,
)
from ai_intervention_agent.notification_models import (
    NotificationTrigger,
    NotificationType,
)


def _make_manager() -> NotificationManager:
    mgr = NotificationManager.__new__(NotificationManager)
    mgr._initialized = True
    mgr.config = NotificationConfig()
    mgr._providers = {}
    mgr._providers_lock = threading.Lock()
    mgr._event_queue = []
    mgr._queue_lock = threading.Lock()
    mgr._config_lock = threading.Lock()
    mgr._config_file_mtime = 0.0
    mgr._worker_thread = None
    mgr._stop_event = threading.Event()
    mgr._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="TestWorker")
    mgr._delayed_timers = {}
    mgr._delayed_timers_lock = threading.Lock()
    mgr._shutdown_called = False
    mgr._stats_lock = threading.Lock()
    mgr._stats = {
        "events_total": 0,
        "events_succeeded": 0,
        "events_failed": 0,
        "attempts_total": 0,
        "retries_scheduled": 0,
        "last_event_id": None,
        "last_event_at": None,
        "providers": {},
    }
    mgr._provider_latency_histograms = {}
    mgr._finalized_event_ids = {}
    mgr._finalized_max_size = 500
    mgr._callbacks_lock = threading.Lock()
    mgr._callbacks = {}
    mgr._inflight_persisted_ids = set()
    mgr._inflight_seen_at_startup = []
    return mgr


class TestNotificationEnqueueTimestampSnapshot(unittest.TestCase):
    def test_send_notification_uses_single_creation_time_snapshot(self) -> None:
        source = inspect.getsource(NotificationManager.send_notification)

        self.assertIn("created_at_ts = time.time()", source)
        self.assertIn("int(created_at_ts * 1000)", source)
        self.assertIn('self._stats["last_event_at"] = created_at_ts', source)
        self.assertNotIn('self._stats["last_event_at"] = time.time()', source)

    def test_event_id_timestamp_and_last_event_at_share_snapshot(self) -> None:
        mgr = _make_manager()
        created_at_ts = 1_700_000_000.123

        # patch("...notification_manager.time.time") 实际改写的是**全局 time
        # 模块**的 time 属性（notification_manager.time 就是共享的 time 模块
        # 对象）。补丁窗口内其他代码也可能调用 time.time()：
        #   - 相邻测试在同一 xdist worker 上启动的后台线程（config 文件监听 /
        #     TaskQueue 清理线程）；
        #   - EnhancedLogger 的结构化日志路径（enhanced_logging 的 ts_unix
        #     字段），当相邻测试把日志级别调到 DEBUG 时 ``send_notification``
        #     内部的 logger.debug 也会额外调用一次 time.time()。
        # 因此**不能**用 call_count 断言"只调用一次"——那是对全局补丁面的
        # 过强假设。改为序列时间戳断言：每次调用返回递增值，若实现回归为
        # "event_id 与 stats 分别读时钟"，两者数值必然不同而失败；额外的
        # 日志/后台线程调用只会消耗后续序列值，不影响断言。
        call_sequence: list[float] = []

        def _fake_time() -> float:
            value = created_at_ts + len(call_sequence) * 1000.0
            call_sequence.append(value)
            return value

        try:
            with (
                patch(
                    "ai_intervention_agent.notification_manager.time.time",
                    side_effect=_fake_time,
                ),
                patch.object(mgr, "_track_event_inflight") as fake_track,
                patch.object(mgr, "_process_event") as fake_process,
            ):
                event_id = mgr.send_notification(
                    "title",
                    "message",
                    trigger=NotificationTrigger.IMMEDIATE,
                    types=[NotificationType.WEB],
                )

            self.assertGreaterEqual(len(call_sequence), 1)
            self.assertEqual(fake_track.call_count, 1)
            self.assertEqual(fake_process.call_count, 1)
            self.assertEqual(mgr._stats["last_event_at"], created_at_ts)
            self.assertEqual(mgr._stats["last_event_id"], event_id)

            match = re.match(r"notification_(\d+)_", event_id)
            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(int(match.group(1)), int(created_at_ts * 1000))
        finally:
            mgr._executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
