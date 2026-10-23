"""把"队列没收下答案"说给客户端听 — 两个提交路由共用（R846 / R851）。

``POST /api/tasks/<id>/submit`` 和 ``POST /api/submit``（带 ``task_id``，或落到活动任务）
最后都是 ``TaskQueue.complete_task``，它没收下答案时答什么，只在这一处写：

* 任务不在了（MCP 调用放弃并关闭了它、用户在别处关了它、清理线程跑了）：``404``（R846）。
* 任务已经有答案了（两台设备同时回答、双击、倒计时自动重提撞上手动提交）：``409``（R851）。
  第一个答案算数；后来的这个没有发给智能体，页面要如实说，而不是答“已提交”再清空输入框。

两种情况队列都只答 ``False``，这里按任务还在不在来分。调用留在路由里（各路由手里的队列
就是测试里替换的那一个），这一步在队列的锁外，只决定怎么说：两次读之间任务被清理，409 会
变成 404，两种情况答案都没被收下，用户看到的都是失败。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import jsonify
from flask.typing import ResponseReturnValue

from ai_intervention_agent.i18n import msg

if TYPE_CHECKING:
    from ai_intervention_agent.task_queue import TaskQueue


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
