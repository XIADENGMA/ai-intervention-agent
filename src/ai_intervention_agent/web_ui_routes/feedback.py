"""反馈提交路由 Mixin — 通用提交、内容更新、反馈查询。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from flask import jsonify, request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import RequestEntityTooLarge

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.feedback_types import FeedbackResult
from ai_intervention_agent.i18n import msg
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui_routes._request_body import (
    fields_that_are_not_text,
    invalid_value_response,
    loads_bounded,
    require_json_object,
)
from ai_intervention_agent.web_ui_routes._task_answer import (
    refused_answer_response,
)
from ai_intervention_agent.web_ui_routes._upload_helpers import extract_uploaded_images

if TYPE_CHECKING:
    import threading

    from flask import Flask

    from ai_intervention_agent.web_ui_rate_limiter import WebUiLimiterProtocol

logger = EnhancedLogger(__name__)


def _sanitize_selected_options(raw: Any) -> list[str]:
    """【P6Y-3 修复】清洗 /api/submit 传入的 selected_options 字段。

    前端可能通过 multipart/form-data、URL-encoded form、application/json 三种方式提交，
    任何一种都可能把 selected_options 传成 None / 字符串 / 字典 / 包含非字符串元素的列表。
    若不校验直接写入 Task.result['selected_options']，前端读取时会出现：
      - `.forEach is not a function` 或 `.map is not a function`
      - 历史任务面板渲染崩溃
      - 状态事件推送的数据结构异常

    规则：
      1. 非 list → 空列表
      2. list 中的每个元素：非字符串则先用 str() 转；然后 strip；
         过滤掉空字符串和超过 ``MAX_STORED_OPTION_LENGTH`` 的异常长串；
      3. 去重但保持顺序；
      4. 最多保留 50 项（上层 UI 一般也就几项，这里只做兜底防滥用）。

    R166：单项长度上限从硬编码 500 → 引用 server_config 的常量，对齐服务端
    ``validate_input_with_defaults``，避免软上限不一致让"前端提交"和"后端
    schema 校验"两套数值漂移。

    R858：上限是 ``MAX_STORED_OPTION_LENGTH``（10000 个字符加截断标记 ``...``），
    不是 ``MAX_OPTION_LENGTH``：服务端把更长的选项截成这个长度再显示，用户勾选的
    就是这份文字；上限再小一点，这个选项就被悄悄丢掉，AI 收不到用户选了什么，页面
    却答"已提交"。
    """
    if not isinstance(raw, list):
        return []

    from ai_intervention_agent.server_config import MAX_STORED_OPTION_LENGTH

    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw:
        if item is None:
            continue
        if not isinstance(item, str):
            try:
                item = str(item)
            except Exception:
                continue
        item = item.strip()
        if not item:
            continue
        if len(item) > MAX_STORED_OPTION_LENGTH:
            continue
        if item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
        if len(cleaned) >= 50:
            break
    return cleaned


def _selected_options_from_form(raw: str) -> list[str]:
    """Cleaned ``selected_options`` of a form field that carries a JSON array.

    A value that is not readable JSON means "nothing selected", as a syntax error
    always did. ``json.loads`` also raises ``ValueError`` (not a ``JSONDecodeError``)
    for an integer of more than 4300 digits, the interpreter's limit on int/str
    conversion, and ``RecursionError`` for nesting deeper than the interpreter
    allows; both used to escape the handler and came back as ``500``.

    The interpreter's limit is not a limit any more on Python 3.14 (it reads documents
    ~100 000 levels deep), so the depth is bounded here as well (R828): a nested array
    would otherwise be kept as the ``str()`` of its first element. ``loads_bounded``
    does both, and turns a lone surrogate (``"\\ud800"``) into U+FFFD (R845): kept, it
    would make the tool result impossible to serialise.
    """
    try:
        parsed = loads_bounded(raw)
    except ValueError:
        parsed = []
    return _sanitize_selected_options(parsed)


class FeedbackRoutesMixin:
    """提供 3 个反馈相关 API 路由，由 WebFeedbackUI 通过 MRO 继承。"""

    if TYPE_CHECKING:
        app: Flask
        limiter: WebUiLimiterProtocol
        _state_lock: threading.RLock
        feedback_result: FeedbackResult | None
        current_prompt: str
        current_options: list[str]
        current_options_defaults: list[bool]
        current_task_id: str | None
        current_auto_resubmit_timeout: int
        _single_task_timeout_explicit: bool
        has_content: bool

        def render_markdown(self, text: str) -> str: ...

    def _setup_feedback_routes(self) -> None:
        from ai_intervention_agent.web_ui import (
            _get_default_auto_resubmit_timeout_from_config,
            validate_auto_resubmit_timeout,
        )

        @self.app.route("/api/submit", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def submit_feedback() -> ResponseReturnValue:
            """提交用户反馈（文本 / 选项 / 图片）
            ---
            tags:
              - Feedback
            consumes:
              - multipart/form-data
              - application/json
            parameters:
              - in: formData
                name: task_id
                type: string
                description: 目标任务 ID
              - in: formData
                name: feedback_text
                type: string
                description: 反馈文本
              - in: formData
                name: selected_options
                type: string
                description: 已选选项（JSON 数组字符串）
              - in: formData
                name: images
                type: file
                description: 上传的图片文件
            responses:
              200:
                description: 提交成功
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success
                    message:
                      type: string
                    persistent:
                      type: boolean
                      description: 是否保留在前端历史 (true=保留, false=自动清空)
                    clear_content:
                      type: boolean
                      description: 提交后是否清空 textarea (前端 UX 提示)
              400:
                description: 请求体不能用（只出现在既没有文件也没有表单字段、按 JSON 读体的提交上）
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                      description: 固定为 "error"
                    error:
                      type: string
                      enum: [invalid_json, invalid_body, invalid_value]
                      description: invalid_json=无法解析（空体、语法错、含嵌套超过 32 层）/缺 JSON Content-Type，invalid_body=不是 JSON 对象，invalid_value=task_id / feedback_text / user_input 不是字符串
                    fields:
                      type: array
                      items:
                        type: string
                      description: 仅 invalid_value 时出现：不是字符串的字段名
                    message:
                      type: string
                      description: 人类可读的说明
              404:
                description: task_id 指定的任务不存在
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      enum: [false]
                    error:
                      type: string
                      description: 错误说明文本
              409:
                description: 这个任务已经有答案了：第一个答案算数，这次的没有收下，也没有改动已有的答案
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      enum: [false]
                    status:
                      type: string
                      enum: [error]
                    error:
                      type: string
                      enum: [task_already_answered]
                    message:
                      type: string
                      description: 人类可读的说明（语言随请求的 Accept-Language）
              413:
                description: |
                  请求超过上传上限：整个请求大于 ``MAX_CONTENT_LENGTH``
                  （``MAX_TOTAL_UPLOAD_BYTES`` + 1 MB），或 multipart 里某个文本字段大于
                  ``MAX_FORM_MEMORY_SIZE``（默认 500 000 字节），或表单字段多于
                  ``MAX_FORM_PARTS``（默认 1000）
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    status:
                      type: string
                      enum: [error]
                    error:
                      type: string
                      enum: [payload_too_large]
                    message:
                      type: string
              429:
                description: 速率超限 (60 per minute)；响应头 `Retry-After` 给出建议等待的秒数
                headers:
                  Retry-After:
                    type: integer
                    description: 建议等待的秒数（≥ 1）
                schema:
                  type: object
                  properties:
                    error:
                      type: string
                      enum: [rate_limit_exceeded]
                      description: 固定为 rate_limit_exceeded
            """
            logger.info(f"收到提交请求 - Content-Type: {request.content_type}")
            logger.debug(f"request.files keys: {list(request.files.keys())}")
            logger.debug(f"request.form keys: {list(request.form.keys())}")

            if request.files:
                requested_task_id = request.form.get("task_id", "").strip()
                feedback_text = request.form.get("feedback_text", "").strip()
                selected_options_str = request.form.get("selected_options", "[]")
                selected_options = _selected_options_from_form(selected_options_str)

                logger.debug("接收到的反馈数据:")
                logger.debug(f"  - 文字内容长度: {len(feedback_text)}")
                logger.debug(f"  - 选项数量: {len(selected_options)}")
                logger.debug(f"  - 文件数量: {len(request.files)}")

                images: list[Any] = extract_uploaded_images(
                    request, include_metadata=True
                )
            elif request.form:
                requested_task_id = request.form.get("task_id", "").strip()
                feedback_text = request.form.get("feedback_text", "").strip()
                selected_options_str = request.form.get("selected_options", "[]")
                selected_options = _selected_options_from_form(selected_options_str)

                logger.debug("接收到的表单数据:")
                logger.debug(
                    f"  - 文字内容: '{feedback_text}' (长度: {len(feedback_text)})"
                )
                logger.debug(f"  - 选项数据: {selected_options_str}")
                logger.debug(f"  - 解析后选项: {selected_options}")

                images = []
            else:
                # R829: 既没有文件也没有表单字段时，体必须是 JSON 对象。读不了的体（空体、
                # 缺 JSON Content-Type、语法错、不是对象、嵌套过深）原来被当作“空答案”，
                # 去完成当前活动任务并答 200：一个坏掉的脚本就能让用户正在等的那个问题
                # 以空答案结束。调用必须在任何 ``try`` 之外，否则 400 又被吞掉。
                data = require_json_object()
                # null 等同没带；文本字段给了别的类型（数字、列表、对象）原来被 str()
                # 成 "5" / "['a']"，null 成了字面的 "None" 答案。
                not_text = fields_that_are_not_text(
                    task_id=data.get("task_id"),
                    feedback_text=data.get("feedback_text"),
                    user_input=data.get("user_input"),
                )
                if not_text:
                    logger.warning(f"提交被拒绝，字段值不是文本: {sorted(not_text)}")
                    return invalid_value_response(not_text)
                requested_task_id = (data.get("task_id") or "").strip()
                # ``user_input`` 是旧名字，只在 ``feedback_text`` 没给（或为 null）时用。
                text_value = data.get("feedback_text")
                if text_value is None:
                    text_value = data.get("user_input")
                feedback_text = (text_value or "").strip()
                selected_options = _sanitize_selected_options(
                    data.get("selected_options")
                )
                images = data.get("images")
                if not isinstance(images, list):
                    images = []

                logger.debug("接收到的JSON数据:")
                logger.debug(
                    f"  - 文字内容: '{feedback_text}' (长度: {len(feedback_text)})"
                )
                logger.debug(f"  - 选项: {selected_options}")
                logger.debug(f"  - 图片数量: {len(images)}")

            task_queue = get_task_queue()
            target_task_id = requested_task_id
            if requested_task_id:
                target_task = task_queue.get_task(requested_task_id)
                if not target_task:
                    logger.warning(f"提交反馈时任务不存在: {requested_task_id}")
                    return (
                        jsonify({"success": False, "error": "任务不存在"}),
                        404,
                    )
            else:
                active_task = task_queue.get_active_task()
                target_task_id = active_task.task_id if active_task else ""

            feedback_result: FeedbackResult = {
                "user_input": feedback_text,
                "selected_options": selected_options,
                "images": images,  # type: ignore[typeddict-item]  # 运行时总是正确类型
            }

            if target_task_id:
                logger.info(f"同时将反馈提交到TaskQueue中的目标任务: {target_task_id}")
                # R846：队列没收下答案（任务刚被移除）就不能答"成功"，也不能把这份答案留在
                # ``feedback_result`` 里让 ``GET /api/feedback`` 当作已提交的取走；见 task.py。
                # R851：任务已经有答案时同理，答 409。
                if not task_queue.complete_task(
                    target_task_id,
                    cast(dict[str, Any], feedback_result),
                ):
                    return refused_answer_response(task_queue, target_task_id)

            with self._state_lock:
                self.feedback_result = feedback_result

            logger.debug("最终存储的反馈结果:")
            logger.debug(
                f"  - user_input: '{feedback_result['user_input']}' (长度: {len(feedback_result['user_input'])})"
            )
            logger.debug(f"  - selected_options: {feedback_result['selected_options']}")
            logger.debug(f"  - images数量: {len(feedback_result['images'])}")

            with self._state_lock:
                self.current_prompt = ""
                self.current_options = []
                self.has_content = False
            return jsonify(
                {
                    "status": "success",
                    "message": msg("feedback.submitted"),
                    "persistent": True,
                    "clear_content": True,
                }
            )

        @self.app.route("/api/update", methods=["POST"])
        def update_content() -> ResponseReturnValue:
            """更新页面内容（单任务模式）
            ---
            tags:
              - Feedback
            consumes:
              - application/json
            parameters:
              - in: body
                name: body
                required: true
                schema:
                  type: object
                  properties:
                    prompt:
                      type: string
                      description: 新的提示文本（Markdown 格式）
                    predefined_options:
                      type: array
                      items:
                        type: string
                      description: |
                        预定义选项列表 (供前端 chip 按钮显示); 缺省则前端
                        只渲染 freeform 输入框, 不展示 chip。
                    task_id:
                      type: string
                      description: |
                        目标任务 ID; 必须是当前 queue 内存在的 task, 否则
                        返回 400。
                    auto_resubmit_timeout:
                      type: integer
                      minimum: 0
                      maximum: 3600
                      description: 倒计时秒数；0=禁用；非零值范围 [10, 3600]，与 server_config.AUTO_RESUBMIT_TIMEOUT_MAX 对齐（与 POST /api/update-feedback-config 同字段一致）
            responses:
              200:
                description: 更新成功
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success
                    message:
                      type: string
                    prompt:
                      type: string
                      description: 提示文本原文 (Markdown)
                    prompt_html:
                      type: string
                      description: Markdown 渲染后的 HTML
                    predefined_options:
                      type: array
                      items:
                        type: string
                      description: 预定义选项列表 (供前端 chip 按钮)
                    task_id:
                      type: string
                      description: 关联的任务 ID
                    auto_resubmit_timeout:
                      type: number
                      description: 倒计时秒数, 0=禁用
                    has_content:
                      type: boolean
                      description: 是否已有内容 (用于前端判断是否需要 toast 通知)
              400:
                description: 请求参数错误
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                      description: 固定为 "error"
                    message:
                      type: string
                      description: 人类可读错误说明
              500:
                description: 服务器内部错误
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                      description: 固定为 "error"
                    message:
                      type: string
                      description: 服务器异常详情或通用提示
            """
            try:
                raw = request.get_json(silent=False)
            except RequestEntityTooLarge:
                # R800: 体超过上限的 413 是 HTTP 本身的状态，不是"JSON 格式不对"
                raise
            except Exception:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "error": "invalid_json",
                            "message": msg("feedback.bodyMustBeJson"),
                        }
                    ),
                    400,
                )

            if not isinstance(raw, dict):
                return (
                    jsonify(
                        {
                            "status": "error",
                            "error": "invalid_body",
                            "message": msg("feedback.bodyMustBeObject"),
                        }
                    ),
                    400,
                )

            data: dict[str, Any] = raw

            if "prompt" not in data:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "error": "missing_field",
                            "message": msg("feedback.missingPrompt"),
                        }
                    ),
                    400,
                )
            new_prompt_raw = data.get("prompt")
            if not isinstance(new_prompt_raw, str):
                return (
                    jsonify(
                        {
                            "status": "error",
                            "error": "invalid_field_type",
                            "message": msg("feedback.promptMustBeString"),
                        }
                    ),
                    400,
                )
            new_prompt = new_prompt_raw

            from ai_intervention_agent.server_config import MAX_MESSAGE_LENGTH

            if len(new_prompt) > MAX_MESSAGE_LENGTH:
                logger.warning(
                    f"/api/update prompt 过长：{len(new_prompt)}，将截断到 {MAX_MESSAGE_LENGTH}"
                )
                new_prompt = new_prompt[:MAX_MESSAGE_LENGTH] + "..."

            new_options_raw = data.get("predefined_options")
            if new_options_raw is None:
                new_options_raw = []
            if not isinstance(new_options_raw, list):
                return (
                    jsonify(
                        {
                            "status": "error",
                            "error": "invalid_field_type",
                            "message": msg("feedback.optionsMustBeArray"),
                        }
                    ),
                    400,
                )

            new_options: list[str] = []
            for opt in new_options_raw:
                if not isinstance(opt, str):
                    continue
                t = opt.strip()
                if not t:
                    continue
                if len(t) > 500:
                    new_options.append(t[:500] + "...")
                else:
                    new_options.append(t)

            new_task_id_raw = data.get("task_id")
            if new_task_id_raw is None:
                new_task_id = None
            elif isinstance(new_task_id_raw, str):
                t = new_task_id_raw.strip()
                new_task_id = t if t else None
            else:
                t = str(new_task_id_raw).strip()
                new_task_id = t if t else None

            default_timeout = _get_default_auto_resubmit_timeout_from_config()
            timeout_explicit = "auto_resubmit_timeout" in data
            if timeout_explicit:
                raw_timeout = data.get("auto_resubmit_timeout")
                try:
                    timeout_int = int(raw_timeout)  # ty: ignore[invalid-argument-type]
                except Exception:
                    return (
                        jsonify(
                            {
                                "status": "error",
                                "error": "invalid_field_value",
                                "message": msg("feedback.timeoutMustBeInt"),
                            }
                        ),
                        400,
                    )
            else:
                timeout_int = default_timeout

            new_auto_resubmit_timeout = validate_auto_resubmit_timeout(timeout_int)

            try:
                with self._state_lock:
                    self.current_prompt = new_prompt
                    self.current_options = new_options
                    self.current_options_defaults = []
                    self.current_task_id = new_task_id
                    self.current_auto_resubmit_timeout = new_auto_resubmit_timeout
                    self._single_task_timeout_explicit = timeout_explicit
                    self.has_content = bool(new_prompt.strip())
                    self.feedback_result = None

                    prompt_snapshot = str(self.current_prompt)
                    options_snapshot = list(self.current_options)
                    task_id_snapshot = self.current_task_id
                    timeout_snapshot = int(self.current_auto_resubmit_timeout)
                    has_content_snapshot = bool(self.has_content)

                prompt_html = ""
                if has_content_snapshot:
                    try:
                        prompt_html = self.render_markdown(prompt_snapshot)
                    except Exception as e:
                        logger.warning(
                            f"/api/update prompt 渲染失败: {e}", exc_info=True
                        )
                        prompt_html = ""

                return jsonify(
                    {
                        "status": "success",
                        "message": msg("feedback.contentUpdated"),
                        "prompt": prompt_snapshot,
                        "prompt_html": prompt_html,
                        "predefined_options": options_snapshot,
                        "predefined_options_defaults": [],
                        "task_id": task_id_snapshot,
                        "auto_resubmit_timeout": timeout_snapshot,
                        "has_content": has_content_snapshot,
                    }
                )
            except Exception as e:
                logger.error(f"/api/update 处理失败: {e}", exc_info=True)
                return (
                    jsonify(
                        {
                            "status": "error",
                            "error": "internal_error",
                            "message": msg("feedback.serverError"),
                        }
                    ),
                    500,
                )

        @self.app.route("/api/feedback", methods=["GET"])
        def get_feedback() -> ResponseReturnValue:
            """获取用户反馈结果（单任务模式）
            ---
            tags:
              - Feedback
            responses:
              200:
                description: 反馈结果（读后清除）
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [success, waiting]
                    feedback:
                      type: object
                      nullable: true
                      description: 反馈内容，无反馈时为 null
            """
            with self._state_lock:
                result = self.feedback_result
                self.feedback_result = None
            if result:
                return jsonify({"status": "success", "feedback": result})
            return jsonify({"status": "waiting", "feedback": None})
