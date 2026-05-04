"""反馈提交路由 Mixin — 通用提交、内容更新、反馈查询。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from flask import jsonify, request
from flask.typing import ResponseReturnValue

from enhanced_logging import EnhancedLogger
from i18n import msg
from server import get_task_queue
from shared_types import FeedbackResult
from web_ui_routes._upload_helpers import extract_uploaded_images

if TYPE_CHECKING:
    import threading

    from flask import Flask
    from flask_limiter import Limiter

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
         过滤掉空字符串和超过 500 字符的异常长串；
      3. 去重但保持顺序；
      4. 最多保留 50 项（上层 UI 一般也就几项，这里只做兜底防滥用）。
    """
    if not isinstance(raw, list):
        return []

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
        if len(item) > 500:
            continue
        if item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
        if len(cleaned) >= 50:
            break
    return cleaned


class FeedbackRoutesMixin:
    """提供 3 个反馈相关 API 路由，由 WebFeedbackUI 通过 MRO 继承。"""

    if TYPE_CHECKING:
        app: Flask
        limiter: Limiter
        _state_lock: threading.RLock
        feedback_result: FeedbackResult | None
        current_prompt: str
        current_options: list[str]
        current_task_id: str | None
        current_auto_resubmit_timeout: int
        _single_task_timeout_explicit: bool
        has_content: bool

        def render_markdown(self, text: str) -> str: ...

    def _setup_feedback_routes(self) -> None:
        from web_ui import (
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
                    clear_content:
                      type: boolean
            """
            logger.info(f"收到提交请求 - Content-Type: {request.content_type}")
            logger.debug(f"request.files keys: {list(request.files.keys())}")
            logger.debug(f"request.form keys: {list(request.form.keys())}")
            try:
                json_data = request.get_json()
                logger.debug(
                    f"request.json keys: {list(json_data.keys()) if isinstance(json_data, dict) else type(json_data)}"
                )
            except Exception as e:
                logger.debug(f"无法解析JSON数据: {e}")

            if request.files:
                requested_task_id = request.form.get("task_id", "").strip()
                feedback_text = request.form.get("feedback_text", "").strip()
                selected_options_str = request.form.get("selected_options", "[]")
                try:
                    selected_options = json.loads(selected_options_str)
                except json.JSONDecodeError:
                    selected_options = []
                selected_options = _sanitize_selected_options(selected_options)

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
                try:
                    selected_options = json.loads(selected_options_str)
                except json.JSONDecodeError:
                    selected_options = []
                selected_options = _sanitize_selected_options(selected_options)

                logger.debug("接收到的表单数据:")
                logger.debug(
                    f"  - 文字内容: '{feedback_text}' (长度: {len(feedback_text)})"
                )
                logger.debug(f"  - 选项数据: {selected_options_str}")
                logger.debug(f"  - 解析后选项: {selected_options}")

                images = []
            else:
                try:
                    data = request.get_json() or {}
                    requested_task_id = str(data.get("task_id", "")).strip()
                    feedback_text = str(
                        data.get("feedback_text", data.get("user_input", ""))
                    ).strip()
                    selected_options = _sanitize_selected_options(
                        data.get("selected_options", [])
                    )
                    images = data.get("images", [])
                    if not isinstance(images, list):
                        images = []

                    logger.debug("接收到的JSON数据:")
                    logger.debug(
                        f"  - 文字内容: '{feedback_text}' (长度: {len(feedback_text)})"
                    )
                    logger.debug(f"  - 选项: {selected_options}")
                    logger.debug(f"  - 图片数量: {len(images)}")
                except Exception:
                    requested_task_id = ""
                    feedback_text = ""
                    selected_options = []
                    images = []
                    logger.debug("JSON解析失败，使用默认值")

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

            with self._state_lock:
                self.feedback_result = feedback_result

            logger.debug("最终存储的反馈结果:")
            logger.debug(
                f"  - user_input: '{feedback_result['user_input']}' (长度: {len(feedback_result['user_input'])})"
            )
            logger.debug(f"  - selected_options: {feedback_result['selected_options']}")
            logger.debug(f"  - images数量: {len(feedback_result['images'])}")

            if target_task_id:
                logger.info(f"同时将反馈提交到TaskQueue中的目标任务: {target_task_id}")
                task_queue.complete_task(
                    target_task_id,
                    cast(dict[str, Any], feedback_result),
                )

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
                    task_id:
                      type: string
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
                    prompt_html:
                      type: string
                      description: Markdown 渲染后的 HTML
                    predefined_options:
                      type: array
                      items:
                        type: string
                    task_id:
                      type: string
                    auto_resubmit_timeout:
                      type: number
                    has_content:
                      type: boolean
              400:
                description: 请求参数错误
              500:
                description: 服务器内部错误
            """
            try:
                raw = request.get_json(silent=False)
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

            if len(new_prompt) > 10000:
                logger.warning(
                    f"/api/update prompt 过长：{len(new_prompt)}，将截断到 10000"
                )
                new_prompt = new_prompt[:10000] + "..."

            new_options_raw = data.get("predefined_options", [])
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
                    timeout_int = int(raw_timeout)
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
                      description: 反馈内容，无反馈时为 null
            """
            with self._state_lock:
                result = self.feedback_result
                self.feedback_result = None
            if result:
                return jsonify({"status": "success", "feedback": result})
            return jsonify({"status": "waiting", "feedback": None})
