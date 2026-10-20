"""请求体读取 — 把"体不是 JSON 对象"统一成 400（必填）或忽略（可选）。

为什么要单独一个模块（R789）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
读 JSON 体的写接口原来各读各的：

* ``request.json or {}`` 写在宽泛的 ``try`` 里：缺 ``Content-Type``、空体、截断的 JSON、
  嵌套过深的文档，都会让 Werkzeug 抛 ``BadRequest`` / ``UnsupportedMediaType`` /
  ``RecursionError``，被 ``except Exception`` 吞成 **500**；而合法 JSON 但不是对象
  （``"s"``、``123``、``[1]``）有的 500、有的 200「无更新字段」。``curl -X POST`` 漏写
  ``-H 'Content-Type: application/json'`` 就会被告知「服务器坏了」。
* ``get_json(silent=True) or {}`` 只吞解析错误：JSON 标量/数组一路走到 ``payload.get``，
  抛出**未处理**的 ``AttributeError``（HTML 500 + traceback）；嵌套过深的文档更是
  绕过 ``silent=True``——``json.loads`` 抛的是 ``RecursionError``，不是 ``ValueError``。

两个入口，语义写死：

``require_json_object()``
    体必填。不是 JSON 对象就抛 ``InvalidRequestBody``（400），响应体与 ``/api/update`` 一直
    使用的格式一致：``{"status": "error", "error": "invalid_json" | "invalid_body",
    "message": …}``。**必须在路由自己的 ``try`` 之外调用**——否则会被那里的
    ``except Exception`` 再次吞成 500。``InvalidRequestBody`` 自己渲染成 JSON
    （覆写 ``get_response``），所以不依赖 app 级 ``errorhandler`` 是否注册。

``optional_json_object()``
    体可选。凡不是 JSON 对象的一律当作"没带体"（``{}``），永不抛——这正是这些路由原本
    ``silent=True`` 对不可解析文本的语义，只是补上了标量/数组/过深嵌套三种漏网情形。

``Content-Type`` 仍然必须是 JSON：``force=True`` 会让 ``text/plain`` / 表单提交也能携带 JSON，
削弱"写接口只收 ``application/json``（跨站表单发不出来）"这层纵深防御（R787 之外的第二道门）。
"""

from __future__ import annotations

from typing import Any

from flask import Response, current_app, jsonify, request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from ai_intervention_agent.i18n import msg


class InvalidRequestBody(BadRequest):
    """请求体不是 JSON 对象；渲染成 ``400`` + JSON，不依赖 ``errorhandler``。"""

    def __init__(self, error: str, message: str) -> None:
        super().__init__(description=message)
        self.error = error
        self.message = message

    def get_response(self, environ: Any = None, scope: Any = None) -> Response:
        response = jsonify(
            {"status": "error", "error": self.error, "message": self.message}
        )
        response.status_code = 400
        return response


def require_json_object() -> dict[str, Any]:
    """返回请求体里的 JSON 对象；做不到就抛 ``InvalidRequestBody``（400）。

    捕获 ``Exception`` 而不是 ``BadRequest``：``RecursionError``（嵌套过深）和
    ``UnsupportedMediaType``（缺 / 错 ``Content-Type``）都属于"调用方给了不能用的体"。
    体超过 ``MAX_CONTENT_LENGTH`` 的 ``RequestEntityTooLarge``（413）例外，照常往上走
    （R800）：那是 HTTP 本身的状态，不是"体格式不对"，``optional_json_object`` 一直如此。
    """
    try:
        raw = request.get_json(silent=False)
    except RequestEntityTooLarge:
        raise
    except Exception as exc:
        raise InvalidRequestBody(
            "invalid_json", msg("feedback.bodyMustBeJson")
        ) from exc
    if not isinstance(raw, dict):
        raise InvalidRequestBody("invalid_body", msg("feedback.bodyMustBeObject"))
    return raw


def optional_json_object() -> dict[str, Any]:
    """返回请求体里的 JSON 对象；没带 / 不可解析 / 不是对象一律返回 ``{}``。

    体的**内容**永远不会让它抛异常。传输层的 ``HTTPException``（体超过
    ``MAX_CONTENT_LENGTH`` 的 413、客户端中途断开）照常往上走——那是 HTTP 本身的状态，
    不是"体格式不对"。
    """
    try:
        raw = request.get_json(silent=True)
    except RecursionError:
        # ``silent=True`` 只吞 ValueError；json.loads 对过深嵌套抛 RecursionError。
        return {}
    return raw if isinstance(raw, dict) else {}


def _format_byte_count(value: object) -> str:
    """``101 MB``、``488.3 KB`` 或 ``512 B``；没有上限（``None``）写成 ``∞``。"""
    if not isinstance(value, int) or isinstance(value, bool):
        return "∞"
    if value >= 1024 * 1024:
        number, unit = value / (1024 * 1024), "MB"
    elif value >= 1024:
        number, unit = value / 1024, "KB"
    else:
        return f"{value} B"
    return f"{number:.1f}".rstrip("0").rstrip(".") + f" {unit}"


def request_too_large_response(exc: RequestEntityTooLarge) -> ResponseReturnValue:
    """``RequestEntityTooLarge`` 的统一答复：``/api/`` 下是 JSON 413，其余保持 Werkzeug 页面。

    Werkzeug 在三种情况下抛它：整个请求超过 ``MAX_CONTENT_LENGTH``；``multipart/form-data``
    里某个文本字段超过 ``MAX_FORM_MEMORY_SIZE``（Flask 默认 500 000 字节）；表单字段多于
    ``MAX_FORM_PARTS``（默认 1000）。``Content-Length`` 已经超过总上限时能肯定是第一种，
    消息只报总上限；其余（包括分块上传没有 ``Content-Length``）三个上限都列出，不猜。

    信封是 ``/api/submit`` 的 OpenAPI 一直声明的 ``{status, message}`` 加上任务系列路由
    客户端判断成败用的 ``success``，机器可读的原因在 ``error``。
    """
    if not request.path.startswith("/api/"):
        return exc
    config = current_app.config
    total = config.get("MAX_CONTENT_LENGTH")
    length = request.content_length
    if isinstance(total, int) and length is not None and length > total:
        message = msg("feedback.payloadTooLarge", limit=_format_byte_count(total))
    else:
        parts = config.get("MAX_FORM_PARTS")
        message = msg(
            "feedback.requestLimitsExceeded",
            limit=_format_byte_count(total),
            field_limit=_format_byte_count(config.get("MAX_FORM_MEMORY_SIZE")),
            parts=str(parts) if isinstance(parts, int) else "∞",
        )
    response = jsonify(
        {
            "success": False,
            "status": "error",
            "error": "payload_too_large",
            "message": message,
        }
    )
    response.status_code = 413
    return response
