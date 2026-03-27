"""TOML 解析/保存引擎 Mixin。

提供 ConfigManager 在保存/更新 TOML 配置文件时所需的
解析、保留注释格式的写回、以及 network_security 段定位能力。

使用 tomlkit 实现注释保留，替代旧版 JSONC 引擎中 800+ 行的手写解析器。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

import tomlkit
from tomlkit.items import Table

from enhanced_logging import EnhancedLogger

if TYPE_CHECKING:
    pass

logger = EnhancedLogger(__name__)


class TomlEngineMixin:
    """TOML 格式配置文件的解析/保存方法集合。"""

    if TYPE_CHECKING:
        _original_content: str | None

        @staticmethod
        def _exclude_network_security(config: Dict[str, Any]) -> Dict[str, Any]: ...

    # ------------------------------------------------------------------
    # TOML 解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_toml(content: str) -> Dict[str, Any]:
        """解析 TOML 内容为普通 dict（丢弃 tomlkit 元数据）"""
        doc = tomlkit.parse(content)
        return doc.unwrap()  # type: ignore[return-value]

    @staticmethod
    def _parse_toml_document(content: str) -> tomlkit.TOMLDocument:
        """解析 TOML 内容为 TOMLDocument（保留注释/格式元数据，用于写回）"""
        return tomlkit.parse(content)

    # ------------------------------------------------------------------
    # TOML 保存（保留注释格式）
    # ------------------------------------------------------------------

    def _save_toml_with_comments(self, config: Dict[str, Any]) -> str:
        """保存 TOML 配置并保留原有注释和格式，排除 network_security"""
        config_to_save = self._exclude_network_security(config.copy())
        if not self._original_content:
            return tomlkit.dumps(tomlkit.item(config_to_save))

        doc = self._parse_toml_document(self._original_content)
        for section_key, section_value in config_to_save.items():
            if section_key == "network_security":
                continue

            if isinstance(section_value, dict) and section_key in doc:
                existing_table = doc[section_key]
                if isinstance(existing_table, Table):
                    self._update_toml_table(existing_table, section_value)
                else:
                    doc[section_key] = section_value
            elif section_key not in doc:
                doc[section_key] = section_value
            else:
                doc[section_key] = section_value

        return tomlkit.dumps(doc)

    @staticmethod
    def _update_toml_table(table: Table, values: Dict[str, Any]) -> None:
        """递归更新 tomlkit Table，仅更新已存在的键（保留格式/注释）"""
        for key, value in values.items():
            if key in table:
                existing = table[key]
                if isinstance(value, dict) and isinstance(existing, Table):
                    TomlEngineMixin._update_toml_table(existing, value)
                else:
                    table[key] = value
            else:
                table[key] = value

    # ------------------------------------------------------------------
    # network_security 段操作
    # ------------------------------------------------------------------

    def _save_network_security_toml(self, ns_config: Dict[str, Any]) -> str:
        """仅更新 TOML 文件中的 network_security 段并返回完整内容"""
        if not self._original_content:
            logger.warning("无原始内容，无法保留格式保存 network_security")
            return ""

        doc = self._parse_toml_document(self._original_content)
        if "network_security" in doc and isinstance(doc["network_security"], Table):
            self._update_toml_table(doc["network_security"], ns_config)
        else:
            doc["network_security"] = ns_config

        return tomlkit.dumps(doc)
