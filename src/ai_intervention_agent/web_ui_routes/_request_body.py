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

嵌套深度（R828）
~~~~~~~~~~~~~~~~
"嵌套过深的文档按不可解析处理"原来靠的是解释器自己的上限：3.11–3.13 的 ``json.loads``
在几千层处抛 ``RecursionError``。Python 3.14 把 C 解析器的上限改成跟 C 栈走，十万层的
文档照样读得进来，这张网就没了：对它做 ``str()`` / ``repr()`` 是平方级的、最后还会撑爆 C 栈。
120–200 kB 的体让处理它的线程空转 0.6–1.1 秒（闲着的机器上量的；C 代码握着 GIL，同时进来的别的
请求，SSE 心跳也一样，只能等：``/api/health`` 被拖了 0.66 秒），十万层的体有的路由直接答
``500 RecursionError: Stack overflow``。

所以深度在读体的地方统一限住：``MAX_JSON_NESTING`` 层（客户端最深发 5 层）。app 的 JSON provider
（``BoundedJSONProvider``）读完文档后检查深度，过深就抛 Werkzeug 本来就当作"不是 JSON"的
``ValueError``，解释器自己的 ``RecursionError`` 也转成同一个 ``ValueError``——于是
``require_json_object()`` 在每个解释器上都答 ``400 invalid_json``，``optional_json_object()`` 都当
"没带体"。表单字段里的 JSON 文本（``selected_options``）走同一个 ``loads_bounded``。

孤立代理项（R845）
~~~~~~~~~~~~~~~~~~
标准库 ``json.loads`` 会把不成对的 ``"\\ud800"`` 读成一个没有 UTF-8 编码的字符串（原因和后果见
``text_safety``：MCP 服务进程会在序列化工具结果时退出）。``loads_bounded`` 读完文档、查过深度之后
把它们换成 U+FFFD，所以所有读 JSON 文本的入口——任何路由的体、表单里的 JSON 字段——拿到的都是
能编码的文本。路由里不该再有自己的 ``json.loads``。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Final

from flask import Response, current_app, jsonify, request
from flask.json.provider import DefaultJSONProvider
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from ai_intervention_agent.i18n import msg
from ai_intervention_agent.text_safety import scrub_lone_surrogates

# 容器（对象 / 数组）最多嵌套几层。第一方客户端最深 5 层（任务 → prompt_images → 条目 …）；
# 32 层留足余地，又远在会让 str() / repr() 变慢的深度之下。
MAX_JSON_NESTING: Final = 32


def json_nesting_exceeds(value: object, limit: int = MAX_JSON_NESTING) -> bool:
    """解析出来的 JSON 值嵌套的容器是否超过 ``limit`` 层（标量 0 层，``[]`` 1 层）。

    用显式栈而不是递归：被检查的就是"深到递归会出事"的值。栈里放的是每一层的迭代器，
    所以内存只和深度成正比，不和宽度成正比：一个 10 MB、330 万个 ``[]`` 的体检查时不多占
    内存（把每个子容器连同深度压栈的写法要多占 160 MB）。一超过 ``limit`` 立刻返回，
    不必走完整个文档。"""
    if not isinstance(value, dict | list):
        return False
    if limit < 1:
        return True
    stack: list[Iterator[object]] = [
        iter(value.values() if isinstance(value, dict) else value)
    ]
    while stack:
        for child in stack[-1]:
            if isinstance(child, dict | list):
                if len(stack) >= limit:
                    return True
                stack.append(iter(child.values() if isinstance(child, dict) else child))
                break
        else:
            stack.pop()
    return False


def loads_bounded(s: str | bytes | bytearray, **kwargs: Any) -> Any:
    """读不可信的 JSON 文本：嵌套过深一律当"不是 JSON"（``ValueError``），孤立代理项换成 U+FFFD。

    Werkzeug 的 ``get_json(silent=True)`` 只吞 ``ValueError``、``silent=False`` 把它变成
    ``400``；解释器自己的 ``RecursionError`` 不是 ``ValueError``，这里一并转成它。语法错误仍是
    ``json.JSONDecodeError``（也是 ``ValueError``）。深度检查在代理项清洗之前，清洗才可以放心遍历。
    """
    try:
        value = json.loads(s, **kwargs)
    except RecursionError as exc:
        raise ValueError(
            f"JSON document nested deeper than {MAX_JSON_NESTING} levels"
        ) from exc
    if json_nesting_exceeds(value):
        raise ValueError(f"JSON document nested deeper than {MAX_JSON_NESTING} levels")
    return scrub_lone_surrogates(value)


class BoundedJSONProvider(DefaultJSONProvider):
    """``request.get_json()`` 读体用的 provider：读法见 ``loads_bounded``。"""

    def loads(self, s: str | bytes, **kwargs: Any) -> Any:
        return loads_bounded(s, **kwargs)


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
        # ``silent=True`` 只吞 ValueError。app 的 provider（``BoundedJSONProvider``）已把
        # 过深嵌套转成 ValueError；这里兜住没装它的 app（比如测试里临时搭的）。
        return {}
    return raw if isinstance(raw, dict) else {}


def fields_that_are_not_text(**values: Any) -> list[str]:
    """Names of the given request values that are present but are not strings.

    ``None`` (JSON ``null``) counts as absent: every caller treats it like a missing
    or empty value already.
    """
    return [
        name
        for name, value in values.items()
        if value is not None and not isinstance(value, str)
    ]


def invalid_value_response(fields: list[str]) -> ResponseReturnValue:
    """``400 invalid_value`` naming the request fields whose value cannot be used.

    The envelope ``/api/update-notification-config`` has answered since R790:
    ``{"status": "error", "error": "invalid_value", "fields": [...], "message": ...}``.
    The message names the fields and never echoes the values (``bark_device_key``
    sits beside the rest of the notification settings, and a feedback text is
    the user's own words).
    """
    named = sorted(set(fields))
    return jsonify(
        {
            "status": "error",
            "error": "invalid_value",
            "fields": named,
            "message": msg("notify.invalidFieldValue", fields=", ".join(named)),
        }
    ), 400


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
