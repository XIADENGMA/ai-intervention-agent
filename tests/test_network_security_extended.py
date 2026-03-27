"""config_modules/network_security.py 覆盖率补充测试。

覆盖 _validate_network_security_config 边界、
_save_network_security_config_immediate 各写入路径、
get_network_security_config 异常/默认/JSON 分支、
回调异常路径等。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_manager import ConfigManager


class TestValidateBlockedIps(unittest.TestCase):
    """_validate_network_security_config 中 blocked_ips 分支"""

    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_blocked_ips_non_string_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"blocked_ips": [123, "127.0.0.1"]}
        )
        self.assertIn("127.0.0.1", result["blocked_ips"])
        self.assertNotIn(123, result["blocked_ips"])

    def test_blocked_ips_empty_string_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"blocked_ips": ["", " ", "127.0.0.1"]}
        )
        self.assertIn("127.0.0.1", result["blocked_ips"])
        self.assertEqual(len(result["blocked_ips"]), 1)

    def test_blocked_ips_invalid_address(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"blocked_ips": ["not_an_ip", "192.168.1.1"]}
        )
        self.assertIn("192.168.1.1", result["blocked_ips"])
        self.assertNotIn("not_an_ip", result["blocked_ips"])

    def test_blocked_ips_not_list(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config({"blocked_ips": "not_a_list"})
        self.assertEqual(result["blocked_ips"], [])


class TestValidateAllowedNetworks(unittest.TestCase):
    """_validate_network_security_config 中 allowed_networks 边界"""

    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_non_string_item_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": [42, "10.0.0.0/8"]}
        )
        self.assertIn("10.0.0.0/8", result["allowed_networks"])

    def test_empty_string_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["", "10.0.0.0/8"]}
        )
        self.assertIn("10.0.0.0/8", result["allowed_networks"])

    def test_invalid_cidr_ignored(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["not/cidr", "10.0.0.0/8"]}
        )
        self.assertIn("10.0.0.0/8", result["allowed_networks"])

    def test_not_list_uses_default(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config({"allowed_networks": "bad"})
        self.assertIn("127.0.0.0/8", result["allowed_networks"])

    def test_empty_list_gets_fallback(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config({"allowed_networks": []})
        self.assertIn("127.0.0.0/8", result["allowed_networks"])
        self.assertIn("::1/128", result["allowed_networks"])

    def test_ip_without_cidr(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["192.168.1.100"]}
        )
        self.assertIn("192.168.1.100", result["allowed_networks"])

    def test_dedup(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"allowed_networks": ["10.0.0.0/8", "10.0.0.0/8"]}
        )
        self.assertEqual(result["allowed_networks"].count("10.0.0.0/8"), 1)


class TestValidateBindInterface(unittest.TestCase):
    """_validate_network_security_config 中 bind_interface 边界"""

    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_non_string_bind(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config({"bind_interface": 12345})
        self.assertEqual(result["bind_interface"], "127.0.0.1")

    def test_invalid_bind(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"bind_interface": "bad_address"}
        )
        self.assertEqual(result["bind_interface"], "127.0.0.1")

    def test_valid_ip_bind(self):
        mgr = self._mgr()
        result = mgr._validate_network_security_config(
            {"bind_interface": "192.168.1.1"}
        )
        self.assertEqual(result["bind_interface"], "192.168.1.1")


# ──────────────────────────────────────────────────────────
# _save_network_security_config_immediate 各路径
# ──────────────────────────────────────────────────────────


class TestSaveNetworkSecurityImmediate(unittest.TestCase):
    """测试各种文件格式/内容状态下的保存逻辑"""

    def test_json_format_save(self):
        """非 JSONC 后缀 → JSON 保存路径"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{"notification": {}}')
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["10.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)

    def test_json_format_empty_content(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("")
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)

    def test_json_format_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("{bad json")
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)

    def test_jsonc_no_content_fallback(self):
        """JSONC 文件但无 base_content 和 original_content → JSON dump"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            cfg_path.write_text("")
            mgr = ConfigManager(str(cfg_path))
            mgr._original_content = None
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)

    def test_jsonc_no_ns_range(self):
        """JSONC 有内容但找不到 network_security 范围 → parse + dump"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            cfg_path.write_text('{\n  "notification": {}\n}')
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["10.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            }
            mgr._save_network_security_config_immediate(ns)
            content = cfg_path.read_text()
            self.assertIn("network_security", content)

    def test_config_file_not_exist_creates_default(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "subdir" / "config.jsonc"
            mgr = ConfigManager.__new__(ConfigManager)
            mgr.config_file = cfg_path
            mgr._config = {}
            mgr._original_content = None
            mgr._lock = __import__("threading").RLock()
            mgr._network_security_cache = None
            mgr._network_security_cache_time = 0
            mgr._network_security_cache_ttl = 30.0
            mgr._section_cache = {}
            mgr._section_cache_time = {}
            mgr._section_cache_ttl = 10.0
            mgr._cache_stats = {"hits": 0, "misses": 0, "invalidations": 0}
            mgr._last_file_mtime = 0
            mgr._file_watcher_running = False

            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }

            with patch.object(mgr, "_create_default_config_file"):
                with patch.object(mgr, "_update_file_mtime"):
                    mgr._save_network_security_config_immediate(ns)

    def test_write_exception_raised(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{"a":1}')
            mgr = ConfigManager(str(cfg_path))
            ns = {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [],
                "blocked_ips": [],
                "access_control_enabled": True,
            }

            import os

            os.chmod(str(cfg_path), 0o444)
            try:
                with self.assertRaises(RuntimeError):
                    mgr._save_network_security_config_immediate(ns)
            finally:
                os.chmod(str(cfg_path), 0o644)


# ──────────────────────────────────────────────────────────
# get_network_security_config 各分支
# ──────────────────────────────────────────────────────────


class TestGetNetworkSecurityConfig(unittest.TestCase):
    def test_file_not_exist_returns_default(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "nonexistent.jsonc"
            mgr = ConfigManager(str(cfg_path))
            mgr.invalidate_all_caches()
            result = mgr.get_network_security_config()
            self.assertIn("bind_interface", result)

    def test_json_file_format(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_data = {
                "notification": {},
                "network_security": {
                    "bind_interface": "192.168.1.1",
                    "allowed_networks": ["10.0.0.0/8"],
                    "blocked_ips": [],
                    "access_control_enabled": True,
                },
            }
            cfg_path.write_text(json.dumps(cfg_data))
            mgr = ConfigManager(str(cfg_path))
            mgr.invalidate_all_caches()
            result = mgr.get_network_security_config()
            self.assertEqual(result["bind_interface"], "192.168.1.1")

    def test_no_ns_in_file_uses_default(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            cfg_path.write_text('{\n  "notification": {}\n}')
            mgr = ConfigManager(str(cfg_path))
            mgr.invalidate_all_caches()
            result = mgr.get_network_security_config()
            self.assertIn("bind_interface", result)

    def test_read_exception_returns_cached(self):
        mgr = ConfigManager()
        mgr._network_security_cache = {
            "bind_interface": "1.2.3.4",
            "allowed_networks": [],
            "blocked_ips": [],
            "access_control_enabled": True,
        }
        mgr._network_security_cache_time = 0

        with patch("builtins.open", side_effect=IOError("disk error")):
            result = mgr.get_network_security_config()
            self.assertEqual(result["bind_interface"], "1.2.3.4")

    def test_read_exception_no_cache_returns_default(self):
        mgr = ConfigManager()
        mgr._network_security_cache = None
        mgr._network_security_cache_time = 0

        with patch("builtins.open", side_effect=IOError("disk error")):
            result = mgr.get_network_security_config()
            self.assertIn("bind_interface", result)


# ──────────────────────────────────────────────────────────
# 回调异常路径
# ──────────────────────────────────────────────────────────


class TestCallbackExceptions(unittest.TestCase):
    def test_set_callback_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("fail")
        ):
            mgr.set_network_security_config({"bind_interface": "127.0.0.1"}, save=True)

    def test_update_callback_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("fail")
        ):
            mgr.update_network_security_config(
                {"bind_interface": "127.0.0.1"}, save=True
            )

    def test_update_unknown_field_warned(self):
        mgr = ConfigManager()
        mgr.update_network_security_config({"unknown_field": "val"}, save=True)


# ──────────────────────────────────────────────────────────
# blocked_ips AddressValueError 分支（防御性代码）
# ──────────────────────────────────────────────────────────


class TestBlockedIpsAddressValueError(unittest.TestCase):
    """line 98-99: ip_address 实际抛 ValueError，但代码有 AddressValueError 守卫"""

    def test_address_value_error_caught(self):
        from ipaddress import AddressValueError

        mgr = ConfigManager()
        with patch(
            "config_modules.network_security.ip_address",
            side_effect=AddressValueError("mock"),
        ):
            result = mgr._validate_network_security_config({"blocked_ips": ["1.2.3.4"]})
        self.assertEqual(result["blocked_ips"], [])


# ──────────────────────────────────────────────────────────
# _save_network_security_config_immediate 异常路径
# ──────────────────────────────────────────────────────────


class TestSaveImmediateExceptionPaths(unittest.TestCase):
    """覆盖 save 方法中各种异常/边界分支"""

    def _make_mgr(self, cfg_path: Path) -> ConfigManager:
        mgr = ConfigManager(str(cfg_path))
        return mgr

    _NS = {
        "bind_interface": "0.0.0.0",
        "allowed_networks": ["10.0.0.0/8"],
        "blocked_ips": [],
        "access_control_enabled": True,
    }

    def test_config_file_exists_exception_swallowed(self):
        """lines 131-132: config_file.exists() 首次检查抛异常时被吞掉"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{"a":1}')
            mgr = self._make_mgr(cfg_path)

            original_exists = cfg_path.exists

            call_count = 0

            def exists_side_effect() -> bool:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise OSError("permission denied")
                return original_exists()

            with patch.object(
                type(mgr.config_file),
                "exists",
                new_callable=lambda: property(lambda self: exists_side_effect),
            ):
                mgr._save_network_security_config_immediate(self._NS)

    def test_read_text_exception_raised(self):
        """lines 138-139: read_text 失败时抛 RuntimeError"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text('{"a":1}')
            mgr = self._make_mgr(cfg_path)
            with patch.object(
                type(cfg_path), "read_text", side_effect=PermissionError("denied")
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    mgr._save_network_security_config_immediate(self._NS)
                self.assertIn("读取配置文件失败", str(ctx.exception))

    def test_json_non_dict_content_reset(self):
        """line 145: JSON 解析结果不是 dict（如数组）时重置为空 dict"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("[1, 2, 3]")
            mgr = self._make_mgr(cfg_path)
            mgr._save_network_security_config_immediate(self._NS)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)
            self.assertIsInstance(content, dict)

    def test_jsonc_empty_content_with_original(self):
        """line 161: JSONC 文件内容为空但 _original_content 非空时使用 original"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            cfg_path.write_text("")
            mgr = self._make_mgr(cfg_path)
            mgr._original_content = '{\n  "notification": {}\n}'
            mgr._save_network_security_config_immediate(self._NS)
            content = cfg_path.read_text()
            self.assertIn("network_security", content)

    def test_jsonc_no_base_content_write_exception(self):
        """lines 167-168: JSONC 无 base_content 时写入失败"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            cfg_path.write_text("")
            mgr = self._make_mgr(cfg_path)
            mgr._original_content = None
            with patch.object(
                type(cfg_path), "write_text", side_effect=PermissionError("denied")
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    mgr._save_network_security_config_immediate(self._NS)
                self.assertIn("写入配置文件失败", str(ctx.exception))

    def test_jsonc_parse_returns_non_dict(self):
        """line 183-184: parse_jsonc 返回非 dict 时重置"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            cfg_path.write_text('{\n  "notification": {}\n}')
            mgr = self._make_mgr(cfg_path)
            with patch.object(
                mgr, "_find_network_security_range", return_value=(-1, -1)
            ):
                with patch("config_manager.parse_jsonc", return_value=[1, 2, 3]):
                    mgr._save_network_security_config_immediate(self._NS)
            content = json.loads(cfg_path.read_text())
            self.assertIn("network_security", content)

    def test_jsonc_parse_failure_when_no_ns_range(self):
        """lines 185-186: parse_jsonc 失败时 full_cfg 重置为空 dict"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            cfg_path.write_text('{\n  "notification": {}\n}')
            mgr = self._make_mgr(cfg_path)
            with patch.object(
                mgr, "_find_network_security_range", return_value=(-1, -1)
            ):
                with patch(
                    "config_manager.parse_jsonc", side_effect=ValueError("bad jsonc")
                ):
                    mgr._save_network_security_config_immediate(self._NS)
            content = cfg_path.read_text()
            self.assertIn("network_security", content)

    def test_jsonc_ns_range_not_found_write_exception(self):
        """lines 191-192: ns_range 未找到 + 写入失败"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            cfg_path.write_text('{\n  "notification": {}\n}')
            mgr = self._make_mgr(cfg_path)
            with patch.object(
                mgr, "_find_network_security_range", return_value=(-1, -1)
            ):
                with patch.object(
                    type(cfg_path),
                    "write_text",
                    side_effect=PermissionError("denied"),
                ):
                    with self.assertRaises(RuntimeError) as ctx:
                        mgr._save_network_security_config_immediate(self._NS)
                    self.assertIn("写入配置文件失败", str(ctx.exception))

    def test_jsonc_range_found_write_exception(self):
        """lines 204-205: JSONC 正常路径写入失败"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            original = (
                '{\n  "network_security": {\n    "bind_interface": "127.0.0.1"\n  }\n}'
            )
            cfg_path.write_text(original)
            mgr = self._make_mgr(cfg_path)
            with patch.object(
                type(cfg_path), "write_text", side_effect=PermissionError("denied")
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    mgr._save_network_security_config_immediate(self._NS)
                self.assertIn("写入配置文件失败", str(ctx.exception))


# ──────────────────────────────────────────────────────────
# set/update save=False 分支
# ──────────────────────────────────────────────────────────


class TestSaveSkipBranch(unittest.TestCase):
    """branch 215->217 / 246->249: save=False 时跳过写入"""

    def test_set_network_security_save_false(self):
        mgr = ConfigManager()
        with patch.object(mgr, "_save_network_security_config_immediate") as mock_save:
            mgr.set_network_security_config({"bind_interface": "127.0.0.1"}, save=False)
            mock_save.assert_not_called()

    def test_update_network_security_save_false(self):
        mgr = ConfigManager()
        with patch.object(mgr, "_save_network_security_config_immediate") as mock_save:
            mgr.update_network_security_config(
                {"bind_interface": "127.0.0.1"}, save=False
            )
            mock_save.assert_not_called()


# ──────────────────────────────────────────────────────────
# get_network_security_config 文件不存在分支
# ──────────────────────────────────────────────────────────


class TestGetConfigFileNotExistBranch(unittest.TestCase):
    """lines 274-282: 配置文件在 get 时确实不存在"""

    def test_file_deleted_after_init(self):
        """init 后删除文件，get 走 file-not-exist 分支"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.jsonc"
            cfg_path.write_text('{"network_security":{}}')
            mgr = ConfigManager(str(cfg_path))
            mgr._network_security_cache = None
            mgr._network_security_cache_time = 0
            cfg_path.unlink()
            result = mgr.get_network_security_config()
            self.assertIn("bind_interface", result)
            self.assertIn("allowed_networks", result)
            self.assertIsNotNone(mgr._network_security_cache)


if __name__ == "__main__":
    unittest.main()
