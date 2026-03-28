"""配置导出/导入/备份/恢复 Mixin。

提供 ConfigManager 的配置数据导出、导入（合并/覆盖）、
文件备份及恢复能力。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import TYPE_CHECKING, Any, cast

from enhanced_logging import EnhancedLogger

if TYPE_CHECKING:
    from pathlib import Path
    from threading import RLock

logger = EnhancedLogger(__name__)


class IOOperationsMixin:
    """配置导出/导入/备份/恢复方法集合。"""

    if TYPE_CHECKING:
        _lock: RLock
        _config: dict[str, Any]
        _pending_changes: dict[str, Any]
        config_file: Path
        _original_content: str | None

        def get_network_security_config(self) -> dict[str, Any]: ...
        def set_network_security_config(
            self,
            config: dict[str, Any],
            save: bool = True,
            trigger_callbacks: bool = True,
        ) -> None: ...
        @staticmethod
        def _exclude_network_security(config: dict[str, Any]) -> dict[str, Any]: ...
        def _save_config(self) -> None: ...
        def _trigger_config_change_callbacks(self) -> None: ...
        def _is_toml_file(self) -> bool: ...
        def _update_file_mtime(self) -> None: ...
        def _load_config(self) -> None: ...
        def invalidate_all_caches(self) -> None: ...

    def export_config(self, include_network_security: bool = False) -> dict[str, Any]:
        """导出当前配置（可选包含 network_security）"""
        with self._lock:
            export_data = {
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "version": "1.0",
                "config": self._exclude_network_security(self._config.copy()),
            }

            if include_network_security:
                export_data["network_security"] = self.get_network_security_config()

            return export_data

    def import_config(
        self, config_data: dict[str, Any], merge: bool = True, save: bool = True
    ) -> bool:
        """导入配置（支持合并或覆盖模式）"""
        try:
            if not isinstance(config_data, dict):
                logger.error("导入失败：配置数据必须是字典格式")
                return False

            actual_config: Any
            network_security: dict[str, Any] | None = None

            if "config" in config_data:
                actual_config = config_data.get("config")
                network_security_raw = config_data.get("network_security")
                if isinstance(network_security_raw, dict):
                    network_security = cast(dict[str, Any], network_security_raw)
            else:
                actual_config = config_data
                network_security_raw = actual_config.get("network_security")
                if isinstance(network_security_raw, dict):
                    network_security = cast(dict[str, Any], network_security_raw)

            if not isinstance(actual_config, dict):
                logger.error("导入失败：配置数据必须是字典格式（config 字段）")
                return False

            if network_security is None:
                ns_in_config = actual_config.get("network_security")
                if isinstance(ns_in_config, dict):
                    network_security = cast(dict[str, Any], ns_in_config)

            with self._lock:
                if merge:
                    tmp = dict(actual_config)
                    tmp.pop("network_security", None)
                    self._deep_merge(self._config, tmp)
                    logger.info("配置已合并导入")
                else:
                    tmp = dict(actual_config)
                    tmp.pop("network_security", None)
                    self._config = tmp.copy()
                    logger.info("配置已覆盖导入")

                if save:
                    tmp = dict(actual_config)
                    tmp.pop("network_security", None)
                    self._pending_changes.update(tmp)
                    self._save_config()

            if network_security is not None:
                try:
                    self.set_network_security_config(
                        network_security, save=save, trigger_callbacks=False
                    )
                except Exception as e:
                    logger.error(f"导入 network_security 失败: {e}", exc_info=True)
                    return False

            self._trigger_config_change_callbacks()

            return True

        except Exception as e:
            logger.error(f"导入配置失败: {e}", exc_info=True)
            return False

    def _deep_merge(self, base: dict, update: dict):
        """递归合并 update 到 base"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def backup_config(self, backup_path: str | None = None) -> str:
        """备份当前配置到文件"""
        if backup_path is None:
            backup_path = str(self.config_file) + ".backup"

        export_data = self.export_config(include_network_security=True)

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        logger.info(f"配置已备份到: {backup_path}")
        return backup_path

    def restore_config(self, backup_path: str) -> bool:
        """从备份文件恢复配置"""
        try:
            with open(backup_path, encoding="utf-8") as f:
                backup_data = json.load(f)

            if not isinstance(backup_data, dict):
                logger.error("恢复配置失败: 备份文件内容必须是字典")
                return False

            if "config" in backup_data:
                actual_config = backup_data.get("config", {})
                if not isinstance(actual_config, dict):
                    logger.error("恢复配置失败: 备份中的 config 必须是字典")
                    return False
                restored_config = dict(actual_config)
                network_security = backup_data.get("network_security")
                if isinstance(network_security, dict):
                    restored_config["network_security"] = network_security
            else:
                restored_config = dict(backup_data)

            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            if self._is_toml_file():
                import tomlkit as _tk

                content = _tk.dumps(_tk.item(restored_config))
            else:
                content = json.dumps(restored_config, indent=2, ensure_ascii=False)

            # 原子写入：tempfile → fsync → os.replace
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", dir=str(self.config_file.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(self.config_file))
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            with self._lock:
                self._original_content = content
            self._update_file_mtime()
            self._load_config()
            self.invalidate_all_caches()
            self._trigger_config_change_callbacks()
            logger.info(f"配置已从 {backup_path} 恢复")
            return True

        except FileNotFoundError:
            logger.error(f"备份文件不存在: {backup_path}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"备份文件格式错误: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"恢复配置失败: {e}", exc_info=True)
            return False
