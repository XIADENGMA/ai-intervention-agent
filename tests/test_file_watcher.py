"""file_watcher.py (FileWatcherMixin) 单元测试。

覆盖文件监听、回调管理、shutdown 的各分支：
- start/stop_file_watcher 基本流程
- 启动时检测文件已变更（mtime > 缓存）
- 启动时 mtime==0 的首次初始化
- _update_file_mtime 异常处理
- shutdown 清理 save_timer
- _file_watcher_loop 异常处理
- 回调注册/注销/执行异常
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from config_manager import ConfigManager


class TestFileWatcherStartStop(unittest.TestCase):
    """start/stop_file_watcher 基本流程"""

    def _get_manager(self) -> ConfigManager:
        return ConfigManager()

    def test_start_and_stop(self):
        mgr = self._get_manager()
        mgr.start_file_watcher(interval=0.1)
        self.assertTrue(mgr.is_file_watcher_running)
        mgr.stop_file_watcher()
        self.assertFalse(mgr.is_file_watcher_running)

    def test_start_twice_no_error(self):
        mgr = self._get_manager()
        mgr.start_file_watcher(interval=0.1)
        mgr.start_file_watcher(interval=0.1)
        self.assertTrue(mgr.is_file_watcher_running)
        mgr.stop_file_watcher()

    def test_stop_when_not_running(self):
        mgr = self._get_manager()
        mgr.stop_file_watcher()
        self.assertFalse(mgr.is_file_watcher_running)


class TestFileWatcherMtimeSync(unittest.TestCase):
    """启动时 mtime 同步"""

    def _get_manager(self) -> ConfigManager:
        return ConfigManager()

    def test_start_detects_mtime_change(self):
        """文件在上次加载后已修改 → 自动重载"""
        mgr = self._get_manager()
        with mgr._lock:
            mgr._last_file_mtime = 1.0
        if mgr.config_file.exists():
            mgr.start_file_watcher(interval=60)
            time.sleep(0.05)
            mgr.stop_file_watcher()

    def test_start_initializes_mtime_when_zero(self):
        """首次启动（mtime==0）→ 记录当前 mtime"""
        mgr = self._get_manager()
        with mgr._lock:
            mgr._last_file_mtime = 0
        if mgr.config_file.exists():
            mgr.start_file_watcher(interval=60)
            time.sleep(0.05)
            with mgr._lock:
                self.assertGreater(mgr._last_file_mtime, 0)
            mgr.stop_file_watcher()


class TestUpdateFileMtime(unittest.TestCase):
    """_update_file_mtime 方法"""

    def test_normal_update(self):
        mgr = ConfigManager()
        if mgr.config_file.exists():
            mgr._update_file_mtime()
            with mgr._lock:
                self.assertGreater(mgr._last_file_mtime, 0)

    def test_exception_handling(self):
        mgr = ConfigManager()
        with patch.object(type(mgr.config_file), "exists", side_effect=OSError("fail")):
            mgr._update_file_mtime()


class TestShutdown(unittest.TestCase):
    """shutdown 方法"""

    def test_shutdown_stops_watcher(self):
        mgr = ConfigManager()
        mgr.start_file_watcher(interval=0.1)
        mgr.shutdown()
        self.assertFalse(mgr.is_file_watcher_running)

    def test_shutdown_cancels_save_timer(self):
        mgr = ConfigManager()
        timer = threading.Timer(999, lambda: None)
        with mgr._lock:
            mgr._save_timer = timer
        mgr.shutdown()
        with mgr._lock:
            self.assertIsNone(mgr._save_timer)
        self.assertTrue(timer.finished.is_set())

    def test_shutdown_idempotent(self):
        mgr = ConfigManager()
        mgr.shutdown()
        mgr.shutdown()

    def test_shutdown_handles_watcher_exception(self):
        mgr = ConfigManager()
        with patch.object(mgr, "stop_file_watcher", side_effect=RuntimeError("fail")):
            mgr.shutdown()


class TestFileWatcherLoop(unittest.TestCase):
    """_file_watcher_loop 异常处理"""

    def test_loop_handles_exception(self):
        mgr = ConfigManager()
        mgr._file_watcher_running = True
        mgr._file_watcher_interval = 0.01

        call_count = 0
        original_exists = mgr.config_file.exists

        def mock_exists():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise OSError("disk error")
            mgr._file_watcher_running = False
            return original_exists()

        with patch.object(type(mgr.config_file), "exists", side_effect=mock_exists):
            mgr._file_watcher_loop()

        self.assertGreaterEqual(call_count, 2)


class TestCallbackManagement(unittest.TestCase):
    """回调注册/注销/执行"""

    def _get_manager(self) -> ConfigManager:
        return ConfigManager()

    def test_register_and_trigger(self):
        mgr = self._get_manager()
        results = []
        cb = lambda: results.append("called")  # noqa: E731
        mgr.register_config_change_callback(cb)
        mgr._trigger_config_change_callbacks()
        self.assertEqual(results, ["called"])

    def test_register_duplicate_ignored(self):
        mgr = self._get_manager()
        cb = MagicMock()
        mgr.register_config_change_callback(cb)
        mgr.register_config_change_callback(cb)
        mgr._trigger_config_change_callbacks()
        cb.assert_called_once()

    def test_unregister_callback(self):
        mgr = self._get_manager()
        cb = MagicMock()
        mgr.register_config_change_callback(cb)
        mgr.unregister_config_change_callback(cb)
        mgr._trigger_config_change_callbacks()
        cb.assert_not_called()

    def test_unregister_nonexistent(self):
        mgr = self._get_manager()
        mgr.unregister_config_change_callback(lambda: None)

    def test_callback_exception_isolated(self):
        """一个回调异常不影响其他回调执行"""
        mgr = self._get_manager()
        results = []
        bad_cb = MagicMock(side_effect=RuntimeError("boom"))
        good_cb = lambda: results.append("ok")  # noqa: E731
        mgr.register_config_change_callback(bad_cb)
        mgr.register_config_change_callback(good_cb)
        mgr._trigger_config_change_callbacks()
        self.assertEqual(results, ["ok"])
        bad_cb.assert_called_once()


if __name__ == "__main__":
    unittest.main()
