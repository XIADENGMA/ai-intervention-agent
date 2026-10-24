"""io_operations.py (IOOperationsMixin) 单元测试。

覆盖导出/导入/备份/恢复的各分支：
- import_config: 合并/覆盖模式、无 config 包装、network_security 导入失败、非 dict 输入
- backup_config: 默认路径
- restore_config: FileNotFoundError、JSONDecodeError、非 dict 备份、带 network_security
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from ai_intervention_agent.config_manager import ConfigManager


class TestImportConfig(unittest.TestCase):
    """import_config 方法"""

    def _get_manager(self) -> ConfigManager:
        # 私有管理器 + 私有配置文件，用例结束时关掉：save=True 的导入会排一个 3 秒的延迟保存，
        # 不关的话它落进别的用例里去写那个用例共用的配置文件（见 TestImportConfigLeavesNoSaveBehind）
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        manager = ConfigManager(os.path.join(directory.name, "config.toml"))
        self.addCleanup(manager.shutdown)
        return manager

    def test_import_non_dict_returns_false(self):
        mgr = self._get_manager()
        self.assertFalse(mgr.import_config("not a dict", save=False))  # ty: ignore[invalid-argument-type]

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


class TestImportConfigLeavesNoSaveBehind(unittest.TestCase):
    """TestImportConfig 的用例结束时，它们排的延迟保存都已了结。

    ``import_config(save=True)`` 在私有管理器上排一个 3 秒的定时器。定时器活过用例的话，
    3 秒后它会落进当时正在跑的别的用例里（别的文件也一样），去解析并写那个用例共用的
    配置文件；``tracemalloc`` 数的是整个进程，R845 的内存测试就这样被一次保存弄红过。
    """

    def test_every_save_scheduled_by_these_tests_is_done_when_they_end(self):
        saves: list[threading.Timer] = []
        real_start = threading.Timer.start
        this_thread = threading.get_ident()

        def start_and_remember(timer: threading.Timer) -> None:
            # 只记这个线程（跑用例的线程）起的配置保存定时器，别的线程里起的不算
            is_a_config_save = (
                getattr(timer.function, "__func__", None) is ConfigManager._delayed_save
            )
            if is_a_config_save and threading.get_ident() == this_thread:
                saves.append(timer)
            real_start(timer)

        result = unittest.TestResult()
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestImportConfig)
        try:
            with patch.object(threading.Timer, "start", start_and_remember):
                suite.run(result)
            # 先数还没了结的，再统一取消：不管结论如何，这里都不留定时器给别的用例
            left_behind = [timer for timer in saves if not timer.finished.is_set()]
        finally:
            for timer in saves:
                timer.cancel()

        self.assertEqual(result.errors + result.failures, [])
        # 对照：这些用例确实会排保存（没有的话，下面的断言就空转了）
        self.assertTrue(saves, "TestImportConfig 里没有用例排保存了，这条测试已经空转")
        self.assertEqual(
            left_behind,
            [],
            f"{len(left_behind)} 个延迟保存在用例结束后还排着",
        )


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

    def test_restore_config_lookup_uses_lazy_default_path(self):
        import inspect

        from ai_intervention_agent.config_modules.io_operations import IOOperationsMixin

        source = inspect.getsource(IOOperationsMixin.restore_config)

        self.assertIn('actual_config = backup_data.get("config")', source)
        self.assertNotIn('backup_data.get("config", {})', source)

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


# ---------------------------------------------------------------------------
# 边界路径补充（原 test_io_operations_extended.py）
# ---------------------------------------------------------------------------


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
