"""Web 反馈界面 - Flask Web UI，支持多任务、文件上传、通知、安全机制。"""

__all__ = [
    "AUTO_RESUBMIT_TIMEOUT_MAX",
    "AUTO_RESUBMIT_TIMEOUT_MIN",
    "DEFAULT_ALLOWED_NETWORKS",
    "MDNS_DEFAULT_HOSTNAME",
    "MDNS_SERVICE_TYPE_HTTP",
    "VALID_BIND_INTERFACES",
    "WebFeedbackUI",
    "_get_default_route_ipv4",
    "_is_probably_virtual_interface",
    "_list_non_loopback_ipv4",
    "_sync_existing_tasks_timeout_from_config",
    "_sync_network_security_from_config",
    "detect_best_publish_ipv4",
    "normalize_mdns_hostname",
    "validate_allowed_networks",
    "validate_bind_interface",
    "validate_blocked_ips",
    "validate_network_cidr",
    "validate_network_security_config",
]

import argparse
import json
import os
import re
import signal
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import markdown
from flasgger import Swagger
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
)
from flask.typing import ResponseReturnValue
from flask_compress import Compress
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config_manager import get_config
from enhanced_logging import EnhancedLogger
from i18n import msg
from protocol import get_capabilities, get_server_clock
from server import get_task_queue
from server_config import (
    AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    AUTO_RESUBMIT_TIMEOUT_MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN,
)
from shared_types import FeedbackResult
from web_ui_config_sync import (
    _ensure_feedback_timeout_hot_reload_callback_registered,
    _ensure_network_security_hot_reload_callback_registered,
    _get_default_auto_resubmit_timeout_from_config,
    _sync_existing_tasks_timeout_from_config,
    _sync_network_security_from_config,
)
from web_ui_mdns import MdnsMixin
from web_ui_mdns_utils import (
    MDNS_DEFAULT_HOSTNAME,
    MDNS_SERVICE_TYPE_HTTP,
    _get_default_route_ipv4,
    _is_probably_virtual_interface,
    _list_non_loopback_ipv4,
    detect_best_publish_ipv4,
    normalize_mdns_hostname,
)
from web_ui_routes import (
    FeedbackRoutesMixin,
    NotificationRoutesMixin,
    StaticRoutesMixin,
    SystemRoutesMixin,
    TaskRoutesMixin,
)
from web_ui_security import SecurityMixin
from web_ui_validators import (
    DEFAULT_ALLOWED_NETWORKS,
    VALID_BIND_INTERFACES,
    validate_allowed_networks,
    validate_auto_resubmit_timeout,
    validate_bind_interface,
    validate_blocked_ips,
    validate_network_cidr,
    validate_network_security_config,
)

logger = EnhancedLogger(__name__)

# ============================================================================
# 版本号和项目信息
# ============================================================================

# GitHub 仓库地址
GITHUB_URL = "https://github.com/XIADENGMA/ai-intervention-agent"


@lru_cache(maxsize=1)
def get_project_version() -> str:
    """从 pyproject.toml 读取版本号，缓存结果"""
    version = "unknown"

    try:
        # 获取 pyproject.toml 路径
        current_dir = Path(__file__).resolve().parent
        pyproject_path = current_dir / "pyproject.toml"

        if pyproject_path.exists():
            try:
                import tomllib

                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                raw_version: Any = data.get("project", {}).get("version", "unknown")
                version = (
                    raw_version if isinstance(raw_version, str) else str(raw_version)
                )
            except Exception:
                # 回退到正则表达式
                with open(pyproject_path, encoding="utf-8") as f:
                    content = f.read()
                match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    version = match.group(1)
    except Exception as e:
        logger.warning(f"读取版本号失败: {e}", exc_info=True)

    return version


# ============================================================================
# 模块级状态（配置热更新回调使用，web_ui_config_sync 通过 lazy import 访问）
# ============================================================================

_FEEDBACK_TIMEOUT_CALLBACK_REGISTERED: bool = False
_LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT: int | None = None
_CURRENT_WEB_UI_INSTANCE: Any | None = None
_NETWORK_SECURITY_CALLBACK_REGISTERED: bool = False
_NETWORK_SECURITY_CALLBACK_LOCK = threading.Lock()
_FEEDBACK_TIMEOUT_CALLBACK_LOCK = threading.RLock()


class WebFeedbackUI(
    SecurityMixin,
    MdnsMixin,
    TaskRoutesMixin,
    FeedbackRoutesMixin,
    NotificationRoutesMixin,
    StaticRoutesMixin,
    SystemRoutesMixin,
):
    """Web 反馈界面核心类 - Flask 应用、安全策略、API 路由、任务管理。

    功能通过 Mixin 组织：
    - SecurityMixin          — IP 访问控制、CSP、安全头（web_ui_security.py）
    - MdnsMixin              — mDNS/Zeroconf 服务发布（web_ui_mdns.py）
    - TaskRoutesMixin        — 任务 CRUD（5 个路由）
    - FeedbackRoutesMixin    — 反馈提交/查询（3 个路由）
    - NotificationRoutesMixin — 通知配置/触发（5 个路由）
    - StaticRoutesMixin      — 静态资源（8 个路由）
    - SystemRoutesMixin      — 系统集成（用 IDE 打开配置文件等）
    核心路由（index / config / health / close）保留在本类。
    """

    def __init__(
        self,
        prompt: str,
        predefined_options: list[str] | None = None,
        task_id: str | None = None,
        auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        """初始化 Flask 应用、安全策略、路由"""
        self.prompt = prompt
        self.predefined_options = predefined_options or []
        self.task_id = task_id
        self.auto_resubmit_timeout = auto_resubmit_timeout
        self.host = host
        self.port = port
        # mDNS / DNS-SD 状态（仅在 run() 真正启动服务时启用）
        self._mdns_zeroconf: Any | None = None
        self._mdns_service_info: Any | None = None
        self._mdns_hostname: str | None = None
        self._mdns_publish_ip: str | None = None
        self.feedback_result: FeedbackResult | None = None
        self._project_root: Path = Path(__file__).resolve().parent
        self.current_prompt = prompt if prompt else ""
        self.current_options = predefined_options or []
        self.current_task_id = task_id
        self.current_auto_resubmit_timeout = auto_resubmit_timeout
        # 单任务模式下：current_auto_resubmit_timeout 是否为“显式指定”（/api/update 传入）
        # - False：认为来自配置默认值，应随配置热更新
        # - True：认为调用方显式指定，不随全局配置变化
        self._single_task_timeout_explicit = False
        self.has_content = bool(prompt)
        self.initial_empty = not bool(prompt)
        # WebFeedbackUI 会被轮询与提交并发访问（Flask 默认 threaded），用锁保护共享状态
        self._state_lock = threading.RLock()
        self.app = Flask(__name__)
        _cors_origins: list[str | re.Pattern[str]] = [
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
            re.compile(r"^vscode-webview://"),
        ]
        if host not in ("127.0.0.1", "localhost", "::1"):
            _cors_origins.append(f"http://{host}:{port}")
        CORS(
            self.app,
            origins=_cors_origins,
            supports_credentials=False,
        )

        # OpenAPI / Swagger 文档（访问 /apidocs 查看交互式 API 文档）
        self.app.config["SWAGGER"] = {
            "title": "AI Intervention Agent API",
            "version": get_project_version(),
            "description": "AI 交互反馈代理的 RESTful API，支持多任务管理、反馈提交、通知配置等功能。",
            "termsOfService": "",
            "specs_route": "/apidocs/",
        }
        Swagger(
            self.app,
            template={
                "info": {
                    "title": "AI Intervention Agent API",
                    "version": get_project_version(),
                    "description": "AI 交互反馈代理的 RESTful API",
                    "contact": {"url": GITHUB_URL},
                    "license": {"name": "MIT"},
                },
                "basePath": "/",
                "schemes": ["http"],
                "tags": [
                    {
                        "name": "Tasks",
                        "description": "任务管理（创建、查询、激活、提交）",
                    },
                    {"name": "Feedback", "description": "反馈提交与查询"},
                    {"name": "Notification", "description": "通知配置与测试"},
                    {"name": "System", "description": "系统状态与配置"},
                ],
            },
        )

        # 【热更新】注册配置变更回调：让运行中的任务倒计时也能跟随配置更新
        _ensure_feedback_timeout_hot_reload_callback_registered()
        # 记录当前实例（用于单任务模式热更新兜底）
        global _CURRENT_WEB_UI_INSTANCE
        _CURRENT_WEB_UI_INSTANCE = self

        # ==================================================================
        # Gzip 压缩配置
        # ==================================================================
        # 启用响应压缩，显著减少传输大小：
        # - CSS: ~85% 压缩率（232KB → ~35KB）
        # - JavaScript: ~70% 压缩率
        # - JSON: ~90% 压缩率（包括 Lottie 动画）
        #
        # 配置项：
        # - COMPRESS_MIMETYPES: 压缩的 MIME 类型
        # - COMPRESS_LEVEL: 压缩级别（1-9，6 为平衡点）
        # - COMPRESS_MIN_SIZE: 最小压缩阈值（500 字节以下不压缩）
        # ==================================================================
        self.app.config["COMPRESS_MIMETYPES"] = [
            "text/html",
            "text/css",
            "text/xml",
            "text/javascript",
            "application/json",
            "application/javascript",
            "application/x-javascript",
            "application/xml",
            "application/xml+rss",
            "image/svg+xml",
        ]
        self.app.config["COMPRESS_LEVEL"] = 6  # 压缩级别（平衡压缩率和 CPU）
        self.app.config["COMPRESS_MIN_SIZE"] = 500  # 小于 500 字节不压缩
        Compress(self.app)

        self.network_security_config = self._load_network_security_config()
        # 【热更新】network_security（allowed_networks/blocked_ips/access_control_enabled）也应随配置文件变化生效
        _ensure_network_security_hot_reload_callback_registered()

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

    def setup_markdown(self) -> None:
        """设置Markdown渲染器和扩展

        功能说明：
            初始化Python-Markdown实例，配置渲染扩展和代码高亮样式。

        启用的扩展：
            - fenced_code：围栏代码块（```语法）
            - codehilite：代码语法高亮（基于Pygments）
            - tables：表格支持（GFM风格）
            - toc：自动生成目录
            - nl2br：换行符转<br>标签
            - attr_list：元素属性语法
            - def_list：定义列表
            - abbr：缩写词
            - footnotes：脚注支持
            - md_in_html：HTML中嵌入Markdown

        代码高亮配置：
            - css_class: highlight（用于CSS样式）
            - use_pygments: True（使用Pygments进行语法高亮）
            - noclasses: True（内联样式，无需外部CSS）
            - pygments_style: monokai（Monokai配色方案）
            - guess_lang: True（自动检测代码语言）
            - linenums: False（禁用行号）

        副作用：
            - 创建self.md实例（Markdown渲染器）

        注意事项：
            - Pygments需要额外安装（pip install pygments）
            - 内联样式会增加HTML体积，但避免CSP问题
            - 扩展顺序可能影响渲染结果
        """
        self._md_lock = threading.Lock()
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
        """渲染Markdown文本为HTML

        功能说明：
            将Markdown格式的文本转换为HTML，应用代码高亮、表格、LaTeX等扩展。

        参数说明：
            text: Markdown格式的文本字符串（支持GFM风格）

        返回值：
            str: 渲染后的HTML字符串（已应用语法高亮和格式化）

        处理流程：
            1. 检查文本是否为空
            2. 重置 Markdown 实例状态（避免脚注编号、TOC 跨渲染泄漏）
            3. 调用self.md.convert()进行Markdown到HTML转换
            4. 应用所有启用的扩展（代码高亮、表格、脚注等）
            5. 返回渲染后的HTML

        注意事项：
            - 空文本返回空字符串（避免None错误）
            - HTML未进行额外的XSS过滤，依赖Markdown库的安全性
        """
        if not text:
            return ""
        with self._md_lock:
            self.md.reset()
            return str(self.md.convert(text))

    def setup_routes(self) -> None:
        """注册所有API路由和静态资源路由

        功能说明：
            注册Flask路由处理器，包括主页面、API端点、静态资源服务。

        路由分类：
            **页面路由**：
                - GET / - 主页面HTML

            **任务管理API**：
                - GET  /api/config              - 获取当前任务配置
                - GET  /api/tasks               - 获取所有任务列表
                - POST /api/tasks               - 创建新任务
                - GET  /api/tasks/<id>          - 获取单个任务详情
                - POST /api/tasks/<id>/activate - 激活指定任务
                - POST /api/tasks/<id>/submit   - 提交任务反馈

            **反馈API**：
                - POST /api/submit              - 提交反馈（通用端点）
                - POST /api/update              - 更新页面内容
                - GET  /api/feedback            - 获取反馈结果

            **系统API**：
                - GET  /api/health              - 健康检查
                - POST /api/close               - 关闭服务器

            **通知API**：
                - POST /api/test-bark                - 测试Bark通知
                - POST /api/notify-new-tasks         - 新任务 Bark 触发（兼容第三方外部调用；内部 UI 不再调用，由 MCP 主进程统一推送）
                - POST /api/update-notification-config - 更新通知配置
                - GET  /api/get-notification-config  - 获取通知配置

            **静态资源**：
                - /static/css/<filename>        - CSS文件
                - /static/js/<filename>         - JavaScript文件
                - /fonts/<filename>             - 字体文件
                - /icons/<filename>             - 图标文件
                - /sounds/<filename>            - 音频文件
                - /favicon.ico                  - 网站图标

        频率限制：
            - 默认：60次/分钟，10次/秒（全局）
            - /api/config：300次/分钟（轮询高频场景）
            - /api/tasks（GET）：300次/分钟（轮询高频场景）
            - /api/submit：60次/分钟（防止恶意提交）
            - /api/tasks（POST）：60次/分钟（防止任务创建滥用）

        注意事项：
            - 所有路由处理器定义为内部函数，通过闭包访问self
            - limiter装饰器需要放在路由装饰器之后
            - 静态资源路由使用send_from_directory安全地提供文件
        """

        @self.app.route("/")
        def index() -> ResponseReturnValue:
            """主页面路由：通过 Jinja2 原生渲染 web_ui.html 模板。"""
            return render_template("web_ui.html", **self._get_template_context())

        @self.app.route("/api/config")
        @self.limiter.limit("300 per minute")
        def get_api_config() -> ResponseReturnValue:
            """获取当前激活任务的配置信息
            ---
            tags:
              - System
            responses:
              200:
                description: 当前任务配置
                schema:
                  type: object
                  properties:
                    prompt:
                      type: string
                      description: 提示文本（Markdown 原文）
                    prompt_html:
                      type: string
                      description: 渲染后的 HTML
                    predefined_options:
                      type: array
                      items:
                        type: string
                      description: 预定义选项列表
                    task_id:
                      type: string
                    auto_resubmit_timeout:
                      type: number
                      description: 超时时间（秒）
                    has_content:
                      type: boolean
                    initial_empty:
                      type: boolean
              500:
                description: 服务器内部错误
            """
            try:
                # 从 TOML 配置读取语言设置，随每次响应返回给前端（插件/Web 通用）
                try:
                    ui_lang = get_config().get_section("web_ui").get("language", "auto")
                except Exception:
                    ui_lang = "auto"

                # 优先从 TaskQueue 获取激活任务
                task_queue = get_task_queue()
                active_task = task_queue.get_active_task()

                if active_task:
                    # 使用TaskQueue中的激活任务
                    # 返回剩余时间而非固定超时，解决刷新页面后倒计时重置的问题
                    # 【优化】添加 server_time 和 deadline，让前端可以基于服务器时间计算倒计时
                    return jsonify(
                        {
                            "prompt": active_task.prompt,
                            "prompt_html": self.render_markdown(active_task.prompt),
                            "predefined_options": active_task.predefined_options,
                            "task_id": active_task.task_id,
                            "auto_resubmit_timeout": active_task.auto_resubmit_timeout,
                            "remaining_time": active_task.get_remaining_time(),
                            "server_time": time.time(),
                            "deadline": active_task.created_at.timestamp()
                            + active_task.auto_resubmit_timeout,
                            "language": ui_lang,
                            "persistent": True,
                            "has_content": True,
                            "initial_empty": False,
                        }
                    )
                else:
                    # 如果没有激活任务，检查是否有 pending 任务
                    all_tasks = task_queue.get_all_tasks()
                    # 过滤出未完成的任务（排除 completed 状态）
                    incomplete_tasks = [t for t in all_tasks if t.status != "completed"]

                    if incomplete_tasks:
                        # 有未完成任务存在，激活第一个
                        first_task = incomplete_tasks[0]
                        task_queue.set_active_task(first_task.task_id)
                        logger.info(f"自动激活第一个pending任务: {first_task.task_id}")

                        # 【优化】添加 server_time 和 deadline，让前端可以基于服务器时间计算倒计时
                        return jsonify(
                            {
                                "prompt": first_task.prompt,
                                "prompt_html": self.render_markdown(first_task.prompt),
                                "predefined_options": first_task.predefined_options,
                                "task_id": first_task.task_id,
                                "auto_resubmit_timeout": first_task.auto_resubmit_timeout,
                                "remaining_time": first_task.get_remaining_time(),
                                "server_time": time.time(),
                                "deadline": first_task.created_at.timestamp()
                                + first_task.auto_resubmit_timeout,
                                "language": ui_lang,
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
                                "language": ui_lang,
                                "persistent": True,
                                "has_content": False,
                                "initial_empty": False,
                            }
                        )

                    # 回退到旧的单任务模式
                    # 单任务模式没有创建时间，remaining_time 等于 auto_resubmit_timeout
                    # 【热更新增强】若未显式指定 timeout，则使用配置文件的默认值（运行中修改可立即生效）
                    timeout_explicit = bool(
                        getattr(self, "_single_task_timeout_explicit", True)
                    )
                    with self._state_lock:
                        effective_timeout = int(self.current_auto_resubmit_timeout)
                        prompt_snapshot = str(self.current_prompt)
                        options_snapshot = list(self.current_options)
                        task_id_snapshot = self.current_task_id
                        has_content_snapshot = bool(self.has_content)
                        initial_empty_snapshot = bool(self.initial_empty)

                    if not timeout_explicit:
                        try:
                            effective_timeout = (
                                _get_default_auto_resubmit_timeout_from_config()
                            )
                        except Exception:
                            # 配置读取失败不影响主流程，沿用当前值
                            pass
                        with self._state_lock:
                            # 保持实例状态同步，便于其他逻辑复用
                            self.current_auto_resubmit_timeout = effective_timeout

                    prompt_html = ""
                    if has_content_snapshot:
                        try:
                            prompt_html = self.render_markdown(prompt_snapshot)
                        except Exception as e:
                            logger.warning(
                                f"/api/config prompt 渲染失败: {e}", exc_info=True
                            )
                            prompt_html = ""
                    return jsonify(
                        {
                            "prompt": prompt_snapshot,
                            "prompt_html": prompt_html,
                            "predefined_options": options_snapshot,
                            "task_id": task_id_snapshot,
                            "auto_resubmit_timeout": effective_timeout,
                            "remaining_time": effective_timeout,
                            "language": ui_lang,
                            "persistent": True,
                            "has_content": has_content_snapshot,
                            "initial_empty": initial_empty_snapshot,
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
                        "language": "auto",
                        "persistent": True,
                        "has_content": False,
                        "initial_empty": True,
                    }
                ), 500

        @self.app.route("/api/close", methods=["POST"])
        def close_interface() -> ResponseReturnValue:
            """优雅关闭 Flask 服务器
            ---
            tags:
              - System
            responses:
              200:
                description: 关闭指令已接受
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: success
                    message:
                      type: string
            """
            threading.Timer(0.5, self.shutdown_server).start()
            return jsonify({"status": "success", "message": msg("server.shuttingDown")})

        @self.app.route("/api/health", methods=["GET"])
        def health_check() -> ResponseReturnValue:
            """健康检查端点
            ---
            tags:
              - System
            responses:
              200:
                description: 服务正常运行
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      example: ok
            """
            return jsonify({"status": "ok"})

        @self.app.route("/api/capabilities", methods=["GET"])
        def capabilities() -> ResponseReturnValue:
            """返回服务器协议版本 / 声明的 features / build_id。

            前端在连接早期调用本端点，用于：
            - 依据 `protocol_version` 决定是否需要兼容模式或提示升级
            - 依据 `features` 决定是否启用某个 UI 入口

            `server_version` 来自 pyproject.toml；`build_id` 若可得则为 git short SHA。
            详见 `protocol.py`。
            ---
            tags:
              - System
            responses:
              200:
                description: 能力声明
                schema:
                  type: object
                  properties:
                    protocol_version:
                      type: string
                      example: "1.0.0"
                    server_version:
                      type: string
                      example: "1.5.18"
                    build_id:
                      type: string
                      example: ""
                    features:
                      type: object
            """
            build_id = os.environ.get("AIIA_BUILD_ID", "")
            return jsonify(get_capabilities(get_project_version(), build_id=build_id))

        @self.app.route("/api/time", methods=["GET"])
        def server_time() -> ResponseReturnValue:
            """返回服务器实时时钟与单调时钟（毫秒）。

            客户端用于 wall clock 对齐，避免前后端时间漂移导致 TTL / 动画错乱。
            详见 `protocol.py::get_server_clock`。
            ---
            tags:
              - System
            responses:
              200:
                description: 服务器时钟
                schema:
                  type: object
                  properties:
                    time_ms:
                      type: integer
                    monotonic_ms:
                      type: integer
            """
            return jsonify(get_server_clock())

        @self.app.route("/api/update-language", methods=["POST"])
        @self.limiter.limit("30 per minute")
        def update_language() -> ResponseReturnValue:
            """更新界面语言配置并持久化到 config.toml"""
            try:
                data = request.json or {}
                lang = str(data.get("language", "auto")).strip()

                supported = ("auto", "en", "zh-CN")
                if lang not in supported:
                    return jsonify(
                        {"status": "error", "message": f"不支持的语言: {lang}"}
                    ), 400

                config_mgr = get_config()
                config_mgr.update_section("web_ui", {"language": lang})

                return jsonify({"status": "success", "language": lang})
            except Exception as e:
                logger.error(f"更新语言配置失败: {e}", exc_info=True)
                return jsonify({"status": "error", "message": str(e)}), 500

        # 路由通过 Mixin 注册（各 Mixin 定义在 web_ui_routes/ 下）
        self._setup_task_routes()
        self._setup_feedback_routes()
        self._setup_notification_routes()
        self._setup_static_routes()
        self._setup_system_routes()

        # 模板缺失降级：返回简洁 HTML 错误页（无外部依赖）
        from jinja2 import TemplateNotFound

        @self.app.errorhandler(TemplateNotFound)
        def handle_template_not_found(
            exc: TemplateNotFound,
        ) -> ResponseReturnValue:
            logger.error("Jinja2 模板缺失: %s", exc)
            from markupsafe import escape

            return (
                '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
                "<title>模板文件未找到</title></head><body>"
                "<h1>模板文件未找到</h1>"
                f"<p>无法找到 {escape(str(exc))} 文件，请确保模板文件存在。</p>"
                "</body></html>",
                500,
            )

        # 全局异常处理：将 AIAgentError 统一转为标准 JSON 错误响应
        from exceptions import AIAgentError

        @self.app.errorhandler(AIAgentError)
        def handle_agent_error(exc: AIAgentError) -> ResponseReturnValue:
            status = 500
            if exc.code == "not_found":
                status = 404
            elif exc.code == "validation":
                status = 400
            elif exc.code == "timeout":
                status = 504
            body: dict[str, Any] = {"success": False, "error": str(exc)}
            if exc.code:
                body["code"] = exc.code
            logger.warning(f"AIAgentError ({exc.code}): {exc}", exc_info=True)
            return jsonify(body), status

    def shutdown_server(self) -> None:
        """优雅关闭Flask服务器

        功能说明：
            向当前进程发送SIGINT信号，触发Flask服务器的优雅关闭流程。

        处理逻辑：
            1. 获取当前进程PID（os.getpid()）
            2. 发送SIGINT信号（os.kill()）
            3. Flask接收信号后执行关闭流程

        副作用：
            - 当前进程收到SIGINT信号
            - Flask服务器停止接受新请求
            - 等待现有请求处理完毕后退出

        注意事项：
            - SIGINT相当于Ctrl+C信号
            - 关闭是全局的，影响所有客户端连接
            - 适用于单次任务完成后的自动关闭场景
            - 多任务模式下应避免调用此方法
        """

        os.kill(os.getpid(), signal.SIGINT)

    def _get_template_context(self) -> dict[str, str]:
        """构建 Jinja2 模板渲染上下文。

        返回 render_template('web_ui.html', **ctx) 所需的全部变量：
        csp_nonce / version / github_url / language / css_version /
        multi_task_version / theme_version / app_version。
        """
        try:
            ui_lang = get_config().get_section("web_ui").get("language", "auto")
        except Exception:
            ui_lang = "auto"

        # HTML 根 lang 属性："auto" 时退化为 "en"（客户端 i18n 会在 DOM 上再改 <html lang>）。
        # 必须是有效 BCP-47 tag，避免 <html lang="auto"> 导致屏幕阅读器判断错乱。
        html_lang = ui_lang if ui_lang in ("en", "zh-CN") else "en"

        # HTML 根 dir 属性：现仅支持 en / zh-CN（都 LTR）。显式注入 "ltr" 而不是省略，
        # 是为了：(1) 无障碍工具拿到明确方向信号；(2) 未来扩 RTL 语言时 setLang()
        # 走同一套逻辑即可。对应 static/js/i18n.js::langToDir 白名单。
        _RTL_LANG_PREFIXES = (
            "ar",
            "fa",
            "he",
            "iw",
            "ps",
            "ur",
            "yi",
            "ug",
            "ckb",
            "ku",
            "dv",
            "sd",
        )
        html_dir = (
            "rtl"
            if any(
                html_lang.lower().startswith(p + "-") or html_lang.lower() == p
                for p in _RTL_LANG_PREFIXES
            )
            else "ltr"
        )

        static_dir = Path(__file__).resolve().parent / "static"
        return {
            "csp_nonce": self._get_csp_nonce(),
            "version": get_project_version(),
            "github_url": GITHUB_URL,
            "language": ui_lang,
            "html_lang": html_lang,
            "html_dir": html_dir,
            "css_version": self._get_file_version(static_dir / "css" / "main.css"),
            "multi_task_version": self._get_file_version(
                static_dir / "js" / "multi_task.js"
            ),
            "theme_version": self._get_file_version(static_dir / "js" / "theme.js"),
            "app_version": self._get_file_version(static_dir / "js" / "app.js"),
        }

    def update_content(
        self,
        new_prompt: str,
        new_options: list[str] | None = None,
        new_task_id: str | None = None,
    ) -> None:
        """更新页面内容（单任务模式，实例方法）

        功能说明：
            更新当前任务的prompt、选项、任务ID，用于单任务模式下的内容动态更新。

        参数说明：
            new_prompt: 新的提示文本（Markdown格式）
            new_options: 新的预定义选项列表（可选，默认为空列表）
            new_task_id: 新的任务ID（可选）

        处理逻辑：
            1. 更新self.current_prompt
            2. 更新self.current_options（None转为空列表）
            3. 更新self.current_task_id
            4. 更新self.has_content标志
            5. 记录日志（INFO级别）

        副作用：
            - 修改self.current_prompt、current_options、current_task_id
            - 更新self.has_content标志
            - 记录日志到enhanced_logging

        注意事项：
            - 仅更新实例属性，不修改self.feedback_result
            - 适用于单任务模式，多任务模式请使用TaskQueue API
            - 前端需通过/api/config轮询获取更新后的内容
        """
        with self._state_lock:
            self.current_prompt = new_prompt
            self.current_options = new_options if new_options is not None else []
            self.current_task_id = new_task_id
            self.has_content = bool(new_prompt)
        if new_prompt:
            logger.info(f"内容已更新: {new_prompt[:50]}... (task_id: {new_task_id})")
        else:
            logger.info("内容已清空，显示无有效内容页面")

    def _get_minified_file(
        self, directory: str | Path, filename: str, extension: str
    ) -> str:
        """获取压缩版本的文件名（如存在）

        功能说明：
            自动检测并优先使用压缩版本的静态资源文件。

        参数说明：
            directory: 文件所在目录的绝对路径
            filename: 原始请求的文件名
            extension: 文件扩展名（如 ".js" 或 ".css"）

        返回值：
            str: 实际使用的文件名（压缩版本或原始版本）

        处理逻辑：
            1. 如果请求的已是 .min.* 文件，直接返回
            2. 检查对应的 .min.* 文件是否存在
            3. 如存在压缩版本，优先使用压缩版本
            4. 否则返回原始文件名

        示例：
            - 请求 multi_task.js，若 multi_task.min.js 存在，则返回 multi_task.min.js
            - 请求 multi_task.min.js，直接返回 multi_task.min.js
            - 请求 prism-xxx.js（外部库），直接返回原文件
        """
        # 已经是压缩版本，直接返回
        if f".min{extension}" in filename:
            return filename

        # 构建压缩版本的文件名
        base_name = filename.replace(extension, "")
        minified_name = f"{base_name}.min{extension}"
        dir_path = Path(directory)
        minified_path = dir_path / minified_name

        # 检查压缩版本是否存在
        if minified_path.exists():
            return minified_name

        # 压缩版本不存在，返回原始文件名
        return filename

    def _get_file_version(self, file_path: str | Path) -> str:
        """获取文件版本号（基于修改时间）

        功能说明：
            根据文件的最后修改时间生成版本号，用于静态资源缓存控制。
            每次文件更新后，版本号会自动变化，浏览器会获取新版本。

        参数说明：
            file_path: 文件的完整路径

        返回值：
            str: 版本号（Unix 时间戳的后 8 位，确保唯一性）

        处理逻辑：
            1. 获取文件的最后修改时间
            2. 转换为 Unix 时间戳
            3. 取后 8 位作为版本号（避免过长）

        异常处理：
            - 文件不存在：返回默认版本号 "1"

        注意事项：
            - 版本号会在文件每次修改后自动更新
            - 用于解决浏览器缓存旧版本 JS/CSS 的问题
        """
        try:
            mtime = Path(file_path).stat().st_mtime
            # 使用时间戳的后 8 位作为版本号
            return str(int(mtime))[-8:]
        except OSError:
            return "1"

    def run(self) -> FeedbackResult:
        """启动Flask Web服务器并等待用户反馈

        功能说明：
            启动Flask开发服务器，监听指定的host和port，等待用户提交反馈。

        返回值：
            FeedbackResult: 用户反馈结果，包含以下字段：
                - user_input: 用户输入文本
                - selected_options: 选中的选项数组
                - images: 图片数组（Base64编码）

        处理逻辑：
            1. 打印启动信息（访问URL、SSH端口转发命令等）
            2. 调用Flask的app.run()启动服务器
            3. 服务器运行直到收到SIGINT信号或调用shutdown_server()
            4. 返回self.feedback_result（若无反馈则返回空字典）

        启动参数：
            - host: self.host（默认"0.0.0.0"）
            - port: self.port（默认8080）
            - debug: False（禁用调试模式）
            - use_reloader: False（禁用自动重载）

        异常处理：
            - KeyboardInterrupt: 捕获Ctrl+C信号，正常退出

        副作用：
            - 阻塞当前线程，直到服务器关闭
            - 打印启动信息到标准输出

        注意事项：
            - 使用Flask开发服务器，不适合生产环境
            - 生产环境建议使用Gunicorn或uWSGI
            - 若self.feedback_result为None，返回空反馈字典
            - 服务器关闭后才返回，适用于单次任务模式
        """
        print("\nWeb反馈界面已启动")
        # 0.0.0.0 是“监听所有网卡”的服务端绑定地址，但并不适合作为浏览器访问地址。
        # 部分浏览器/环境访问 http://0.0.0.0:PORT 时可能出现异常（例如权限/请求失败）。
        if self.host == "0.0.0.0":
            print(f"监听地址: http://{self.host}:{self.port}")
            print(f"本机访问（推荐）: http://127.0.0.1:{self.port}")
            print(f"本机访问（推荐）: http://localhost:{self.port}")
            print(
                f"SSH端口转发命令: ssh -L {self.port}:localhost:{self.port} user@remote_server"
            )
        else:
            print(f"请在浏览器中打开: http://{self.host}:{self.port}")

        # mDNS 发布（默认：bind_interface 不是 127.0.0.1 时启用）
        self._start_mdns_if_needed()

        print("🔄 页面将保持打开，可实时更新内容")
        print()

        try:
            try:
                self.app.run(
                    host=self.host, port=self.port, debug=False, use_reloader=False
                )
            except KeyboardInterrupt:
                pass
        finally:
            self._stop_mdns()

        empty_result: FeedbackResult = {
            "user_input": "",
            "selected_options": [],
            "images": [],
        }
        return self.feedback_result or empty_result


def web_feedback_ui(
    prompt: str,
    predefined_options: list[str] | None = None,
    task_id: str | None = None,
    auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    output_file: str | None = None,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> FeedbackResult | None:
    """启动 Web UI（交互反馈界面）的便捷函数

    功能说明：
        创建 WebFeedbackUI 实例并启动服务，收集用户反馈。可选地将结果保存到文件。

    参数说明：
        prompt: 提示文本（Markdown 格式）
        predefined_options: 预定义选项列表（可选）
        task_id: 任务 ID（可选）
        auto_resubmit_timeout: 自动重调倒计时（秒，默认 240；范围 [10, 3600]；0=禁用）
        output_file: 输出文件路径（可选；若指定则将结果保存为 JSON 文件）
        host: 绑定主机地址（默认"0.0.0.0"）
        port: 绑定端口（默认8080）

    返回值：
        FeedbackResult | None: 用户反馈结果字典，包含：
            - user_input: 用户输入文本
            - selected_options: 选中的选项数组
            - images: 图片数组（Base64编码）
        若指定output_file，则返回None（结果已保存到文件）

    处理逻辑：
        1. 创建WebFeedbackUI实例
        2. 调用ui.run()启动服务器并等待反馈
        3. 若指定output_file：
           - 确保输出目录存在
           - 将反馈结果保存为JSON文件（UTF-8编码，格式化缩进）
           - 返回None
        4. 否则直接返回反馈结果

    使用场景：
        - 命令行工具快速启动反馈界面
        - 自动化脚本收集用户输入
        - 测试和开发环境

    注意事项：
        - 服务器会阻塞当前线程，直到用户提交反馈或关闭服务器
        - output_file路径的父目录会被自动创建
        - JSON文件使用ensure_ascii=False保留中文字符
    """
    auto_resubmit_timeout = validate_auto_resubmit_timeout(int(auto_resubmit_timeout))
    ui = WebFeedbackUI(
        prompt, predefined_options, task_id, auto_resubmit_timeout, host, port
    )
    result = ui.run()

    if output_file and result:
        # 确保目录存在
        output_path = Path(str(output_file)).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 保存结果到输出文件
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return None

    return result


if __name__ == "__main__":
    """主程序入口：命令行启动 Web UI（交互反馈界面）

    功能说明：
        解析命令行参数，启动 Web UI，并在用户提交后输出反馈结果。

    命令行参数：
        --prompt: 向用户展示的提示/问题（支持 Markdown，默认"我已经实现了您请求的更改。"）
        --predefined-options: 预定义选项列表（用 ||| 分隔）
        --task-id: 任务 ID（可选；主要用于调试/脚本集成）
        --auto-resubmit-timeout: 自动重调倒计时（秒，默认 240；范围 [10, 3600]；0=禁用）
        --output-file: 将反馈结果保存为 JSON 文件的路径
        --host: Web UI 监听地址（默认 "0.0.0.0"）
        --port: Web UI 监听端口（默认 8080）

    执行流程：
        1. 创建ArgumentParser解析命令行参数
        2. 解析predefined_options（|||分隔符）
        3. 调用web_feedback_ui()启动服务器
        4. 打印反馈结果到标准输出
        5. 退出程序（sys.exit(0)）

    输出格式：
        收到反馈:
        选择的选项: option1, option2
        用户输入: <user text>
        包含 <N> 张图片

    注意事项：
        - 适用于命令行工具和自动化脚本
        - 服务器会阻塞直到用户提交反馈
        - 可通过Ctrl+C中断服务器
    """
    parser = argparse.ArgumentParser(description="运行 Web UI（交互反馈界面）")
    parser.add_argument(
        "--prompt",
        default="我已经实现了您请求的更改。",
        help="向用户展示的提示/问题（支持 Markdown）",
    )
    parser.add_argument(
        "--predefined-options",
        default="",
        help="预定义选项列表（用 ||| 分隔；为空表示无选项）",
    )
    parser.add_argument(
        "--task-id", default=None, help="任务 ID（可选；主要用于调试/脚本集成）"
    )
    parser.add_argument(
        "--auto-resubmit-timeout",
        type=int,
        default=AUTO_RESUBMIT_TIMEOUT_DEFAULT,
        help="自动重调倒计时（秒；0 表示禁用；范围 [10, 3600]，与 server_config.AUTO_RESUBMIT_TIMEOUT_MAX 对齐）",
    )
    parser.add_argument("--output-file", help="将反馈结果保存为 JSON 文件的路径")
    parser.add_argument("--host", default="0.0.0.0", help="Web UI 监听地址")
    parser.add_argument("--port", type=int, default=8080, help="Web UI 监听端口")
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
