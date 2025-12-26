"""
Web UI for AI Intervention Agent MCP - Web反馈界面模块

功能说明：
    提供基于Flask的Web反馈界面，用于人工干预代理系统的用户交互。
    支持实时内容轮询、多任务并发管理、文件上传、Markdown渲染等功能。

核心特性：
    - **多任务支持**：支持任务队列管理、任务切换、状态追踪
    - **实时更新**：通过API轮询实现内容实时更新，无需刷新页面
    - **安全机制**：CSP内容安全策略、IP访问控制、请求频率限制、文件验证
    - **文件上传**：支持图片上传、验证、Base64编码、安全文件名处理
    - **Markdown渲染**：支持代码高亮、表格、脚注、LaTeX数学公式
    - **通知系统**：Web通知、Bark推送、声音提示、移动端优化
    - **远程访问**：支持SSH端口转发、0.0.0.0绑定、跨域CORS

架构设计：
    - Flask作为Web框架，提供RESTful API
    - Flask-CORS处理跨域请求
    - Flask-Limiter实现请求频率限制
    - markdown库进行Markdown到HTML转换
    - TaskQueue进行任务队列管理
    - NotificationManager进行通知管理

API端点：
    - GET  /                             - 主页面（HTML模板）
    - GET  /api/config                   - 获取当前任务配置
    - GET  /api/health                   - 健康检查
    - GET  /api/tasks                    - 获取所有任务列表
    - POST /api/tasks                    - 创建新任务
    - GET  /api/tasks/<id>               - 获取单个任务详情
    - POST /api/tasks/<id>/activate      - 激活指定任务
    - POST /api/tasks/<id>/submit        - 提交任务反馈
    - POST /api/submit                   - 提交反馈（通用端点）
    - POST /api/update                   - 更新页面内容
    - GET  /api/feedback                 - 获取反馈结果
    - POST /api/close                    - 关闭服务器
    - POST /api/test-bark                - 测试Bark通知
    - POST /api/update-notification-config - 更新通知配置
    - GET  /api/get-notification-config  - 获取通知配置
    - 静态资源路由：/static/css/*, /static/js/*, /fonts/*, /icons/*, /sounds/*

安全机制：
    - CSP（Content Security Policy）：防止XSS攻击
    - IP访问控制：基于白名单/黑名单的网络访问控制
    - 请求频率限制：防止DoS攻击（60次/分钟，10次/秒）
    - 文件验证：上传文件的MIME类型、大小、内容验证
    - 安全头部：X-Frame-Options、X-Content-Type-Options、X-XSS-Protection等

使用场景：
    - SSH远程环境下的人工干预交互
    - MCP（Model Context Protocol）服务的用户反馈收集
    - AI代理与人类协作的界面层

依赖模块：
    - config_manager: 配置管理
    - enhanced_logging: 增强日志系统
    - file_validator: 文件验证器
    - server: 任务队列获取
    - notification_manager: 通知管理（可选）
    - notification_providers: 通知提供者（可选）

注意事项：
    - 默认监听所有网络接口（0.0.0.0），确保防火墙正确配置
    - 生产环境建议启用IP访问控制
    - 文件上传大小和数量受Flask配置限制
    - 通知系统为可选功能，缺失时自动降级
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
from functools import lru_cache
from ipaddress import (
    AddressValueError,
    IPv4Network,
    IPv6Network,
    ip_address,
    ip_network,
)
from typing import Any, Dict, List, Optional, cast

import markdown
from flask import (
    Flask,
    abort,
    jsonify,
    render_template_string,
    request,
    send_from_directory,
)
from flask_compress import Compress
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config_manager import get_config
from config_utils import clamp_value
from enhanced_logging import EnhancedLogger
from file_validator import validate_uploaded_file
from server import get_task_queue
from shared_types import FeedbackResult

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

# ============================================================================
# 版本号和项目信息
# ============================================================================

# GitHub 仓库地址
GITHUB_URL = "https://github.com/XIADENGMA/ai-intervention-agent"


@lru_cache(maxsize=1)
def get_project_version() -> str:
    """
    从 pyproject.toml 读取项目版本号

    返回
    ----
    str
        项目版本号（如 "1.3.0"），读取失败时返回 "unknown"

    实现逻辑
    --------
    1. 使用 tomllib（Python 3.11+）解析 pyproject.toml
    2. 解析失败则回退到正则表达式匹配
    3. 所有方法失败则返回 "unknown"

    缓存说明
    --------
    使用 lru_cache 缓存首次读取结果，避免重复 I/O。
    """
    version = "unknown"

    try:
        # 获取 pyproject.toml 路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        pyproject_path = os.path.join(current_dir, "pyproject.toml")

        if os.path.exists(pyproject_path):
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
                with open(pyproject_path, "r", encoding="utf-8") as f:
                    content = f.read()
                match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    version = match.group(1)
    except Exception as e:
        logger.warning(f"读取版本号失败: {e}")

    return version


# ============================================================================
# 前端倒计时超时常量（需与 server.py 保持一致）
# ============================================================================
AUTO_RESUBMIT_TIMEOUT_MIN = 30  # 前端最小倒计时（秒）
AUTO_RESUBMIT_TIMEOUT_MAX = 250  # 前端最大倒计时（秒）【优化】从290→250，预留安全余量
AUTO_RESUBMIT_TIMEOUT_DEFAULT = 240  # 默认前端倒计时（秒）


def validate_auto_resubmit_timeout(value: int) -> int:
    """
    验证并调整 auto_resubmit_timeout 值

    参数
    ----
    value : int
        输入的超时时间值（秒）

    返回
    ----
    int
        验证后的超时时间值（秒）

    验证规则
    --------
    - 0 表示禁用自动提交（保持不变）
    - 负值转换为 0（禁用）
    - 小于最小值（30秒）调整为最小值
    - 大于最大值（290秒）调整为最大值

    【重构】使用 config_utils.clamp_value 简化边界检查。
    """
    if value <= 0:
        return 0  # 禁用自动提交

    # 【重构】使用 clamp_value 简化边界检查
    return clamp_value(
        value,
        AUTO_RESUBMIT_TIMEOUT_MIN,
        AUTO_RESUBMIT_TIMEOUT_MAX,
        "auto_resubmit_timeout",
    )


# ============================================================================
# 网络安全配置验证函数
# ============================================================================

# 有效的 bind_interface 值
VALID_BIND_INTERFACES = {"0.0.0.0", "127.0.0.1", "localhost", "::1", "::"}

# 默认的允许网络列表（本地回环 + 私有网络）
DEFAULT_ALLOWED_NETWORKS = [
    "127.0.0.0/8",  # IPv4 本地回环
    "::1/128",  # IPv6 本地回环
    "192.168.0.0/16",  # 私有网络 C 类
    "10.0.0.0/8",  # 私有网络 A 类
    "172.16.0.0/12",  # 私有网络 B 类
]


def validate_bind_interface(value: Any) -> str:
    """
    验证并调整 bind_interface 值

    参数
    ----
    value : str
        绑定接口的值

    返回
    ----
    str
        验证后的绑定接口值

    验证规则
    --------
    - 特殊值（0.0.0.0、127.0.0.1、localhost、::1、::）直接通过
    - 尝试解析为 IP 地址，成功则通过
    - 验证失败使用默认值 "127.0.0.1"
    """
    if not value or not isinstance(value, str):
        logger.warning("bind_interface 值无效，使用默认值 127.0.0.1")
        return "127.0.0.1"

    value = value.strip()

    # 特殊值直接通过
    if value in VALID_BIND_INTERFACES:
        if value == "0.0.0.0":
            logger.info(
                "⚠️  bind_interface 设为 0.0.0.0，将监听所有网络接口。"
                "请确保已正确配置 allowed_networks 和防火墙规则。"
            )
        return value

    # 尝试解析为 IP 地址
    try:
        ip_address(value)
        return value
    except (AddressValueError, ValueError):
        logger.warning(
            f"bind_interface '{value}' 不是有效的 IP 地址，使用默认值 127.0.0.1"
        )
        return "127.0.0.1"


def validate_network_cidr(network_str: Any) -> bool:
    """
    验证网络 CIDR 格式是否有效

    参数
    ----
    network_str : str
        网络地址字符串（CIDR 格式或单个 IP）

    返回
    ----
    bool
        True 表示有效，False 表示无效
    """
    if not network_str or not isinstance(network_str, str):
        return False

    try:
        if "/" in network_str:
            # CIDR 格式
            ip_network(network_str, strict=False)
        else:
            # 单个 IP
            ip_address(network_str)
        return True
    except (AddressValueError, ValueError):
        return False


def validate_allowed_networks(networks: Any) -> list[str]:
    """
    验证并清理 allowed_networks 列表

    参数
    ----
    networks : list
        允许的网络列表

    返回
    ----
    list
        验证后的网络列表

    验证规则
    --------
    - 过滤无效的 CIDR/IP 格式
    - 空列表自动添加本地回环地址
    - 记录无效条目的警告日志
    """
    if not isinstance(networks, list):
        logger.warning("allowed_networks 不是列表，使用默认值")
        return DEFAULT_ALLOWED_NETWORKS.copy()

    valid_networks: list[str] = []
    invalid_networks: list[str] = []

    for network in networks:
        if validate_network_cidr(network):
            # validate_network_cidr 已确保 network 为 str
            valid_networks.append(str(network))
        else:
            invalid_networks.append(str(network))

    # 记录无效条目
    if invalid_networks:
        logger.warning(f"以下网络配置无效，已跳过: {', '.join(invalid_networks)}")

    # 空列表保护：确保至少包含本地回环
    if not valid_networks:
        logger.warning("allowed_networks 为空或全部无效，自动添加本地回环地址")
        valid_networks = ["127.0.0.0/8", "::1/128"]

    return valid_networks


def validate_blocked_ips(ips: Any) -> list[str]:
    """
    验证并清理 blocked_ips 列表

    参数
    ----
    ips : list
        黑名单 IP 列表

    返回
    ----
    list
        验证后的 IP 列表

    验证规则
    --------
    - 过滤无效的 IP 格式
    - 记录无效条目的警告日志
    """
    if not isinstance(ips, list):
        return []

    valid_ips: list[str] = []
    invalid_ips: list[str] = []

    for ip in ips:
        if isinstance(ip, str):
            try:
                ip_address(ip)
                valid_ips.append(ip)
            except (AddressValueError, ValueError):
                invalid_ips.append(ip)
        else:
            invalid_ips.append(str(ip))

    if invalid_ips:
        logger.warning(f"以下黑名单 IP 无效，已跳过: {', '.join(invalid_ips)}")

    return valid_ips


def validate_network_security_config(config: Any) -> dict[str, Any]:
    """
    验证并清理完整的 network_security 配置

    参数
    ----
    config : dict
        原始的 network_security 配置字典

    返回
    ----
    dict
        验证后的配置字典

    验证规则
    --------
    - bind_interface: 验证为有效 IP 或特殊值
    - allowed_networks: 验证 CIDR 格式，空列表添加本地回环
    - blocked_ips: 验证 IP 格式
    - enable_access_control: 转换为布尔值
    """
    if not isinstance(config, dict):
        config = {}

    validated = {
        "bind_interface": validate_bind_interface(
            config.get("bind_interface", "0.0.0.0")
        ),
        "allowed_networks": validate_allowed_networks(
            config.get("allowed_networks", DEFAULT_ALLOWED_NETWORKS)
        ),
        "blocked_ips": validate_blocked_ips(config.get("blocked_ips", [])),
        # 【命名优化】使用新名称，保持向后兼容
        "enable_access_control": bool(
            config.get(
                "access_control_enabled",  # 新名称
                config.get("enable_access_control", True),  # 旧名称回退
            )
        ),
    }

    return validated


class WebFeedbackUI:
    """Web反馈界面核心类

    功能说明：
        封装Flask应用和相关配置，提供完整的Web反馈交互界面。
        管理任务内容、用户反馈、安全策略、路由注册等。

    核心职责：
        - Flask应用初始化和配置
        - HTTP安全头部设置（CSP、XSS保护、点击劫持防护）
        - Markdown渲染器配置
        - RESTful API路由注册
        - 静态资源服务
        - IP访问控制
        - 请求频率限制
        - 用户反馈收集和存储

    属性说明：
        prompt (str): 当前提示文本（Markdown格式）
        predefined_options (List[str]): 预定义选项列表
        task_id (Optional[str]): 当前任务ID
        auto_resubmit_timeout (int): 自动重新提交超时时间（秒，最大290秒）
        host (str): 服务器绑定地址（默认0.0.0.0）
        port (int): 服务器监听端口（默认8080）
        feedback_result (Optional[Dict]): 用户反馈结果存储
        current_prompt (str): 当前显示的提示文本
        current_options (List[str]): 当前显示的选项列表
        current_task_id (Optional[str]): 当前任务ID
        current_auto_resubmit_timeout (int): 当前超时时间
        has_content (bool): 是否有有效内容
        initial_empty (bool): 初始是否为空
        app (Flask): Flask应用实例
        csp_nonce (str): CSP随机数（用于内联脚本/样式）
        network_security_config (Dict): 网络安全配置
        limiter (Limiter): 请求频率限制器
        md (Markdown): Markdown渲染器实例

    生命周期：
        1. __init__：初始化配置、创建Flask应用、设置安全策略
        2. setup_security_headers：配置HTTP安全头部
        3. setup_markdown：配置Markdown渲染器
        4. setup_routes：注册所有API路由
        5. run：启动Flask服务器，等待用户反馈
        6. shutdown_server：优雅关闭服务器

    线程安全：
        - Flask应用内部使用Werkzeug线程本地存储，路由处理器线程安全
        - feedback_result在单线程写入（提交反馈时），多线程读取（轮询时）需注意竞态条件
        - TaskQueue内部使用threading.Lock保证线程安全

    使用场景：
        - 单次反馈收集：创建实例 → 调用run() → 获取feedback_result
        - 持续服务模式：创建实例 → 调用run()（持续运行），通过API动态更新内容
        - 多任务模式：与TaskQueue配合，实现任务队列的Web界面管理
    """

    def __init__(
        self,
        prompt: str,
        predefined_options: Optional[List[str]] = None,
        task_id: Optional[str] = None,
        auto_resubmit_timeout: int = 240,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        """初始化Web反馈界面实例

        功能说明：
            创建Flask应用实例，配置安全策略，初始化任务内容，注册路由。

        参数说明：
            prompt: 提示文本（支持Markdown格式，将被渲染为HTML）
            predefined_options: 预定义选项列表（显示为复选框，可多选）
            task_id: 任务唯一标识符（用于任务队列管理和日志追踪）
            auto_resubmit_timeout: 自动重新提交超时时间（秒），最大不超过290秒，0表示禁用
            host: 服务器绑定地址
                   - "0.0.0.0": 监听所有网络接口（允许远程访问）
                   - "127.0.0.1": 仅本地访问
                   - 特定IP: 绑定到指定网络接口
            port: 服务器监听端口（默认8080，需确保端口未被占用）

        初始化步骤：
            1. 存储任务配置（prompt、options、task_id、timeout）
            2. 初始化反馈结果存储（feedback_result）
            3. 创建Flask应用实例，启用CORS跨域支持
            4. 生成CSP随机数（用于内联脚本的安全策略）
            5. 加载网络安全配置（IP访问控制规则）
            6. 配置请求频率限制器（60次/分钟，10次/秒）
            7. 调用setup_security_headers()配置HTTP安全头部
            8. 调用setup_markdown()配置Markdown渲染器
            9. 调用setup_routes()注册所有API路由

        副作用：
            - 创建Flask应用实例（self.app）
            - 启用全局CORS策略
            - 配置全局请求频率限制
            - 注册before_request和after_request钩子
            - 注册所有API路由和静态资源路由

        异常处理：
            - 配置加载失败时使用默认安全配置
            - Markdown扩展加载失败时使用基础渲染

        注意事项：
            - auto_resubmit_timeout最大值为290秒，超过将被截断
            - host="0.0.0.0"时务必配置防火墙和IP访问控制
            - CSP随机数在每次初始化时重新生成，确保安全性
        """
        self.prompt = prompt
        self.predefined_options = predefined_options or []
        self.task_id = task_id
        self.auto_resubmit_timeout = auto_resubmit_timeout
        self.host = host
        self.port = port
        self.feedback_result: FeedbackResult | None = None
        self.current_prompt = prompt if prompt else ""
        self.current_options = predefined_options or []
        self.current_task_id = task_id
        self.current_auto_resubmit_timeout = auto_resubmit_timeout
        self.has_content = bool(prompt)
        self.initial_empty = not bool(prompt)
        self.app = Flask(__name__)
        CORS(self.app)

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
        """设置HTTP安全头部和访问控制

        功能说明：
            注册Flask的before_request和after_request钩子，实现IP访问控制和HTTP安全头部注入。

        安全策略：
            - **IP访问控制**：基于白名单/黑名单验证客户端IP地址
            - **CSP**：Content Security Policy，防止XSS攻击
            - **X-Frame-Options**：防止点击劫持（Clickjacking）
            - **X-Content-Type-Options**：防止MIME类型嗅探
            - **X-XSS-Protection**：启用浏览器XSS过滤
            - **Referrer-Policy**：控制Referer头部信息泄露
            - **Permissions-Policy**：禁用敏感浏览器API（地理位置、麦克风、摄像头等）

        CSP策略详情：
            - default-src 'self'：默认只允许同源资源
            - script-src 'self' 'nonce-{随机数}'：脚本需要CSP随机数
            - style-src 'self' 'nonce-{随机数}' + MathJax内联样式哈希：样式支持随机数和白名单哈希
            - img-src 'self' data: blob:：图片支持同源、Data URL、Blob URL
            - font-src 'self' data:：字体支持同源和Data URL
            - connect-src 'self'：AJAX请求仅限同源
            - frame-ancestors 'none'：禁止被iframe嵌入
            - base-uri 'self'：<base>标签仅限同源
            - object-src 'none'：禁止<object>、<embed>、<applet>

        执行时机：
            - before_request：在每个请求处理前检查IP访问权限
            - after_request：在每个响应返回前注入安全头部

        副作用：
            - 修改所有HTTP响应头部（添加安全策略）
            - 拒绝不在白名单中的IP访问（返回403 Forbidden）

        注意事项：
            - MathJax内联样式需要添加SHA-256哈希到CSP白名单
            - CSP随机数在__init__中生成，需传递给HTML模板
            - IP访问控制依赖network_security_config配置
        """

        @self.app.before_request
        def check_ip_access():
            """检查IP访问权限（before_request钩子）

            功能说明：
                在每个请求处理前验证客户端IP地址是否在允许的网络范围内。

            验证逻辑：
                1. 从HTTP_X_FORWARDED_FOR或REMOTE_ADDR获取客户端IP
                2. 处理代理转发的多IP情况（取第一个IP）
                3. 调用_is_ip_allowed()进行白名单/黑名单验证
                4. 拒绝不合法的IP访问（返回403）

            副作用：
                - 记录被拒绝的IP地址到日志
                - 调用abort(403)中断请求处理

            注意事项：
                - 代理环境下需检查HTTP_X_FORWARDED_FOR头部
                - IP伪造风险：确保代理服务器可信任
            """
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
            """添加HTTP安全头部（after_request钩子）

            功能说明：
                在每个响应返回前注入安全相关的HTTP头部。

            注入的头部：
                - Content-Security-Policy：详见setup_security_headers文档
                - X-Frame-Options: DENY：完全禁止被iframe嵌入
                - X-Content-Type-Options: nosniff：禁止MIME类型嗅探
                - X-XSS-Protection: 1; mode=block：启用XSS过滤并阻止页面加载
                - Referrer-Policy: strict-origin-when-cross-origin：跨域时仅发送origin
                - Permissions-Policy：禁用geolocation、microphone、camera、payment、usb、magnetometer、gyroscope

            参数说明：
                response: Flask响应对象

            返回值：
                Flask响应对象（添加了安全头部）

            注意事项：
                - 此钩子对所有路由生效，包括静态资源
                - CSP策略严格，修改时需谨慎测试
            """
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{self.csp_nonce}'; "
                "style-src 'self' 'unsafe-inline'; "  # 允许内联样式（MathJax 和 Pygments 需要，nonce 会导致 unsafe-inline 失效）
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

            # 静态资源缓存优化：为 JS/CSS/字体/音频/动画 设置长期缓存
            path = request.path
            if path.startswith("/static/js/") or path.startswith("/static/css/"):
                # JS/CSS 文件：带版本号时使用长期缓存（1年），否则使用短期缓存（1天）
                if request.args.get("v"):
                    response.headers["Cache-Control"] = (
                        "public, max-age=31536000, immutable"
                    )
                else:
                    response.headers["Cache-Control"] = "public, max-age=86400"
            elif path.startswith("/static/lottie/"):
                # Lottie 动画 JSON 文件缓存 30 天（动画文件通常不会频繁更新）
                response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
            elif path.startswith("/fonts/"):
                # 字体文件缓存 30 天（2592000秒）
                response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
            elif path.startswith("/sounds/"):
                # 音频文件缓存 7 天（604800秒）
                response.headers["Cache-Control"] = "public, max-age=604800"
            elif path.startswith("/icons/") and not path.endswith(".ico"):
                # 图标文件（非 favicon.ico）缓存 7 天
                response.headers["Cache-Control"] = "public, max-age=604800"

            return response

    def setup_markdown(self):
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
            2. 调用self.md.convert()进行Markdown到HTML转换
            3. 应用所有启用的扩展（代码高亮、表格、脚注等）
            4. 返回渲染后的HTML

        注意事项：
            - 空文本返回空字符串（避免None错误）
            - HTML未进行额外的XSS过滤，依赖Markdown库的安全性
            - Markdown实例状态会累积，重复调用可能有副作用（目录编号等）
        """
        if not text:
            return ""
        return self.md.convert(text)

    def setup_routes(self):
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
        def index():
            """主页面路由处理器

            功能说明：
                返回Web反馈界面的HTML模板页面。

            返回值：
                str: 渲染后的HTML页面（包含CSP随机数、外部CSS/JS引用）

            注意事项：
                - HTML模板通过get_html_template()读取和处理
                - 模板中的内联CSS/JS已替换为外部文件引用
                - CSP随机数在模板中用于安全策略
            """
            return render_template_string(self.get_html_template())

        @self.app.route("/api/config")
        @self.limiter.limit("300 per minute")  # 允许更频繁的轮询，支持测试场景
        def get_api_config():
            """获取当前任务配置的API端点

            功能说明：
                返回当前激活任务的配置信息，支持前端内容轮询和动态更新。

            处理逻辑：
                1. 尝试从TaskQueue获取激活任务（active_task）
                2. 若无激活任务，自动激活第一个pending任务
                3. 若所有任务都已完成，返回空内容状态
                4. 回退到单任务模式（使用self.current_prompt等属性）

            返回值：
                JSON对象，包含以下字段：
                    - prompt: 提示文本（Markdown原文）
                    - prompt_html: 渲染后的HTML
                    - predefined_options: 预定义选项列表
                    - task_id: 任务ID
                    - auto_resubmit_timeout: 超时时间（秒）
                    - persistent: 是否持久化（True表示页面保持打开）
                    - has_content: 是否有有效内容
                    - initial_empty: 初始是否为空

            频率限制：
                - 300次/分钟（支持高频轮询）

            异常处理：
                - 获取任务失败时返回安全的默认响应（HTTP 500）
                - 记录详细错误日志（包含堆栈信息）

            注意事项：
                - 此端点是前端轮询的核心，性能影响大
                - 自动激活pending任务确保任务队列不会卡住
                - completed任务会在10秒后自动清理
            """
            try:
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
                            "remaining_time": active_task.get_remaining_time(),  # 剩余倒计时秒数
                            "server_time": time.time(),  # 【新增】服务器当前时间戳（秒）
                            "deadline": active_task.created_at.timestamp()
                            + active_task.auto_resubmit_timeout,  # 【新增】截止时间戳（秒）
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
                                "remaining_time": first_task.get_remaining_time(),  # 剩余倒计时秒数
                                "server_time": time.time(),  # 【新增】服务器当前时间戳（秒）
                                "deadline": first_task.created_at.timestamp()
                                + first_task.auto_resubmit_timeout,  # 【新增】截止时间戳（秒）
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
                    # 单任务模式没有创建时间，remaining_time 等于 auto_resubmit_timeout
                    return jsonify(
                        {
                            "prompt": self.current_prompt,
                            "prompt_html": self.render_markdown(self.current_prompt)
                            if self.has_content
                            else "",
                            "predefined_options": self.current_options,
                            "task_id": self.current_task_id,
                            "auto_resubmit_timeout": self.current_auto_resubmit_timeout,
                            "remaining_time": self.current_auto_resubmit_timeout,  # 单任务模式无创建时间
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
            """关闭服务器的API端点

            功能说明：
                优雅关闭Flask服务器，适用于单次任务完成后的自动关闭场景。

            处理逻辑：
                1. 启动一个0.5秒延时的定时器
                2. 定时器触发时调用shutdown_server()发送SIGINT信号
                3. 立即返回成功响应（响应发送后才关闭）

            返回值：
                JSON对象：{"status": "success", "message": "服务即将关闭"}

            副作用：
                - 0.5秒后服务器进程收到SIGINT信号并关闭
                - 所有未完成的请求可能被中断

            注意事项：
                - 延时0.5秒确保响应成功发送
                - 关闭是全局的，影响所有客户端连接
                - 多任务模式下应避免使用此端点
            """
            threading.Timer(0.5, self.shutdown_server).start()
            return jsonify({"status": "success", "message": "服务即将关闭"})

        @self.app.route("/api/health", methods=["GET"])
        def health_check():
            """健康检查端点

            功能说明：
                提供简单的健康检查，用于监控和负载均衡探测。

            返回值：
                JSON对象：{"status": "ok"}

            频率限制：
                - 使用全局默认限制（60次/分钟，10次/秒）

            使用场景：
                - Kubernetes/Docker健康探针
                - 负载均衡器健康检查
                - 外部监控系统
            """
            return jsonify({"status": "ok"})

        @self.app.route("/api/tasks", methods=["GET"])
        @self.limiter.limit("300 per minute")
        def get_tasks():
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

                # 自动清理超过 10 秒的已完成任务
                task_queue.cleanup_completed_tasks(age_seconds=10)

                tasks = task_queue.get_all_tasks()

                # 【优化】添加 server_time 和 deadline，让前端可以基于服务器时间计算倒计时
                server_time = (
                    time.time()
                )  # 获取当前服务器时间戳（只获取一次，保证所有任务的时间一致）

                task_list = []
                for task in tasks:
                    task_list.append(
                        {
                            "task_id": task.task_id,
                            "status": task.status,
                            "prompt": task.prompt[:100],  # 只返回前100个字符
                            "created_at": task.created_at.isoformat(),
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "remaining_time": task.get_remaining_time(),  # 剩余倒计时秒数
                            "deadline": task.created_at.timestamp()
                            + task.auto_resubmit_timeout,  # 【新增】截止时间戳（秒）
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
                logger.error(f"获取任务列表失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/tasks", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def create_task():
            """创建新任务的API端点

            功能说明：
                接收JSON请求，创建新的任务并添加到任务队列。

            请求体（JSON）：
                - task_id: 任务唯一标识符（必填）
                - prompt: 提示文本（必填，Markdown格式）
                - predefined_options: 预定义选项列表（可选）
                - auto_resubmit_timeout: 超时时间（可选，默认240秒，最大290秒）

            处理逻辑：
                1. 解析JSON请求体
                2. 验证必填字段（task_id、prompt）
                3. 限制auto_resubmit_timeout最大值为290秒
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

            异常处理：
                - 缺少请求数据：返回HTTP 400
                - 缺少task_id或prompt：返回HTTP 400
                - 队列已满或ID重复：返回HTTP 409
                - 其他异常：返回HTTP 500

            注意事项：
                - auto_resubmit_timeout自动截断为290秒
                - 任务ID需全局唯一，重复添加会失败
                - 任务创建后状态为pending，需手动或自动激活
            """
            try:
                data = request.get_json()
                if not data:
                    return jsonify({"success": False, "error": "缺少请求数据"}), 400

                task_id = data.get("task_id")
                prompt = data.get("prompt")
                predefined_options = data.get("predefined_options")

                # 从配置文件读取默认 auto_resubmit_timeout
                config_mgr = get_config()
                feedback_config = config_mgr.get_section("feedback")
                # 【命名优化】使用新名称，保持向后兼容
                default_timeout = feedback_config.get(
                    "frontend_countdown",  # 新名称
                    feedback_config.get(
                        "auto_resubmit_timeout", AUTO_RESUBMIT_TIMEOUT_DEFAULT
                    ),  # 旧名称回退
                )
                auto_resubmit_timeout = data.get(
                    "auto_resubmit_timeout", default_timeout
                )
                # 【优化】使用统一的验证函数，同时验证最小值和最大值
                auto_resubmit_timeout = validate_auto_resubmit_timeout(
                    int(auto_resubmit_timeout)
                )

                if not task_id or not prompt:
                    return jsonify(
                        {"success": False, "error": "缺少必要参数：task_id 和 prompt"}
                    ), 400

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
                    return jsonify(
                        {"success": False, "error": "任务队列已满或任务ID重复"}
                    ), 409

            except Exception as e:
                logger.error(f"创建任务失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/tasks/<task_id>", methods=["GET"])
        @self.limiter.limit("300 per minute")
        def get_task(task_id):
            """获取单个任务详情的API端点

            功能说明：
                返回指定任务的完整信息，包括prompt全文、选项、状态、结果等。

            参数说明：
                task_id: 任务ID（URL路径参数）

            处理逻辑：
                1. 调用TaskQueue.cleanup_completed_tasks(age_seconds=10)清理过期任务
                2. 根据task_id查询任务
                3. 若任务不存在，返回HTTP 404
                4. 返回任务完整信息

            返回值：
                成功：JSON对象 {"success": true, "task": {...}}
                    - task_id: 任务ID
                    - prompt: 提示文本（完整）
                    - predefined_options: 预定义选项列表
                    - status: 任务状态（pending/active/completed）
                    - created_at: 创建时间（ISO 8601格式）
                    - auto_resubmit_timeout: 超时时间（秒）
                    - result: 反馈结果（completed状态时有值）
                失败：HTTP 404 + 错误信息（任务不存在）
                      HTTP 500 + 错误信息（其他异常）

            频率限制：
                - 300次/分钟（支持高频轮询）

            异常处理：
                - 任务不存在：返回HTTP 404
                - 其他异常：返回HTTP 500

            注意事项：
                - 返回完整prompt（无截断），注意响应体大小
                - 自动清理10秒前的completed任务
                - 此端点用于任务切换时加载详情
            """
            try:
                task_queue = get_task_queue()

                # 自动清理超过 10 秒的已完成任务
                task_queue.cleanup_completed_tasks(age_seconds=10)

                task = task_queue.get_task(task_id)

                if not task:
                    return jsonify({"success": False, "error": "任务不存在"}), 404

                # 【优化】添加 server_time 和 deadline，让前端可以基于服务器时间计算倒计时
                return jsonify(
                    {
                        "success": True,
                        "server_time": time.time(),  # 【新增】服务器当前时间戳（秒）
                        "task": {
                            "task_id": task.task_id,
                            "prompt": task.prompt,
                            "predefined_options": task.predefined_options,
                            "status": task.status,
                            "created_at": task.created_at.isoformat(),
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "remaining_time": task.get_remaining_time(),  # 剩余倒计时秒数
                            "deadline": task.created_at.timestamp()
                            + task.auto_resubmit_timeout,  # 【新增】截止时间戳（秒）
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
            """激活指定任务的API端点

            功能说明：
                将指定任务设置为激活状态（active_task），用于任务切换。

            参数说明：
                task_id: 任务ID（URL路径参数）

            处理逻辑：
                1. 调用TaskQueue.set_active_task(task_id)
                2. 若切换失败（任务不存在或已完成），返回HTTP 400
                3. 返回成功响应

            返回值：
                成功：JSON对象 {"success": true, "active_task_id": "<task_id>"}
                失败：HTTP 400 + 错误信息（切换失败）
                      HTTP 500 + 错误信息（其他异常）

            频率限制：
                - 60次/分钟（防止频繁切换）

            异常处理：
                - 切换失败：返回HTTP 400
                - 其他异常：返回HTTP 500

            副作用：
                - 修改TaskQueue的active_task_id
                - 触发前端内容更新（通过/api/config轮询）

            注意事项：
                - 只能激活pending或active状态的任务
                - completed任务无法激活
            """
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
            """提交指定任务反馈的API端点

            功能说明：
                接收表单数据（支持文件上传），将反馈内容提交到指定任务并标记为完成。

            参数说明：
                task_id: 任务ID（URL路径参数）

            请求体（multipart/form-data）：
                - feedback_text: 用户输入文本
                - selected_options: 选中的选项（JSON数组字符串）
                - image_*: 图片文件（可多个，键名以image_开头）

            处理逻辑：
                1. 根据task_id查询任务
                2. 若任务不存在，返回HTTP 404
                3. 解析表单数据（feedback_text、selected_options）
                4. 处理上传的图片文件：
                   - 读取文件内容
                   - 调用validate_uploaded_file()进行安全验证
                   - 验证失败的文件跳过
                   - 转换为Base64编码
                   - 记录文件元数据（filename、size、content_type等）
                5. 构建反馈结果对象
                6. 调用TaskQueue.complete_task()标记任务完成
                7. 返回成功响应

            返回值：
                成功：JSON对象 {"success": true, "message": "反馈已提交"}
                失败：HTTP 404 + 错误信息（任务不存在）
                      HTTP 500 + 错误信息（其他异常）

            频率限制：
                - 60次/分钟（防止恶意提交）

            异常处理：
                - 任务不存在：返回HTTP 404
                - 文件验证失败：跳过该文件，记录警告日志
                - 文件处理异常：跳过该文件，记录错误日志
                - 其他异常：返回HTTP 500

            副作用：
                - 修改任务状态为completed
                - 存储反馈结果到Task.result
                - 记录提交日志

            注意事项：
                - 文件验证使用file_validator确保安全性
                - 图片转换为Base64后体积增大约33%
                - 与/api/submit的文件处理逻辑保持一致
            """
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

                # 处理图片（与 /api/submit 保持一致）
                images = []
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
                                    logger.warning(
                                        f"文件验证失败: {file.filename} - {'; '.join(validation_result['errors'])}"
                                    )
                                    continue

                                # 转换为base64
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
            """提交反馈的通用API端点（兼容多种请求格式）

            功能说明：
                接收用户反馈（文本、选项、图片），支持多种请求格式（multipart/form-data、application/x-www-form-urlencoded、application/json）。
                同时更新self.feedback_result和TaskQueue中的激活任务。

            支持的请求格式：
                1. multipart/form-data（带文件上传）
                   - feedback_text: 用户输入文本
                   - selected_options: JSON数组字符串
                   - image_*: 图片文件

                2. application/x-www-form-urlencoded（无文件）
                   - feedback_text: 用户输入文本
                   - selected_options: JSON数组字符串

                3. application/json（传统格式，向后兼容）
                   - feedback_text: 用户输入文本
                   - selected_options: 数组
                   - images: 图片数组（已Base64编码）

            处理逻辑：
                1. 检查request.files，判断是否有文件上传
                2. 根据请求类型解析数据：
                   - 有文件：解析表单数据，处理上传文件
                   - 无文件但有表单：解析表单数据
                   - 其他：解析JSON数据（向后兼容）
                3. 对于上传的图片：
                   - 读取文件内容
                   - 调用validate_uploaded_file()验证安全性
                   - 验证失败的跳过，记录警告
                   - 生成安全文件名（UUID + 扩展名）
                   - 转换为Base64编码
                   - 记录文件元数据（原始文件名、安全文件名、大小、类型、SHA-256指纹等）
                4. 构建反馈结果对象
                5. 存储到self.feedback_result
                6. 若有激活任务，同时提交到TaskQueue
                7. 清空当前内容（单任务模式）
                8. 返回成功响应

            返回值：
                JSON对象：
                    - status: "success"
                    - message: "反馈已提交"
                    - persistent: true
                    - clear_content: true

            频率限制：
                - 60次/分钟（支持测试场景）

            文件验证：
                - MIME类型检测（基于文件头）
                - 文件大小限制
                - 扩展名白名单
                - 内容安全扫描

            安全机制：
                - 文件名清理（防止路径遍历）
                - UUID安全文件名生成
                - SHA-256文件指纹
                - 验证失败文件自动跳过

            副作用：
                - 存储反馈到self.feedback_result
                - 更新TaskQueue中激活任务的状态
                - 清空self.current_prompt等属性（单任务模式）

            日志记录：
                - INFO级别：请求类型、数据概要
                - DEBUG级别：详细数据（文本长度、选项内容、文件信息）
                - WARNING级别：文件验证失败
                - ERROR级别：文件处理异常

            注意事项：
                - 支持三种请求格式，向后兼容JSON格式
                - 文件上传使用multipart/form-data
                - selected_options在表单中是JSON字符串，需要解析
                - Base64编码后图片体积增大约33%
                - 验证失败的文件不会中断整个提交流程
            """
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
                logger.info(
                    f"同时将反馈提交到TaskQueue中的激活任务: {active_task.task_id}"
                )
                if self.feedback_result is not None:
                    task_queue.complete_task(
                        active_task.task_id,
                        cast(dict[str, Any], self.feedback_result),
                    )

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
            """更新页面内容的API端点（单任务模式）

            功能说明：
                接收新的任务内容，动态更新页面显示（不刷新页面）。用于单任务模式下的内容更新。

            请求体（JSON）：
                - prompt: 新的提示文本（Markdown格式）
                - predefined_options: 新的预定义选项列表
                - task_id: 新的任务ID
                - auto_resubmit_timeout: 新的超时时间（默认240秒，最大290秒）

            处理逻辑：
                1. 解析JSON请求体
                2. 限制auto_resubmit_timeout最大值为290秒
                3. 更新self.current_prompt等属性
                4. 更新self.has_content标志
                5. 重置self.feedback_result（清空上次反馈）
                6. 返回更新后的配置信息

            返回值：
                JSON对象：
                    - status: "success"
                    - message: "内容已更新"
                    - prompt: 新的提示文本（原文）
                    - prompt_html: 渲染后的HTML
                    - predefined_options: 新的选项列表
                    - task_id: 新的任务ID
                    - auto_resubmit_timeout: 新的超时时间
                    - has_content: 是否有有效内容

            频率限制：
                - 使用全局默认限制（60次/分钟，10次/秒）

            副作用：
                - 修改self.current_prompt、current_options等属性
                - 清空self.feedback_result
                - 更新self.has_content标志

            注意事项：
                - auto_resubmit_timeout自动截断为290秒
                - 仅适用于单任务模式，多任务模式请使用TaskQueue API
                - 更新后前端需重新渲染内容
            """
            raw = request.get_json(silent=True)
            data: dict[str, Any] = raw if isinstance(raw, dict) else {}
            new_prompt = data.get("prompt", "")
            new_options = data.get("predefined_options", [])
            new_task_id = data.get("task_id")

            # 从配置文件读取默认 auto_resubmit_timeout
            config_mgr = get_config()
            feedback_config = config_mgr.get_section("feedback")
            # 【命名优化】使用新名称，保持向后兼容
            default_timeout = feedback_config.get(
                "frontend_countdown",  # 新名称
                feedback_config.get(
                    "auto_resubmit_timeout", AUTO_RESUBMIT_TIMEOUT_DEFAULT
                ),  # 旧名称回退
            )
            new_auto_resubmit_timeout = data.get(
                "auto_resubmit_timeout", default_timeout
            )
            # 【优化】使用统一的验证函数，同时验证最小值和最大值
            new_auto_resubmit_timeout = validate_auto_resubmit_timeout(
                int(new_auto_resubmit_timeout)
            )

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
            """获取用户反馈结果的API端点（单任务模式）

            功能说明：
                返回当前存储的反馈结果，并清空存储。用于单任务模式下的反馈查询。

            处理逻辑：
                1. 检查self.feedback_result是否有值
                2. 若有反馈：返回结果并清空存储
                3. 若无反馈：返回waiting状态

            返回值：
                有反馈：JSON对象 {"status": "success", "feedback": {...}}
                    - user_input: 用户输入文本
                    - selected_options: 选中的选项数组
                    - images: 图片数组（Base64编码）
                无反馈：JSON对象 {"status": "waiting", "feedback": null}

            频率限制：
                - 使用全局默认限制（60次/分钟，10次/秒）

            副作用：
                - 返回反馈后清空self.feedback_result

            注意事项：
                - 仅适用于单任务模式，多任务模式请使用TaskQueue API
                - 反馈结果是一次性的，读取后即清空
                - 适用于轮询场景，waiting状态表示还未提交
            """
            if self.feedback_result:
                # 返回反馈结果并清空
                result = self.feedback_result
                self.feedback_result = None
                return jsonify({"status": "success", "feedback": result})
            else:
                return jsonify({"status": "waiting", "feedback": None})

        @self.app.route("/api/test-bark", methods=["POST"])
        def test_bark_notification():
            """测试Bark通知的API端点

            功能说明：
                使用临时配置发送Bark测试通知，验证Bark服务器连接和Device Key是否正确。

            请求体（JSON）：
                - bark_url: Bark服务器地址（默认"https://api.day.app/push"）
                - bark_device_key: Bark设备密钥（必填）
                - bark_icon: 通知图标URL（可选）
                - bark_action: 点击动作（默认"none"）

            处理逻辑：
                1. 验证bark_device_key不为空
                2. 检查通知系统是否可用
                3. 创建临时配置对象
                4. 创建BarkNotificationProvider实例
                5. 构建测试通知事件
                6. 发送通知并返回结果

            返回值：
                成功：JSON对象 {"status": "success", "message": "Bark 测试通知发送成功！请检查您的设备"}
                失败：HTTP 400/500 + 错误信息
                    - 400: Device Key为空
                    - 500: 通知系统不可用或发送失败

            频率限制：
                - 使用全局默认限制（60次/分钟，10次/秒）

            异常处理：
                - Device Key为空：返回HTTP 400
                - 通知系统不可用：返回HTTP 500
                - 发送失败：返回HTTP 500

            注意事项：
                - 使用临时配置，不保存到文件
                - 需要NOTIFICATION_AVAILABLE = True
                - Bark服务器需要可访问（网络连通性）
            """
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
                        # 尽量返回更可诊断的错误信息（已在提供者层做脱敏）
                        bark_error = None
                        try:
                            if isinstance(test_event.metadata, dict):
                                bark_error = test_event.metadata.get("bark_error")
                        except Exception:
                            bark_error = None

                        if isinstance(bark_error, dict) and bark_error.get("detail"):
                            detail = str(bark_error.get("detail"))[:300]
                            status_code = bark_error.get("status_code")
                            status_hint = (
                                f"(HTTP {status_code}) " if status_code else ""
                            )
                            return jsonify(
                                {
                                    "status": "error",
                                    "message": f"Bark 通知发送失败：{status_hint}{detail}",
                                }
                            ), 500
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
            """更新通知配置的API端点

            功能说明：
                接收前端通知设置，更新通知管理器和配置文件。

            请求体（JSON）：
                - enabled: 通知总开关
                - webEnabled: Web通知开关
                - autoRequestPermission: 自动请求权限
                - soundEnabled: 声音提示开关
                - soundMute: 静音开关
                - soundVolume: 音量（0-100）
                - mobileOptimized: 移动端优化
                - mobileVibrate: 震动开关
                - barkEnabled: Bark通知开关
                - barkUrl: Bark服务器地址
                - barkDeviceKey: Bark设备密钥
                - barkIcon: 通知图标URL
                - barkAction: 点击动作

            处理逻辑：
                1. 解析JSON请求体
                2. 检查通知系统是否可用
                3. 调用notification_manager.update_config_without_save()更新内存配置
                4. 调用config_mgr.update_section()保存到配置文件
                5. 返回成功响应

            返回值：
                成功：JSON对象 {"status": "success", "message": "通知配置已更新"}
                失败：HTTP 500 + 错误信息

            频率限制：
                - 使用全局默认限制（60次/分钟，10次/秒）

            异常处理：
                - 通知系统不可用：返回HTTP 500
                - 配置更新失败：返回HTTP 500

            副作用：
                - 修改notification_manager内存配置
                - 更新config.jsonc配置文件

            注意事项：
                - soundVolume需要除以100转换为0-1范围
                - 统一保存，避免重复写入文件
                - 需要NOTIFICATION_AVAILABLE = True
            """
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
            """获取当前通知配置的API端点

            功能说明：
                从配置文件读取通知相关配置，返回给前端。

            处理逻辑：
                1. 调用get_config()获取配置管理器
                2. 调用get_section("notification")获取通知配置
                3. 返回JSON响应

            返回值：
                成功：JSON对象 {"status": "success", "config": {...}}
                    - enabled: 通知总开关
                    - web_enabled: Web通知开关
                    - auto_request_permission: 自动请求权限
                    - sound_enabled: 声音提示开关
                    - sound_mute: 静音开关
                    - sound_volume: 音量（0-100）
                    - mobile_optimized: 移动端优化
                    - mobile_vibrate: 震动开关
                    - bark_enabled: Bark通知开关
                    - bark_url: Bark服务器地址
                    - bark_device_key: Bark设备密钥
                    - bark_icon: 通知图标URL
                    - bark_action: 点击动作
                失败：HTTP 500 + 错误信息

            频率限制：
                - 使用全局默认限制（60次/分钟，10次/秒）

            异常处理：
                - 配置读取失败：返回HTTP 500

            注意事项：
                - 配置来自config.jsonc文件
                - 不依赖notification_manager（可能不可用）
            """
            try:
                config_mgr = get_config()
                notification_config = config_mgr.get_section("notification")

                return jsonify({"status": "success", "config": notification_config})

            except Exception as e:
                logger.error(f"获取通知配置失败: {e}")
                return jsonify(
                    {"status": "error", "message": f"获取配置失败: {str(e)}"}
                ), 500

        @self.app.route("/api/get-feedback-prompts", methods=["GET"])
        def get_feedback_prompts_api():
            """获取反馈提示语配置的API端点

            功能说明：
                从配置文件读取反馈提示语配置，返回给前端。

            返回值：
                成功：JSON对象 {"status": "success", "config": {...}}
                    - resubmit_prompt: 错误/超时时返回的提示语
                    - prompt_suffix: 追加到用户反馈末尾的提示语
                失败：HTTP 500 + 错误信息

            使用场景：
                - 前端自动提交时使用配置的默认消息
                - 保持前后端提示语一致
            """
            try:
                config_mgr = get_config()
                feedback_config = config_mgr.get_section("feedback")

                return jsonify(
                    {
                        "status": "success",
                        "config": {
                            "resubmit_prompt": feedback_config.get(
                                "resubmit_prompt",
                                "请立即调用 interactive_feedback 工具",
                            ),
                            "prompt_suffix": feedback_config.get(
                                "prompt_suffix",
                                "\n请积极调用 interactive_feedback 工具",
                            ),
                        },
                    }
                )

            except Exception as e:
                logger.error(f"获取反馈提示语配置失败: {e}")
                return jsonify(
                    {"status": "error", "message": f"获取配置失败: {str(e)}"}
                ), 500

        # 静态文件路由
        @self.app.route("/fonts/<filename>")
        @self.limiter.exempt
        def serve_fonts(filename):
            """提供字体文件的静态资源路由

            功能说明：
                安全地提供fonts目录下的字体文件（woff、woff2、ttf等）。

            参数说明：
                filename: 字体文件名（URL路径参数）

            返回值：
                字体文件的二进制内容（application/font-woff等MIME类型）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - 文件名自动清理，不支持../ 等危险路径
            """
            current_dir = os.path.dirname(os.path.abspath(__file__))
            fonts_dir = os.path.join(current_dir, "fonts")
            return send_from_directory(fonts_dir, filename)

        @self.app.route("/icons/<filename>")
        @self.limiter.exempt
        def serve_icons(filename):
            """提供图标文件的静态资源路由

            功能说明：
                安全地提供icons目录下的图标文件（ico、png、svg等）。

            参数说明：
                filename: 图标文件名（URL路径参数）

            返回值：
                图标文件的二进制内容（image/x-icon、image/png等MIME类型）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - 文件名自动清理，不支持../ 等危险路径
            """
            current_dir = os.path.dirname(os.path.abspath(__file__))
            icons_dir = os.path.join(current_dir, "icons")
            return send_from_directory(icons_dir, filename)

        @self.app.route("/sounds/<filename>")
        @self.limiter.exempt
        def serve_sounds(filename):
            """提供音频文件的静态资源路由

            功能说明：
                安全地提供sounds目录下的音频文件（mp3、wav、ogg等）。

            参数说明：
                filename: 音频文件名（URL路径参数）

            返回值：
                音频文件的二进制内容（audio/mpeg、audio/wav等MIME类型）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - 文件名自动清理，不支持../ 等危险路径
                - 音频文件较大，注意带宽占用
            """
            current_dir = os.path.dirname(os.path.abspath(__file__))
            sounds_dir = os.path.join(current_dir, "sounds")
            return send_from_directory(sounds_dir, filename)

        @self.app.route("/static/css/<filename>")
        @self.limiter.exempt
        def serve_css(filename):
            """提供CSS文件的静态资源路由

            功能说明：
                安全地提供static/css目录下的CSS样式文件。

            参数说明：
                filename: CSS文件名（URL路径参数）

            返回值：
                CSS文件内容（text/css MIME类型）

            【性能优化】缓存策略：
                - 普通 CSS 文件：缓存 1 小时
                - 带版本号的 CSS 文件（?v=xxx）：缓存 1 年

            【性能优化】自动压缩版本选择：
                - 自动检测并优先使用 .min.css 压缩版本
                - 如果请求 main.css，优先返回 main.min.css（如存在）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载/MathJax 等资源被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - CSS文件通过CSP nonce验证安全性
                - 使用版本号参数实现缓存失效控制
            """
            current_dir = os.path.dirname(os.path.abspath(__file__))
            css_dir = os.path.join(current_dir, "static", "css")

            # 【性能优化】自动选择压缩版本
            actual_filename = self._get_minified_file(css_dir, filename, ".css")

            response = send_from_directory(css_dir, actual_filename)

            # 【性能优化】添加缓存控制头
            # 如果 URL 带版本号，使用长期缓存；否则使用短期缓存
            if request.args.get("v"):
                # 带版本号：缓存 1 年（不可变资源）
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            else:
                # 无版本号：缓存 1 小时
                response.headers["Cache-Control"] = "public, max-age=3600"

            return response

        @self.app.route("/static/js/<filename>")
        @self.limiter.exempt
        def serve_js(filename):
            """提供JavaScript文件的静态资源路由

            功能说明：
                安全地提供static/js目录下的JavaScript脚本文件。

            参数说明：
                filename: JavaScript文件名（URL路径参数）

            返回值：
                JavaScript文件内容（application/javascript MIME类型）

            【性能优化】缓存策略：
                - 普通 JS 文件：缓存 1 小时
                - 带版本号的 JS 文件（?v=xxx）：缓存 1 年

            【性能优化】自动压缩版本选择：
                - 自动检测并优先使用 .min.js 压缩版本
                - 如果请求 multi_task.js，优先返回 multi_task.min.js（如存在）

            频率限制：
                - 已豁免（静态资源不做限流，避免首屏加载/MathJax 等资源被 429 影响）

            注意事项：
                - 使用send_from_directory防止路径遍历攻击
                - JavaScript文件通过CSP nonce验证安全性
                - 使用版本号参数实现缓存失效控制
            """
            current_dir = os.path.dirname(os.path.abspath(__file__))
            js_dir = os.path.join(current_dir, "static", "js")

            # 【性能优化】自动选择压缩版本
            actual_filename = self._get_minified_file(js_dir, filename, ".js")

            response = send_from_directory(js_dir, actual_filename)

            # 【性能优化】添加缓存控制头
            # 如果 URL 带版本号，使用长期缓存；否则使用短期缓存
            if request.args.get("v"):
                # 带版本号：缓存 1 年（不可变资源）
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            else:
                # 无版本号：缓存 1 小时
                response.headers["Cache-Control"] = "public, max-age=3600"

            return response

        @self.app.route("/favicon.ico")
        @self.limiter.exempt
        def favicon():
            """提供网站图标的路由

            功能说明：
                提供网站favicon.ico文件，浏览器会自动请求此文件用于标签页图标。

            返回值：
                icon.ico文件的二进制内容（image/x-icon MIME类型）

            处理逻辑：
                1. 构建icon.ico文件路径
                2. 记录调试日志（路径、文件存在性）
                3. 使用send_from_directory返回文件
                4. 设置正确的MIME类型（image/x-icon）
                5. 禁用缓存（no-cache, no-store, must-revalidate）

            频率限制：
                - 已豁免（静态资源不做限流，避免 favicon 请求被 429 影响）

            副作用：
                - 修改响应头部（Content-Type、Cache-Control等）

            注意事项：
                - 禁用缓存确保图标更新立即生效
                - 浏览器每次访问页面都会请求favicon
                - 文件不存在时Flask返回404
            """
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

    def get_html_template(self):
        """读取并处理HTML模板文件

        功能说明：
            读取web_ui.html模板文件，替换内联CSS/JS为外部文件引用，返回处理后的HTML。

        处理逻辑：
            1. 尝试使用importlib.resources读取模板（Python 3.9+，适用于打包环境）
            2. 失败则降级到传统文件路径读取（开发环境）
            3. 若模板不存在，尝试从sys.path查找（打包环境）
            4. 调用_replace_inline_css()替换内联CSS为外部链接
            5. 为 multi_task.js 添加版本号
            6. 返回处理后的HTML

        返回值：
            str: 处理后的HTML模板内容（包含CSP随机数、外部CSS/JS引用）

        异常处理：
            - FileNotFoundError: 返回基本错误页面
            - 其他异常: 返回包含错误信息的页面

        注意事项：
            - 优先使用importlib.resources，兼容打包后的环境
            - 模板路径：templates/web_ui.html
            - 内联CSS/JS替换确保CSP安全策略生效
            - 错误页面是fallback，正常情况不应触发
        """
        try:
            # 优先尝试使用 importlib.resources (Python 3.9+)
            try:
                from importlib import resources

                # 尝试从包中读取资源
                html_content = (
                    resources.files("templates")
                    .joinpath("web_ui.html")
                    .read_text(encoding="utf-8")
                )
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

            # 替换模板变量 {{ csp_nonce }} 为实际的 CSP nonce 值
            html_content = html_content.replace("{{ csp_nonce }}", self.csp_nonce)

            # 替换模板变量 {{ version }} 为项目版本号
            html_content = html_content.replace("{{ version }}", get_project_version())

            # 替换模板变量 {{ github_url }} 为 GitHub 仓库地址
            html_content = html_content.replace("{{ github_url }}", GITHUB_URL)

            # 获取静态资源版本号（基于文件修改时间，解决浏览器缓存问题）
            current_dir = os.path.dirname(os.path.abspath(__file__))
            css_version = self._get_file_version(
                os.path.join(current_dir, "static", "css", "main.css")
            )
            multi_task_version = self._get_file_version(
                os.path.join(current_dir, "static", "js", "multi_task.js")
            )

            # 替换内联CSS为外部CSS文件引用（带版本号）
            css_link = f'<link rel="stylesheet" href="/static/css/main.css?v={css_version}" nonce="{self.csp_nonce}">'
            html_content = self._replace_inline_css(html_content, css_link)

            # 为 multi_task.js 也添加版本号（在 HTML 模板中引用）
            html_content = html_content.replace(
                'src="/static/js/multi_task.js"',
                f'src="/static/js/multi_task.js?v={multi_task_version}"',
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
        self.current_prompt = new_prompt
        self.current_options = new_options if new_options is not None else []
        self.current_task_id = new_task_id
        self.has_content = bool(new_prompt)
        if new_prompt:
            logger.info(f"📝 内容已更新: {new_prompt[:50]}... (task_id: {new_task_id})")
        else:
            logger.info("📝 内容已清空，显示无有效内容页面")

    def _replace_inline_css(self, html_content: str, css_link: str) -> str:
        """替换内联CSS为外部CSS文件引用

        功能说明：
            使用正则表达式匹配HTML中的<style>标签，替换为外部CSS文件链接。

        参数说明：
            html_content: 原始HTML内容（包含内联<style>标签）
            css_link: 外部CSS文件链接标签（如<link rel="stylesheet" href="...">）

        返回值：
            str: 替换后的HTML内容（<style>标签被css_link替换）

        处理逻辑：
            1. 定义正则表达式：r"<style>.*?</style>"（非贪婪匹配）
            2. 使用re.sub()替换所有匹配的<style>标签
            3. 使用re.DOTALL标志，使.匹配换行符

        注意事项：
            - 非贪婪匹配（.*?）避免跨标签匹配
            - DOTALL标志确保匹配多行的<style>内容
            - 替换后CSS需要通过外部文件加载，确保/static/css/路由正确
        """

        # 匹配<style>标签及其内容
        style_pattern = r"<style>.*?</style>"
        # 替换为外部CSS链接
        return re.sub(style_pattern, css_link, html_content, flags=re.DOTALL)

    def _get_minified_file(self, directory: str, filename: str, extension: str) -> str:
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
        minified_path = os.path.join(directory, minified_name)

        # 检查压缩版本是否存在
        if os.path.exists(minified_path):
            return minified_name

        # 压缩版本不存在，返回原始文件名
        return filename

    def _get_file_version(self, file_path: str) -> str:
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
            mtime = os.path.getmtime(file_path)
            # 使用时间戳的后 8 位作为版本号
            return str(int(mtime))[-8:]
        except (OSError, FileNotFoundError):
            return "1"

    def _load_network_security_config(self) -> Dict:
        """加载并验证网络安全配置

        功能说明：
            从配置文件读取网络安全相关配置，用于IP访问控制。
            【优化】加载时进行预验证，确保配置有效性。

        返回值：
            Dict: 验证后的网络安全配置字典，包含以下字段：
                - bind_interface: 绑定的网络接口（验证为有效 IP 或特殊值）
                - allowed_networks: 允许访问的网络列表（验证 CIDR 格式）
                - blocked_ips: 黑名单 IP 列表（验证 IP 格式）
                - enable_access_control: 是否启用访问控制（布尔值）

        处理逻辑：
            1. 调用 get_config() 获取配置管理器
            2. 调用 get_section("network_security") 读取配置
            3. 【优化】调用 validate_network_security_config() 验证配置
            4. 若加载失败，返回默认配置

        验证规则：
            - bind_interface: 必须是有效 IP 或 0.0.0.0/127.0.0.1/localhost
            - allowed_networks: 无效的 CIDR 会被过滤，空列表自动添加本地回环
            - blocked_ips: 无效的 IP 会被过滤
            - enable_access_control: 转换为布尔值

        异常处理：
            - 配置加载失败：记录警告日志，返回默认配置

        默认配置：
            - bind_interface: "0.0.0.0"
            - allowed_networks: 本地回环 + 私有网络段
            - blocked_ips: 空列表
            - enable_access_control: True

        注意事项：
            - 配置来自 config.jsonc 文件
            - 默认配置允许本地和内网访问
            - 生产环境建议自定义配置
            - 绑定 0.0.0.0 时会输出安全警告
        """
        try:
            config_mgr = get_config()
            raw_config = config_mgr.get_section("network_security")
            # 【优化】验证配置
            return validate_network_security_config(raw_config)
        except Exception as e:
            logger.warning(f"无法加载网络安全配置，使用默认配置: {e}")
            return validate_network_security_config({})

    def _is_ip_allowed(self, client_ip: str) -> bool:
        """检查IP是否被允许访问

        功能说明：
            根据网络安全配置验证客户端IP地址是否在允许的网络范围内。

        参数说明：
            client_ip: 客户端IP地址（字符串格式，支持IPv4和IPv6）

        返回值：
            bool: True表示允许访问，False表示拒绝访问

        验证逻辑：
            1. 若enable_access_control=False，直接返回True（禁用访问控制）
            2. 解析client_ip为ip_address对象
            3. 检查黑名单：若IP在blocked_ips中，返回False
            4. 检查白名单：遍历allowed_networks
               - 若是CIDR格式（包含/），解析为IPv4Network/IPv6Network
               - 若IP在网络范围内，返回True
               - 若是单个IP，比较是否相等
            5. 若不在任何白名单中，返回False

        异常处理：
            - AddressValueError: 无效的IP地址，记录警告并返回False
            - ValueError: 无效的网络配置，记录警告并跳过该配置

        注意事项：
            - 支持IPv4和IPv6地址
            - 支持CIDR网络段和单个IP白名单
            - 黑名单优先级高于白名单
            - 无效的IP地址或网络配置会被跳过
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
        print("\n🌐 Web反馈界面已启动")
        # 0.0.0.0 是“监听所有网卡”的服务端绑定地址，但并不适合作为浏览器访问地址。
        # 部分浏览器/环境访问 http://0.0.0.0:PORT 时可能出现异常（例如权限/请求失败）。
        if self.host == "0.0.0.0":
            print(f"📍 监听地址: http://{self.host}:{self.port}")
            print(f"✅ 本机访问（推荐）: http://127.0.0.1:{self.port}")
            print(f"✅ 本机访问（推荐）: http://localhost:{self.port}")
            print(
                f"🔗 SSH端口转发命令: ssh -L {self.port}:localhost:{self.port} user@remote_server"
            )
        else:
            print(f"📍 请在浏览器中打开: http://{self.host}:{self.port}")

        print("🔄 页面将保持打开，可实时更新内容")
        print()

        try:
            self.app.run(
                host=self.host, port=self.port, debug=False, use_reloader=False
            )
        except KeyboardInterrupt:
            pass

        empty_result: FeedbackResult = {
            "user_input": "",
            "selected_options": [],
            "images": [],
        }
        return self.feedback_result or empty_result


def web_feedback_ui(
    prompt: str,
    predefined_options: Optional[List[str]] = None,
    task_id: Optional[str] = None,
    auto_resubmit_timeout: int = 290,
    output_file: Optional[str] = None,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> Optional[FeedbackResult]:
    """启动Web版反馈界面的便捷函数

    功能说明：
        创建WebFeedbackUI实例并启动服务器，收集用户反馈。可选地将结果保存到文件。

    参数说明：
        prompt: 提示文本（Markdown格式）
        predefined_options: 预定义选项列表（可选）
        task_id: 任务ID（可选）
        auto_resubmit_timeout: 自动重新提交超时时间（秒，默认290秒）
        output_file: 输出文件路径（可选，若指定则将结果保存为JSON文件）
        host: 绑定主机地址（默认"0.0.0.0"）
        port: 绑定端口（默认8080）

    返回值：
        Optional[FeedbackResult]: 用户反馈结果字典，包含：
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
    """主程序入口：命令行启动Web反馈界面

    功能说明：
        解析命令行参数，启动Web反馈界面，打印反馈结果。

    命令行参数：
        --prompt: 向用户显示的提示信息（默认"我已经实现了您请求的更改。"）
        --predefined-options: 预定义选项列表，用|||分隔
        --task-id: 任务标识符
        --auto-resubmit-timeout: 自动重新提交超时时间（秒，默认290秒，0表示禁用）
        --output-file: 将反馈结果保存为JSON文件的路径
        --host: Web服务器监听地址（默认"0.0.0.0"）
        --port: Web服务器监听端口（默认8080）

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
