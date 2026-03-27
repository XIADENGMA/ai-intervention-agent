"""notification_manager.py 覆盖率补充测试。

覆盖 NotificationConfig 边界、send_notification 路由、
_process_event 重试/降级/超时、_send_single_notification 统计、
shutdown/restart、refresh/update_config、get_status 等。
"""

from __future__ import annotations

import threading
import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from notification_models import (
    NotificationEvent,
    NotificationPriority,
    NotificationTrigger,
    NotificationType,
)


def _make_manager():
    """创建一个干净的 NotificationManager 实例（绕过单例）"""
    from notification_manager import NotificationConfig, NotificationManager

    NotificationManager._instance = None
    mgr = NotificationManager.__new__(NotificationManager)
    mgr._initialized = False
    mgr.config = NotificationConfig()
    mgr._providers = {}
    mgr._providers_lock = threading.Lock()
    mgr._event_queue = []
    mgr._queue_lock = threading.Lock()
    mgr._config_lock = threading.Lock()
    mgr._config_file_mtime = 0.0
    mgr._worker_thread = None
    mgr._stop_event = threading.Event()
    from concurrent.futures import ThreadPoolExecutor

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
    mgr._finalized_event_ids = set()
    mgr._callbacks_lock = threading.Lock()
    mgr._callbacks = {}
    mgr._initialized = True
    return mgr


def _make_event(**kw) -> NotificationEvent:
    defaults: dict[str, Any] = {
        "id": "test_001",
        "title": "Test",
        "message": "Hello",
        "trigger": NotificationTrigger.IMMEDIATE,
        "types": [NotificationType.WEB],
        "metadata": {},
        "max_retries": 3,
        "priority": NotificationPriority.NORMAL,
    }
    defaults.update(kw)
    return NotificationEvent(**defaults)


# ──────────────────────────────────────────────────────────
# NotificationConfig 边界
# ──────────────────────────────────────────────────────────


class TestNotificationConfigEdgeCases(unittest.TestCase):
    def test_retry_count_string_coerced(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(retry_count="5")  # type: ignore[arg-type]
        self.assertEqual(cfg.retry_count, 5)

    def test_retry_count_invalid_string(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(retry_count="abc")  # type: ignore[arg-type]
        self.assertEqual(cfg.retry_count, 3)

    def test_retry_delay_invalid(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(retry_delay="bad")  # type: ignore[arg-type]
        self.assertEqual(cfg.retry_delay, 2)

    def test_bark_timeout_invalid(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(bark_timeout="x")  # type: ignore[arg-type]
        self.assertEqual(cfg.bark_timeout, 10)

    def test_bark_action_invalid_enum(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(bark_action="invalid_action")
        self.assertEqual(cfg.bark_action, "none")

    def test_bark_url_invalid_warns(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(
            bark_url="ftp://bad", bark_enabled=True, bark_device_key="k"
        )
        self.assertEqual(cfg.bark_url, "ftp://bad")

    def test_bark_enabled_no_device_key_warns(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(bark_enabled=True, bark_device_key="")
        self.assertTrue(cfg.bark_enabled)

    def test_from_config_file_unavailable(self):
        from exceptions import NotificationError
        from notification_manager import NotificationConfig

        with patch("notification_manager.CONFIG_FILE_AVAILABLE", False):
            self.assertRaises(NotificationError, NotificationConfig.from_config_file)

    def test_from_config_file_volume_invalid(self):
        from notification_manager import NotificationConfig

        mock_cfg = MagicMock()
        section = {
            "sound_volume": "bad",
            "enabled": True,
        }
        mock_cfg.get_section.return_value = section

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            cfg = NotificationConfig.from_config_file()
            self.assertAlmostEqual(cfg.sound_volume, 0.8, places=2)

    def test_from_config_file_safe_bool_branches(self):
        from notification_manager import NotificationConfig

        mock_cfg = MagicMock()
        section = {
            "enabled": 1,
            "debug": "unknown_str",
            "sound_volume": 50,
        }
        mock_cfg.get_section.return_value = section

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            cfg = NotificationConfig.from_config_file()
            self.assertTrue(cfg.enabled)
            self.assertFalse(cfg.debug)


# ──────────────────────────────────────────────────────────
# register_provider 替换旧 provider
# ──────────────────────────────────────────────────────────


class TestRegisterProvider(unittest.TestCase):
    def test_replace_old_provider_closes_it(self):
        mgr = _make_manager()
        old = MagicMock()
        new = MagicMock()
        mgr.register_provider(NotificationType.WEB, old)
        mgr.register_provider(NotificationType.WEB, new)
        old.close.assert_called_once()

    def test_safe_close_provider_no_close(self):
        from notification_manager import NotificationManager

        NotificationManager._safe_close_provider(object())

    def test_safe_close_provider_exception(self):
        from notification_manager import NotificationManager

        p = MagicMock()
        p.close.side_effect = RuntimeError("fail")
        NotificationManager._safe_close_provider(p)


# ──────────────────────────────────────────────────────────
# add_callback / trigger_callbacks
# ──────────────────────────────────────────────────────────


class TestCallbacks(unittest.TestCase):
    def test_add_and_trigger(self):
        mgr = _make_manager()
        results: list[str] = []
        mgr.add_callback("test_event", lambda: results.append("called"))
        mgr.trigger_callbacks("test_event")
        self.assertEqual(results, ["called"])

    def test_callback_exception_doesnt_break(self):
        mgr = _make_manager()

        def bad():
            raise RuntimeError("boom")

        mgr.add_callback("evt", bad)
        mgr.add_callback("evt", lambda: None)
        mgr.trigger_callbacks("evt")


# ──────────────────────────────────────────────────────────
# send_notification 路由
# ──────────────────────────────────────────────────────────


class TestSendNotification(unittest.TestCase):
    def test_disabled_returns_empty(self):
        mgr = _make_manager()
        mgr.config.enabled = False
        result = mgr.send_notification("t", "m")
        self.assertEqual(result, "")

    def test_shutdown_returns_empty(self):
        mgr = _make_manager()
        mgr._shutdown_called = True
        result = mgr.send_notification("t", "m")
        self.assertEqual(result, "")

    def test_auto_types_selection(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr.config.web_enabled = True
        mgr.config.sound_enabled = False
        mgr.config.bark_enabled = True
        mgr.config.system_enabled = True

        event_id = mgr.send_notification("t", "m")
        self.assertNotEqual(event_id, "")

    def test_priority_string_conversion(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event_id = mgr.send_notification(
            "t", "m", types=[NotificationType.WEB], priority="high"
        )
        self.assertNotEqual(event_id, "")

    def test_priority_invalid_string(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event_id = mgr.send_notification(
            "t", "m", types=[NotificationType.WEB], priority="invalid"
        )
        self.assertNotEqual(event_id, "")

    def test_delayed_trigger(self):
        mgr = _make_manager()
        event_id = mgr.send_notification(
            "t",
            "m",
            trigger=NotificationTrigger.DELAYED,
            types=[NotificationType.WEB],
        )
        self.assertNotEqual(event_id, "")
        with mgr._delayed_timers_lock:
            for t in mgr._delayed_timers.values():
                t.cancel()

    def test_delayed_trigger_after_shutdown(self):
        mgr = _make_manager()
        mgr._shutdown_called = True
        event_id = mgr.send_notification(
            "t", "m", trigger=NotificationTrigger.DELAYED, types=[NotificationType.WEB]
        )
        self.assertEqual(event_id, "")

    def test_queue_trimming(self):
        mgr = _make_manager()
        mgr.config.enabled = True
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        for i in range(205):
            mgr.send_notification(f"t{i}", f"m{i}", types=[NotificationType.WEB])

        with mgr._queue_lock:
            self.assertLessEqual(len(mgr._event_queue), 200)


# ──────────────────────────────────────────────────────────
# _process_event 内部逻辑
# ──────────────────────────────────────────────────────────


class TestProcessEvent(unittest.TestCase):
    def test_shutdown_skips(self):
        mgr = _make_manager()
        mgr._shutdown_called = True
        event = _make_event()
        mgr._process_event(event)

    def test_no_types_skips(self):
        mgr = _make_manager()
        event = _make_event(types=[])
        mgr._process_event(event)

    def test_all_fail_triggers_retry(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event = _make_event(max_retries=2)
        mgr._process_event(event)
        self.assertEqual(event.retry_count, 1)

    def test_all_fail_no_retries_triggers_fallback(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.WEB, mock_provider)

        fallback_called: list[bool] = []
        mgr.add_callback(
            "notification_fallback", lambda e: fallback_called.append(True)
        )

        event = _make_event(max_retries=0)
        mgr._process_event(event)
        self.assertTrue(fallback_called)

    def test_exception_in_process_triggers_retry(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.side_effect = RuntimeError("crash")
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event = _make_event(max_retries=2)
        mgr._process_event(event)
        self.assertEqual(event.retry_count, 1)

    def test_exception_no_retries_triggers_fallback(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.side_effect = RuntimeError("crash")
        mgr.register_provider(NotificationType.WEB, mock_provider)

        fallback_called: list[bool] = []
        mgr.add_callback(
            "notification_fallback", lambda e: fallback_called.append(True)
        )

        event = _make_event(max_retries=0)
        mgr._process_event(event)
        self.assertTrue(fallback_called)


# ──────────────────────────────────────────────────────────
# _send_single_notification
# ──────────────────────────────────────────────────────────


class TestSendSingleNotification(unittest.TestCase):
    def test_no_provider_returns_false(self):
        mgr = _make_manager()
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)

    def test_no_send_method_returns_false(self):
        mgr = _make_manager()
        provider = object()
        mgr.register_provider(NotificationType.WEB, provider)
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)

    def test_provider_exception_returns_false(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.side_effect = RuntimeError("network")
        mgr.register_provider(NotificationType.WEB, mock_provider)
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)

    def test_provider_success_records_stats(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertTrue(result)
        with mgr._stats_lock:
            self.assertGreater(mgr._stats["providers"]["web"]["success"], 0)

    def test_bark_error_in_metadata(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.BARK, mock_provider)
        event = _make_event(
            types=[NotificationType.BARK],
            metadata={"bark_error": "APNs connection failed"},
        )
        result = mgr._send_single_notification(NotificationType.BARK, event)
        self.assertFalse(result)
        with mgr._stats_lock:
            stats = mgr._stats["providers"]["bark"]
            self.assertEqual(stats["last_error"], "APNs connection failed")


# ──────────────────────────────────────────────────────────
# _mark_event_finalized
# ──────────────────────────────────────────────────────────


class TestMarkEventFinalized(unittest.TestCase):
    def test_success_increments(self):
        mgr = _make_manager()
        event = _make_event(id="fin_1")
        mgr._mark_event_finalized(event, succeeded=True)
        self.assertEqual(mgr._stats["events_succeeded"], 1)

    def test_failure_increments(self):
        mgr = _make_manager()
        event = _make_event(id="fin_2")
        mgr._mark_event_finalized(event, succeeded=False)
        self.assertEqual(mgr._stats["events_failed"], 1)

    def test_duplicate_ignored(self):
        mgr = _make_manager()
        event = _make_event(id="fin_3")
        mgr._mark_event_finalized(event, succeeded=True)
        mgr._mark_event_finalized(event, succeeded=False)
        self.assertEqual(mgr._stats["events_succeeded"], 1)
        self.assertEqual(mgr._stats["events_failed"], 0)


# ──────────────────────────────────────────────────────────
# _schedule_retry
# ──────────────────────────────────────────────────────────


class TestScheduleRetry(unittest.TestCase):
    def test_shutdown_skips(self):
        mgr = _make_manager()
        mgr._shutdown_called = True
        event = _make_event()
        mgr._schedule_retry(event)
        self.assertEqual(len(mgr._delayed_timers), 0)

    def test_creates_timer(self):
        mgr = _make_manager()
        event = _make_event()
        mgr._schedule_retry(event)
        self.assertGreater(len(mgr._delayed_timers), 0)
        with mgr._delayed_timers_lock:
            for t in mgr._delayed_timers.values():
                t.cancel()


# ──────────────────────────────────────────────────────────
# shutdown / restart
# ──────────────────────────────────────────────────────────


class TestShutdownRestart(unittest.TestCase):
    def test_shutdown_idempotent(self):
        mgr = _make_manager()
        mgr.shutdown(wait=False)
        mgr.shutdown(wait=False)
        self.assertTrue(mgr._shutdown_called)

    def test_shutdown_cancels_timers(self):
        mgr = _make_manager()
        timer = MagicMock()
        mgr._delayed_timers["t1"] = timer
        mgr.shutdown(wait=False)
        timer.cancel.assert_called_once()

    def test_shutdown_closes_providers(self):
        mgr = _make_manager()
        provider = MagicMock()
        mgr.register_provider(NotificationType.WEB, provider)
        mgr.shutdown(wait=False)
        provider.close.assert_called()

    def test_restart(self):
        mgr = _make_manager()
        mgr.shutdown(wait=False)
        mgr.restart()
        self.assertFalse(mgr._shutdown_called)

    def test_restart_when_not_shutdown(self):
        mgr = _make_manager()
        mgr.restart()
        self.assertFalse(mgr._shutdown_called)


# ──────────────────────────────────────────────────────────
# refresh_config_from_file
# ──────────────────────────────────────────────────────────


class TestRefreshConfig(unittest.TestCase):
    def test_no_config_available(self):
        mgr = _make_manager()
        with patch("notification_manager.CONFIG_FILE_AVAILABLE", False):
            mgr.refresh_config_from_file()

    def test_mtime_unchanged_skips(self):
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 1000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {}

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr._config_file_mtime = 1000.0
            mgr.refresh_config_from_file(force=False)

    def test_force_refresh(self):
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 1000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {
            "enabled": True,
            "sound_volume": 50,
        }

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr._config_file_mtime = 1000.0
            mgr.refresh_config_from_file(force=True)
            self.assertAlmostEqual(mgr.config.sound_volume, 0.5, places=2)

    def test_bark_toggle_on_refresh(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = False

        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 2000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {
            "bark_enabled": True,
            "bark_device_key": "key",
            "sound_volume": 80,
        }

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
            patch.object(mgr, "_update_bark_provider"),
        ):
            mgr.refresh_config_from_file(force=True)
            mgr._update_bark_provider.assert_called_once()

    def test_file_stat_oserror(self):
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.side_effect = OSError("no file")
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {"sound_volume": 80}

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr.refresh_config_from_file()

    def test_exception_in_refresh(self):
        mgr = _make_manager()
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", side_effect=RuntimeError("fail")),
        ):
            mgr.refresh_config_from_file()


# ──────────────────────────────────────────────────────────
# update_config / update_config_without_save
# ──────────────────────────────────────────────────────────


class TestUpdateConfig(unittest.TestCase):
    def test_update_config_without_save(self):
        mgr = _make_manager()
        mgr.update_config_without_save(debug=True)
        self.assertTrue(mgr.config.debug)

    def test_update_config_saves(self):
        mgr = _make_manager()
        with patch.object(mgr, "_save_config_to_file"):
            mgr.update_config(debug=True)
            mgr._save_config_to_file.assert_called_once()

    def test_update_bark_toggle(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = False
        with patch.object(mgr, "_update_bark_provider"):
            mgr.update_config_without_save(bark_enabled=True)
            mgr._update_bark_provider.assert_called_once()

    def test_update_sensitive_key(self):
        mgr = _make_manager()
        mgr.update_config_without_save(bark_device_key="secret_key")
        self.assertEqual(mgr.config.bark_device_key, "secret_key")

    def test_post_init_exception_ignored(self):
        mgr = _make_manager()
        with patch.object(mgr.config, "__post_init__", side_effect=RuntimeError("bad")):
            mgr.update_config_without_save(debug=True)


# ──────────────────────────────────────────────────────────
# _update_bark_provider
# ──────────────────────────────────────────────────────────


class TestUpdateBarkProvider(unittest.TestCase):
    def test_enable_bark(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        mgr._update_bark_provider()
        with mgr._providers_lock:
            self.assertIn(NotificationType.BARK, mgr._providers)

    def test_disable_bark(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        mgr._update_bark_provider()

        mgr.config.bark_enabled = False
        mgr._update_bark_provider()
        with mgr._providers_lock:
            self.assertNotIn(NotificationType.BARK, mgr._providers)

    def test_enable_bark_already_registered(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        mock_bark = MagicMock()
        mgr.register_provider(NotificationType.BARK, mock_bark)
        mgr._update_bark_provider()

    def test_import_error(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        with mgr._providers_lock:
            mgr._providers.pop(NotificationType.BARK, None)
        with patch(
            "notification_manager.NotificationType",
            side_effect=ImportError("no module"),
        ):
            pass


# ──────────────────────────────────────────────────────────
# _save_config_to_file
# ──────────────────────────────────────────────────────────


class TestSaveConfigToFile(unittest.TestCase):
    def test_config_unavailable(self):
        mgr = _make_manager()
        with patch("notification_manager.CONFIG_FILE_AVAILABLE", False):
            mgr._save_config_to_file()

    def test_save_success(self):
        mgr = _make_manager()
        mock_cfg = MagicMock()
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr._save_config_to_file()
            mock_cfg.update_section.assert_called_once()

    def test_save_exception(self):
        mgr = _make_manager()
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", side_effect=RuntimeError("fail")),
        ):
            mgr._save_config_to_file()

    def test_volume_above_1(self):
        mgr = _make_manager()
        mgr.config.sound_volume = 50.0
        mock_cfg = MagicMock()
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr._save_config_to_file()
            call_args = mock_cfg.update_section.call_args[0][1]
            self.assertEqual(call_args["sound_volume"], 50)


# ──────────────────────────────────────────────────────────
# get_status
# ──────────────────────────────────────────────────────────


class TestGetStatus(unittest.TestCase):
    def test_basic_status(self):
        mgr = _make_manager()
        status = mgr.get_status()
        self.assertIn("enabled", status)
        self.assertIn("providers", status)
        self.assertIn("stats", status)

    def test_status_with_events(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr.send_notification("t", "m", types=[NotificationType.WEB])
        time.sleep(0.1)

        status = mgr.get_status()
        self.assertGreater(status["stats"]["events_total"], 0)

    def test_status_delivery_rate(self):
        mgr = _make_manager()
        mgr._stats["events_total"] = 10
        mgr._stats["events_succeeded"] = 8
        mgr._stats["events_failed"] = 2
        status = mgr.get_status()
        self.assertAlmostEqual(status["stats"]["delivery_success_rate"], 0.8)

    def test_status_provider_stats(self):
        mgr = _make_manager()
        mgr._stats["providers"] = {
            "web": {
                "attempts": 10,
                "success": 8,
                "failure": 2,
                "last_success_at": None,
                "last_failure_at": None,
                "last_error": None,
                "last_latency_ms": 50,
                "latency_ms_total": 500,
                "latency_ms_count": 10,
            }
        }
        status = mgr.get_status()
        web_stats = status["stats"]["providers"]["web"]
        self.assertAlmostEqual(web_stats["success_rate"], 0.8)
        self.assertAlmostEqual(web_stats["avg_latency_ms"], 50.0)


# ──────────────────────────────────────────────────────────
# _shutdown_global_notification_manager
# ──────────────────────────────────────────────────────────


class TestGlobalShutdown(unittest.TestCase):
    def test_shutdown_function(self):
        from notification_manager import _shutdown_global_notification_manager

        _shutdown_global_notification_manager()

    def test_shutdown_exception_silenced(self):
        """全局关闭函数异常不外抛"""
        from notification_manager import _shutdown_global_notification_manager

        with patch("notification_manager.notification_manager") as mock_nm:
            mock_nm.shutdown.side_effect = RuntimeError("boom")
            _shutdown_global_notification_manager()


# ──────────────────────────────────────────────────────────
# from_config_file: safe_int 非数字回退
# ──────────────────────────────────────────────────────────


class TestFromConfigFileSafeInt(unittest.TestCase):
    def test_safe_int_non_numeric_values(self):
        """safe_int 遇到非数字时回退默认值"""
        from notification_manager import NotificationConfig

        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {
            "retry_count": "not_a_number",
            "retry_delay": None,
            "bark_timeout": [],
            "sound_volume": 80,
        }
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            cfg = NotificationConfig.from_config_file()
            self.assertEqual(cfg.retry_count, 3)
            self.assertEqual(cfg.retry_delay, 2)
            self.assertEqual(cfg.bark_timeout, 10)


# ──────────────────────────────────────────────────────────
# _process_event: TimeoutError 分支 (lines 559-579)
# ──────────────────────────────────────────────────────────


class TestProcessEventTimeout(unittest.TestCase):
    def test_timeout_cancels_unfinished_futures(self):
        """futures 超时时尝试取消未完成任务"""
        mgr = _make_manager()

        cancellable = MagicMock()
        cancellable.done.return_value = False
        cancellable.cancel.return_value = True

        running = MagicMock()
        running.done.return_value = False
        running.cancel.return_value = False

        futures_iter = iter([cancellable, running])
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = lambda fn, *a, **kw: next(futures_iter)

        with patch(
            "notification_manager.as_completed",
            side_effect=TimeoutError("timeout"),
        ):
            event = _make_event(
                types=[NotificationType.WEB, NotificationType.SOUND],
                max_retries=0,
            )
            mgr._process_event(event)

        cancellable.cancel.assert_called_once()
        running.cancel.assert_called_once()

    def test_timeout_partial_completion(self):
        """部分 future 完成后超时"""
        mgr = _make_manager()

        done_future = MagicMock()
        done_future.done.return_value = True
        done_future.result.return_value = True

        pending_future = MagicMock()
        pending_future.done.return_value = False
        pending_future.cancel.return_value = False

        futures_iter = iter([done_future, pending_future])
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = lambda fn, *a, **kw: next(futures_iter)

        def mock_as_completed(fs, timeout=None):
            yield done_future
            raise TimeoutError("1 unfinished")

        with patch("notification_manager.as_completed", side_effect=mock_as_completed):
            event = _make_event(
                types=[NotificationType.WEB, NotificationType.SOUND],
                max_retries=0,
            )
            mgr._process_event(event)

        pending_future.cancel.assert_called_once()


# ──────────────────────────────────────────────────────────
# _process_event: 外层 Exception 分支 (lines 616-636)
# ──────────────────────────────────────────────────────────


class TestProcessEventOuterException(unittest.TestCase):
    def test_submit_raises_triggers_retry(self):
        """executor.submit 异常走重试路径"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = RuntimeError("pool shutdown")

        event = _make_event(max_retries=2, retry_count=0)
        with patch.object(mgr, "_schedule_retry"):
            mgr._process_event(event)
            self.assertEqual(event.retry_count, 1)
            mgr._schedule_retry.assert_called_once()

    def test_submit_raises_no_retry_with_fallback(self):
        """executor.submit 异常 + 重试耗尽 → 降级"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = RuntimeError("pool shutdown")
        mgr.config.fallback_enabled = True

        fallback = []
        mgr.add_callback("notification_fallback", lambda e: fallback.append(True))

        event = _make_event(max_retries=0, retry_count=0)
        mgr._process_event(event)
        self.assertTrue(fallback)

    def test_submit_raises_no_retry_no_fallback(self):
        """executor.submit 异常 + 无降级"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = RuntimeError("pool shutdown")
        mgr.config.fallback_enabled = False

        event = _make_event(max_retries=0, retry_count=0)
        mgr._process_event(event)


# ──────────────────────────────────────────────────────────
# shutdown 边界异常 (lines 800-813, 822-823)
# ──────────────────────────────────────────────────────────


class TestShutdownEdgeCases(unittest.TestCase):
    def test_timer_cancel_exception_ignored(self):
        """单个 Timer.cancel() 异常不中断 shutdown"""
        mgr = _make_manager()
        bad_timer = MagicMock()
        bad_timer.cancel.side_effect = RuntimeError("cancel fail")
        good_timer = MagicMock()
        mgr._delayed_timers = {"t1": bad_timer, "t2": good_timer}
        mgr.shutdown(wait=False)
        good_timer.cancel.assert_called_once()

    def test_timer_cleanup_outer_exception(self):
        """整个 Timer 清理块异常"""
        mgr = _make_manager()
        lock = MagicMock()
        lock.__enter__ = MagicMock(side_effect=RuntimeError("lock broken"))
        lock.__exit__ = MagicMock(return_value=False)
        mgr._delayed_timers_lock = lock
        mgr.shutdown(wait=False)

    def test_executor_shutdown_type_error_fallback(self):
        """executor.shutdown(cancel_futures=...) 不支持时降级"""
        mgr = _make_manager()
        mock_exec = MagicMock()
        call_count = [0]

        def mock_shutdown(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and "cancel_futures" in kwargs:
                raise TypeError("unexpected keyword argument 'cancel_futures'")

        mock_exec.shutdown = mock_shutdown
        mgr._executor = mock_exec
        mgr.shutdown(wait=False)
        self.assertEqual(call_count[0], 2)

    def test_executor_shutdown_generic_exception(self):
        """executor.shutdown() 通用异常"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.shutdown.side_effect = RuntimeError("crash")
        mgr.shutdown(wait=False)

    def test_provider_cleanup_exception(self):
        """providers 清理异常"""
        mgr = _make_manager()
        lock = MagicMock()
        lock.__enter__ = MagicMock(side_effect=RuntimeError("lock broken"))
        lock.__exit__ = MagicMock(return_value=False)
        mgr._providers_lock = lock
        mgr.shutdown(wait=False)


# ──────────────────────────────────────────────────────────
# _update_bark_provider 错误路径 (lines 1045-1051)
# ──────────────────────────────────────────────────────────


class TestUpdateBarkProviderErrors(unittest.TestCase):
    def test_import_error(self):
        """BarkNotificationProvider 导入失败"""
        import builtins

        mgr = _make_manager()
        mgr.config.bark_enabled = True
        with mgr._providers_lock:
            mgr._providers.pop(NotificationType.BARK, None)

        real_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if name == "notification_providers":
                raise ImportError("mock: no notification_providers")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            mgr._update_bark_provider()

        with mgr._providers_lock:
            self.assertNotIn(NotificationType.BARK, mgr._providers)

    def test_generic_exception(self):
        """BarkNotificationProvider 构造异常"""
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        with mgr._providers_lock:
            mgr._providers.pop(NotificationType.BARK, None)

        with patch(
            "notification_providers.BarkNotificationProvider",
            side_effect=RuntimeError("init failed"),
        ):
            mgr._update_bark_provider()

        with mgr._providers_lock:
            self.assertNotIn(NotificationType.BARK, mgr._providers)


# ──────────────────────────────────────────────────────────
# refresh_config_from_file: safe_bool 分支 (lines 870-877)
# ──────────────────────────────────────────────────────────


class TestRefreshSafeBoolBranches(unittest.TestCase):
    def test_int_and_float_coercion(self):
        """refresh 时 safe_bool 处理 int/float"""
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 5000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {
            "enabled": 1,
            "debug": 0.0,
            "sound_volume": 80,
        }
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr.refresh_config_from_file(force=True)
            self.assertTrue(mgr.config.enabled)
            self.assertFalse(mgr.config.debug)

    def test_string_true_false_unknown(self):
        """refresh 时 safe_bool 处理各种字符串"""
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 6000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {
            "enabled": "yes",
            "debug": "on",
            "web_enabled": "off",
            "sound_enabled": "no",
            "bark_enabled": "maybe",
            "sound_volume": 80,
        }
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr.refresh_config_from_file(force=True)
            self.assertTrue(mgr.config.enabled)
            self.assertTrue(mgr.config.debug)
            self.assertFalse(mgr.config.web_enabled)
            self.assertFalse(mgr.config.sound_enabled)
            self.assertFalse(mgr.config.bark_enabled)

    def test_post_init_exception_in_refresh(self):
        """refresh 时 __post_init__ 异常被静默"""
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 7000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {"sound_volume": 80}

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
            patch.object(mgr.config, "__post_init__", side_effect=RuntimeError("bad")),
        ):
            mgr.refresh_config_from_file(force=True)


# ──────────────────────────────────────────────────────────
# _schedule_retry 边界 (lines 497-507)
# ──────────────────────────────────────────────────────────


class TestScheduleRetryEdge(unittest.TestCase):
    def test_invalid_delay_fallback(self):
        """retry_delay 不合法时回退默认值 2"""
        mgr = _make_manager()
        mgr.config.retry_delay = "invalid"  # type: ignore[assignment]

        event = _make_event()
        mgr._schedule_retry(event)

        with mgr._delayed_timers_lock:
            self.assertGreater(len(mgr._delayed_timers), 0)
            for t in mgr._delayed_timers.values():
                t.cancel()

    def test_retry_callback_executes(self):
        """_retry_run 内部函数实际执行并清理 Timer"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event = _make_event(max_retries=3, retry_count=1)
        mgr.config.retry_delay = 0

        mgr._schedule_retry(event)
        time.sleep(0.3)

        timer_key = f"{event.id}__retry_{event.retry_count}"
        with mgr._delayed_timers_lock:
            self.assertNotIn(timer_key, mgr._delayed_timers)


# ──────────────────────────────────────────────────────────
# stats 异常静默 (lines 435-437, 486-488, 529-530, etc.)
# ──────────────────────────────────────────────────────────


class TestProcessEventInnerFutureException(unittest.TestCase):
    def test_future_result_raises(self):
        """future.result() 异常被内层 except 捕获"""
        mgr = _make_manager()

        bad_future = MagicMock()
        bad_future.result.side_effect = RuntimeError("future error")

        mgr._executor = MagicMock()
        mgr._executor.submit.return_value = bad_future

        def mock_as_completed(fs, timeout=None):
            for f in fs:
                yield f

        with patch("notification_manager.as_completed", side_effect=mock_as_completed):
            event = _make_event(types=[NotificationType.WEB], max_retries=0)
            mgr._process_event(event)

    def test_retry_stats_exception_silenced(self):
        """重试路径中 stats 异常不影响重试调度"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr._stats = None  # type: ignore[assignment]

        event = _make_event(max_retries=2, retry_count=0)
        with patch.object(mgr, "_schedule_retry"):
            mgr._process_event(event)
        self.assertEqual(event.retry_count, 1)

    def test_outer_exception_retry_stats_broken(self):
        """外层异常重试路径中 stats 异常不影响重试"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = RuntimeError("crash")
        mgr._stats = None  # type: ignore[assignment]

        event = _make_event(max_retries=2, retry_count=0)
        with patch.object(mgr, "_schedule_retry"):
            mgr._process_event(event)
        self.assertEqual(event.retry_count, 1)


class TestStatsExceptionSilenced(unittest.TestCase):
    def test_send_notification_stats_broken(self):
        """send_notification 中 _stats 异常不影响事件创建"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr._stats = None  # type: ignore[assignment]

        event_id = mgr.send_notification("t", "m", types=[NotificationType.WEB])
        self.assertNotEqual(event_id, "")

    def test_mark_event_finalized_stats_broken(self):
        """_mark_event_finalized 中 _stats 异常不外抛"""
        mgr = _make_manager()
        mgr._stats = None  # type: ignore[assignment]
        event = _make_event(id="fin_broken")
        mgr._mark_event_finalized(event, succeeded=True)

    def test_send_single_no_provider_stats_broken(self):
        """无 provider 时统计记录异常不外抛"""
        mgr = _make_manager()
        mgr._stats = None  # type: ignore[assignment]
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)

    def test_send_single_success_stats_broken(self):
        """provider 发送成功但统计记录异常"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr._stats = None  # type: ignore[assignment]
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertTrue(result)

    def test_send_single_exception_stats_broken(self):
        """provider 异常且统计记录也异常"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.side_effect = RuntimeError("crash")
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr._stats = None  # type: ignore[assignment]
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)


# ──────────────────────────────────────────────────────────
# get_status stats 异常 (lines 1131-1132, 1149-1152)
# ──────────────────────────────────────────────────────────


class TestBranchCoverage(unittest.TestCase):
    """补充分支覆盖"""

    def test_auto_types_all_disabled(self):
        """types=None 且所有渠道关闭 → 空 types"""
        mgr = _make_manager()
        mgr.config.web_enabled = False
        mgr.config.sound_enabled = False
        mgr.config.bark_enabled = False
        mgr.config.system_enabled = False

        event_id = mgr.send_notification("t", "m")
        self.assertNotEqual(event_id, "")

    def test_priority_non_string_non_enum(self):
        """priority 传入非字符串非枚举值 → 使用默认"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event_id = mgr.send_notification(
            "t",
            "m",
            types=[NotificationType.WEB],
            priority=999,  # type: ignore[arg-type]
        )
        self.assertNotEqual(event_id, "")

    def test_all_fail_no_fallback(self):
        """所有渠道失败 + 重试耗尽 + fallback 关闭"""
        mgr = _make_manager()
        mgr.config.fallback_enabled = False
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event = _make_event(max_retries=0)
        mgr._process_event(event)

    def test_update_config_nonexistent_key(self):
        """update_config_without_save 忽略不存在的配置键"""
        mgr = _make_manager()
        mgr.update_config_without_save(nonexistent_key_xyz="value")
        self.assertFalse(hasattr(mgr.config, "nonexistent_key_xyz"))


class TestGetStatusEdge(unittest.TestCase):
    def test_derived_stats_calculation_exception(self):
        """派生指标计算异常被静默"""
        mgr = _make_manager()
        mgr._stats["events_succeeded"] = "not_a_number"
        status = mgr.get_status()
        self.assertIn("stats", status)

    def test_provider_stats_calculation_exception(self):
        """提供者级别统计计算异常"""
        mgr = _make_manager()
        mgr._stats["providers"] = {"web": {"attempts": "bad", "success": "bad"}}
        status = mgr.get_status()
        self.assertIn("stats", status)

    def test_stats_lock_failure(self):
        """stats 锁获取失败 → 返回空 stats"""
        mgr = _make_manager()
        lock = MagicMock()
        lock.__enter__ = MagicMock(side_effect=RuntimeError("lock broken"))
        lock.__exit__ = MagicMock(return_value=False)
        mgr._stats_lock = lock
        status = mgr.get_status()
        self.assertEqual(status["stats"], {})


if __name__ == "__main__":
    unittest.main()
