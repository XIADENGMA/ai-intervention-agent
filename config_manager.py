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


def _is_uvx_mode() -> bool:
    """检测是否为uvx方式运行

    通过检查以下特征判断：
    1. 执行路径是否包含uvx相关路径
    2. 环境变量是否包含uvx标识
    3. 当前工作目录是否为临时目录

    Returns:
        True if running via uvx, False otherwise
    """
    import os
    import sys

    # 检查执行路径
    executable_path = sys.executable
    if "uvx" in executable_path or ".local/share/uvx" in executable_path:
        return True

    # 检查环境变量
    if os.getenv("UVX_PROJECT"):
        return True

    # 检查是否在项目开发目录（包含pyproject.toml等开发文件）
    current_dir = Path.cwd()
    dev_files = ["pyproject.toml", "setup.py", "setup.cfg", ".git"]

    # 如果当前目录或父目录包含开发文件，认为是开发模式
    for path in [current_dir] + list(current_dir.parents):
        if any((path / dev_file).exists() for dev_file in dev_files):
            return False

    # 默认认为是uvx模式（更安全的假设）
    return True


def find_config_file(config_filename: str = "config.jsonc") -> Path:
    """查找配置文件路径

    根据运行方式查找配置文件：
    - uvx方式：只使用用户配置目录的全局配置
    - 开发模式：优先当前目录，然后用户配置目录

    跨平台配置目录位置：
    - Linux: ~/.config/ai-intervention-agent/
    - macOS: ~/Library/Application Support/ai-intervention-agent/
    - Windows: %APPDATA%/ai-intervention-agent/

    Args:
        config_filename: 配置文件名

    Returns:
        配置文件的Path对象
    """
    # 检测是否为uvx方式运行
    is_uvx_mode = _is_uvx_mode()

    if is_uvx_mode:
        logger.info("检测到uvx运行模式，使用用户配置目录")
    else:
        logger.info("检测到开发模式，优先使用当前目录配置")

    if not is_uvx_mode:
        # 开发模式：1. 检查当前工作目录
        current_dir_config = Path(config_filename)
        if current_dir_config.exists():
            logger.info(f"使用当前目录的配置文件: {current_dir_config.absolute()}")
            return current_dir_config

        # 向后兼容：检查当前目录的.json文件
        if config_filename == "config.jsonc":
            current_dir_json = Path("config.json")
            if current_dir_json.exists():
                logger.info(
                    f"使用当前目录的JSON配置文件: {current_dir_json.absolute()}"
                )
                return current_dir_json

    # 2. 检查用户配置目录（使用跨平台标准位置）
    try:
        # 尝试使用 platformdirs 库获取标准配置目录
        try:
            from platformdirs import user_config_dir

            user_config_dir_path = Path(user_config_dir("ai-intervention-agent"))
        except ImportError:
            # 如果没有 platformdirs，回退到手动判断
            user_config_dir_path = _get_user_config_dir_fallback()

        user_config_file = user_config_dir_path / config_filename

        if user_config_file.exists():
            logger.info(f"使用用户配置目录的配置文件: {user_config_file}")
            return user_config_file

        # 向后兼容：检查用户配置目录的.json文件
        if config_filename == "config.jsonc":
            user_json_file = user_config_dir_path / "config.json"
            if user_json_file.exists():
                logger.info(f"使用用户配置目录的JSON配置文件: {user_json_file}")
                return user_json_file

        # 3. 如果都不存在，返回用户配置目录路径（用于创建默认配置）
        logger.info(f"配置文件不存在，将在用户配置目录创建: {user_config_file}")
        return user_config_file

    except Exception as e:
        logger.warning(f"获取用户配置目录失败: {e}，使用当前目录")
        return Path(config_filename)


def _get_user_config_dir_fallback() -> Path:
    """获取用户配置目录的回退实现（不依赖 platformdirs）"""
    import os
    import platform

    system = platform.system().lower()
    home = Path.home()

    if system == "windows":
        # Windows: %APPDATA%/ai-intervention-agent/
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "ai-intervention-agent"
        else:
            return home / "AppData" / "Roaming" / "ai-intervention-agent"
    elif system == "darwin":
        # macOS: ~/Library/Application Support/ai-intervention-agent/
        return home / "Library" / "Application Support" / "ai-intervention-agent"
    else:
        # Linux/Unix: ~/.config/ai-intervention-agent/
        xdg_config_home = os.getenv("XDG_CONFIG_HOME")
        if xdg_config_home:
            return Path(xdg_config_home) / "ai-intervention-agent"
        else:
            return home / ".config" / "ai-intervention-agent"


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_file: str = "config.jsonc"):
        # 使用新的配置文件查找逻辑
        self.config_file = find_config_file(config_file)

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
                "bark_url": "https://api.day.app/push",
                "bark_device_key": "",
                "bark_icon": "",
                "bark_action": "none",
            },
            "web_ui": {
                "host": "0.0.0.0",
                "port": 8080,
                "debug": False,
                "max_retries": 3,
                "retry_delay": 1.0,
            },
            "feedback": {"timeout": 600},
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
                    self._create_default_config_file()
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

    def _create_default_config_file(self):
        """创建带注释的默认配置文件"""
        try:
            # 确保配置文件目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            # 创建带注释的JSONC配置文件内容
            default_content = """{
  // 通知配置
  "notification": {
    "enabled": true,                    // 是否启用通知功能
    "web_enabled": true,                // 是否启用Web浏览器通知
    "auto_request_permission": true,    // 是否自动请求通知权限
    "sound_enabled": true,              // 是否启用声音通知
    "sound_mute": false,                // 是否静音
    "sound_volume": 800000,             // 声音音量 (0-1000000)
    "mobile_optimized": true,           // 是否启用移动端优化
    "mobile_vibrate": true,             // 移动端是否启用震动
    "bark_enabled": false,              // 是否启用Bark推送通知
    "bark_url": "",                     // Bark服务器URL (例如: https://api.day.app/push)
    "bark_device_key": "",              // Bark设备密钥
    "bark_icon": "",                    // Bark通知图标URL (可选)
    "bark_action": "none"               // Bark通知动作 (none/url/copy)
  },

  // Web界面配置
  "web_ui": {
    "host": "0.0.0.0",                  // Web服务监听地址
    "port": 8080,                       // Web服务端口
    "debug": false,                     // 是否启用调试模式
    "max_retries": 3,                   // 最大重试次数
    "retry_delay": 1.0                  // 重试延迟时间(秒)
  },

  // 反馈配置
  "feedback": {
    "timeout": 600                      // 反馈超时时间(秒)
  }
}"""

            with open(self.config_file, "w", encoding="utf-8") as f:
                f.write(default_content)

            # 保存原始内容用于后续更新时保留注释
            self._original_content = default_content

            logger.info(f"已创建默认JSONC配置文件: {self.config_file}")

        except Exception as e:
            logger.error(f"创建默认配置文件失败: {e}")
            # 如果创建JSONC文件失败，回退到普通JSON文件
            self._save_config()

    def _save_config(self):
        """保存配置文件"""
        try:
            # 确保配置文件目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

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
