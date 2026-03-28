"""任务管理路由 Mixin — 任务列表、创建、详情、激活、提交反馈、SSE 事件流。"""

from __future__ import annotations

import base64
import json
import queue
import threading
import time
from typing import TYPE_CHECKING, Any, Optional

from flask import Response, jsonify, request
from flask.typing import ResponseReturnValue

from enhanced_logging import EnhancedLogger
from file_validator import validate_uploaded_file
from i18n import msg
from server import get_task_queue

if TYPE_CHECKING:
    from flask import Flask
    from flask_limiter import Limiter

logger = EnhancedLogger(__name__)


class _SSEBus:
    """线程安全的 SSE 事件总线：TaskQueue 回调 → 所有已连接的 EventSource 客户端"""

    def __init__(self) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def emit(self, event_type: str, data: dict | None = None) -> None:
        payload = {"type": event_type, "data": data or {}}
        with self._lock:
            dead: list[queue.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


_sse_bus = _SSEBus()


def _on_task_status_change(
    task_id: str, old_status: Optional[str], new_status: str
) -> None:
    _sse_bus.emit(
        "task_changed",
        {"task_id": task_id, "old_status": old_status, "new_status": new_status},
    )


_sse_callback_registered = False


class TaskRoutesMixin:
    """提供 5 个任务管理 API 路由，由 WebFeedbackUI 通过 MRO 继承。"""

    if TYPE_CHECKING:
        app: Flask
        limiter: Limiter

    def _setup_task_routes(self) -> None:  # noqa: C901
        from web_ui import (
            _get_default_auto_resubmit_timeout_from_config,
            validate_auto_resubmit_timeout,
        )

        global _sse_callback_registered  # noqa: PLW0603
        if not _sse_callback_registered:
            try:
                tq = get_task_queue()
                if tq is not None:
                    tq.register_status_change_callback(_on_task_status_change)
                    _sse_callback_registered = True
                    logger.info("SSE 事件总线已注册到 TaskQueue")
            except Exception:
                pass

        @self.app.route("/api/events")
        def sse_events() -> Response:
            """SSE 事件流：实时推送任务变更通知
            ---
            tags:
              - Tasks
            produces:
              - text/event-stream
            responses:
              200:
                description: SSE 事件流（task_changed 事件 + 25s 心跳）
            """
            global _sse_callback_registered  # noqa: PLW0603
            if not _sse_callback_registered:
                try:
                    tq = get_task_queue()
                    if tq is not None:
                        tq.register_status_change_callback(_on_task_status_change)
                        _sse_callback_registered = True
                except Exception:
                    pass

            q = _sse_bus.subscribe()

            def generate():
                try:
                    while True:
                        try:
                            event = q.get(timeout=25)
                            yield f"event: {event['type']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                        except queue.Empty:
                            yield ": heartbeat\n\n"
                except GeneratorExit:
                    pass
                finally:
                    _sse_bus.unsubscribe(q)

            return Response(
                generate(),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                },
            )

        @self.app.route("/api/tasks", methods=["GET"])
        @self.limiter.limit("300 per minute")
        def get_tasks() -> ResponseReturnValue:
            """获取所有任务列表
            ---
            tags:
              - Tasks
            responses:
              200:
                description: 任务列表与统计信息
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    tasks:
                      type: array
                      items:
                        type: object
                        properties:
                          task_id:
                            type: string
                          status:
                            type: string
                            enum: [pending, active, completed]
                          prompt:
                            type: string
                            description: 提示文本（前 100 字符）
                          created_at:
                            type: string
                            format: date-time
                          auto_resubmit_timeout:
                            type: number
                          remaining_time:
                            type: number
                    stats:
                      type: object
                      properties:
                        total:
                          type: integer
                        pending:
                          type: integer
                        active:
                          type: integer
                        completed:
                          type: integer
                    server_time:
                      type: number
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()

                task_queue.cleanup_completed_tasks(age_seconds=10)

                tasks = task_queue.get_all_tasks()

                server_time = time.time()

                task_list = []
                for task in tasks:
                    task_list.append(
                        {
                            "task_id": task.task_id,
                            "status": task.status,
                            "prompt": task.prompt[:100],
                            "created_at": task.created_at.isoformat(),
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "remaining_time": task.get_remaining_time(),
                            "deadline": task.created_at.timestamp()
                            + task.auto_resubmit_timeout,
                        }
                    )

                stats = task_queue.get_task_count()

                return jsonify(
                    {
                        "success": True,
                        "tasks": task_list,
                        "stats": stats,
                        "server_time": server_time,
                    }
                )
            except Exception as e:
                logger.error(f"获取任务列表失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def create_task() -> ResponseReturnValue:
            """创建新任务
            ---
            tags:
              - Tasks
            consumes:
              - application/json
            parameters:
              - in: body
                name: body
                required: true
                schema:
                  type: object
                  required:
                    - task_id
                    - prompt
                  properties:
                    task_id:
                      type: string
                      description: 任务唯一标识符
                    prompt:
                      type: string
                      description: 提示文本（Markdown 格式）
                    predefined_options:
                      type: array
                      items:
                        type: string
                      description: 预定义选项列表
                    auto_resubmit_timeout:
                      type: number
                      description: 超时时间（秒，最大 250）
                      default: 240
            responses:
              200:
                description: 任务创建成功
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    task_id:
                      type: string
              400:
                description: 请求参数错误
              409:
                description: 任务 ID 重复或队列已满
              500:
                description: 服务器内部错误
            """
            try:
                raw = request.get_json(silent=False)
            except Exception:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "请求体必须是 JSON（object）",
                        }
                    ),
                    400,
                )

            if not isinstance(raw, dict):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "请求体必须是 JSON object",
                        }
                    ),
                    400,
                )

            data: dict[str, Any] = raw

            task_id_raw = data.get("task_id", data.get("id"))
            prompt_raw = data.get("prompt", data.get("message"))
            options_raw = data.get("predefined_options", data.get("options"))
            timeout_raw = data.get("auto_resubmit_timeout", data.get("timeout"))

            if not isinstance(task_id_raw, str) or not task_id_raw.strip():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "缺少必要参数：task_id（或 id）",
                        }
                    ),
                    400,
                )
            if not isinstance(prompt_raw, str) or not prompt_raw:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "缺少必要参数：prompt（或 message）",
                        }
                    ),
                    400,
                )

            task_id = task_id_raw.strip()
            prompt = prompt_raw

            predefined_options: Optional[list[str]] = None
            if options_raw is None:
                predefined_options = None
            elif not isinstance(options_raw, list):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "predefined_options（或 options）必须是数组",
                        }
                    ),
                    400,
                )
            else:
                cleaned: list[str] = []
                for opt in options_raw:
                    if not isinstance(opt, str):
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "predefined_options（或 options）元素必须是字符串",
                                }
                            ),
                            400,
                        )
                    s = opt.strip()
                    if s:
                        cleaned.append(s)
                predefined_options = cleaned

            default_timeout = _get_default_auto_resubmit_timeout_from_config()
            timeout_explicit = "auto_resubmit_timeout" in data or "timeout" in data
            if timeout_explicit:
                if timeout_raw is None or isinstance(timeout_raw, bool):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "auto_resubmit_timeout（或 timeout）必须是整数",
                            }
                        ),
                        400,
                    )
                try:
                    timeout_int = int(timeout_raw)
                except Exception:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "auto_resubmit_timeout（或 timeout）必须是整数",
                            }
                        ),
                        400,
                    )
            else:
                timeout_int = default_timeout

            auto_resubmit_timeout = validate_auto_resubmit_timeout(timeout_int)

            try:
                task_queue = get_task_queue()
                success = task_queue.add_task(
                    task_id=task_id,
                    prompt=prompt,
                    predefined_options=predefined_options,
                    auto_resubmit_timeout=auto_resubmit_timeout,
                )
            except Exception as e:
                logger.error(f"创建任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

            if success:
                logger.info(f"任务已通过API添加到队列: {task_id}")
                return jsonify({"success": True, "task_id": task_id})

            logger.error(f"添加任务失败: {task_id}")
            return (
                jsonify({"success": False, "error": "任务队列已满或任务ID重复"}),
                409,
            )

        @self.app.route("/api/tasks/<task_id>", methods=["GET"])
        @self.limiter.limit("300 per minute")
        def get_task(task_id: str) -> ResponseReturnValue:
            """获取单个任务详情
            ---
            tags:
              - Tasks
            parameters:
              - name: task_id
                in: path
                type: string
                required: true
                description: 任务 ID
            responses:
              200:
                description: 任务详情
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    task:
                      type: object
                      properties:
                        task_id:
                          type: string
                        prompt:
                          type: string
                        status:
                          type: string
                          enum: [pending, active, completed]
                        predefined_options:
                          type: array
                          items:
                            type: string
                        created_at:
                          type: string
                          format: date-time
                        remaining_time:
                          type: number
                        result:
                          type: object
              404:
                description: 任务不存在
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()

                task_queue.cleanup_completed_tasks(age_seconds=10)

                task = task_queue.get_task(task_id)

                if not task:
                    return jsonify({"success": False, "error": "任务不存在"}), 404

                return jsonify(
                    {
                        "success": True,
                        "server_time": time.time(),
                        "task": {
                            "task_id": task.task_id,
                            "prompt": task.prompt,
                            "predefined_options": task.predefined_options,
                            "status": task.status,
                            "created_at": task.created_at.isoformat(),
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "remaining_time": task.get_remaining_time(),
                            "deadline": task.created_at.timestamp()
                            + task.auto_resubmit_timeout,
                            "result": task.result,
                        },
                    }
                )
            except Exception as e:
                logger.error(f"获取任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks/<task_id>/activate", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def activate_task(task_id: str) -> ResponseReturnValue:
            """激活指定任务
            ---
            tags:
              - Tasks
            parameters:
              - name: task_id
                in: path
                type: string
                required: true
            responses:
              200:
                description: 任务已激活
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    active_task_id:
                      type: string
              404:
                description: 任务不存在
                失败：HTTP 400 + 错误信息（切换失败）
                      HTTP 500 + 错误信息（其他异常）

            频率限制：
                - 60次/分钟（防止频繁切换）
            """
            try:
                task_queue = get_task_queue()
                success = task_queue.set_active_task(task_id)

                if not success:
                    return jsonify({"success": False, "error": "切换任务失败"}), 400

                return jsonify({"success": True, "active_task_id": task_id})
            except Exception as e:
                logger.error(f"激活任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks/<task_id>/submit", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def submit_task_feedback(task_id: str) -> ResponseReturnValue:
            """提交指定任务的反馈
            ---
            tags:
              - Tasks
            consumes:
              - multipart/form-data
            parameters:
              - name: task_id
                in: path
                type: string
                required: true
              - name: feedback_text
                in: formData
                type: string
                description: 用户反馈文本
              - name: selected_options
                in: formData
                type: string
                description: 已选选项（JSON 数组字符串）
              - name: images
                in: formData
                type: file
                description: 上传的图片文件
            responses:
              200:
                description: 反馈提交成功
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    message:
                      type: string
              404:
                description: 任务不存在
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()
                task = task_queue.get_task(task_id)

                if not task:
                    return jsonify({"success": False, "error": "任务不存在"}), 404

                feedback_text = request.form.get("feedback_text", "")
                selected_options_raw = request.form.get("selected_options", "[]")
                try:
                    selected_options = json.loads(selected_options_raw)
                except Exception:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "selected_options 必须是 JSON 数组字符串",
                            }
                        ),
                        400,
                    )

                if not isinstance(selected_options, list):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "selected_options 必须是 JSON 数组",
                            }
                        ),
                        400,
                    )

                cleaned_selected_options: list[str] = []
                for opt in selected_options:
                    if not isinstance(opt, str):
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "selected_options 数组元素必须是字符串",
                                }
                            ),
                            400,
                        )
                    s = opt.strip()
                    if s:
                        cleaned_selected_options.append(s)
                selected_options = cleaned_selected_options

                images = []
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
                                    logger.warning(
                                        f"文件验证失败: {file.filename} - {'; '.join(validation_result['errors'])}"
                                    )
                                    continue

                                image_data = base64.b64encode(file_content).decode(
                                    "utf-8"
                                )

                                images.append(
                                    {
                                        "filename": file.filename,
                                        "data": image_data,
                                        "content_type": validation_result["mime_type"]
                                        or file.content_type
                                        or "image/jpeg",
                                        "size": len(file_content),
                                    }
                                )
                            except Exception as img_error:
                                logger.error(
                                    f"处理图片失败: {img_error}", exc_info=True
                                )

                result = {
                    "user_input": feedback_text,
                    "selected_options": selected_options,
                }

                if images:
                    result["images"] = images

                task_queue.complete_task(task_id, result)

                logger.info(f"任务 {task_id} 反馈已提交")
                return jsonify({"success": True, "message": msg("feedback.submitted")})
            except Exception as e:
                logger.error(f"提交任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500
