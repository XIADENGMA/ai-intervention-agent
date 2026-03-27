"""io_operations.py 扩展单元测试。

覆盖基础测试未触及的边界路径：
- import_config: network_security 在 "config" 内（line 65）
- import_config: set_network_security_config 异常（lines 90-92）
- import_config: 外层异常捕获（lines 98-100）
- restore_config: 备份含 network_security（140->145 分支）
- restore_config: 通用异常处理（lines 165-167）
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from config_manager import ConfigManager


class _ManagerHelper:
    @staticmethod
    def make() -> ConfigManager:
        return ConfigManager()


class TestImportConfigNsInsideWrapper(unittest.TestCase):
    """network_security 在 config wrapper 内部而非顶层"""

    def test_ns_found_in_actual_config(self):
        """ "config" 字段内含 network_security 时应被提取（line 65）"""
        mgr = _ManagerHelper.make()
        data = {
            "config": {
                "notification": {"enabled": True},
                "network_security": {
                    "bind_interface": "0.0.0.0",
                    "allowed_networks": ["127.0.0.0/8"],
                    "blocked_ips": [],
                    "access_control_enabled": False,
                },
            }
        }
        result = mgr.import_config(data, merge=True, save=False)
        self.assertTrue(result)


class TestImportConfigNsSetException(unittest.TestCase):
    """set_network_security_config 抛出异常"""

    def test_ns_set_raises_returns_false(self):
        """network_security 导入异常时返回 False（lines 90-92）"""
        mgr = _ManagerHelper.make()
        data = {
            "config": {"notification": {"enabled": True}},
            "network_security": {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["127.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": False,
            },
        }
        with patch.object(
            mgr, "set_network_security_config", side_effect=RuntimeError("boom")
        ):
            result = mgr.import_config(data, merge=True, save=False)
        self.assertFalse(result)


class TestImportConfigOuterException(unittest.TestCase):
    """import_config 外层 try/except"""

    def test_deep_merge_raises(self):
        """合并过程中异常被外层捕获（lines 98-100）"""
        mgr = _ManagerHelper.make()
        data = {"config": {"notification": {"enabled": True}}}
        with patch.object(mgr, "_deep_merge", side_effect=RuntimeError("merge boom")):
            result = mgr.import_config(data, merge=True, save=False)
        self.assertFalse(result)


class TestRestoreConfigWithNs(unittest.TestCase):
    """restore_config 备份包含 network_security"""

    def test_restore_with_network_security(self):
        """备份中含 network_security 时应被合并恢复（140->145 分支）"""
        mgr = _ManagerHelper.make()
        backup_data = {
            "config": {
                "notification": {"enabled": True},
            },
            "network_security": {
                "bind_interface": "127.0.0.1",
                "allowed_networks": ["127.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": False,
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(backup_data, f)
            backup_path = f.name

        try:
            result = mgr.restore_config(backup_path)
            self.assertTrue(result)
        finally:
            os.unlink(backup_path)


class TestRestoreConfigGenericException(unittest.TestCase):
    """restore_config 通用异常"""

    def test_generic_exception_returns_false(self):
        """非 FileNotFoundError/JSONDecodeError 的异常（lines 165-167）"""
        mgr = _ManagerHelper.make()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"config": {"notification": {"enabled": True}}}, f)
            backup_path = f.name

        try:
            with patch.object(mgr, "_load_config", side_effect=OSError("disk error")):
                result = mgr.restore_config(backup_path)
            self.assertFalse(result)
        finally:
            os.unlink(backup_path)


if __name__ == "__main__":
    unittest.main()
