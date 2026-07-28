"""项目统一异常定义。"""

from __future__ import annotations

from typing import Any


class AIAgentError(Exception):
    """项目基础异常。"""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details: dict[str, Any] = details or {}


class ConfigError(AIAgentError):
    """配置加载、解析或校验失败。"""


class ConfigFileNotFoundError(ConfigError):
    """配置文件不存在。"""


class ConfigValidationError(ConfigError):
    """配置值不满足约束条件。"""


class ServiceConnectionError(AIAgentError):
    """与 Web UI / 外部服务通信失败（连接、超时、HTTP 非 2xx 等）。"""


class ServiceUnavailableError(ServiceConnectionError):
    """服务未启动或无法到达。"""


class ServiceTimeoutError(ServiceConnectionError):
    """请求超时。"""


class TaskError(AIAgentError):
    """任务创建、执行或等待失败。"""


class TaskNotFoundError(TaskError):
    """指定任务不存在。"""


class TaskTimeoutError(TaskError):
    """等待任务完成超时。"""


class NotificationError(AIAgentError):
    """通知发送或配置错误。"""


class ValidationError(AIAgentError):
    """输入参数不合法。"""


def make_error_response(
    message: str,
    status_code: int = 400,
    *,
    code: str | None = None,
) -> tuple[dict[str, Any], int]:
    """构建标准化的 Flask API 错误响应。"""
    body: dict[str, Any] = {"success": False, "error": message}
    if code:
        body["code"] = code
    return body, status_code
