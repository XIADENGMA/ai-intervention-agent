"""pytest 全局测试配置

目标：
- 让测试完全可重复、可离线运行
- 避免读取/污染用户真实配置（~/.config/ai-intervention-agent/）

实现：
- 通过环境变量 AI_INTERVENTION_AGENT_CONFIG_FILE 指定临时配置文件路径
- 该环境变量会被 config_manager.find_config_file() 优先读取

注意：
- 这里使用 TemporaryDirectory，并把对象保存在模块全局，确保整个 pytest 会话期间目录不被提前清理
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# 会话级临时目录（pytest 退出时自动清理）
_TEST_TMP_DIR = tempfile.TemporaryDirectory(prefix="ai-intervention-agent-pytest-")
_TEST_CONFIG_PATH = Path(_TEST_TMP_DIR.name) / "config.jsonc"

# 仅当外部未显式指定时才注入，方便本地/CI 自定义
os.environ.setdefault("AI_INTERVENTION_AGENT_CONFIG_FILE", str(_TEST_CONFIG_PATH))
