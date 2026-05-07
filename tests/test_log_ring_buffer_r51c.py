"""R51-C：``enhanced_logging`` ring buffer + ``server_info`` recent_logs 契约。

覆盖项：

  1. ``_record_to_ring`` 把 WARNING+ 日志推入 buffer，DEBUG/INFO 不进。
  2. ring buffer 容量受 ``_LOG_RING_MAXLEN`` 上限约束（不会无限涨）。
  3. 单条 message 超过 ``_LOG_RING_MESSAGE_MAXLEN`` 字符会被截断。
  4. 内容自动脱敏（含 password / sk- / ghp_ 等模式时被替换）。
  5. 多线程并发 ``_record_to_ring`` 不丢更新且不抛。
  6. ``get_recent_logs(limit=N)`` 返回浅拷贝、按时间正序、长度受 limit 约束。
  7. ``EnhancedLogger.warning`` / ``.error`` 走完整 ``log`` 路径会进 buffer。
  8. ``server.server_info_resource`` 暴露 ``recent_logs`` 子块、字段齐全、
     ``limit=20`` 上限生效。
"""

from __future__ import annotations

import logging
import sys
import threading
import unittest
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import enhanced_logging
import server


class TestRingBufferLevelFiltering(unittest.TestCase):
    """``_record_to_ring`` 必须只接受 WARNING+ 的日志。"""

    def setUp(self) -> None:
        enhanced_logging.clear_recent_logs()

    def test_debug_not_recorded(self) -> None:
        enhanced_logging._record_to_ring(logging.DEBUG, "test", "ignored")
        self.assertEqual(enhanced_logging.get_recent_logs(), [])

    def test_info_not_recorded(self) -> None:
        enhanced_logging._record_to_ring(logging.INFO, "test", "ignored")
        self.assertEqual(enhanced_logging.get_recent_logs(), [])

    def test_warning_recorded(self) -> None:
        enhanced_logging._record_to_ring(logging.WARNING, "test", "warn-msg")
        entries = enhanced_logging.get_recent_logs()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["level_name"], "WARNING")
        self.assertEqual(entries[0]["message"], "warn-msg")

    def test_error_recorded(self) -> None:
        enhanced_logging._record_to_ring(logging.ERROR, "test", "err-msg")
        entries = enhanced_logging.get_recent_logs()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["level_name"], "ERROR")

    def test_critical_recorded(self) -> None:
        enhanced_logging._record_to_ring(logging.CRITICAL, "test", "crit-msg")
        entries = enhanced_logging.get_recent_logs()
        self.assertEqual(len(entries), 1)


class TestRingBufferCapacity(unittest.TestCase):
    """ring buffer 容量受 ``_LOG_RING_MAXLEN`` 约束。"""

    def setUp(self) -> None:
        enhanced_logging.clear_recent_logs()

    def test_buffer_caps_at_maxlen(self) -> None:
        maxlen = enhanced_logging._LOG_RING_MAXLEN
        for i in range(maxlen + 50):
            enhanced_logging._record_to_ring(logging.WARNING, "test", f"msg-{i}")
        entries = enhanced_logging.get_recent_logs()
        self.assertEqual(len(entries), maxlen)
        # 最早的 50 条应当被 evict
        self.assertEqual(entries[0]["message"], "msg-50")
        self.assertEqual(entries[-1]["message"], f"msg-{maxlen + 49}")


class TestRingBufferTruncation(unittest.TestCase):
    """超长 message 自动截断。"""

    def setUp(self) -> None:
        enhanced_logging.clear_recent_logs()

    def test_long_message_truncated(self) -> None:
        maxlen = enhanced_logging._LOG_RING_MESSAGE_MAXLEN
        long_msg = "X" * (maxlen + 100)
        enhanced_logging._record_to_ring(logging.WARNING, "test", long_msg)
        entries = enhanced_logging.get_recent_logs()
        self.assertEqual(len(entries), 1)
        # 长度 = maxlen + 1（包含末尾 …）
        self.assertEqual(len(entries[0]["message"]), maxlen + 1)
        self.assertTrue(entries[0]["message"].endswith("…"))


class TestRingBufferSanitization(unittest.TestCase):
    """ring buffer 内容必须脱敏。"""

    def setUp(self) -> None:
        enhanced_logging.clear_recent_logs()

    def test_password_redacted(self) -> None:
        enhanced_logging._record_to_ring(
            logging.WARNING, "test", "password=verysecret123"
        )
        entries = enhanced_logging.get_recent_logs()
        self.assertEqual(len(entries), 1)
        # ``LogSanitizer`` 会用 ``***REDACTED***`` 替换
        self.assertIn("REDACTED", entries[0]["message"])
        self.assertNotIn("verysecret123", entries[0]["message"])

    def test_openai_key_redacted(self) -> None:
        fake_key = "sk-" + "a" * 40
        enhanced_logging._record_to_ring(
            logging.ERROR, "test", f"call failed: {fake_key} bad"
        )
        entries = enhanced_logging.get_recent_logs()
        self.assertEqual(len(entries), 1)
        self.assertIn("REDACTED", entries[0]["message"])
        self.assertNotIn(fake_key, entries[0]["message"])


class TestRingBufferThreadSafety(unittest.TestCase):
    """多线程并发推入不丢更新且不抛。"""

    def setUp(self) -> None:
        enhanced_logging.clear_recent_logs()

    def test_concurrent_recordings(self) -> None:
        threads_count = 4
        bumps_per_thread = 25
        # 必须 < _LOG_RING_MAXLEN，否则会 evict 让计数失真
        total = threads_count * bumps_per_thread
        self.assertLess(total, enhanced_logging._LOG_RING_MAXLEN)

        def _worker(tid: int) -> None:
            for i in range(bumps_per_thread):
                enhanced_logging._record_to_ring(
                    logging.WARNING, "thread", f"t{tid}-msg{i}"
                )

        threads = [
            threading.Thread(target=_worker, args=(i,)) for i in range(threads_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        entries = enhanced_logging.get_recent_logs()
        self.assertEqual(len(entries), total)


class TestGetRecentLogsAPI(unittest.TestCase):
    """``get_recent_logs`` 的返回值必须是 copy 且按时间正序。"""

    def setUp(self) -> None:
        enhanced_logging.clear_recent_logs()
        for i in range(10):
            enhanced_logging._record_to_ring(logging.WARNING, "test", f"msg-{i}")

    def test_returns_copy_not_reference(self) -> None:
        first = enhanced_logging.get_recent_logs()
        first.clear()
        # ring buffer 本身不应被影响
        second = enhanced_logging.get_recent_logs()
        self.assertEqual(len(second), 10)

    def test_limit_param_truncates_to_last_n(self) -> None:
        last_3 = enhanced_logging.get_recent_logs(limit=3)
        self.assertEqual(len(last_3), 3)
        self.assertEqual(last_3[0]["message"], "msg-7")
        self.assertEqual(last_3[-1]["message"], "msg-9")

    def test_limit_none_returns_all(self) -> None:
        all_entries = enhanced_logging.get_recent_logs(limit=None)
        self.assertEqual(len(all_entries), 10)

    def test_entries_in_chronological_order(self) -> None:
        entries = enhanced_logging.get_recent_logs()
        for i, entry in enumerate(entries):
            self.assertEqual(entry["message"], f"msg-{i}")


class TestEnhancedLoggerIntegration(unittest.TestCase):
    """``EnhancedLogger.warning`` / ``.error`` 必须把日志推入 ring buffer。"""

    def setUp(self) -> None:
        enhanced_logging.clear_recent_logs()

    def test_warning_call_recorded(self) -> None:
        log = enhanced_logging.EnhancedLogger("test_r51c_integration")
        log.setLevel(logging.WARNING)
        log.warning("integration-warn")
        entries = enhanced_logging.get_recent_logs()
        self.assertGreaterEqual(len(entries), 1)
        # 找我们的 logger name
        ours = [e for e in entries if "test_r51c_integration" in e["logger_name"]]
        self.assertGreaterEqual(len(ours), 1)
        self.assertEqual(ours[-1]["level_name"], "WARNING")

    def test_error_call_recorded(self) -> None:
        log = enhanced_logging.EnhancedLogger("test_r51c_integration_err")
        log.setLevel(logging.WARNING)
        log.error("integration-err")
        entries = enhanced_logging.get_recent_logs()
        ours = [e for e in entries if "test_r51c_integration_err" in e["logger_name"]]
        self.assertGreaterEqual(len(ours), 1)
        self.assertEqual(ours[-1]["level_name"], "ERROR")


class TestServerInfoExposesRecentLogs(unittest.TestCase):
    """``server.server_info_resource`` 必须暴露 ``recent_logs`` 子块。"""

    def setUp(self) -> None:
        enhanced_logging.clear_recent_logs()

    def test_recent_logs_key_present(self) -> None:
        info = server.server_info_resource()
        self.assertIn("recent_logs", info)

    def test_recent_logs_block_is_dict(self) -> None:
        info = server.server_info_resource()
        block = info["recent_logs"]
        self.assertIsInstance(block, dict)

    def test_recent_logs_includes_count_and_entries_when_buffer_has_data(self) -> None:
        enhanced_logging._record_to_ring(logging.WARNING, "x", "warn-from-test")
        enhanced_logging._record_to_ring(logging.ERROR, "x", "err-from-test")
        info = server.server_info_resource()
        block = cast(dict[str, Any], info["recent_logs"])
        self.assertIn("count", block)
        self.assertIn("entries", block)
        self.assertEqual(block["count"], 2)
        msgs = [e["message"] for e in block["entries"]]
        self.assertIn("warn-from-test", msgs)
        self.assertIn("err-from-test", msgs)

    def test_recent_logs_limit_caps_at_20(self) -> None:
        for i in range(50):
            enhanced_logging._record_to_ring(logging.WARNING, "x", f"bulk-{i}")
        info = server.server_info_resource()
        block = cast(dict[str, Any], info["recent_logs"])
        self.assertLessEqual(block["count"], 20)
        self.assertLessEqual(len(block["entries"]), 20)


if __name__ == "__main__":
    unittest.main()
