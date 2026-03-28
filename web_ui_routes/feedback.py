"""反馈提交路由 Mixin — 通用提交、内容更新、反馈查询。"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from flask import jsonify, request
from flask.typing import ResponseReturnValue

from enhanced_logging import EnhancedLogger
from file_validator import validate_uploaded_file
from i18n import msg
from server import get_task_queue
from shared_types import FeedbackResult

if TYPE_CHECKING:
    import threading

    from flask import Flask
    from flask_limiter import Limiter

logger = EnhancedLogger(__name__)


class FeedbackRoutesMixin:
    """提供 3 个反馈相关 API 路由，由 WebFeedbackUI 通过 MRO 继承。"""

    if TYPE_CHECKING:
        app: Flask
        limiter: Limiter
        _state_lock: threading.RLock
        feedback_result: Optional[FeedbackResult]
        current_prompt: str
        current_options: list[str]
        current_task_id: Optional[str]
        current_auto_resubmit_timeout: int
        _single_task_timeout_explicit: bool
        has_content: bool

        def render_markdown(self, text: str) -> str: ...

    def _setup_feedback_routes(self) -> None:  # noqa: C901
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
            logger.info(f"request.files: {dict(request.files)}")
            logger.info(f"request.form: {dict(request.form)}")
            try:
                json_data = request.get_json()
                logger.info(f"request.json: {json_data}")
            except Exception as e:
                logger.info(f"无法解析JSON数据: {e}")

            if request.files:
                requested_task_id = request.form.get("task_id", "").strip()
                feedback_text = request.form.get("feedback_text", "").strip()
                selected_options_str = request.form.get("selected_options", "[]")
                try:
                    selected_options = json.loads(selected_options_str)
                except json.JSONDecodeError:
                    selected_options = []

                logger.debug("接收到的反馈数据:")
                logger.debug(
                    f"  - 文字内容: '{feedback_text}' (长度: {len(feedback_text)})"
                )
                logger.debug(f"  - 选项数据: {selected_options_str}")
                logger.debug(f"  - 解析后选项: {selected_options}")
                logger.debug(f"  - 文件数量: {len(request.files)}")

                uploaded_images: list[dict[str, Any]] = []
                for key in request.files:
                    if key.startswith("image_"):
                        file = request.files[key]
                        if file and file.filename:
                            try:
                                file_content = file.read()

                                validation_result = validate_uploaded_file(
                                    file_content, file.filename, file.content_type
                                )

                                if not validation_result["valid"]:
                                    error_msg = f"文件验证失败: {file.filename} - {'; '.join(validation_result['errors'])}"
                                    logger.warning(error_msg)
                                    continue

                                if validation_result["warnings"]:
                                    logger.info(
                                        f"文件验证警告: {file.filename} - {'; '.join(validation_result['warnings'])}"
                                    )

                                safe_filename = f"{uuid.uuid4().hex}{validation_result.get('extension', '.bin')}"
                                original_filename = Path(
                                    file.filename.replace("\\", "/")
                                ).name

                                base64_data = base64.b64encode(file_content).decode(
                                    "utf-8"
                                )

                                uploaded_images.append(
                                    {
                                        "filename": original_filename,
                                        "safe_filename": safe_filename,
                                        "content_type": validation_result["mime_type"]
                                        or file.content_type
                                        or "application/octet-stream",
                                        "data": base64_data,
                                        "size": len(file_content),
                                        "validated_type": validation_result[
                                            "file_type"
                                        ],
                                        "validation_warnings": validation_result[
                                            "warnings"
                                        ],
                                        "file_hash": hashlib.sha256(
                                            file_content
                                        ).hexdigest()[:16],
                                    }
                                )
                                logger.debug(
                                    f"  - 处理图片: {file.filename} ({len(file_content)} bytes) - 类型: {validation_result['file_type']}"
                                )
                            except Exception as e:
                                logger.error(
                                    f"处理文件 {file.filename} 时出错: {e}",
                                    exc_info=True,
                                )
                                continue

                images: list[Any] = uploaded_images
            elif request.form:
                requested_task_id = request.form.get("task_id", "").strip()
                feedback_text = request.form.get("feedback_text", "").strip()
                selected_options_str = request.form.get("selected_options", "[]")
                try:
                    selected_options = json.loads(selected_options_str)
                except json.JSONDecodeError:
                    selected_options = []

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
                    selected_options = data.get("selected_options", [])
                    images = data.get("images", [])

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
                      type: number
                      description: 超时时间（秒，最大 250）
            responses:
              200:
                description: 更新成功
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success

            返回值：
                JSON对象：
                    - status: "success"
                    - message: msg("feedback.contentUpdated")
                    - prompt / prompt_html / predefined_options / task_id / auto_resubmit_timeout / has_content
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
