"""任务管理路由 Mixin — 任务列表、创建、详情、激活、提交反馈。"""

from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING, Any, Optional

from flask import jsonify, request
from flask.typing import ResponseReturnValue

from enhanced_logging import EnhancedLogger
from file_validator import validate_uploaded_file
from server import get_task_queue

if TYPE_CHECKING:
    from flask import Flask
    from flask_limiter import Limiter

logger = EnhancedLogger(__name__)


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

        @self.app.route("/api/tasks", methods=["GET"])
        @self.limiter.limit("300 per minute")
        def get_tasks() -> ResponseReturnValue:
            """获取所有任务列表的API端点

            功能说明：
                返回任务队列中的所有任务（包含状态、创建时间等），并自动清理过期的已完成任务。

            处理逻辑：
                1. 调用TaskQueue.cleanup_completed_tasks(age_seconds=10)清理10秒前完成的任务
                2. 获取所有任务列表
                3. 遍历任务列表，构建简化的任务信息（仅前100字符prompt）
                4. 获取任务统计信息（总数、pending、active、completed）
                5. 返回JSON响应

            返回值：
                JSON对象，包含以下字段：
                    - success: 是否成功（Boolean）
                    - tasks: 任务列表（Array）
                        - task_id: 任务ID
                        - status: 任务状态（pending/active/completed）
                        - prompt: 提示文本（前100字符）
                        - created_at: 创建时间（ISO 8601格式）
                        - auto_resubmit_timeout: 超时时间（秒）
                    - stats: 任务统计信息（Object）
                        - total: 总任务数
                        - pending: 等待中任务数
                        - active: 激活中任务数
                        - completed: 已完成任务数

            频率限制：
                - 300次/分钟（支持高频轮询）

            异常处理：
                - 获取失败时返回HTTP 500和错误信息
                - 记录详细错误日志

            注意事项：
                - 自动清理10秒前的completed任务，避免列表过长
                - prompt仅返回前100字符，避免响应体过大
                - 此端点用于前端多任务标签页的轮询更新
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
            """创建新任务的API端点

            功能说明：
                接收JSON请求，创建新的任务并添加到任务队列。

            请求体（JSON）：
                - task_id: 任务唯一标识符（必填）
                - prompt: 提示文本（必填，Markdown格式）
                - predefined_options: 预定义选项列表（可选）
                - auto_resubmit_timeout: 超时时间（可选，默认240秒，最大250秒）

            处理逻辑：
                1. 解析JSON请求体
                2. 验证必填字段（task_id、prompt）
                3. 限制auto_resubmit_timeout最大值为250秒
                4. 调用TaskQueue.add_task()添加任务
                5. 返回成功或失败响应

            返回值：
                成功：JSON对象 {"success": true, "task_id": "<task_id>"}
                失败：HTTP 400/409/500 + 错误信息
                    - 400: 缺少请求数据或必要参数
                    - 409: 任务队列已满或任务ID重复
                    - 500: 其他异常

            频率限制：
                - 60次/分钟（防止任务创建滥用）

            注意事项：
                - auto_resubmit_timeout 自动截断为 250 秒
                - 任务ID需全局唯一，重复添加会失败
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
            """获取单个任务详情的API端点

            功能说明：
                返回指定任务的完整信息，包括prompt全文、选项、状态、结果等。

            参数说明：
                task_id: 任务ID（URL路径参数）

            返回值：
                成功：JSON对象 {"success": true, "task": {...}}
                失败：HTTP 404 + 错误信息（任务不存在）
                      HTTP 500 + 错误信息（其他异常）

            频率限制：
                - 300次/分钟（支持高频轮询）
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
            """激活指定任务的API端点

            功能说明：
                将指定任务设置为激活状态（active_task），用于任务切换。

            参数说明：
                task_id: 任务ID（URL路径参数）

            返回值：
                成功：JSON对象 {"success": true, "active_task_id": "<task_id>"}
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
            """提交指定任务反馈的API端点

            功能说明：
                接收表单数据（支持文件上传），将反馈内容提交到指定任务并标记为完成。

            参数说明：
                task_id: 任务ID（URL路径参数）

            请求体（multipart/form-data）：
                - feedback_text: 用户输入文本
                - selected_options: 选中的选项（JSON数组字符串）
                - image_*: 图片文件（可多个，键名以image_开头）

            返回值：
                成功：JSON对象 {"success": true, "message": "反馈已提交"}
                失败：HTTP 404 + 错误信息（任务不存在）
                      HTTP 500 + 错误信息（其他异常）

            频率限制：
                - 60次/分钟（防止恶意提交）
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
                return jsonify({"success": True, "message": "反馈已提交"})
            except Exception as e:
                logger.error(f"提交任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500
