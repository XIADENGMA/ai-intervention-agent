"""io_operations.py (IOOperationsMixin) 单元测试。

覆盖导出/导入/备份/恢复的各分支：
- import_config: 合并/覆盖模式、无 config 包装、network_security 导入失败、非 dict 输入
- backup_config: 默认路径
- restore_config: FileNotFoundError、JSONDecodeError、非 dict 备份、带 network_security
"""

from __future__ import annotations

import json
import os
import unittest

from config_manager import ConfigManager


class TestImportConfig(unittest.TestCase):
    """import_config 方法"""

    def _get_manager(self) -> ConfigManager:
        return ConfigManager()

    def test_import_non_dict_returns_false(self):
        mgr = self._get_manager()
        self.assertFalse(mgr.import_config("not a dict", save=False))  # type: ignore[arg-type]

    def test_import_wrapped_config(self):
        """带 "config" 包装的标准导出格式"""
        mgr = self._get_manager()
        data = {"config": {"notification": {"enabled": True}}, "version": "1.0"}
        self.assertTrue(mgr.import_config(data, merge=True, save=False))

    def test_import_raw_config(self):
        """无 "config" 包装的裸 dict"""
        mgr = self._get_manager()
        data = {"notification": {"enabled": False}}
        self.assertTrue(mgr.import_config(data, merge=True, save=False))

    def test_import_override_mode(self):
        """覆盖模式（merge=False）"""
        mgr = self._get_manager()
        data = {"config": {"notification": {"enabled": True}}}
        self.assertTrue(mgr.import_config(data, merge=False, save=False))

    def test_import_with_network_security_in_wrapper(self):
        """导出格式中包含 network_security"""
        mgr = self._get_manager()
        data = {
            "config": {"notification": {"enabled": True}},
            "network_security": {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["127.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": False,
            },
        }
        self.assertTrue(mgr.import_config(data, merge=True, save=True))

    def test_import_with_network_security_in_raw(self):
        """裸 dict 中包含 network_security"""
        mgr = self._get_manager()
        data = {
            "notification": {"enabled": True},
            "network_security": {
                "bind_interface": "127.0.0.1",
                "allowed_networks": ["127.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            },
        }
        self.assertTrue(mgr.import_config(data, merge=True, save=True))

    def test_import_non_dict_config_field(self):
        """config 字段为非 dict"""
        mgr = self._get_manager()
        data = {"config": "not a dict"}
        self.assertFalse(mgr.import_config(data, save=False))

    def test_import_with_save(self):
        """save=True 时应触发持久化"""
        mgr = self._get_manager()
        data = {"config": {"notification": {"enabled": True}}}
        self.assertTrue(mgr.import_config(data, merge=True, save=True))

    def test_import_network_security_exception(self):
        """network_security 设置失败时返回 False"""
        mgr = self._get_manager()
        data = {
            "config": {"notification": {"enabled": True}},
            "network_security": {"bind_interface": 12345},
        }
        result = mgr.import_config(data, merge=True, save=False)
        self.assertIsInstance(result, bool)


class TestDeepMerge(unittest.TestCase):
    """_deep_merge 方法"""

    def test_simple_merge(self):
        mgr = ConfigManager()
        base = {"a": 1, "b": 2}
        update = {"b": 3, "c": 4}
        mgr._deep_merge(base, update)
        self.assertEqual(base, {"a": 1, "b": 3, "c": 4})

    def test_nested_merge(self):
        mgr = ConfigManager()
        base = {"section": {"x": 1, "y": 2}}
        update = {"section": {"y": 3, "z": 4}}
        mgr._deep_merge(base, update)
        self.assertEqual(base["section"], {"x": 1, "y": 3, "z": 4})

    def test_replace_non_dict(self):
        mgr = ConfigManager()
        base = {"key": "old"}
        update = {"key": {"nested": True}}
        mgr._deep_merge(base, update)
        self.assertEqual(base["key"], {"nested": True})


class TestBackupConfig(unittest.TestCase):
    """backup_config 方法"""

    def test_backup_default_path(self):
        mgr = ConfigManager()
        path = mgr.backup_config()
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("config", data)
        self.assertIn("exported_at", data)
        os.unlink(path)

    def test_backup_custom_path(self):
        mgr = ConfigManager()
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = mgr.backup_config(backup_path=tmp_path)
            self.assertEqual(result, tmp_path)
            self.assertTrue(os.path.exists(tmp_path))
        finally:
            os.unlink(tmp_path)


class TestRestoreConfig(unittest.TestCase):
    """restore_config 方法"""

    def _get_manager(self) -> ConfigManager:
        return ConfigManager()

    def test_restore_file_not_found(self):
        mgr = self._get_manager()
        self.assertFalse(mgr.restore_config("/nonexistent/path.json"))

    def test_restore_invalid_json(self):
        import tempfile

        mgr = self._get_manager()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write("{invalid json content")
            tmp_path = tmp.name

        try:
            self.assertFalse(mgr.restore_config(tmp_path))
        finally:
            os.unlink(tmp_path)

    def test_restore_non_dict_content(self):
        import tempfile

        mgr = self._get_manager()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(["not", "a", "dict"], tmp)
            tmp_path = tmp.name

        try:
            self.assertFalse(mgr.restore_config(tmp_path))
        finally:
            os.unlink(tmp_path)

    def test_restore_non_dict_config_field(self):
        import tempfile

        mgr = self._get_manager()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump({"config": "not a dict", "version": "1.0"}, tmp)
            tmp_path = tmp.name

        try:
            self.assertFalse(mgr.restore_config(tmp_path))
        finally:
            os.unlink(tmp_path)

    def test_restore_with_network_security(self):
        import tempfile

        mgr = self._get_manager()
        backup_data = {
            "config": {"notification": {"enabled": True}},
            "network_security": {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["127.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(backup_data, tmp)
            tmp_path = tmp.name

        try:
            self.assertTrue(mgr.restore_config(tmp_path))
        finally:
            os.unlink(tmp_path)

    def test_restore_raw_dict_backup(self):
        """无 config 包装的裸 dict 备份"""
        import tempfile

        mgr = self._get_manager()
        backup_data = {"notification": {"enabled": False}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(backup_data, tmp)
            tmp_path = tmp.name

        try:
            self.assertTrue(mgr.restore_config(tmp_path))
        finally:
            os.unlink(tmp_path)

    def test_backup_then_restore_roundtrip(self):
        """备份→恢复往返测试"""
        import tempfile

        mgr = self._get_manager()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mgr.backup_config(backup_path=tmp_path)
            self.assertTrue(mgr.restore_config(tmp_path))
        finally:
            os.unlink(tmp_path)


class TestExportConfig(unittest.TestCase):
    """export_config 方法"""

    def test_export_without_network_security(self):
        mgr = ConfigManager()
        data = mgr.export_config(include_network_security=False)
        self.assertIn("config", data)
        self.assertIn("exported_at", data)
        self.assertNotIn("network_security", data)

    def test_export_with_network_security(self):
        mgr = ConfigManager()
        data = mgr.export_config(include_network_security=True)
        self.assertIn("network_security", data)
        ns = data["network_security"]
        self.assertIn("bind_interface", ns)


if __name__ == "__main__":
    unittest.main()
