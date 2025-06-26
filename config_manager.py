#!/usr/bin/env python3
"""
配置管理模块
统一管理应用程序的所有配置
"""

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def parse_jsonc(content: str) -> Dict[str, Any]:
    """解析 JSONC (JSON with Comments) 格式的内容

    Args:
        content: JSONC 格式的字符串内容

    Returns:
        解析后的字典对象
    """
    # 更安全的注释移除方式
    lines = content.split("\n")
    cleaned_lines = []
    in_multiline_comment = False

    for line in lines:
        if in_multiline_comment:
            # 查找多行注释结束
            if "*/" in line:
                line = line[line.find("*/") + 2 :]
                in_multiline_comment = False
            else:
                continue

        # 处理多行注释开始
        if "/*" in line:
            before_comment = line[: line.find("/*")]
            after_comment = line[line.find("/*") :]
            if "*/" in after_comment:
                # 单行内的多行注释
                line = before_comment + after_comment[after_comment.find("*/") + 2 :]
            else:
                # 多行注释开始
                line = before_comment
                in_multiline_comment = True

        # 移除单行注释 //（但要注意字符串内的 //）
        in_string = False
        escape_next = False
        comment_pos = -1

        for i, char in enumerate(line):
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if (
                not in_string
                and char == "/"
                and i + 1 < len(line)
                and line[i + 1] == "/"
            ):
                comment_pos = i
                break

        if comment_pos >= 0:
            line = line[:comment_pos]

        cleaned_lines.append(line)

    cleaned_content = "\n".join(cleaned_lines)

    # 解析 JSON
    return json.loads(cleaned_content)


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_file: str = "config.jsonc"):
        self.config_file = Path(config_file)
        # 向后兼容：如果 .jsonc 不存在但 .json 存在，则使用 .json
        if not self.config_file.exists() and config_file == "config.jsonc":
            json_file = Path("config.json")
            if json_file.exists():
                self.config_file = json_file
                logger.info("使用现有的 config.json 文件")

        self._config = {}
        self._lock = threading.RLock()
        self._original_content: Optional[str] = None  # 保存原始文件内容
        self._load_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "notification": {
                "enabled": True,
                "web_enabled": True,
                "auto_request_permission": True,
                "sound_enabled": True,
                "sound_mute": False,
                "sound_volume": 80,
                "mobile_optimized": True,
                "mobile_vibrate": True,
                "bark_enabled": False,
                "bark_url": "https://bark.xiadengma.com/push",
                "bark_device_key": "",
                "bark_icon": "https://filess.s3.bitiful.net/Bark/btc.png",
                "bark_action": "none",
            },
            "web_ui": {
                "host": "0.0.0.0",
                "port": 8082,
                "debug": False,
                "max_retries": 3,
                "retry_delay": 1.0,
            },
            "feedback": {"timeout": 300},
        }

    def _load_config(self):
        """加载配置文件"""
        with self._lock:
            try:
                if self.config_file.exists():
                    with open(self.config_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    # 保存原始内容（用于保留注释）
                    self._original_content = content

                    # 根据文件扩展名选择解析方式
                    if self.config_file.suffix.lower() == ".jsonc":
                        self._config = parse_jsonc(content)
                        logger.info(f"JSONC 配置文件已加载: {self.config_file}")
                    else:
                        self._config = json.loads(content)
                        logger.info(f"JSON 配置文件已加载: {self.config_file}")
                else:
                    # 创建默认配置文件
                    self._config = self._get_default_config()
                    self._save_config()
                    logger.info(f"创建默认配置文件: {self.config_file}")

                # 合并默认配置（确保新增的配置项存在）
                default_config = self._get_default_config()
                self._config = self._merge_config(default_config, self._config)

            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
                self._config = self._get_default_config()

    def _merge_config(
        self, default: Dict[str, Any], current: Dict[str, Any]
    ) -> Dict[str, Any]:
        """合并配置，确保所有默认键都存在"""
        result = default.copy()
        for key, value in current.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result

    def _save_jsonc_with_comments(self, config: Dict[str, Any]) -> str:
        """保存 JSONC 格式配置，保留原有注释和格式"""
        if not self._original_content:
            # 如果没有原始内容，使用标准 JSON 格式
            return json.dumps(config, indent=2, ensure_ascii=False)

        lines = self._original_content.split("\n")
        result_lines = []

        def update_value_in_line(line: str, key: str, value: Any) -> str:
            """在行中更新配置值，保留注释和格式"""
            # 匹配 JSON 键值对的正则表达式
            pattern = rf'(\s*"{re.escape(key)}"\s*:\s*)([^,\n\r]+)(.*)'
            match = re.match(pattern, line)

            if match:
                prefix, _, suffix = match.groups()
                # 格式化新值
                if isinstance(value, str):
                    new_value = json.dumps(value, ensure_ascii=False)
                elif isinstance(value, bool):
                    new_value = "true" if value else "false"
                elif value is None:
                    new_value = "null"
                else:
                    new_value = json.dumps(value, ensure_ascii=False)

                return f"{prefix}{new_value}{suffix}"
            return line

        def process_config_section(config_dict: Dict[str, Any], section_name: str = ""):
            """递归处理配置段"""
            for key, value in config_dict.items():
                current_key = f"{section_name}.{key}" if section_name else key

                if isinstance(value, dict):
                    # 递归处理嵌套对象
                    process_config_section(value, current_key)
                else:
                    # 更新配置值
                    for i, line in enumerate(result_lines):
                        if f'"{key}"' in line and not line.strip().startswith("//"):
                            result_lines[i] = update_value_in_line(line, key, value)
                            break

        # 复制原始行
        result_lines = lines.copy()

        # 处理配置更新
        process_config_section(config)

        return "\n".join(result_lines)

    def _save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                if (
                    self.config_file.suffix.lower() == ".jsonc"
                    and self._original_content
                ):
                    # 对于 JSONC 文件，尝试保留注释
                    content = self._save_jsonc_with_comments(self._config)
                    f.write(content)
                    logger.debug(
                        f"JSONC 配置文件已保存（保留注释）: {self.config_file}"
                    )
                else:
                    # 对于 JSON 文件或没有原始内容的情况，使用标准 JSON 格式
                    json.dump(self._config, f, indent=2, ensure_ascii=False)
                    logger.debug(f"JSON 配置文件已保存: {self.config_file}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号分隔的嵌套键"""
        with self._lock:
            keys = key.split(".")
            value = self._config
            try:
                for k in keys:
                    value = value[k]
                return value
            except (KeyError, TypeError):
                return default

    def set(self, key: str, value: Any, save: bool = True):
        """设置配置值，支持点号分隔的嵌套键"""
        with self._lock:
            keys = key.split(".")
            config = self._config

            # 导航到目标位置
            for k in keys[:-1]:
                if k not in config:
                    config[k] = {}
                config = config[k]

            # 设置值
            config[keys[-1]] = value

            if save:
                self._save_config()

            logger.debug(f"配置已更新: {key} = {value}")

    def update(self, updates: Dict[str, Any], save: bool = True):
        """批量更新配置"""
        with self._lock:
            for key, value in updates.items():
                self.set(key, value, save=False)

            if save:
                self._save_config()

    def get_section(self, section: str) -> Dict[str, Any]:
        """获取配置段"""
        return self.get(section, {})

    def update_section(self, section: str, updates: Dict[str, Any], save: bool = True):
        """更新配置段"""
        with self._lock:
            current_section = self.get_section(section)
            current_section.update(updates)
            self.set(section, current_section, save=save)

    def reload(self):
        """重新加载配置文件"""
        logger.info("重新加载配置文件")
        self._load_config()

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        with self._lock:
            return self._config.copy()


# 全局配置管理器实例
config_manager = ConfigManager()


def get_config() -> ConfigManager:
    """获取配置管理器实例"""
    return config_manager
