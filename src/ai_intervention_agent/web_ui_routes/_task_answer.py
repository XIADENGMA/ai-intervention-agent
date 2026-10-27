"""把"队列没收下答案"和"请求里没有答案"说给客户端听 — 两个提交路由共用（R846 / R851 / R912）。

``POST /api/tasks/<id>/submit`` 和 ``POST /api/submit``（带 ``task_id``，或落到活动任务）
最后都是 ``TaskQueue.complete_task``，它没收下答案时答什么，只在这一处写：

* 任务不在了（MCP 调用放弃并关闭了它、用户在别处关了它、清理线程跑了）：``404``（R846）。
* 任务已经有答案了（两台设备同时回答、双击、倒计时自动重提撞上手动提交）：``409``（R851）。
  第一个答案算数；后来的这个没有发给智能体，页面要如实说，而不是答“已提交”再清空输入框。

两种情况队列都只答 ``False``，这里按任务还在不在来分。调用留在路由里（各路由手里的队列
就是测试里替换的那一个），这一步在队列的锁外，只决定怎么说：两次读之间任务被清理，409 会
变成 404，两种情况答案都没被收下，用户看到的都是失败。

请求里压根没有答案（R912）：路由读表单用的是 ``request.form.get("feedback_text", "")`` 和
``request.form.get("selected_options", "[]")``：不是表单的请求（空体、JSON、纯文本、读不了的
multipart），或者表单里既没有这两个字段也没有文件，两个都取到默认值，任务就以空答案完成，答
``200``。agent 收到“用户未提供任何内容”，页面上的问题没了，真正的答案再送来只会得到 ``409``。
R829 在 ``/api/submit`` 的 JSON 分支上堵过读不了的体；这里规定表单一侧的同一条规则，两个路由
共用：一个请求里有 ``feedback_text`` 或 ``selected_options`` 字段（值为空也算：页面在什么都没输入
时就是这样发的），或者带了上传文件，才算带了答案，否则 ``400 invalid_body``，任务保持未回答。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from flask import jsonify, request
from flask.typing import ResponseReturnValue

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.i18n import msg

if TYPE_CHECKING:
    from ai_intervention_agent.task_queue import TaskQueue

logger = EnhancedLogger(__name__)

# 一个答案由这两个表单字段（外加上传的图片文件）组成。页面、VS Code 面板和自动重提交的
# ``FormData`` 永远两个都带，没内容时也带空值。
ANSWER_FIELDS: Final[tuple[str, ...]] = ("feedback_text", "selected_options")


def refused_answer_response(queue: TaskQueue, task_id: str) -> ResponseReturnValue:
    """``queue.complete_task(task_id, ...)`` 答了 ``False`` 之后，该答复客户端的响应。

    409 的信封与 413 一样：``/api/submit`` 的 OpenAPI 一直声明的 ``{status, message}``，
    加上任务系列路由客户端判断成败用的 ``success``，机器可读的原因在 ``error``。
    """
    if queue.get_task(task_id) is None:
        return jsonify({"success": False, "error": "任务不存在"}), 404
    return (
        jsonify(
            {
                "success": False,
                "status": "error",
                "error": "task_already_answered",
                "message": msg("feedback.alreadyAnswered"),
            }
        ),
        409,
    )


def request_holds_an_answer() -> bool:
    """这个请求的表单里有答案吗：``feedback_text`` / ``selected_options`` 字段，或上传的文件。

    字段只看在不在，不看值：空文字（``feedback_text=``）是用户在什么都没输入时点了提交，
    是一个真实的、明确的空答案。读表单时 Werkzeug 抛的 413（整体超限、单个文本字段超限、
    字段过多）原样往上走，由应用级的错误处理函数回答（R800）。
    """
    return bool(request.files) or any(name in request.form for name in ANSWER_FIELDS)


def no_answer_response(task_id: str | None = None) -> ResponseReturnValue:
    """``request_holds_an_answer()`` 答了 ``False`` 之后，该答复客户端的响应：``400 invalid_body``。

    信封与 409 一样（``success`` + ``status`` + ``error`` + 本地化的 ``message``）。任务没有被
    动过：不收下答案、不发状态事件、不改队列，下一个正常的表单照常被收下。日志只记请求头里的
    ``Content-Type`` 和长度（``task_id`` 只在调用方已经确认任务存在时才传）。
    """
    subject = f"任务 {task_id} 的提交" if task_id else "提交"
    logger.warning(
        f"{subject}里没有答案，已拒绝 | "
        f"content_type={(request.content_type or '')[:80]!r} "
        f"content_length={request.content_length}"
    )
    return (
        jsonify(
            {
                "success": False,
                "status": "error",
                "error": "invalid_body",
                "message": msg("feedback.bodyMustBeForm"),
            }
        ),
        400,
    )
