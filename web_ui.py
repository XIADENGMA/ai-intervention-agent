"""Web 反馈界面 - Flask Web UI，支持多任务、文件上传、通知、安全机制。"""

import argparse
import inspect
import json
import os
import re
import secrets
import signal
import socket
import sys
import threading
import time
from functools import lru_cache
from ipaddress import (
    AddressValueError,
    ip_address,
    ip_network,
)
from pathlib import Path
from typing import Any, Dict, List, Optional

import markdown
import psutil
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template_string,
    request,
)
from flask.typing import ResponseReturnValue
from flask_compress import Compress
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config_manager import get_config
from config_utils import clamp_value
from enhanced_logging import EnhancedLogger
from server import get_task_queue
from shared_types import FeedbackResult
from web_ui_routes import (
    FeedbackRoutesMixin,
    NotificationRoutesMixin,
    StaticRoutesMixin,
    TaskRoutesMixin,
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
                with open(pyproject_path, "r", encoding="utf-8") as f:
                    content = f.read()
                match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    version = match.group(1)
    except Exception as e:
        logger.warning(f"读取版本号失败: {e}", exc_info=True)

    return version


# ============================================================================
# 前端倒计时超时常量（需与 server.py 保持一致）
# ============================================================================
AUTO_RESUBMIT_TIMEOUT_MIN = 30  # 前端最小倒计时（秒）
AUTO_RESUBMIT_TIMEOUT_MAX = 250  # 前端最大倒计时（秒）【优化】从290→250，预留安全余量
AUTO_RESUBMIT_TIMEOUT_DEFAULT = 240  # 默认前端倒计时（秒）


def validate_auto_resubmit_timeout(value: int) -> int:
    """验证并限制 auto_resubmit_timeout 范围

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
    - 0 表示禁用自动重调（保持不变）
    - 负值转换为 0（禁用）
    - 小于最小值（30秒）调整为最小值
    - 大于最大值（250秒）调整为最大值

    【重构】使用 config_utils.clamp_value 简化边界检查。
    """
    if value <= 0:
        return 0  # 禁用自动重调

    # 【重构】使用 clamp_value 简化边界检查
    return clamp_value(
        value,
        AUTO_RESUBMIT_TIMEOUT_MIN,
        AUTO_RESUBMIT_TIMEOUT_MAX,
        "auto_resubmit_timeout",
    )


# ============================================================================
# feedback 配置热更新：同步已存在任务的倒计时
# ============================================================================

_FEEDBACK_TIMEOUT_CALLBACK_REGISTERED = False
_LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT: int | None = None
# 运行中的 WebFeedbackUI 实例（用于单任务模式兜底热更新）
# 注意：测试里会用 SimpleNamespace 之类的轻量对象模拟，因此这里用 Any 放宽类型约束。
_CURRENT_WEB_UI_INSTANCE: Any | None = None
_NETWORK_SECURITY_CALLBACK_REGISTERED = False
_NETWORK_SECURITY_CALLBACK_LOCK = threading.Lock()


def _get_default_auto_resubmit_timeout_from_config() -> int:
    """从配置文件读取默认 auto_resubmit_timeout（保持向后兼容）"""
    config_mgr = get_config()
    feedback_config = config_mgr.get_section("feedback")
    raw_timeout = feedback_config.get(
        "frontend_countdown",  # 新名称
        feedback_config.get(
            "auto_resubmit_timeout", AUTO_RESUBMIT_TIMEOUT_DEFAULT
        ),  # 旧名称
    )
    try:
        return validate_auto_resubmit_timeout(int(raw_timeout))
    except Exception:
        return AUTO_RESUBMIT_TIMEOUT_DEFAULT


def _sync_existing_tasks_timeout_from_config() -> None:
    """配置变更回调：将新的默认倒计时同步到所有未完成任务"""
    global _LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT
    try:
        new_timeout = _get_default_auto_resubmit_timeout_from_config()
        if _LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT == new_timeout:
            return
        _LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = new_timeout

        task_queue = get_task_queue()
        updated = task_queue.update_auto_resubmit_timeout_for_all(new_timeout)
        if updated > 0:
            logger.info(
                f"配置变更：已将 {updated} 个未完成任务的 auto_resubmit_timeout 同步为 {new_timeout} 秒"
            )

        # 单任务模式兜底：如果当前实例没有显式指定 timeout，则跟随配置更新
        global _CURRENT_WEB_UI_INSTANCE
        inst = _CURRENT_WEB_UI_INSTANCE
        if inst is not None and not getattr(
            inst, "_single_task_timeout_explicit", True
        ):
            try:
                lock = getattr(inst, "_state_lock", None)
                if lock is not None:
                    with lock:
                        inst.current_auto_resubmit_timeout = new_timeout
                else:
                    inst.current_auto_resubmit_timeout = new_timeout
            except Exception:
                # 测试场景可能注入了无锁的 mock 实例；这里兜底不抛异常
                inst.current_auto_resubmit_timeout = new_timeout
    except Exception as e:
        logger.warning(f"配置变更回调执行失败（同步任务倒计时）：{e}", exc_info=True)


def _sync_network_security_from_config() -> None:
    """配置变更回调：同步运行中 Web UI 的 network_security 配置。"""
    global _CURRENT_WEB_UI_INSTANCE
    inst = _CURRENT_WEB_UI_INSTANCE
    if inst is None:
        return
    try:
        loader = getattr(inst, "_load_network_security_config", None)
        if not callable(loader):
            return
        new_cfg = loader()
        if not isinstance(new_cfg, dict):
            return
        lock = getattr(inst, "_state_lock", None)
        if lock is not None:
            with lock:
                inst.network_security_config = new_cfg
        else:
            inst.network_security_config = new_cfg
    except Exception as e:
        logger.warning(f"配置变更回调执行失败（同步网络安全配置）：{e}", exc_info=True)


def _ensure_network_security_hot_reload_callback_registered() -> None:
    """确保仅注册一次 network_security 配置热更新回调（避免重复注册）"""
    global _NETWORK_SECURITY_CALLBACK_REGISTERED
    if _NETWORK_SECURITY_CALLBACK_REGISTERED:
        return
    with _NETWORK_SECURITY_CALLBACK_LOCK:
        if _NETWORK_SECURITY_CALLBACK_REGISTERED:
            return
        try:
            cfg = get_config()
            cfg.register_config_change_callback(_sync_network_security_from_config)
            _NETWORK_SECURITY_CALLBACK_REGISTERED = True
            # 启动时先同步一次（若当前实例已存在）
            _sync_network_security_from_config()
            logger.debug("已注册 network_security 热更新回调（同步访问控制配置）")
        except Exception as e:
            logger.warning(
                f"注册 network_security 配置热更新回调失败（将仅在启动时生效）：{e}",
                exc_info=True,
            )


def _ensure_feedback_timeout_hot_reload_callback_registered() -> None:
    """确保仅注册一次配置热更新回调（避免重复注册）"""
    global _FEEDBACK_TIMEOUT_CALLBACK_REGISTERED
    if _FEEDBACK_TIMEOUT_CALLBACK_REGISTERED:
        return
    try:
        config_mgr = get_config()
        config_mgr.register_config_change_callback(
            _sync_existing_tasks_timeout_from_config
        )
        _FEEDBACK_TIMEOUT_CALLBACK_REGISTERED = True
        # 启动时先同步一次，保证“已经在队列里的任务”也与当前配置一致
        _sync_existing_tasks_timeout_from_config()
        logger.debug(
            "已注册 feedback.auto_resubmit_timeout 热更新回调（同步已存在任务倒计时）"
        )
    except Exception as e:
        logger.warning(
            f"注册 feedback 配置热更新回调失败（将降级为仅对新任务生效）：{e}",
            exc_info=True,
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


def validate_bind_interface(value: object) -> str:
    """验证绑定接口，无效时返回 127.0.0.1"""
    if not value or not isinstance(value, str):
        logger.warning("bind_interface 值无效，使用默认值 127.0.0.1")
        return "127.0.0.1"

    value = value.strip()

    # 特殊值直接通过
    if value in VALID_BIND_INTERFACES:
        if value == "0.0.0.0":
            logger.info(
                "bind_interface 设为 0.0.0.0，将监听所有网络接口。"
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


# ============================================================================
# mDNS / DNS-SD（Zeroconf）辅助函数
# ============================================================================

MDNS_DEFAULT_HOSTNAME = "ai.local"
MDNS_SERVICE_TYPE_HTTP = "_http._tcp.local."


def normalize_mdns_hostname(value: Any) -> str:
    """规范化 mDNS 主机名

    规则：
    - 非字符串 / 空字符串：回退到默认 ai.local
    - 末尾的 '.' 会被移除（zeroconf 内部会要求 FQDN）
    - 不包含 '.' 的短名：自动追加 '.local'
    """
    if not isinstance(value, str):
        return MDNS_DEFAULT_HOSTNAME

    hostname = value.strip()
    if not hostname:
        return MDNS_DEFAULT_HOSTNAME

    if hostname.endswith("."):
        hostname = hostname[:-1]

    if "." not in hostname:
        hostname = f"{hostname}.local"

    return hostname


def _is_probably_virtual_interface(ifname: str) -> bool:
    """启发式过滤虚拟网卡（避免优先选到 docker0 / veth 等）"""
    name = (ifname or "").lower()
    if name == "lo":
        return True

    # 常见虚拟/容器网卡前缀
    if name.startswith(
        (
            "docker",
            "br-",
            "veth",
            "virbr",
            "vmnet",
            "cni",
            "flannel",
            "lxcbr",
            "podman",
        )
    ):
        return True

    # 隧道/VPN（很多实现不会以 tun0 开头，例如 uif-tun / utun0 / tailscale0）
    if any(
        token in name
        for token in ("tun", "tap", "wg", "tailscale", "zerotier", "vpn", "ppp")
    ):
        return True

    return False


def _get_default_route_ipv4() -> Optional[str]:
    """通过路由选择的方式获取“默认出口”IPv4（不实际发包）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # 该 connect 不会真的发送数据包，但会触发路由选择
            s.connect(("8.8.8.8", 80))
            ip = str(s.getsockname()[0])
        ip_obj = ip_address(ip)
        if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified:
            return None
        if ip_obj.version != 4:
            return None
        return ip
    except OSError:
        return None


def _list_non_loopback_ipv4(prefer_physical: bool = True) -> List[str]:
    """枚举本机非回环 IPv4 地址（优先物理网卡）"""
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception:
        return []

    result: List[str] = []

    for ifname, snics in addrs.items():
        if prefer_physical and _is_probably_virtual_interface(ifname):
            continue

        stat = stats.get(ifname)
        if stat is not None and not stat.isup:
            continue

        for snic in snics:
            if snic.family != socket.AF_INET:
                continue

            ip = snic.address
            try:
                ip_obj = ip_address(ip)
            except (AddressValueError, ValueError):
                continue

            if ip_obj.version != 4:
                continue
            if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified:
                continue

            result.append(ip)

    # 去重并保序
    seen = set()
    uniq: List[str] = []
    for ip in result:
        if ip in seen:
            continue
        seen.add(ip)
        uniq.append(ip)

    # RFC1918 私有地址优先
    uniq.sort(key=lambda x: 0 if ip_address(x).is_private else 1)
    return uniq


def detect_best_publish_ipv4(bind_interface: str) -> Optional[str]:
    """自动探测适合对外发布的 IPv4 地址

    优先级：
    1) 若 bind_interface 是一个具体 IPv4（非 0.0.0.0/回环），直接使用它
    2) 通过默认路由推断（优先）
    3) 枚举物理网卡地址（过滤常见虚拟网卡）
    4) 枚举所有非回环地址（兜底）
    """
    try:
        bind_ip = ip_address(bind_interface)
        if (
            bind_ip.version == 4
            and not bind_ip.is_loopback
            and not bind_ip.is_unspecified
            and not bind_ip.is_link_local
        ):
            return bind_interface
    except (AddressValueError, ValueError):
        pass

    candidates = _list_non_loopback_ipv4(prefer_physical=True)
    route_ip = _get_default_route_ipv4()
    if route_ip and route_ip in candidates:
        return route_ip
    if candidates:
        return candidates[0]

    if route_ip:
        return route_ip

    candidates = _list_non_loopback_ipv4(prefer_physical=False)
    if candidates:
        return candidates[0]

    return None


def validate_network_cidr(network_str: Any) -> bool:
    """验证 CIDR 或 IP 格式是否有效"""
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
    """验证并过滤 allowed_networks，空列表时添加回环地址
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
    """验证并清理 network_security 配置"""
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
        "access_control_enabled": bool(
            config.get(
                "access_control_enabled",
                config.get("enable_access_control", True),
            )
        ),
    }

    return validated


class WebFeedbackUI(
    TaskRoutesMixin,
    FeedbackRoutesMixin,
    NotificationRoutesMixin,
    StaticRoutesMixin,
):
    """Web 反馈界面核心类 - Flask 应用、安全策略、API 路由、任务管理。

    路由通过 Mixin 组织：
    - TaskRoutesMixin        — 任务 CRUD（5 个路由）
    - FeedbackRoutesMixin    — 反馈提交/查询（3 个路由）
    - NotificationRoutesMixin — 通知配置/触发（5 个路由）
    - StaticRoutesMixin      — 静态资源（8 个路由）
    核心路由（index / config / health / close）保留在本类。
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
        CORS(self.app)
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

        self.csp_nonce = secrets.token_urlsafe(16)
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

    def setup_security_headers(self) -> None:
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
        def check_ip_access() -> ResponseReturnValue | None:
            """检查IP访问权限（before_request钩子）

            功能说明：
                在每个请求处理前验证客户端IP地址是否在允许的网络范围内。

            验证逻辑：
                1. 默认使用REMOTE_ADDR作为客户端IP
                2. 仅在请求来自本机反向代理时信任HTTP_X_FORWARDED_FOR
                3. 处理代理转发的多IP情况（取第一个IP）
                3. 调用_is_ip_allowed()进行白名单/黑名单验证
                4. 拒绝不合法的IP访问（返回403）

            副作用：
                - 记录被拒绝的IP地址到日志
                - 调用abort(403)中断请求处理

            注意事项：
                - 仅信任来自本机反向代理的 X-Forwarded-For，避免客户端直接伪造
            """
            client_ip = self._get_request_client_ip(request.environ)

            if not self._is_ip_allowed(client_ip):
                logger.warning(f"拒绝来自 {client_ip} 的访问请求")
                abort(403)

        @self.app.after_request
        def add_security_headers(response: Response) -> Response:
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
                "worker-src 'self'; "
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
                - POST /api/notify-new-tasks         - 新任务通知触发（移动端 Bark）
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
        def get_api_config() -> ResponseReturnValue:
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
                            "remaining_time": effective_timeout,  # 单任务模式无创建时间
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
                        "persistent": True,
                        "has_content": False,
                        "initial_empty": True,
                    }
                ), 500

        @self.app.route("/api/close", methods=["POST"])
        def close_interface() -> ResponseReturnValue:
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
        def health_check() -> ResponseReturnValue:
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

        # 路由通过 Mixin 注册（各 Mixin 定义在 web_ui_routes/ 下）
        self._setup_task_routes()
        self._setup_feedback_routes()
        self._setup_notification_routes()
        self._setup_static_routes()

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

    def get_html_template(self) -> str:
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
                current_dir = Path(__file__).resolve().parent
                # 构建模板文件路径
                template_path = current_dir / "templates" / "web_ui.html"

                # 如果模板文件不存在，尝试从父目录查找
                if not template_path.exists():
                    # 可能是在打包后的环境中，尝试从包的安装位置查找
                    import sys

                    for path in sys.path:
                        candidate_path = Path(path) / "templates" / "web_ui.html"
                        if candidate_path.exists():
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
            current_dir = Path(__file__).resolve().parent
            css_version = self._get_file_version(
                current_dir / "static" / "css" / "main.css"
            )
            multi_task_version = self._get_file_version(
                current_dir / "static" / "js" / "multi_task.js"
            )
            theme_version = self._get_file_version(
                current_dir / "static" / "js" / "theme.js"
            )
            app_version = self._get_file_version(
                current_dir / "static" / "js" / "app.js"
            )

            # 替换内联CSS为外部CSS文件引用（带版本号）
            css_link = f'<link rel="stylesheet" href="/static/css/main.css?v={css_version}" nonce="{self.csp_nonce}">'
            html_content = self._replace_inline_css(html_content, css_link)

            # 为 multi_task.js 也添加版本号（在 HTML 模板中引用）
            html_content = html_content.replace(
                'src="/static/js/multi_task.js"',
                f'src="/static/js/multi_task.js?v={multi_task_version}"',
            )

            # 为主题与主应用脚本添加版本号（避免浏览器缓存导致修复不生效，尤其是 ai.local 真机访问）
            html_content = html_content.replace(
                'src="/static/js/theme.js"',
                f'src="/static/js/theme.js?v={theme_version}"',
            )
            html_content = html_content.replace(
                'src="/static/js/app.js"',
                f'src="/static/js/app.js?v={app_version}"',
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
                - access_control_enabled: 是否启用访问控制（布尔值）

        处理逻辑：
            1. 调用 get_config() 获取配置管理器
            2. 调用 get_section("network_security") 读取配置
            3. 【优化】调用 validate_network_security_config() 验证配置
            4. 若加载失败，返回默认配置

        验证规则：
            - bind_interface: 必须是有效 IP 或 0.0.0.0/127.0.0.1/localhost
            - allowed_networks: 无效的 CIDR 会被过滤，空列表自动添加本地回环
            - blocked_ips: 无效的 IP 会被过滤
            - access_control_enabled: 转换为布尔值

        异常处理：
            - 配置加载失败：记录警告日志，返回默认配置

        默认配置：
            - bind_interface: "0.0.0.0"
            - allowed_networks: 本地回环 + 私有网络段
            - blocked_ips: 空列表
            - access_control_enabled: True

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
            logger.warning(f"无法加载网络安全配置，使用默认配置: {e}", exc_info=True)
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
            1. 若access_control_enabled=False，直接返回True（禁用访问控制）
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
        # 快照配置，避免热更新时读到不一致视图
        cfg = (
            self.network_security_config
            if isinstance(self.network_security_config, dict)
            else {}
        )
        if not cfg.get("access_control_enabled", True):
            return True

        try:
            client_addr = ip_address(client_ip)

            # IPv4-mapped IPv6 地址透传：当服务器绑定 :: (dual-stack) 时，
            # IPv4 客户端可能以 ::ffff:x.x.x.x 形式出现，需要提取底层 IPv4
            # 以便与 IPv4 CIDR 规则（如 192.168.0.0/16）正确匹配
            if hasattr(client_addr, "ipv4_mapped") and client_addr.ipv4_mapped:
                client_addr = client_addr.ipv4_mapped

            # 检查黑名单
            blocked_ips = cfg.get("blocked_ips", [])
            for blocked_ip in blocked_ips:
                if str(client_addr) == blocked_ip:
                    logger.warning(f"IP {client_ip} 在黑名单中，拒绝访问")
                    return False

            # 检查白名单网络
            allowed_networks = cfg.get("allowed_networks", ["127.0.0.0/8", "::1/128"])
            for network_str in allowed_networks:
                try:
                    if "/" in network_str:
                        # 网络段
                        network = ip_network(network_str, strict=False)
                        if client_addr in network:
                            return True
                    else:
                        # 单个IP
                        if str(client_addr) == network_str:
                            return True
                except (AddressValueError, ValueError, TypeError) as e:
                    logger.warning(f"无效的网络配置 {network_str}: {e}")
                    continue

            logger.warning(f"IP {client_ip} 不在允许的网络范围内，拒绝访问")
            return False

        except AddressValueError as e:
            logger.warning(f"无效的IP地址 {client_ip}: {e}")
            return False

    @staticmethod
    def _parse_forwarded_for(forwarded_for: str) -> str:
        """从 X-Forwarded-For 中提取首个客户端 IP。"""
        if not forwarded_for:
            return ""
        return forwarded_for.split(",")[0].strip()

    @staticmethod
    def _should_trust_forwarded_for(remote_addr: str) -> bool:
        """仅信任来自本机反向代理的 X-Forwarded-For。"""
        if not remote_addr:
            return False
        try:
            return ip_address(remote_addr).is_loopback
        except AddressValueError:
            return False

    def _get_request_client_ip(self, environ: Dict[str, Any]) -> str:
        """获取用于访问控制的客户端 IP。"""
        remote_addr = str(environ.get("REMOTE_ADDR", "")).strip()
        forwarded_for = str(environ.get("HTTP_X_FORWARDED_FOR", "")).strip()

        if self._should_trust_forwarded_for(remote_addr):
            forwarded_ip = self._parse_forwarded_for(forwarded_for)
            if forwarded_ip:
                return forwarded_ip

        return remote_addr

    def _get_mdns_config(self) -> dict[str, Any]:
        """读取 mdns 配置段（失败则返回空字典）"""
        try:
            cfg = get_config().get_section("mdns")
            return cfg if isinstance(cfg, dict) else {}
        except Exception as e:
            logger.warning(
                f"无法加载 mdns 配置，已降级为不发布 mDNS: {e}", exc_info=True
            )
            return {}

    def _should_enable_mdns(self, mdns_config: dict[str, Any]) -> bool:
        """判断当前是否应启用 mDNS（默认策略：bind_interface 不是 127.0.0.1）"""
        enabled_raw = mdns_config.get("enabled", None)
        if isinstance(enabled_raw, bool):
            return enabled_raw

        # 自动模式：只要 bind_interface 不是本地回环，就启用
        return self.host not in {"127.0.0.1", "localhost", "::1"}

    def _start_mdns_if_needed(self) -> None:
        """启动 mDNS 发布（失败则降级，不影响 Web UI 启动）"""
        if self._mdns_zeroconf is not None:
            return

        mdns_config = self._get_mdns_config()
        if not self._should_enable_mdns(mdns_config):
            return

        # 若服务只监听本地回环，发布 mDNS 没意义（外部无法访问），直接跳过
        if self.host in {"127.0.0.1", "localhost", "::1"}:
            logger.warning(
                "mDNS 已配置启用，但 bind_interface 为本地回环地址，外部设备无法访问，已跳过发布"
            )
            return

        try:
            # 延迟导入，避免测试/极简环境下无 zeroconf 依赖直接崩溃
            from zeroconf import NonUniqueNameException, ServiceInfo, Zeroconf
        except Exception as e:
            logger.error(f"mDNS 功能不可用：无法导入 zeroconf 依赖: {e}", exc_info=True)
            print("mDNS 功能不可用：缺少依赖 zeroconf（请更新依赖/重新安装）。")
            return

        hostname = normalize_mdns_hostname(
            mdns_config.get("hostname", MDNS_DEFAULT_HOSTNAME)
        )
        service_name_raw = mdns_config.get("service_name", "AI Intervention Agent")
        service_name = (
            service_name_raw.strip()
            if isinstance(service_name_raw, str) and service_name_raw.strip()
            else "AI Intervention Agent"
        )

        publish_ip = detect_best_publish_ipv4(self.host)
        if not publish_ip:
            logger.error("mDNS 发布失败：无法探测可发布的内网 IPv4 地址")
            print(
                "mDNS 发布失败：无法探测可发布的内网 IP（已降级为仅通过 IP/localhost 访问）。"
            )
            return

        server_fqdn = f"{hostname}."
        service_fqdn = f"{service_name}.{MDNS_SERVICE_TYPE_HTTP}"
        properties = {
            "path": "/",
            "hostname": hostname,
            "publish_ip": publish_ip,
        }

        info = ServiceInfo(
            MDNS_SERVICE_TYPE_HTTP,
            service_fqdn,
            addresses=[socket.inet_aton(publish_ip)],
            port=self.port,
            properties=properties,
            server=server_fqdn,
        )

        zc = Zeroconf()
        try:
            # 兼容 zeroconf 不同版本的参数命名（allow_name_change / allow_rename）
            # - 实例名冲突时可自动改名，但不会改变 server/hostname
            kwargs: dict[str, Any] = {}
            try:
                params = inspect.signature(zc.register_service).parameters
                if "allow_name_change" in params:
                    kwargs["allow_name_change"] = True
                elif "allow_rename" in params:
                    kwargs["allow_rename"] = True
            except Exception:
                # 签名解析失败则降级为无参数调用
                kwargs = {}

            zc.register_service(info, **kwargs)
        except NonUniqueNameException:
            config_path = None
            try:
                config_path = str(get_config().config_file)
            except Exception:
                config_path = None

            logger.error(
                f"mDNS 发布失败：主机名冲突（{hostname}）。请修改配置中的 mdns.hostname 后重试"
            )
            print(f"mDNS 发布失败：主机名 {hostname} 可能已被局域网中其他设备占用。")
            print(
                "请修改配置中的 mdns.hostname（例如 ai-你的机器名.local），然后重启服务。"
            )
            if config_path:
                print(f"   配置文件: {config_path}")
            try:
                zc.close()
            except Exception:
                pass
            return
        except Exception as e:
            logger.warning(
                f"mDNS 发布失败（已降级，不影响 Web UI）：{e}", exc_info=True
            )
            print(f"mDNS 发布失败：{e}（已降级为仅通过 IP/localhost 访问）。")
            try:
                zc.close()
            except Exception:
                pass
            return

        self._mdns_zeroconf = zc
        self._mdns_service_info = info
        self._mdns_hostname = hostname
        self._mdns_publish_ip = publish_ip

        logger.info(f"mDNS 已发布: http://{hostname}:{self.port} (IP: {publish_ip})")
        print(f"mDNS 已发布: http://{hostname}:{self.port} (IP: {publish_ip})")

    def _stop_mdns(self) -> None:
        """停止 mDNS 发布（尽力而为）"""
        if self._mdns_zeroconf is None:
            return

        try:
            if self._mdns_service_info is not None:
                self._mdns_zeroconf.unregister_service(self._mdns_service_info)
        except Exception as e:
            logger.debug(f"注销 mDNS 服务失败（忽略）：{e}")

        try:
            self._mdns_zeroconf.close()
        except Exception as e:
            logger.debug(f"关闭 mDNS Zeroconf 失败（忽略）：{e}")

        self._mdns_zeroconf = None
        self._mdns_service_info = None
        self._mdns_hostname = None
        self._mdns_publish_ip = None

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
    predefined_options: Optional[List[str]] = None,
    task_id: Optional[str] = None,
    auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    output_file: Optional[str] = None,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> Optional[FeedbackResult]:
    """启动 Web UI（交互反馈界面）的便捷函数

    功能说明：
        创建 WebFeedbackUI 实例并启动服务，收集用户反馈。可选地将结果保存到文件。

    参数说明：
        prompt: 提示文本（Markdown 格式）
        predefined_options: 预定义选项列表（可选）
        task_id: 任务 ID（可选）
        auto_resubmit_timeout: 自动重调倒计时（秒，默认 240 秒；最大 250 秒；0 表示禁用）
        output_file: 输出文件路径（可选；若指定则将结果保存为 JSON 文件）
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
        --auto-resubmit-timeout: 自动重调倒计时（秒，默认 240 秒；最大 250 秒；0 表示禁用）
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
        help="自动重调倒计时（秒；0 表示禁用；最大 250 秒）",
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
