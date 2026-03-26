"""项目统一异常定义。

所有业务异常均继承 AIAgentError 基类，支持结构化错误码与附加详情，
便于日志分析、错误追踪和前端展示。
"""

from __future__ import annotations

from typing import Any


class AIAgentError(Exception):
    """项目基础异常。

    属性:
        code: 机器可读的错误码（如 "service_unavailable"），可选
        details: 附加结构化信息，便于调试或前端展示
    """

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


# ---------------------------------------------------------------------------
# 配置相关
# ---------------------------------------------------------------------------


class ConfigError(AIAgentError):
    """配置加载、解析或校验失败。"""


class ConfigFileNotFoundError(ConfigError):
    """配置文件不存在。"""


class ConfigValidationError(ConfigError):
    """配置值不满足约束条件。"""


# ---------------------------------------------------------------------------
# 服务连接
# ---------------------------------------------------------------------------


class ServiceConnectionError(AIAgentError):
    """与 Web UI / 外部服务通信失败（连接、超时、HTTP 非 2xx 等）。"""


class ServiceUnavailableError(ServiceConnectionError):
    """服务未启动或无法到达。"""


class ServiceTimeoutError(ServiceConnectionError):
    """请求超时。"""


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


class TaskError(AIAgentError):
    """任务创建、执行或等待失败。"""


class TaskNotFoundError(TaskError):
    """指定任务不存在。"""


class TaskTimeoutError(TaskError):
    """等待任务完成超时。"""


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------


class NotificationError(AIAgentError):
    """通知发送或配置错误。"""


# ---------------------------------------------------------------------------
# 输入验证
# ---------------------------------------------------------------------------


class ValidationError(AIAgentError):
    """输入参数不合法。"""


# ---------------------------------------------------------------------------
# Flask API 错误响应 helper
# ---------------------------------------------------------------------------


def make_error_response(
    message: str,
    status_code: int = 400,
    *,
    code: str | None = None,
) -> tuple[dict[str, Any], int]:
    """构建标准化的 Flask API 错误响应。

    返回值可直接作为 Flask 路由的 return 值（jsonify 由调用方负责）。

    用法::

        from exceptions import make_error_response
        from flask import jsonify
        return jsonify(make_error_response("任务不存在", 404, code="not_found")[0]), 404
        # 或更简洁：
        body, status = make_error_response("任务不存在", 404, code="not_found")
        return jsonify(body), status
    """
    body: dict[str, Any] = {"success": False, "error": message}
    if code:
        body["code"] = code
    return body, status_code
