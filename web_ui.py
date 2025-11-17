"""
Web UI for AI Intervention Agent MCP

支持 GUI 和 Web 模式，适用于SSH远程使用
"""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import signal
import sys
import threading
import time
import uuid
from ipaddress import (
    AddressValueError,
    IPv4Network,
    IPv6Network,
    ip_address,
)
from typing import (
    Dict,
    List,
    Optional,
)

import markdown
from flask import (
    Flask,
    abort,
    jsonify,
    render_template_string,
    request,
    send_from_directory,
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config_manager import get_config
from enhanced_logging import EnhancedLogger
from file_validator import validate_uploaded_file
from server import get_task_queue

try:
    from notification_manager import (
        NotificationEvent,
        NotificationTrigger,
        NotificationType,
        notification_manager,
    )
    from notification_providers import BarkNotificationProvider

    NOTIFICATION_AVAILABLE = True
except ImportError:
    NOTIFICATION_AVAILABLE = False

logger = EnhancedLogger(__name__)


class WebFeedbackUI:
    """Web 反馈界面

    提供基于 Flask 的 Web 界面，用于收集用户反馈
    支持多任务、文件上传、Markdown渲染等功能
    """
    def __init__(
        self,
        prompt: str,
        predefined_options: Optional[List[str]] = None,
        task_id: Optional[str] = None,
        auto_resubmit_timeout: int = 290,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        """初始化 Web 反馈界面

        Args:
            prompt: 提示文本
            predefined_options: 预定义选项列表
            task_id: 任务ID
            auto_resubmit_timeout: 自动重新提交超时时间（秒）
            host: 绑定主机地址
            port: 绑定端口
        """
        self.prompt = prompt
        self.predefined_options = predefined_options or []
        self.task_id = task_id
        self.auto_resubmit_timeout = auto_resubmit_timeout
        self.host = host
        self.port = port
        self.feedback_result = None
        self.current_prompt = prompt if prompt else ""
        self.current_options = predefined_options or []
        self.current_task_id = task_id
        self.current_auto_resubmit_timeout = auto_resubmit_timeout
        self.has_content = bool(prompt)
        self.initial_empty = not bool(prompt)
        self.app = Flask(__name__)
        CORS(self.app)

        self.csp_nonce = secrets.token_urlsafe(16)
        self.network_security_config = self._load_network_security_config()

        self.limiter = Limiter(
            key_func=get_remote_address,
            app=self.app,
            default_limits=["60 per minute", "10 per second"],
            storage_uri="memory://",
            strategy="fixed-window",
        )

        self.setup_security_headers()
        self.setup_markdown()
        self.setup_routes()

    def setup_security_headers(self):
        """设置HTTP安全头部

        配置 CSP、XSS保护、点击劫持保护等安全策略
        """

        @self.app.before_request
        def check_ip_access():
            """检查IP访问权限"""
            client_ip = request.environ.get(
                "HTTP_X_FORWARDED_FOR", request.environ.get("REMOTE_ADDR", "")
            )
            if client_ip and "," in client_ip:
                client_ip = client_ip.split(",")[0].strip()

            if not self._is_ip_allowed(client_ip):
                logger.warning(f"拒绝来自 {client_ip} 的访问请求")
                abort(403)

        @self.app.after_request
        def add_security_headers(response):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{self.csp_nonce}'; "
                f"style-src 'self' 'nonce-{self.csp_nonce}' "
                "'sha256-JLEjeN9e5dGsz5475WyRaoA4eQOdNPxDIeUhclnJDCE=' "  # MathJax inline styles
                "'sha256-mQyxHEuwZJqpxCw3SLmc4YOySNKXunyu2Oiz1r3/wAE=' "  # MathJax inline styles
                "'sha256-OCf+kv5Asiwp++8PIevKBYSgnNLNUZvxAp4a7wMLuKA=' "  # MathJax inline styles
                "'sha256-pYs3hdAJmGSBSoN18N3tD9lPxkQenuhgv/HGUB12p1M='; "
                "img-src 'self' data: blob:; "
                "font-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "object-src 'none'"
            )

            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = (
                "geolocation=(), microphone=(), camera=(), "
                "payment=(), usb=(), magnetometer=(), gyroscope=()"
            )

            return response

    def setup_markdown(self):
        """设置 Markdown 渲染器

        配置支持代码高亮、表格、脚注等扩展
        """
        self.md = markdown.Markdown(
            extensions=[
                "fenced_code",
                "codehilite",
                "tables",
                "toc",
                "nl2br",
                "attr_list",
                "def_list",
                "abbr",
                "footnotes",
                "md_in_html",
            ],
            extension_configs={
                "codehilite": {
                    "css_class": "highlight",
                    "use_pygments": True,
                    "noclasses": True,
                    "pygments_style": "monokai",
                    "guess_lang": True,
                    "linenums": False,
                }
            },
        )

    def render_markdown(self, text: str) -> str:
        """渲染 Markdown 文本为 HTML

        Args:
            text: Markdown 文本

        Returns:
            str: 渲染后的 HTML
        """
        if not text:
            return ""
        return self.md.convert(text)

    def setup_routes(self):
        @self.app.route("/")
        def index():
            return render_template_string(self.get_html_template())

        @self.app.route("/api/config")
        @self.limiter.limit("300 per minute")  # 允许更频繁的轮询，支持测试场景
        def get_api_config():
            try:
                # 优先从 TaskQueue 获取激活任务
                task_queue = get_task_queue()
                active_task = task_queue.get_active_task()

                if active_task:
                    # 使用TaskQueue中的激活任务
                    return jsonify(
                        {
                            "prompt": active_task.prompt,
                            "prompt_html": self.render_markdown(active_task.prompt),
                            "predefined_options": active_task.predefined_options,
                            "task_id": active_task.task_id,
                            "auto_resubmit_timeout": active_task.auto_resubmit_timeout,
                            "persistent": True,
                            "has_content": True,
                            "initial_empty": False,
                        }
                    )
                else:
                    # 如果没有激活任务，检查是否有 pending 任务
                    all_tasks = task_queue.get_all_tasks()
                    # 过滤出未完成的任务（排除 completed 状态）
                    incomplete_tasks = [t for t in all_tasks if t["status"] != "completed"]

                    if incomplete_tasks:
                        # 有未完成任务存在，激活第一个
                        first_task = incomplete_tasks[0]
                        task_queue.set_active_task(first_task["task_id"])
                        logger.info(f"自动激活第一个pending任务: {first_task['task_id']}")

                        return jsonify(
                            {
                                "prompt": first_task["prompt"],
                                "prompt_html": self.render_markdown(first_task["prompt"]),
                                "predefined_options": first_task["predefined_options"],
                                "task_id": first_task["task_id"],
                                "auto_resubmit_timeout": first_task["auto_resubmit_timeout"],
                                "persistent": True,
                                "has_content": True,
                                "initial_empty": False,
                            }
                        )
                    elif all_tasks:
                        # 所有任务都是 completed 状态，显示无有效内容
                        logger.info("所有任务均已完成，显示无有效内容页面")
                        return jsonify(
                            {
                                "prompt": "",
                                "prompt_html": "",
                                "predefined_options": [],
                                "task_id": None,
                                "auto_resubmit_timeout": 0,
                                "persistent": True,
                                "has_content": False,
                                "initial_empty": False,
                            }
                        )

                    # 回退到旧的单任务模式
                    return jsonify(
                        {
                            "prompt": self.current_prompt,
                            "prompt_html": self.render_markdown(self.current_prompt)
                            if self.has_content
                            else "",
                            "predefined_options": self.current_options,
                            "task_id": self.current_task_id,
                            "auto_resubmit_timeout": self.current_auto_resubmit_timeout,
                            "persistent": True,
                            "has_content": self.has_content,
                            "initial_empty": self.initial_empty,
                        }
                    )
            except Exception as e:
                logger.error(f"获取配置失败: {e}", exc_info=True)
                # 返回安全的默认响应
                return jsonify(
                    {
                        "prompt": "",
                        "prompt_html": "",
                        "predefined_options": [],
                        "task_id": None,
                        "auto_resubmit_timeout": 0,
                        "persistent": True,
                        "has_content": False,
                        "initial_empty": True,
                    }
                ), 500

        @self.app.route("/api/close", methods=["POST"])
        def close_interface():
            """关闭界面的API端点"""
            threading.Timer(0.5, self.shutdown_server).start()
            return jsonify({"status": "success", "message": "服务即将关闭"})

        @self.app.route("/api/health", methods=["GET"])
        def health_check():
            """健康检查端点"""
            return jsonify({"status": "ok"})

        @self.app.route("/api/tasks", methods=["GET"])
        @self.limiter.limit("300 per minute")
        def get_tasks():
            """获取所有任务列表（并自动清理过期任务）"""
            try:
                task_queue = get_task_queue()

                # 自动清理超过 10 秒的已完成任务
                task_queue.cleanup_completed_tasks(age_seconds=10)

                tasks = task_queue.get_all_tasks()

                task_list = []
                for task in tasks:
                    task_list.append(
                        {
                            "task_id": task.task_id,
                            "status": task.status,
                            "prompt": task.prompt[:100],  # 只返回前100个字符
                            "created_at": task.created_at.isoformat(),
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                        }
                    )

                stats = task_queue.get_task_count()

                return jsonify({"success": True, "tasks": task_list, "stats": stats})
            except Exception as e:
                logger.error(f"获取任务列表失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/tasks", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def create_task():
            """创建新任务"""
            try:
                data = request.get_json()
                if not data:
                    return jsonify({"success": False, "error": "缺少请求数据"}), 400

                task_id = data.get("task_id")
                prompt = data.get("prompt")
                predefined_options = data.get("predefined_options")
                auto_resubmit_timeout = data.get("auto_resubmit_timeout", 290)

                if not task_id or not prompt:
                    return jsonify({"success": False, "error": "缺少必要参数：task_id 和 prompt"}), 400

                task_queue = get_task_queue()
                success = task_queue.add_task(
                    task_id=task_id,
                    prompt=prompt,
                    predefined_options=predefined_options,
                    auto_resubmit_timeout=auto_resubmit_timeout,
                )

                if success:
                    logger.info(f"任务已通过API添加到队列: {task_id}")
                    return jsonify({"success": True, "task_id": task_id})
                else:
                    logger.error(f"添加任务失败: {task_id}")
                    return jsonify({"success": False, "error": "任务队列已满或任务ID重复"}), 409

            except Exception as e:
                logger.error(f"创建任务失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/tasks/<task_id>", methods=["GET"])
        @self.limiter.limit("300 per minute")
        def get_task(task_id):
            """获取单个任务的完整信息（并自动清理过期任务）"""
            try:
                task_queue = get_task_queue()

                # 自动清理超过 10 秒的已完成任务
                task_queue.cleanup_completed_tasks(age_seconds=10)

                task = task_queue.get_task(task_id)

                if not task:
                    return jsonify({"success": False, "error": "任务不存在"}), 404

                return jsonify(
                    {
                        "success": True,
                        "task": {
                            "task_id": task.task_id,
                            "prompt": task.prompt,
                            "predefined_options": task.predefined_options,
                            "status": task.status,
                            "created_at": task.created_at.isoformat(),
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "result": task.result,  # 添加result字段
                        },
                    }
                )
            except Exception as e:
                logger.error(f"获取任务失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/tasks/<task_id>/activate", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def activate_task(task_id):
            """激活（切换到）指定任务"""
            try:
                task_queue = get_task_queue()
                success = task_queue.set_active_task(task_id)

                if not success:
                    return jsonify({"success": False, "error": "切换任务失败"}), 400

                return jsonify({"success": True, "active_task_id": task_id})
            except Exception as e:
                logger.error(f"激活任务失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/tasks/<task_id>/submit", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def submit_task_feedback(task_id):
            """提交任务反馈"""
            try:
                task_queue = get_task_queue()
                task = task_queue.get_task(task_id)

                if not task:
                    return jsonify({"success": False, "error": "任务不存在"}), 404

                # 获取反馈内容
                feedback_text = request.form.get("feedback_text", "")
                selected_options = json.loads(
                    request.form.get("selected_options", "[]")
                )

                # 处理图片
                images = []
                if "images" in request.files:
                    files = request.files.getlist("images")
                    for file in files:
                        if file and file.filename:
                            try:
                                image_data = base64.b64encode(file.read()).decode(
                                    "utf-8"
                                )
                                images.append(
                                    {"filename": file.filename, "data": image_data}
                                )
                            except Exception as img_error:
                                logger.error(f"处理图片失败: {img_error}")

                # 构建结果
                result = {
                    "user_input": feedback_text,
                    "selected_options": selected_options,
                }

                if images:
                    result["images"] = images

                # 标记任务为完成
                task_queue.complete_task(task_id, result)

                logger.info(f"任务 {task_id} 反馈已提交")
                return jsonify({"success": True, "message": "反馈已提交"})
            except Exception as e:
                logger.error(f"提交任务失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/submit", methods=["POST"])
        @self.limiter.limit("60 per minute")  # 放宽提交频率限制，支持测试场景
        def submit_feedback():
            # 调试信息：记录请求类型和内容（使用INFO级别确保输出）
            logger.info(f"🔍 收到提交请求 - Content-Type: {request.content_type}")
            logger.info(f"🔍 request.files: {dict(request.files)}")
            logger.info(f"🔍 request.form: {dict(request.form)}")
            try:
                json_data = request.get_json()
                logger.info(f"🔍 request.json: {json_data}")
            except Exception as e:
                logger.info(f"🔍 无法解析JSON数据: {e}")

            # 检查是否有文件上传（优先检查 request.files）
            if request.files:
                # 处理文件上传请求（multipart/form-data）
                feedback_text = request.form.get("feedback_text", "").strip()
                selected_options_str = request.form.get("selected_options", "[]")
                try:
                    selected_options = json.loads(selected_options_str)
                except json.JSONDecodeError:
                    selected_options = []

                # 调试信息：记录接收到的数据
                logger.debug("接收到的反馈数据:")
                logger.debug(
                    f"  - 文字内容: '{feedback_text}' (长度: {len(feedback_text)})"
                )
                logger.debug(f"  - 选项数据: {selected_options_str}")
                logger.debug(f"  - 解析后选项: {selected_options}")
                logger.debug(f"  - 文件数量: {len(request.files)}")

                # 处理上传的图片文件
                uploaded_images = []
                for key in request.files:
                    if key.startswith("image_"):
                        file = request.files[key]
                        if file and file.filename:
                            try:
                                # 读取文件内容
                                file_content = file.read()

                                # 安全验证：使用文件验证器检查文件安全性
                                validation_result = validate_uploaded_file(
                                    file_content, file.filename, file.content_type
                                )

                                # 检查验证结果
                                if not validation_result["valid"]:
                                    error_msg = f"文件验证失败: {file.filename} - {'; '.join(validation_result['errors'])}"
                                    logger.warning(error_msg)
                                    continue

                                # 记录警告信息
                                if validation_result["warnings"]:
                                    logger.info(
                                        f"文件验证警告: {file.filename} - {'; '.join(validation_result['warnings'])}"
                                    )

                                # 安全文件名处理：生成安全的文件名
                                # 生成UUID作为安全文件名，避免路径遍历攻击
                                safe_filename = f"{uuid.uuid4().hex}{validation_result.get('extension', '.bin')}"
                                original_filename = os.path.basename(
                                    file.filename
                                )  # 移除路径信息

                                # 转换为base64（用于MCP传输）
                                base64_data = base64.b64encode(file_content).decode(
                                    "utf-8"
                                )

                                uploaded_images.append(
                                    {
                                        "filename": original_filename,  # 保留原始文件名用于显示
                                        "safe_filename": safe_filename,  # 安全文件名用于存储
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
                                        ).hexdigest()[:16],  # 文件指纹
                                    }
                                )
                                logger.debug(
                                    f"  - 处理图片: {file.filename} ({len(file_content)} bytes) - 类型: {validation_result['file_type']}"
                                )
                            except Exception as e:
                                logger.error(f"处理文件 {file.filename} 时出错: {e}")
                                continue

                images = uploaded_images
            elif request.form:
                # 处理表单数据（没有文件）
                feedback_text = request.form.get("feedback_text", "").strip()
                selected_options_str = request.form.get("selected_options", "[]")
                try:
                    selected_options = json.loads(selected_options_str)
                except json.JSONDecodeError:
                    selected_options = []

                # 调试信息：记录接收到的数据
                logger.debug("接收到的表单数据:")
                logger.debug(
                    f"  - 文字内容: '{feedback_text}' (长度: {len(feedback_text)})"
                )
                logger.debug(f"  - 选项数据: {selected_options_str}")
                logger.debug(f"  - 解析后选项: {selected_options}")

                images = []
            else:
                # 兼容原有的JSON请求格式
                try:
                    data = request.get_json() or {}
                    feedback_text = data.get("feedback_text", "").strip()
                    selected_options = data.get("selected_options", [])
                    images = data.get("images", [])

                    # 调试信息：记录接收到的数据
                    logger.debug("接收到的JSON数据:")
                    logger.debug(
                        f"  - 文字内容: '{feedback_text}' (长度: {len(feedback_text)})"
                    )
                    logger.debug(f"  - 选项: {selected_options}")
                    logger.debug(f"  - 图片数量: {len(images)}")
                except Exception:
                    # 如果无法解析JSON，使用默认值
                    feedback_text = ""
                    selected_options = []
                    images = []
                    logger.debug("JSON解析失败，使用默认值")

            # 构建新的返回格式
            self.feedback_result = {
                "user_input": feedback_text,
                "selected_options": selected_options,
                "images": images,
            }

            # 调试信息：记录最终存储的数据
            logger.debug("最终存储的反馈结果:")
            logger.debug(
                f"  - user_input: '{self.feedback_result['user_input']}' (长度: {len(self.feedback_result['user_input'])})"
            )
            logger.debug(
                f"  - selected_options: {self.feedback_result['selected_options']}"
            )
            logger.debug(f"  - images数量: {len(self.feedback_result['images'])}")

            # 如果有激活的任务，也提交到 TaskQueue
            task_queue = get_task_queue()
            active_task = task_queue.get_active_task()
            if active_task:
                logger.info(f"同时将反馈提交到TaskQueue中的激活任务: {active_task.task_id}")
                task_queue.complete_task(active_task.task_id, self.feedback_result)

            # 清空内容并等待下一次调用
            self.current_prompt = ""
            self.current_options = []
            self.has_content = False
            return jsonify(
                {
                    "status": "success",
                    "message": "反馈已提交",
                    "persistent": True,
                    "clear_content": True,
                }
            )

        @self.app.route("/api/update", methods=["POST"])
        def update_content():
            """更新页面内容"""
            data = request.json
            new_prompt = data.get("prompt", "")
            new_options = data.get("predefined_options", [])
            new_task_id = data.get("task_id")
            new_auto_resubmit_timeout = data.get("auto_resubmit_timeout", 290)

            # 更新内容
            self.current_prompt = new_prompt
            self.current_options = new_options if new_options is not None else []
            self.current_task_id = new_task_id
            self.current_auto_resubmit_timeout = new_auto_resubmit_timeout
            self.has_content = bool(new_prompt)
            # 重置反馈结果
            self.feedback_result = None

            return jsonify(
                {
                    "status": "success",
                    "message": "内容已更新",
                    "prompt": self.current_prompt,
                    "prompt_html": self.render_markdown(self.current_prompt)
                    if self.has_content
                    else "",
                    "predefined_options": self.current_options,
                    "task_id": self.current_task_id,
                    "auto_resubmit_timeout": self.current_auto_resubmit_timeout,
                    "has_content": self.has_content,
                }
            )

        @self.app.route("/api/feedback", methods=["GET"])
        def get_feedback():
            """获取用户反馈结果"""
            if self.feedback_result:
                # 返回反馈结果并清空
                result = self.feedback_result
                self.feedback_result = None
                return jsonify({"status": "success", "feedback": result})
            else:
                return jsonify({"status": "waiting", "feedback": None})

        @self.app.route("/api/test-bark", methods=["POST"])
        def test_bark_notification():
            """测试Bark通知的API端点"""
            try:
                # 获取请求数据
                data = request.json or {}
                bark_url = data.get("bark_url", "https://api.day.app/push")
                bark_device_key = data.get("bark_device_key", "")
                bark_icon = data.get("bark_icon", "")
                bark_action = data.get("bark_action", "none")

                if not bark_device_key:
                    return jsonify(
                        {"status": "error", "message": "Device Key 不能为空"}
                    ), 400

                # 尝试导入通知系统
                try:
                    if not NOTIFICATION_AVAILABLE:
                        raise ImportError("通知系统不可用")

                    # 创建临时的Bark配置
                    class TempConfig:
                        def __init__(self):
                            self.bark_enabled = True
                            self.bark_url = bark_url
                            self.bark_device_key = bark_device_key
                            self.bark_icon = bark_icon
                            self.bark_action = bark_action

                    # 创建Bark通知提供者并发送测试通知
                    temp_config = TempConfig()
                    bark_provider = BarkNotificationProvider(temp_config)

                    # 创建测试事件
                    test_event = NotificationEvent(
                        id=f"test_bark_{int(time.time())}",
                        title="AI Intervention Agent 测试",
                        message="这是一个 Bark 通知测试，如果您收到此消息，说明配置正确！",
                        trigger=NotificationTrigger.IMMEDIATE,
                        types=[NotificationType.BARK],
                        metadata={"test": True},
                    )

                    # 发送通知
                    success = bark_provider.send(test_event)

                    if success:
                        return jsonify(
                            {
                                "status": "success",
                                "message": "Bark 测试通知发送成功！请检查您的设备",
                            }
                        )
                    else:
                        return jsonify(
                            {
                                "status": "error",
                                "message": "Bark 通知发送失败，请检查配置",
                            }
                        ), 500

                except ImportError as e:
                    logger.error(f"导入通知系统失败: {e}")
                    return jsonify(
                        {"status": "error", "message": "通知系统不可用"}
                    ), 500

            except Exception as e:
                logger.error(f"Bark 测试通知失败: {e}")
                return jsonify(
                    {"status": "error", "message": f"测试失败: {str(e)}"}
                ), 500

        @self.app.route("/api/update-notification-config", methods=["POST"])
        def update_notification_config():
            """更新通知配置的API端点"""
            try:
                # 获取前端设置
                data = request.json or {}

                # 尝试导入配置管理器和通知系统
                try:
                    if not NOTIFICATION_AVAILABLE:
                        raise ImportError("通知系统不可用")

                    # 更新通知管理器配置（不保存到文件，避免双重保存）
                    notification_manager.update_config_without_save(
                        enabled=data.get("enabled", True),
                        web_enabled=data.get("webEnabled", True),
                        web_permission_auto_request=data.get(
                            "autoRequestPermission", True
                        ),
                        sound_enabled=data.get("soundEnabled", True),
                        sound_mute=data.get("soundMute", False),
                        sound_volume=data.get("soundVolume", 80) / 100,
                        mobile_optimized=data.get("mobileOptimized", True),
                        mobile_vibrate=data.get("mobileVibrate", True),
                        bark_enabled=data.get("barkEnabled", False),
                        bark_url=data.get("barkUrl", ""),
                        bark_device_key=data.get("barkDeviceKey", ""),
                        bark_icon=data.get("barkIcon", ""),
                        bark_action=data.get("barkAction", "none"),
                    )

                    # 更新配置文件（统一保存，避免重复）
                    config_mgr = get_config()
                    notification_config = {
                        "enabled": data.get("enabled", True),
                        "web_enabled": data.get("webEnabled", True),
                        "auto_request_permission": data.get(
                            "autoRequestPermission", True
                        ),
                        "sound_enabled": data.get("soundEnabled", True),
                        "sound_mute": data.get("soundMute", False),
                        "sound_volume": data.get("soundVolume", 80),
                        "mobile_optimized": data.get("mobileOptimized", True),
                        "mobile_vibrate": data.get("mobileVibrate", True),
                        "bark_enabled": data.get("barkEnabled", False),
                        "bark_url": data.get("barkUrl", ""),
                        "bark_device_key": data.get("barkDeviceKey", ""),
                        "bark_icon": data.get("barkIcon", ""),
                        "bark_action": data.get("barkAction", "none"),
                    }
                    config_mgr.update_section("notification", notification_config)

                    logger.info("通知配置已更新到配置文件和内存")
                    return jsonify({"status": "success", "message": "通知配置已更新"})

                except ImportError as e:
                    logger.error(f"导入配置系统失败: {e}")
                    return jsonify(
                        {"status": "error", "message": "配置系统不可用"}
                    ), 500

            except Exception as e:
                logger.error(f"更新通知配置失败: {e}")
                return jsonify(
                    {"status": "error", "message": f"更新失败: {str(e)}"}
                ), 500

        @self.app.route("/api/get-notification-config", methods=["GET"])
        def get_notification_config():
            """获取当前通知配置"""
            try:
                config_mgr = get_config()
                notification_config = config_mgr.get_section("notification")

                return jsonify({"status": "success", "config": notification_config})

            except Exception as e:
                logger.error(f"获取通知配置失败: {e}")
                return jsonify(
                    {"status": "error", "message": f"获取配置失败: {str(e)}"}
                ), 500

        # 静态文件路由
        @self.app.route("/fonts/<filename>")
        def serve_fonts(filename):
            """提供字体文件"""
            current_dir = os.path.dirname(os.path.abspath(__file__))
            fonts_dir = os.path.join(current_dir, "fonts")
            return send_from_directory(fonts_dir, filename)

        @self.app.route("/icons/<filename>")
        def serve_icons(filename):
            """提供图标文件"""
            current_dir = os.path.dirname(os.path.abspath(__file__))
            icons_dir = os.path.join(current_dir, "icons")
            return send_from_directory(icons_dir, filename)

        @self.app.route("/sounds/<filename>")
        def serve_sounds(filename):
            """提供音频文件"""
            current_dir = os.path.dirname(os.path.abspath(__file__))
            sounds_dir = os.path.join(current_dir, "sounds")
            return send_from_directory(sounds_dir, filename)

        @self.app.route("/static/css/<filename>")
        def serve_css(filename):
            """提供CSS文件"""
            current_dir = os.path.dirname(os.path.abspath(__file__))
            css_dir = os.path.join(current_dir, "static", "css")
            return send_from_directory(css_dir, filename)

        @self.app.route("/static/js/<filename>")
        def serve_js(filename):
            """提供JavaScript文件"""
            current_dir = os.path.dirname(os.path.abspath(__file__))
            js_dir = os.path.join(current_dir, "static", "js")
            return send_from_directory(js_dir, filename)

        @self.app.route("/favicon.ico")
        def favicon():
            """提供favicon"""
            current_dir = os.path.dirname(os.path.abspath(__file__))
            icons_dir = os.path.join(current_dir, "icons")
            icon_path = os.path.join(icons_dir, "icon.ico")
            logger.debug(f"Favicon请求 - 图标目录: {icons_dir}")
            logger.debug(f"Favicon请求 - 图标文件: {icon_path}")
            logger.debug(f"Favicon请求 - 文件存在: {os.path.exists(icon_path)}")

            # 设置正确的MIME类型和缓存控制
            response = send_from_directory(icons_dir, "icon.ico")
            response.headers["Content-Type"] = "image/x-icon"
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

    def shutdown_server(self):
        """Gracefully shutdown the Flask server"""

        os.kill(os.getpid(), signal.SIGINT)

    def get_html_template(self):
        """读取 HTML 模板文件

        支持通过 importlib.resources 或传统文件路径读取

        Returns:
            str: HTML 模板内容
        """
        try:
            # 优先尝试使用 importlib.resources (Python 3.9+)
            try:
                from importlib import resources
                # 尝试从包中读取资源
                html_content = resources.files('templates').joinpath('web_ui.html').read_text(encoding='utf-8')
            except (ImportError, AttributeError, FileNotFoundError, TypeError):
                # 降级到传统文件路径方式
                # 获取当前文件所在目录
                current_dir = os.path.dirname(os.path.abspath(__file__))
                # 构建模板文件路径
                template_path = os.path.join(current_dir, "templates", "web_ui.html")

                # 如果模板文件不存在，尝试从父目录查找
                if not os.path.exists(template_path):
                    # 可能是在打包后的环境中，尝试从包的安装位置查找
                    import sys
                    for path in sys.path:
                        candidate_path = os.path.join(path, "templates", "web_ui.html")
                        if os.path.exists(candidate_path):
                            template_path = candidate_path
                            break

                # 读取模板文件
                with open(template_path, "r", encoding="utf-8") as f:
                    html_content = f.read()

            # 替换内联CSS为外部CSS文件引用
            css_link = f'<link rel="stylesheet" href="/static/css/main.css" nonce="{self.csp_nonce}">'
            html_content = self._replace_inline_css(html_content, css_link)

            # 替换内联JS为外部JS文件引用
            mathjax_script = f'<script src="/static/js/mathjax-config.js" nonce="{self.csp_nonce}"></script>'
            main_script = (
                f'<script src="/static/js/main.js" nonce="{self.csp_nonce}"></script>'
            )
            html_content = self._replace_inline_js(
                html_content, mathjax_script, main_script
            )

            return html_content
        except FileNotFoundError:
            # 如果模板文件不存在，返回一个基本的错误页面
            return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>模板文件未找到</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 50px;
            background: #f5f5f5;
        }
        .error {
            color: #d32f2f;
            font-size: 18px;
            margin: 20px 0;
        }
    </style>
</head>
<body>
    <h1>模板文件未找到</h1>
    <div class="error">无法找到 templates/web_ui.html 文件</div>
    <p>请确保模板文件存在于正确的位置。</p>
</body>
</html>
            """
        except Exception as e:
            # 其他读取错误
            return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>模板加载错误</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 50px;
            background: #f5f5f5;
        }}
        .error {{
            color: #d32f2f;
            font-size: 18px;
            margin: 20px 0;
        }}
    </style>
</head>
<body>
    <h1>模板加载错误</h1>
    <div class="error">加载模板文件时发生错误: {str(e)}</div>
    <p>请检查模板文件是否正确。</p>
</body>
</html>
            """

    def update_content(
        self,
        new_prompt: str,
        new_options: Optional[List[str]] = None,
        new_task_id: Optional[str] = None,
    ):
        """更新页面内容"""
        self.current_prompt = new_prompt
        self.current_options = new_options if new_options is not None else []
        self.current_task_id = new_task_id
        self.has_content = bool(new_prompt)
        if new_prompt:
            logger.info(f"📝 内容已更新: {new_prompt[:50]}... (task_id: {new_task_id})")
        else:
            logger.info("📝 内容已清空，显示无有效内容页面")

    def _replace_inline_css(self, html_content: str, css_link: str) -> str:
        """替换内联CSS为外部CSS文件引用"""

        # 匹配<style>标签及其内容
        style_pattern = r"<style>.*?</style>"
        # 替换为外部CSS链接
        return re.sub(style_pattern, css_link, html_content, flags=re.DOTALL)

    def _replace_inline_js(
        self, html_content: str, mathjax_script: str, main_script: str
    ) -> str:
        """替换内联JavaScript为外部JS文件引用"""

        # 替换MathJax配置脚本（第一个<script>标签）
        mathjax_pattern = r"<script>\s*window\.MathJax\s*=.*?</script>"
        html_content = re.sub(
            mathjax_pattern, mathjax_script, html_content, flags=re.DOTALL
        )

        # 替换主要JavaScript代码（最后一个大的<script>标签）
        main_js_pattern = r"<script>\s*let config = null.*?</script>"
        html_content = re.sub(
            main_js_pattern, main_script, html_content, flags=re.DOTALL
        )

        return html_content

    def _load_network_security_config(self) -> Dict:
        """加载网络安全配置

        Returns:
            Dict: 网络安全配置字典，包含允许的网络、黑名单等
        """
        try:
            config_mgr = get_config()
            return config_mgr.get_section("network_security")
        except Exception as e:
            logger.warning(f"无法加载网络安全配置，使用默认配置: {e}")
            return {
                "bind_interface": "0.0.0.0",
                "allowed_networks": [
                    "127.0.0.0/8",
                    "::1/128",
                    "192.168.0.0/16",
                    "10.0.0.0/8",
                    "172.16.0.0/12",
                ],
                "blocked_ips": [],
                "enable_access_control": True,
            }

    def _is_ip_allowed(self, client_ip: str) -> bool:
        """检查 IP 是否被允许访问

        Args:
            client_ip: 客户端IP地址

        Returns:
            bool: 是否允许访问
        """
        if not self.network_security_config.get("enable_access_control", True):
            return True

        try:
            client_addr = ip_address(client_ip)

            # 检查黑名单
            blocked_ips = self.network_security_config.get("blocked_ips", [])
            for blocked_ip in blocked_ips:
                if str(client_addr) == blocked_ip:
                    logger.warning(f"IP {client_ip} 在黑名单中，拒绝访问")
                    return False

            # 检查白名单网络
            allowed_networks = self.network_security_config.get(
                "allowed_networks", ["127.0.0.0/8", "::1/128"]
            )
            for network_str in allowed_networks:
                try:
                    if "/" in network_str:
                        # 网络段
                        if client_addr.version == 4:
                            network = IPv4Network(network_str, strict=False)
                        else:
                            network = IPv6Network(network_str, strict=False)
                        if client_addr in network:
                            return True
                    else:
                        # 单个IP
                        if str(client_addr) == network_str:
                            return True
                except (AddressValueError, ValueError) as e:
                    logger.warning(f"无效的网络配置 {network_str}: {e}")
                    continue

            logger.warning(f"IP {client_ip} 不在允许的网络范围内，拒绝访问")
            return False

        except AddressValueError as e:
            logger.warning(f"无效的IP地址 {client_ip}: {e}")
            return False

    def run(self) -> Dict[str, str]:
        """启动 Web 服务器并等待用户反馈

        Returns:
            Dict[str, str]: 用户反馈结果，包含输入文本、选项和图片
        """
        print("\n🌐 Web反馈界面已启动")
        print(f"📍 请在浏览器中打开: http://{self.host}:{self.port}")
        if self.host == "0.0.0.0":
            print(
                f"🔗 SSH端口转发命令: ssh -L {self.port}:localhost:{self.port} user@remote_server"
            )

        print("🔄 页面将保持打开，可实时更新内容")
        print()

        try:
            self.app.run(
                host=self.host, port=self.port, debug=False, use_reloader=False
            )
        except KeyboardInterrupt:
            pass

        return self.feedback_result or {
            "user_input": "",
            "selected_options": [],
            "images": [],
        }


def web_feedback_ui(
    prompt: str,
    predefined_options: Optional[List[str]] = None,
    task_id: Optional[str] = None,
    auto_resubmit_timeout: int = 290,
    output_file: Optional[str] = None,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> Optional[Dict[str, str]]:
    """启动 Web 版反馈界面

    Args:
        prompt: 提示文本
        predefined_options: 预定义选项列表
        task_id: 任务ID
        auto_resubmit_timeout: 自动重新提交超时时间（秒）
        output_file: 输出文件路径（可选）
        host: 绑定主机地址
        port: 绑定端口

    Returns:
        Optional[Dict[str, str]]: 用户反馈结果
    """
    ui = WebFeedbackUI(
        prompt, predefined_options, task_id, auto_resubmit_timeout, host, port
    )
    result = ui.run()

    if output_file and result:
        # 确保目录存在
        os.makedirs(
            os.path.dirname(output_file) if os.path.dirname(output_file) else ".",
            exist_ok=True,
        )
        # 保存结果到输出文件
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return None

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行Web版反馈界面")
    parser.add_argument(
        "--prompt", default="我已经实现了您请求的更改。", help="向用户显示的提示信息"
    )
    parser.add_argument(
        "--predefined-options", default="", help="预定义选项列表，用|||分隔"
    )
    parser.add_argument("--task-id", default=None, help="任务标识符")
    parser.add_argument(
        "--auto-resubmit-timeout",
        type=int,
        default=290,
        help="自动重新提交超时时间(秒)，0表示禁用",
    )
    parser.add_argument("--output-file", help="将反馈结果保存为JSON文件的路径")
    parser.add_argument("--host", default="0.0.0.0", help="Web服务器监听地址")
    parser.add_argument("--port", type=int, default=8080, help="Web服务器监听端口")
    args = parser.parse_args()

    predefined_options = (
        [opt for opt in args.predefined_options.split("|||") if opt]
        if args.predefined_options
        else None
    )

    result = web_feedback_ui(
        prompt=args.prompt,
        predefined_options=predefined_options,
        task_id=args.task_id,
        auto_resubmit_timeout=args.auto_resubmit_timeout,
        output_file=args.output_file,
        host=args.host,
        port=args.port,
    )
    if result:
        user_input = result.get("user_input", "")
        selected_options = result.get("selected_options", [])
        images = result.get("images", [])

        print("\n收到反馈:")
        if selected_options:
            print(f"选择的选项: {', '.join(selected_options)}")
        if user_input:
            print(f"用户输入: {user_input}")
        if images:
            print(f"包含 {len(images)} 张图片")
    sys.exit(0)
