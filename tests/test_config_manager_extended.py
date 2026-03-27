"""config_manager.py 覆盖率补充测试。

覆盖 update 的 network_security 分支、section 缓存、
typed getters 边界、cache stats、coerce_bool、
_is_uvx_mode、find_config_file、_validate_config_structure、
_create_default_config_file、_delayed_save、set() 路由等。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from config_manager import (
    ConfigManager,
    _get_user_config_dir_fallback,
    _is_uvx_mode,
    _sanitize_config_value_for_log,
    find_config_file,
)

# ──────────────────────────────────────────────────────────
# 辅助工具函数测试
# ──────────────────────────────────────────────────────────


class TestSanitizeConfigValue(unittest.TestCase):
    """_sanitize_config_value_for_log"""

    def test_sensitive_key_redacted(self):
        self.assertEqual(
            _sanitize_config_value_for_log("bark_token", "abc"), "<redacted>"
        )

    def test_normal_key_shown(self):
        self.assertEqual(
            _sanitize_config_value_for_log("host", "127.0.0.1"), "127.0.0.1"
        )

    def test_long_value_truncated(self):
        result = _sanitize_config_value_for_log("data", "x" * 300)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result), 204)

    def test_unprintable_value(self):
        class Bad:
            def __str__(self):
                raise RuntimeError("no str")

        result = _sanitize_config_value_for_log("key", Bad())
        self.assertEqual(result, "<unprintable>")


# ──────────────────────────────────────────────────────────
# _is_uvx_mode 检测逻辑
# ──────────────────────────────────────────────────────────


class TestIsUvxMode(unittest.TestCase):
    def test_uvx_in_executable(self):
        with patch("config_manager.sys") as mock_sys:
            mock_sys.executable = "/home/user/.local/share/uvx/python3.11/bin/python"
            self.assertTrue(_is_uvx_mode())

    def test_uvx_project_env(self):
        with (
            patch("config_manager.sys") as mock_sys,
            patch.dict(os.environ, {"UVX_PROJECT": "ai-intervention-agent"}),
        ):
            mock_sys.executable = "/usr/bin/python3"
            self.assertTrue(_is_uvx_mode())

    def test_dev_mode_in_repo(self):
        result = _is_uvx_mode()
        self.assertFalse(result)


# ──────────────────────────────────────────────────────────
# find_config_file 路径查找
# ──────────────────────────────────────────────────────────


class TestFindConfigFile(unittest.TestCase):
    def test_absolute_path_returned_directly(self):
        result = find_config_file("/tmp/my_config.jsonc")
        self.assertEqual(result, Path("/tmp/my_config.jsonc"))

    def test_relative_path_with_directory(self):
        result = find_config_file("subdir/config.jsonc")
        self.assertEqual(result, Path("subdir/config.jsonc"))

    def test_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "test.jsonc"
            cfg.write_text("{}")
            with patch.dict(
                os.environ, {"AI_INTERVENTION_AGENT_CONFIG_FILE": str(cfg)}
            ):
                result = find_config_file()
                self.assertEqual(result, cfg)

    def test_env_override_directory(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(
                os.environ, {"AI_INTERVENTION_AGENT_CONFIG_FILE": td + "/"}
            ):
                result = find_config_file()
                self.assertEqual(result, Path(td) / "config.jsonc")


# ──────────────────────────────────────────────────────────
# _get_user_config_dir_fallback 跨平台
# ──────────────────────────────────────────────────────────


class TestGetUserConfigDirFallback(unittest.TestCase):
    def test_darwin(self):
        with patch("config_manager.platform.system", return_value="Darwin"):
            result = _get_user_config_dir_fallback()
            self.assertIn("Library", str(result))
            self.assertTrue(str(result).endswith("ai-intervention-agent"))

    def test_windows_with_appdata(self):
        with (
            patch("config_manager.platform.system", return_value="Windows"),
            patch.dict(os.environ, {"APPDATA": "/fake/appdata"}),
        ):
            result = _get_user_config_dir_fallback()
            self.assertEqual(result, Path("/fake/appdata/ai-intervention-agent"))

    def test_windows_without_appdata(self):
        env = os.environ.copy()
        env.pop("APPDATA", None)
        with (
            patch("config_manager.platform.system", return_value="Windows"),
            patch.dict(os.environ, env, clear=True),
        ):
            result = _get_user_config_dir_fallback()
            self.assertIn("ai-intervention-agent", str(result))

    def test_linux_with_xdg(self):
        with (
            patch("config_manager.platform.system", return_value="Linux"),
            patch.dict(os.environ, {"XDG_CONFIG_HOME": "/xdg/config"}),
        ):
            result = _get_user_config_dir_fallback()
            self.assertEqual(result, Path("/xdg/config/ai-intervention-agent"))

    def test_linux_without_xdg(self):
        env = os.environ.copy()
        env.pop("XDG_CONFIG_HOME", None)
        with (
            patch("config_manager.platform.system", return_value="Linux"),
            patch.dict(os.environ, env, clear=True),
        ):
            result = _get_user_config_dir_fallback()
            self.assertIn(".config", str(result))


# ──────────────────────────────────────────────────────────
# update() / set() 路由 network_security
# ──────────────────────────────────────────────────────────


class TestUpdateNetworkSecurity(unittest.TestCase):
    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_update_network_security_dict(self):
        mgr = self._mgr()
        mgr.update(
            {"network_security": {"bind_interface": "127.0.0.1"}},
            save=True,
        )
        ns = mgr.get_network_security_config()
        self.assertEqual(ns["bind_interface"], "127.0.0.1")

    def test_update_network_security_dotted_key(self):
        mgr = self._mgr()
        mgr.update(
            {"network_security.bind_interface": "0.0.0.0"},
            save=True,
        )
        ns = mgr.get_network_security_config()
        self.assertIn(ns["bind_interface"], ("0.0.0.0", "127.0.0.1"))

    def test_update_network_security_invalid_dotted(self):
        mgr = self._mgr()
        with self.assertRaises(ValueError):
            mgr.update({"network_security.nested.field": "val"}, save=False)

    def test_update_network_security_only(self):
        mgr = self._mgr()
        mgr.update(
            {"network_security": {"access_control_enabled": False}},
            save=True,
        )

    def test_update_no_actual_changes(self):
        mgr = self._mgr()
        current = mgr.get("notification", {})
        mgr.update({"notification": current}, save=False)


class TestSetNetworkSecurityRouting(unittest.TestCase):
    """set() 方法 network_security 路由分支"""

    def test_set_network_security_dict(self):
        mgr = ConfigManager()
        mgr.set("network_security", {"bind_interface": "127.0.0.1"}, save=True)
        ns = mgr.get_network_security_config()
        self.assertEqual(ns["bind_interface"], "127.0.0.1")

    def test_set_network_security_non_dict_raises(self):
        mgr = ConfigManager()
        with self.assertRaises(ValueError):
            mgr.set("network_security", "bad", save=False)

    def test_set_network_security_dotted(self):
        mgr = ConfigManager()
        mgr.set("network_security.bind_interface", "0.0.0.0", save=True)

    def test_set_network_security_dotted_invalid(self):
        mgr = ConfigManager()
        with self.assertRaises(ValueError):
            mgr.set("network_security.a.b", "val", save=False)

    def test_set_network_security_dotted_empty_field(self):
        mgr = ConfigManager()
        with self.assertRaises(ValueError):
            mgr.set("network_security.", "val", save=False)

    def test_set_empty_key_invalidates_all(self):
        """空 key 会走 invalidate_all_caches 分支"""
        mgr = ConfigManager()
        mgr.set("", "test_value", save=False)


# ──────────────────────────────────────────────────────────
# update_section 路由
# ──────────────────────────────────────────────────────────


class TestUpdateSectionNetworkSecurity(unittest.TestCase):
    def test_update_section_network_security(self):
        mgr = ConfigManager()
        mgr.update_section("network_security", {"bind_interface": "0.0.0.0"}, save=True)

    def test_update_section_network_security_non_dict(self):
        mgr = ConfigManager()
        with self.assertRaises(ValueError):
            mgr.update_section("network_security", "not dict", save=False)  # type: ignore[arg-type]

    def test_update_section_no_changes(self):
        mgr = ConfigManager()
        current = mgr.get_section("notification")
        mgr.update_section("notification", current, save=False)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────
# _validate_config_structure 分支
# ──────────────────────────────────────────────────────────


class TestValidateConfigStructure(unittest.TestCase):
    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_duplicate_blocked_ips(self):
        content = '{\n"blocked_ips": [],\n"blocked_ips": []\n}'
        parsed = json.loads(content)
        with self.assertRaises(ValueError):
            self._mgr()._validate_config_structure(parsed, content)

    def test_network_security_not_dict(self):
        content = '{"network_security": "bad"}'
        parsed = json.loads(content)
        with self.assertRaises(ValueError):
            self._mgr()._validate_config_structure(parsed, content)

    def test_allowed_networks_not_list(self):
        content = '{"network_security": {"allowed_networks": "bad"}}'
        parsed = json.loads(content)
        with self.assertRaises(ValueError):
            self._mgr()._validate_config_structure(parsed, content)

    def test_allowed_networks_invalid_element(self):
        content = '{"network_security": {"allowed_networks": [123]}}'
        parsed = json.loads(content)
        with self.assertRaises(ValueError):
            self._mgr()._validate_config_structure(parsed, content)

    def test_block_comment_skipped(self):
        content = '/* "allowed_networks": [] */\n{"key": "value"}'
        parsed = {"key": "value"}
        self._mgr()._validate_config_structure(parsed, content)

    def test_inline_block_comment(self):
        content = '/* comment */\n{"key": "value"}'
        parsed = {"key": "value"}
        self._mgr()._validate_config_structure(parsed, content)


# ──────────────────────────────────────────────────────────
# section 缓存
# ──────────────────────────────────────────────────────────


class TestSectionCache(unittest.TestCase):
    def test_cache_hit(self):
        mgr = ConfigManager()
        mgr.reset_cache_stats()
        mgr.get_section("notification")
        mgr.get_section("notification")
        stats = mgr.get_cache_stats()
        self.assertGreater(stats["hits"], 0)

    def test_cache_miss_after_invalidation(self):
        mgr = ConfigManager()
        mgr.get_section("notification")
        mgr.invalidate_section_cache("notification")
        mgr.reset_cache_stats()
        mgr.get_section("notification")
        stats = mgr.get_cache_stats()
        self.assertEqual(stats["misses"], 1)

    def test_cache_network_security_special(self):
        mgr = ConfigManager()
        result = mgr.get_section("network_security")
        self.assertIn("bind_interface", result)

    def test_cache_ttl_expired(self):
        mgr = ConfigManager()
        mgr.set_cache_ttl(section_ttl=0.1)
        mgr.get_section("notification")
        time.sleep(0.15)
        mgr.reset_cache_stats()
        mgr.get_section("notification")
        stats = mgr.get_cache_stats()
        self.assertGreater(stats["misses"], 0)

    def test_get_section_no_cache(self):
        mgr = ConfigManager()
        mgr.reset_cache_stats()
        mgr.get_section("notification", use_cache=False)
        stats = mgr.get_cache_stats()
        self.assertEqual(stats["misses"], 1)


# ──────────────────────────────────────────────────────────
# cache stats 和 TTL
# ──────────────────────────────────────────────────────────


class TestCacheStatsAndTTL(unittest.TestCase):
    def test_get_cache_stats(self):
        mgr = ConfigManager()
        stats = mgr.get_cache_stats()
        self.assertIn("hits", stats)
        self.assertIn("misses", stats)
        self.assertIn("hit_rate", stats)
        self.assertIn("section_cache_size", stats)

    def test_reset_cache_stats(self):
        mgr = ConfigManager()
        mgr.get_section("notification")
        mgr.reset_cache_stats()
        stats = mgr.get_cache_stats()
        self.assertEqual(stats["hits"], 0)
        self.assertEqual(stats["misses"], 0)

    def test_set_cache_ttl(self):
        mgr = ConfigManager()
        mgr.set_cache_ttl(section_ttl=10.0, network_security_ttl=30.0)
        self.assertEqual(mgr._section_cache_ttl, 10.0)
        self.assertEqual(mgr._network_security_cache_ttl, 30.0)

    def test_set_cache_ttl_minimum(self):
        mgr = ConfigManager()
        mgr.set_cache_ttl(section_ttl=0.001, network_security_ttl=0.001)
        self.assertGreaterEqual(mgr._section_cache_ttl, 0.1)
        self.assertGreaterEqual(mgr._network_security_cache_ttl, 1.0)

    def test_set_cache_ttl_none_no_change(self):
        mgr = ConfigManager()
        original_s = mgr._section_cache_ttl
        original_ns = mgr._network_security_cache_ttl
        mgr.set_cache_ttl()
        self.assertEqual(mgr._section_cache_ttl, original_s)
        self.assertEqual(mgr._network_security_cache_ttl, original_ns)


# ──────────────────────────────────────────────────────────
# _coerce_bool
# ──────────────────────────────────────────────────────────


class TestCoerceBool(unittest.TestCase):
    def test_bool_true(self):
        self.assertTrue(ConfigManager._coerce_bool(True))

    def test_bool_false(self):
        self.assertFalse(ConfigManager._coerce_bool(False))

    def test_none_default_true(self):
        self.assertTrue(ConfigManager._coerce_bool(None, default=True))

    def test_none_default_false(self):
        self.assertFalse(ConfigManager._coerce_bool(None, default=False))

    def test_int_truthy(self):
        self.assertTrue(ConfigManager._coerce_bool(1))
        self.assertFalse(ConfigManager._coerce_bool(0))

    def test_float_truthy(self):
        self.assertTrue(ConfigManager._coerce_bool(1.0))
        self.assertFalse(ConfigManager._coerce_bool(0.0))

    def test_string_true_values(self):
        for val in ("true", "True", "1", "yes", "y", "on", "YES", "ON"):
            self.assertTrue(ConfigManager._coerce_bool(val), f"failed for '{val}'")

    def test_string_false_values(self):
        for val in ("false", "False", "0", "no", "n", "off", "NO", "OFF"):
            self.assertFalse(ConfigManager._coerce_bool(val), f"failed for '{val}'")

    def test_string_unknown_returns_default(self):
        self.assertTrue(ConfigManager._coerce_bool("maybe", default=True))
        self.assertFalse(ConfigManager._coerce_bool("maybe", default=False))

    def test_other_object_uses_bool(self):
        self.assertTrue(ConfigManager._coerce_bool([1, 2]))
        self.assertFalse(ConfigManager._coerce_bool([]))

    def test_exception_returns_default(self):
        class BadBool:
            def __bool__(self):
                raise RuntimeError("boom")

        self.assertTrue(ConfigManager._coerce_bool(BadBool(), default=True))
        self.assertFalse(ConfigManager._coerce_bool(BadBool(), default=False))


# ──────────────────────────────────────────────────────────
# Typed getters
# ──────────────────────────────────────────────────────────


class TestTypedGetters(unittest.TestCase):
    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_get_int_with_bounds(self):
        mgr = self._mgr()
        mgr.set("test_int", 50, save=False)
        result = mgr.get_int("test_int", default=0, min_val=10, max_val=100)
        self.assertEqual(result, 50)

    def test_get_int_min_only(self):
        mgr = self._mgr()
        mgr.set("test_int_min", 5, save=False)
        result = mgr.get_int("test_int_min", default=0, min_val=10)
        self.assertGreaterEqual(result, 10)

    def test_get_int_max_only(self):
        mgr = self._mgr()
        mgr.set("test_int_max", 200, save=False)
        result = mgr.get_int("test_int_max", default=0, max_val=100)
        self.assertLessEqual(result, 100)

    def test_get_int_invalid_type_returns_default(self):
        mgr = self._mgr()
        mgr.set("test_bad", "not_a_number", save=False)
        result = mgr.get_int("test_bad", default=42)
        self.assertEqual(result, 42)

    def test_get_float_with_bounds(self):
        mgr = self._mgr()
        mgr.set("test_float", 0.5, save=False)
        result = mgr.get_float("test_float", default=0.0, min_val=0.0, max_val=1.0)
        self.assertEqual(result, 0.5)

    def test_get_float_min_only(self):
        mgr = self._mgr()
        mgr.set("f_min", -5.0, save=False)
        result = mgr.get_float("f_min", default=0.0, min_val=0.0)
        self.assertGreaterEqual(result, 0.0)

    def test_get_float_max_only(self):
        mgr = self._mgr()
        mgr.set("f_max", 999.0, save=False)
        result = mgr.get_float("f_max", default=0.0, max_val=100.0)
        self.assertLessEqual(result, 100.0)

    def test_get_bool(self):
        mgr = self._mgr()
        mgr.set("test_bool", True, save=False)
        self.assertTrue(mgr.get_bool("test_bool"))

    def test_get_bool_string_true(self):
        mgr = self._mgr()
        mgr.set("test_bool_str", "true", save=False)
        self.assertTrue(mgr.get_bool("test_bool_str"))

    def test_get_bool_int_conversion(self):
        mgr = self._mgr()
        mgr.set("test_bool_int", 0, save=False)
        self.assertFalse(mgr.get_bool("test_bool_int"))

    def test_get_str(self):
        mgr = self._mgr()
        mgr.set("test_str", "hello", save=False)
        self.assertEqual(mgr.get_str("test_str"), "hello")

    def test_get_str_truncate(self):
        mgr = self._mgr()
        mgr.set("test_str_long", "a" * 100, save=False)
        result = mgr.get_str("test_str_long", max_length=10)
        self.assertLessEqual(len(result), 15)


# ──────────────────────────────────────────────────────────
# _delayed_save 和 _schedule_save
# ──────────────────────────────────────────────────────────


class TestDelayedSave(unittest.TestCase):
    def test_delayed_save_applies_pending(self):
        mgr = ConfigManager()
        mgr._pending_changes = {"notification.debug": True}
        mgr._delayed_save()
        self.assertTrue(mgr.get("notification.debug"))
        self.assertEqual(mgr._pending_changes, {})

    def test_delayed_save_exception(self):
        mgr = ConfigManager()
        mgr._pending_changes = {"k": "v"}
        with patch.object(mgr, "_save_config_immediate", side_effect=OSError("disk")):
            mgr._delayed_save()

    def test_schedule_save_replaces_timer(self):
        mgr = ConfigManager()
        mock_timer = MagicMock()
        mgr._save_timer = mock_timer
        mgr._schedule_save()
        mock_timer.cancel.assert_called_once()
        self.assertIsNotNone(mgr._save_timer)
        if mgr._save_timer:
            mgr._save_timer.cancel()


# ──────────────────────────────────────────────────────────
# _create_default_config_file 分支
# ──────────────────────────────────────────────────────────


class TestCreateDefaultConfigFile(unittest.TestCase):
    def test_no_template_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.jsonc"
            mgr = ConfigManager.__new__(ConfigManager)
            mgr.config_file = cfg
            mgr._config = {}
            mgr._original_content = None
            mgr._lock = __import__("threading").RLock()

            with patch("config_manager.Path") as mock_path_cls:
                template_mock = MagicMock()
                template_mock.exists.return_value = False

                real_parent = cfg.parent

                class FakePath:
                    def __init__(self, *a, **kw):
                        self._real = Path(*a, **kw)

                    def __truediv__(self, other):
                        if other == "config.jsonc.default":
                            return template_mock
                        return self._real / other

                    @property
                    def parent(self):
                        return real_parent

                mock_path_cls.side_effect = FakePath
                mock_path_cls.__file__ = __file__

                mgr._create_default_config_file()

            self.assertTrue(cfg.exists())
            content = json.loads(cfg.read_text())
            self.assertIn("notification", content)


# ──────────────────────────────────────────────────────────
# _load_config 异常分支
# ──────────────────────────────────────────────────────────


class TestLoadConfigExceptions(unittest.TestCase):
    def test_load_config_first_load_failure_uses_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.jsonc"
            cfg.write_text("{invalid json")
            mgr = ConfigManager(str(cfg))
            self.assertIn("notification", mgr._config)

    def test_load_config_reload_failure_keeps_previous(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.jsonc"
            cfg.write_text('{"notification": {"debug": true}}')
            mgr = ConfigManager(str(cfg))
            self.assertTrue(mgr.get("notification.debug"))

            cfg.write_text("{broken")
            mgr.reload()
            self.assertTrue(mgr.get("notification.debug"))


# ──────────────────────────────────────────────────────────
# _merge_config 的 network_security 跳过
# ──────────────────────────────────────────────────────────


class TestMergeConfig(unittest.TestCase):
    def test_network_security_excluded(self):
        mgr = ConfigManager()
        default = {"network_security": {"k": "v"}, "other": {"a": 1}}
        current: dict[str, Any] = {"other": {"a": 2}}
        result = mgr._merge_config(default, current)
        self.assertNotIn("network_security", result)
        self.assertEqual(result["other"]["a"], 2)


# ──────────────────────────────────────────────────────────
# update() save=True 分支（批量缓冲）
# ──────────────────────────────────────────────────────────


class TestUpdateWithSave(unittest.TestCase):
    def test_update_save_true_schedules_save(self):
        mgr = ConfigManager()
        mgr.update({"notification.debug": True}, save=True)
        self.assertTrue(mgr.get("notification.debug"))
        if mgr._save_timer:
            mgr._save_timer.cancel()

    def test_update_callback_exception_ignored(self):
        mgr = ConfigManager()

        def bad_callback():
            raise RuntimeError("boom")

        mgr.register_config_change_callback(bad_callback)
        mgr.update({"notification.debug": True}, save=False)


# ──────────────────────────────────────────────────────────
# get_config / _shutdown_global_config_manager
# ──────────────────────────────────────────────────────────


class TestGetConfig(unittest.TestCase):
    def test_returns_config_manager(self):
        from config_manager import get_config

        result = get_config()
        self.assertIsInstance(result, ConfigManager)

    def test_get_config_exception_safe(self):
        from config_manager import get_config

        with patch.object(
            ConfigManager, "start_file_watcher", side_effect=RuntimeError("fail")
        ):
            result = get_config()
            self.assertIsInstance(result, ConfigManager)


class TestShutdownGlobal(unittest.TestCase):
    def test_shutdown_function_exists(self):
        from config_manager import _shutdown_global_config_manager

        _shutdown_global_config_manager()

    def test_shutdown_exception_safe(self):
        from config_manager import _shutdown_global_config_manager

        with patch.object(ConfigManager, "shutdown", side_effect=RuntimeError("fail")):
            _shutdown_global_config_manager()


# ──────────────────────────────────────────────────────────
# _save_config_immediate 异常与 JSON 保存路径
# ──────────────────────────────────────────────────────────


class TestSaveConfigImmediate(unittest.TestCase):
    def test_save_json_format(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text('{"notification": {"debug": false}}')
            mgr = ConfigManager(str(cfg))
            mgr.set("notification.debug", True, save=False)
            mgr._save_config_immediate()
            content = json.loads(cfg.read_text())
            self.assertTrue(content["notification"]["debug"])

    def test_save_exception_propagated(self):
        mgr = ConfigManager()
        with patch("builtins.open", side_effect=PermissionError("no write")):
            with self.assertRaises(PermissionError):
                mgr._save_config_immediate()


# ──────────────────────────────────────────────────────────
# ReadWriteLock 写锁等待读者
# ──────────────────────────────────────────────────────────


class TestReadWriteLockWait(unittest.TestCase):
    def test_write_waits_for_readers(self):
        import threading

        from config_manager import ReadWriteLock

        lock = ReadWriteLock()
        log: list[str] = []
        barrier = threading.Event()

        def reader():
            with lock.read_lock():
                log.append("read_start")
                barrier.set()
                time.sleep(0.05)
                log.append("read_end")

        def writer():
            barrier.wait()
            with lock.write_lock():
                log.append("write")

        rt = threading.Thread(target=reader)
        wt = threading.Thread(target=writer)
        rt.start()
        wt.start()
        rt.join(timeout=2)
        wt.join(timeout=2)

        self.assertEqual(log.index("read_end") < log.index("write"), True)


# ──────────────────────────────────────────────────────────
# find_config_file 开发模式分支 (269-322)
# ──────────────────────────────────────────────────────────


class TestFindConfigFileDev(unittest.TestCase):
    """_is_uvx_mode() == False 时的 find_config_file 路径"""

    def test_dev_mode_current_dir_exists(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.jsonc"
            cfg.write_text("{}")
            with (
                patch("config_manager._is_uvx_mode", return_value=False),
                patch("config_manager.Path") as MockPath,
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)

                real_path = Path("config.jsonc")
                mock_instance = MagicMock()
                mock_instance.is_absolute.return_value = False
                mock_instance.parent = Path(".")
                mock_instance.expanduser.return_value = mock_instance

                current_mock = MagicMock()
                current_mock.exists.return_value = True
                current_mock.absolute.return_value = cfg

                call_count = 0

                def path_side_effect(arg="config.jsonc"):
                    nonlocal call_count
                    if arg == "config.jsonc":
                        call_count += 1
                        if call_count == 1:
                            return mock_instance
                        return current_mock
                    if arg == "config.json":
                        m = MagicMock()
                        m.exists.return_value = False
                        return m
                    return Path(arg)

                MockPath.side_effect = path_side_effect
                MockPath.__truediv__ = Path.__truediv__

                result = find_config_file("config.jsonc")
                self.assertEqual(result, current_mock)

    def test_dev_mode_json_fallback(self):
        with (
            patch("config_manager._is_uvx_mode", return_value=False),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
            with tempfile.TemporaryDirectory() as td:
                json_file = Path(td) / "config.json"
                json_file.write_text("{}")
                with patch("config_manager.Path") as MockPath:
                    mock_instance = MagicMock()
                    mock_instance.is_absolute.return_value = False
                    mock_instance.parent = Path(".")
                    mock_instance.expanduser.return_value = mock_instance

                    jsonc_mock = MagicMock()
                    jsonc_mock.exists.return_value = False

                    json_mock = MagicMock()
                    json_mock.exists.return_value = True
                    json_mock.absolute.return_value = json_file

                    call_count = 0

                    def path_side_effect(arg="config.jsonc"):
                        nonlocal call_count
                        if arg == "config.jsonc":
                            call_count += 1
                            if call_count == 1:
                                return mock_instance
                            return jsonc_mock
                        if arg == "config.json":
                            return json_mock
                        return Path(arg)

                    MockPath.side_effect = path_side_effect

                    result = find_config_file("config.jsonc")
                    self.assertEqual(result, json_mock)


# ──────────────────────────────────────────────────────────
# _is_uvx_mode 异常降级 (231-235)
# ──────────────────────────────────────────────────────────


class TestIsUvxModeException(unittest.TestCase):
    def test_exception_returns_true(self):
        with (
            patch("config_manager.sys") as mock_sys,
            patch("config_manager.Path") as MockPath,
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("UVX_PROJECT", None)
            mock_sys.executable = "/usr/bin/python3"
            MockPath.side_effect = RuntimeError("boom")
            self.assertTrue(_is_uvx_mode())


# ──────────────────────────────────────────────────────────
# set() / update() / update_section() 回调异常 (880-881, 962-963, 1097-1098)
# ──────────────────────────────────────────────────────────


class TestCallbackExceptions(unittest.TestCase):
    def test_set_callback_exception_ignored(self):
        mgr = ConfigManager()
        mgr.register_config_change_callback(
            lambda: (_ for _ in ()).throw(RuntimeError("x"))
        )
        mgr.set("notification.debug", True, save=False)

    def test_update_callback_exception_ignored(self):
        mgr = ConfigManager()

        def bad():
            raise RuntimeError("boom")

        mgr.register_config_change_callback(bad)
        mgr.update({"notification.debug": True}, save=False)

    def test_update_section_callback_exception_ignored(self):
        mgr = ConfigManager()

        def bad():
            raise RuntimeError("section boom")

        mgr.register_config_change_callback(bad)
        mgr.update_section("notification", {"debug": True}, save=False)


# ──────────────────────────────────────────────────────────
# update_section 嵌套 key 创建 (1079-1081)
# ──────────────────────────────────────────────────────────


class TestUpdateSectionNestedKey(unittest.TestCase):
    def test_nested_section_key_creation(self):
        mgr = ConfigManager()
        mgr.update_section("notification.sub", {"key": "val"}, save=False)
        result = mgr.get("notification.sub", {})
        self.assertEqual(result.get("key"), "val")


# ──────────────────────────────────────────────────────────
# update() save=True（批量保存） (926-934)
# ──────────────────────────────────────────────────────────


class TestUpdateSaveTrue(unittest.TestCase):
    def test_update_save_true_pending_changes(self):
        mgr = ConfigManager()
        mgr.update(
            {"notification.debug": True, "notification.sound_volume": 50},
            save=True,
        )
        self.assertTrue(mgr.get("notification.debug"))
        self.assertEqual(mgr.get("notification.sound_volume"), 50)
        if mgr._save_timer:
            mgr._save_timer.cancel()


# ──────────────────────────────────────────────────────────
# update() 中 empty section / network_security 缓存失效 (946-950)
# ──────────────────────────────────────────────────────────


class TestUpdateCacheInvalidation(unittest.TestCase):
    def test_update_invalidates_all_on_empty_key(self):
        mgr = ConfigManager()
        mgr.get_section("notification")
        mgr.update({"": "val"}, save=False)
        stats = mgr.get_cache_stats()
        self.assertGreater(stats["invalidations"], 0)


# ──────────────────────────────────────────────────────────
# _validate_saved_config 异常 (745-747)
# ──────────────────────────────────────────────────────────


class TestValidateSavedConfigException(unittest.TestCase):
    def test_validation_failure_raises(self):
        mgr = ConfigManager()
        with (
            patch("builtins.open", side_effect=IOError("can't read")),
            self.assertRaises(IOError),
        ):
            mgr._validate_saved_config()


# ──────────────────────────────────────────────────────────
# _create_default_config_file 双重失败 (622-636)
# ──────────────────────────────────────────────────────────


class TestCreateDefaultConfigFallbackFailure(unittest.TestCase):
    def test_first_write_fails_then_fallback_succeeds(self):
        import shutil

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.jsonc"
            mgr = ConfigManager.__new__(ConfigManager)
            mgr.config_file = cfg
            mgr._config = {}
            mgr._original_content = None
            mgr._lock = __import__("threading").RLock()

            call_count = 0
            original_copy2 = shutil.copy2

            def failing_copy(*a, **kw):
                nonlocal call_count
                call_count += 1
                raise PermissionError("can't copy")

            with patch("config_manager.shutil.copy2", side_effect=failing_copy):
                mgr._create_default_config_file()

            self.assertTrue(cfg.exists())

    def test_total_failure_raises(self):
        mgr = ConfigManager.__new__(ConfigManager)
        mgr.config_file = Path("/nonexistent/deeply/nested/config.jsonc")
        mgr._config = {}
        mgr._original_content = None
        mgr._lock = __import__("threading").RLock()

        with (
            patch("config_manager.shutil.copy2", side_effect=PermissionError("no")),
            patch("builtins.open", side_effect=PermissionError("no write")),
            self.assertRaises(PermissionError),
        ):
            mgr._create_default_config_file()


# ──────────────────────────────────────────────────────────
# get_config 文件监听异常 (1322-1324)
# ──────────────────────────────────────────────────────────


class TestGetConfigWatcherException(unittest.TestCase):
    def test_watcher_start_exception_returns_manager(self):
        from config_manager import config_manager as global_mgr
        from config_manager import get_config

        global_mgr._file_watcher_running = False
        with patch.object(
            ConfigManager, "start_file_watcher", side_effect=OSError("bad")
        ):
            result = get_config()
            self.assertIsInstance(result, ConfigManager)


# ──────────────────────────────────────────────────────────
# _trigger 方法本身抛异常（覆盖 set/update/update_section 的外层 except）
# ──────────────────────────────────────────────────────────


class TestTriggerCallbackMethodException(unittest.TestCase):
    """_trigger_config_change_callbacks 方法自身异常（非回调内异常）"""

    def test_set_trigger_method_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("lock")
        ):
            mgr.set("notification.debug", True, save=False)

    def test_update_trigger_method_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("lock")
        ):
            mgr.update({"notification.debug": True}, save=False)

    def test_update_section_trigger_method_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("lock")
        ):
            mgr.update_section("notification", {"debug": True}, save=False)


# ──────────────────────────────────────────────────────────
# update_section 嵌套 key 中间路径不存在 (1079-1081)
# ──────────────────────────────────────────────────────────


class TestUpdateSectionDeepNested(unittest.TestCase):
    def test_creates_intermediate_dict(self):
        mgr = ConfigManager()
        mgr.update_section("brand_new.child", {"key": "val"}, save=False)
        result = mgr.get("brand_new", {})
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("child", {}).get("key"), "val")


# ──────────────────────────────────────────────────────────
# set() 中 empty key 走 invalidate_all_caches (865)
# ──────────────────────────────────────────────────────────


class TestSetEmptyKeyInvalidation(unittest.TestCase):
    def test_set_network_security_section_value_in_memory(self):
        """直接在 _config 中设置 key="network_security.xxx" 的情况
        因为 set() 会先路由到专用方法，这里测试空 section 的分支"""
        mgr = ConfigManager()
        mgr.get_section("notification")
        mgr.set("", "x", save=False)


# ──────────────────────────────────────────────────────────
# _delayed_save 没有 pending_changes (658->667)
# ──────────────────────────────────────────────────────────


class TestDelayedSaveNoPending(unittest.TestCase):
    def test_no_pending_changes(self):
        mgr = ConfigManager()
        mgr._pending_changes = {}
        mgr._delayed_save()


# ──────────────────────────────────────────────────────────
# find_config_file uvx 模式用户配置目录分支 (293-322)
# ──────────────────────────────────────────────────────────


class TestFindConfigFileUvxMode(unittest.TestCase):
    def test_uvx_mode_user_config_exists(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.jsonc"
            cfg.write_text("{}")
            with (
                patch("config_manager._is_uvx_mode", return_value=True),
                patch("config_manager.user_config_dir", return_value=td),
                patch("config_manager.PLATFORMDIRS_AVAILABLE", True),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                result = find_config_file("config.jsonc")
                self.assertEqual(result, cfg)

    def test_uvx_mode_json_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            json_f = Path(td) / "config.json"
            json_f.write_text("{}")
            with (
                patch("config_manager._is_uvx_mode", return_value=True),
                patch("config_manager.user_config_dir", return_value=td),
                patch("config_manager.PLATFORMDIRS_AVAILABLE", True),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                result = find_config_file("config.jsonc")
                self.assertEqual(result, json_f)

    def test_uvx_mode_no_file_creates_path(self):
        with tempfile.TemporaryDirectory() as td:
            empty_dir = Path(td) / "empty"
            empty_dir.mkdir()
            with (
                patch("config_manager._is_uvx_mode", return_value=True),
                patch("config_manager.user_config_dir", return_value=str(empty_dir)),
                patch("config_manager.PLATFORMDIRS_AVAILABLE", True),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                result = find_config_file("config.jsonc")
                self.assertEqual(result, empty_dir / "config.jsonc")

    def test_uvx_mode_platformdirs_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            with (
                patch("config_manager._is_uvx_mode", return_value=True),
                patch("config_manager.PLATFORMDIRS_AVAILABLE", False),
                patch(
                    "config_manager._get_user_config_dir_fallback",
                    return_value=Path(td),
                ),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                result = find_config_file("config.jsonc")
                self.assertEqual(result, Path(td) / "config.jsonc")

    def test_uvx_mode_exception_fallback(self):
        with (
            patch("config_manager._is_uvx_mode", return_value=True),
            patch("config_manager.PLATFORMDIRS_AVAILABLE", False),
            patch(
                "config_manager._get_user_config_dir_fallback",
                side_effect=RuntimeError("fail"),
            ),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
            result = find_config_file("config.jsonc")
            self.assertEqual(result, Path("config.jsonc"))


# ──────────────────────────────────────────────────────────
# file_watcher.py 边界分支
# ──────────────────────────────────────────────────────────


class TestFileWatcherEdgeCases(unittest.TestCase):
    """覆盖 file_watcher.py 剩余缺失行/分支"""

    def test_start_watcher_initial_sync_exception(self):
        """lines 54-55: start_file_watcher 首次 mtime 同步异常"""
        mgr = ConfigManager()
        mgr.stop_file_watcher()
        with patch.object(
            type(mgr.config_file), "exists", side_effect=OSError("read err")
        ):
            mgr.start_file_watcher(interval=60.0)
        self.assertTrue(mgr.is_file_watcher_running)
        mgr.stop_file_watcher()

    def test_shutdown_cancel_timer_exception(self):
        """lines 96-97: shutdown 取消 save_timer 时异常"""
        mgr = ConfigManager()
        mock_timer = MagicMock()
        mock_timer.cancel.side_effect = RuntimeError("cancel fail")
        mgr._save_timer = mock_timer
        mgr.shutdown()
        mock_timer.cancel.assert_called_once()

    def test_update_file_mtime_file_not_exist(self):
        """branch 24->exit: 文件不存在时 _update_file_mtime 跳过"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "nonexist.jsonc"
            mgr = ConfigManager(str(cfg_path))
            old_mtime = mgr._last_file_mtime
            mgr._update_file_mtime()
            self.assertEqual(mgr._last_file_mtime, old_mtime)

    def test_stop_file_watcher_thread_none(self):
        """branch 80->82: 线程对象为 None 但 running=True"""
        mgr = ConfigManager()
        mgr.stop_file_watcher()
        mgr._file_watcher_running = True
        mgr._file_watcher_thread = None
        mgr.stop_file_watcher()
        self.assertFalse(mgr.is_file_watcher_running)


if __name__ == "__main__":
    unittest.main()
