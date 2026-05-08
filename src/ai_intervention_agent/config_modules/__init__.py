"""config_modules — ConfigManager 路由 Mixin 模块。

将 ConfigManager 的方法按职责拆分为独立 Mixin，
降低单文件复杂度，同时保持外部 API 完全不变。
"""

from ai_intervention_agent.config_modules.file_watcher import FileWatcherMixin
from ai_intervention_agent.config_modules.io_operations import IOOperationsMixin
from ai_intervention_agent.config_modules.network_security import NetworkSecurityMixin
from ai_intervention_agent.config_modules.toml_engine import TomlEngineMixin

__all__ = [
    "FileWatcherMixin",
    "IOOperationsMixin",
    "NetworkSecurityMixin",
    "TomlEngineMixin",
]
