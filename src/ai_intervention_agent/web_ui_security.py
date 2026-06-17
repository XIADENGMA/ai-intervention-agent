"""安全策略 Mixin — 从 WebFeedbackUI 提取。

提供 IP 访问控制、CSP 安全头注入、网络安全配置加载等方法，
由 WebFeedbackUI 通过 MRO 继承。
"""

from __future__ import annotations

import secrets
from ipaddress import AddressValueError, ip_address, ip_network
from typing import TYPE_CHECKING, Any

from flask import Response, abort, g, request
from flask.typing import ResponseReturnValue

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.web_ui_validators import validate_network_security_config

if TYPE_CHECKING:
    from flask import Flask

logger = EnhancedLogger(__name__)


def get_config() -> Any:
    """Lazy proxy kept patchable for tests and security helpers."""
    from ai_intervention_agent.config_manager import get_config as _get_config

    return _get_config()


class SecurityMixin:
    """IP 访问控制 + HTTP 安全头 + CSP nonce 管理。"""

    if TYPE_CHECKING:
        app: Flask
        network_security_config: dict[str, Any]
        host: str

    # ------------------------------------------------------------------
    # CSP 模板预拼接（R23.5）
    # ------------------------------------------------------------------
    # CSP 头里只有 ``script-src`` 的 nonce 因请求而变，其余 9 个 directive
    # 全部是不变常量。R23.5 之前每次 ``after_request`` 都把 10 段字符串
    # 重新 concat 一次（CPython 会用 ``BUILD_STRING`` 字节码合成，但仍要
    # 重新 alloc + 10 次 memcpy）；改成把不变部分预拼接到模块加载阶段，
    # hot path 上每个请求只做 3 段 concat（prefix + nonce + suffix）。
    #
    # why
    # - ``after_request`` 在每个请求（包括静态文件 304）都跑：``/api/tasks``
    #   2 s 轮询、``/static/js/main.<hash>.js`` 多个并发 GET、SSE 心跳……
    #   单进程稳态 50-200 req/s，省 10-15 段 PyUnicode 的 alloc/copy
    #   对应 ~250-400 ns/req，每秒省 12-80 µs CPU。
    # - 让 ``add_security_headers`` 的字节码长度从 ~10 个 BUILD_STRING
    #   token 缩短到 1 个普通 ``+`` 表达式，profile 上更容易看清 hot path。
    # - 维护成本低：CSP directive 加新条目时只需要在对应常量里加一行，
    #   nonce 占位逻辑被 ``_build_csp_header`` 显式锁住，不会出现「多段
    #   拼接漏拼 nonce」的回归。
    _CSP_PREFIX: str = "default-src 'self'; script-src 'self' 'nonce-"
    _CSP_SUFFIX: str = (
        "'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "worker-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "object-src 'none'"
    )

    @classmethod
    def _build_csp_header(cls, nonce: str) -> str:
        """拼出 ``Content-Security-Policy`` 头值（R23.5 hot path 三段 concat）。

        故意写成 ``classmethod`` 而不是模块级函数：让子类（极小概率出现的
        ``SecurityMixin`` 派生类）能 override 常量来调整 directive，而不需要
        重写整个 ``setup_security_headers``。
        """
        return cls._CSP_PREFIX + nonce + cls._CSP_SUFFIX

    # ------------------------------------------------------------------
    # 安全头 & 访问控制 hook
    # ------------------------------------------------------------------

    def setup_security_headers(self) -> None:
        """注册 before_request / after_request 钩子：IP 访问控制 + 安全头注入。

        R306: 同时注册 ``context_processor``, 让所有 ``render_template()``
        调用自动拿到 ``csp_nonce`` 变量, 不再需要每个 route 手动传 ctx。
        历史 bug: ``offline.html`` 通过 ``render_template("offline.html")``
        渲染时没传 ``csp_nonce``, Jinja2 ``{{ csp_nonce }}`` 默认渲染为空
        字符串, 浏览器 CSP 阻止其 ``<script nonce="">`` 执行, "Retry"
        按钮永不工作。改用 context_processor 后, 任何模板都自动获得当前
        请求的 nonce, 防同类 bug 再生。
        """

        @self.app.context_processor
        def _inject_csp_nonce() -> dict[str, str]:
            """让所有模板自动拿到 ``csp_nonce`` (R306 防 offline.html 类 bug)。"""
            return {"csp_nonce": getattr(g, "csp_nonce", "")}

        @self.app.before_request
        def check_ip_and_generate_nonce() -> ResponseReturnValue | None:
            self._ensure_network_security_config_loaded()
            client_ip = self._get_request_client_ip(request.environ)
            if not self._is_ip_allowed(client_ip):
                logger.warning(f"拒绝来自 {client_ip} 的访问请求")
                abort(403)
            g.csp_nonce = secrets.token_urlsafe(16)
            if self.app.config.get("TESTING"):
                return None
            ensure_hooks = getattr(
                self, "_ensure_base_config_runtime_hooks_registered", None
            )
            if callable(ensure_hooks):
                ensure_hooks()

        @self.app.after_request
        def add_security_headers(response: Response) -> Response:
            nonce = getattr(g, "csp_nonce", "")
            response.headers["Content-Security-Policy"] = self._build_csp_header(nonce)
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"
            # ``X-XSS-Protection`` 是 IE / 早期 Chrome 的"反射 XSS auditor"
            # 开关，已被 [MDN 标记为废弃](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-XSS-Protection)：
            # 该 auditor 自身被发现可被滥用造成 XSS（攻击者诱导 auditor
            # 误删合法脚本来打开新攻击面）；现代浏览器已经全部移除实现。
            # OWASP Secure Headers Project / Mozilla Observatory 现在
            # 推荐 **明确写 ``0``** —— 即"显式关闭"，让 CSP 接管唯一的
            # XSS 防御路径，避免遗留浏览器（IE11 / 老 Chrome）跑过期
            # auditor。历史值 ``1; mode=block`` 在现代浏览器是 no-op，
            # 在某些遗留 browser 上反而**降低**安全性，所以 ``0`` 是
            # **更安全**的选择，不是降级。
            response.headers["X-XSS-Protection"] = "0"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            # ``Cross-Origin-Opener-Policy: same-origin`` 让窗口和它的
            # cross-origin opener 互相隔离，关闭 ``window.opener`` 句柄
            # —— 这是 Spectre 类侧信道攻击和 tabnabbing 的标准防御
            # （[MDN 指南](https://developer.mozilla.org/en-US/docs/Web/HTTP/Cross-Origin-Opener-Policy)）。
            # 我们的 Web UI 没有合法的 cross-origin opener 用例（VSCode
            # webview 走 vscode-webview:// 协议有自己的隔离层），所以
            # ``same-origin`` 是 zero-cost 的安全提升。**不**加 ``CORP``
            # 因为 vscode-webview 的资源加载策略目前没法显式标注 origin。
            response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
            response.headers["Permissions-Policy"] = (
                "geolocation=(), microphone=(), camera=(), "
                "payment=(), usb=(), magnetometer=(), gyroscope=()"
            )

            # ----------------------------------------------------------
            # 静态资源缓存策略（R56 整理后）
            # ----------------------------------------------------------
            # Flask 下 ``after_request`` 在 route handler 之后跑，所以这里
            # 设置的 ``Cache-Control`` 会**覆盖** route 级 ``serve_css`` /
            # ``serve_js`` 等手写的同名 header。我们统一以 hook 为唯一权威，
            # route 级保留同值的 header 仅作 belt-and-suspenders（hook 出
            # bug 时 route 级仍能托底），实际生效以本表为准：
            #
            # | 路径前缀                  | 带 ?v=                | 不带 ?v=         |
            # |---------------------------|------------------------|------------------|
            # | /static/js, /static/css   | 1 year immutable       | 1 day            |
            # | /static/locales (R56 加) | 1 year immutable       | 1 day            |
            # | /static/lottie, /fonts    | 30 days immutable      | 30 days immutable|
            # | /sounds, /icons (非 .ico) | 1 week                 | 1 week           |
            #
            # 不在表中的资源（``/manifest.webmanifest`` / ``/favicon.ico`` /
            # ``/notification-service-worker.js``）由 route 级显式设置，hook
            # 不命中其路径前缀，所以保留 route 级的语义化值（manifest=1h、
            # favicon=no-cache、SW=no-cache）。
            path = request.path
            if path.startswith(("/static/js/", "/static/css/", "/static/locales/")):
                if request.args.get("v"):
                    response.headers["Cache-Control"] = (
                        "public, max-age=31536000, immutable"
                    )
                else:
                    response.headers["Cache-Control"] = "public, max-age=86400"
            elif path.startswith(("/static/lottie/", "/fonts/")):
                response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
            elif path.startswith("/sounds/") or (
                path.startswith("/icons/") and not path.endswith(".ico")
            ):
                response.headers["Cache-Control"] = "public, max-age=604800"

            return response

    # ------------------------------------------------------------------
    # CSP nonce
    # ------------------------------------------------------------------

    def _get_csp_nonce(self) -> str:
        """获取当前请求的 CSP nonce；非请求上下文时生成临时随机值。"""
        from flask import has_request_context

        try:
            if has_request_context():
                return getattr(g, "csp_nonce", secrets.token_urlsafe(16))
        except RuntimeError:
            pass
        return secrets.token_urlsafe(16)

    # ------------------------------------------------------------------
    # 网络安全配置
    # ------------------------------------------------------------------

    def _load_network_security_config(self) -> dict:
        """加载并验证 network_security 配置，失败时返回默认值。"""
        try:
            config_mgr = get_config()
            raw_config = config_mgr.get_section("network_security")
            return validate_network_security_config(raw_config)
        except Exception as e:
            logger.warning(f"无法加载网络安全配置，使用默认配置: {e}", exc_info=True)
            return validate_network_security_config({})

    def _ensure_network_security_config_loaded(self) -> None:
        """Load network security config once, just before request enforcement.

        R325 audit: this is a single-attribute lazy load for
        ``network_security_config`` only. It has a non-default-config guard,
        a TESTING short-circuit, and an instance lock, so it is not the
        multi-attribute mock-pollution pattern handled by the notification
        lazy loaders.
        """
        if getattr(self, "_network_security_config_loaded_from_config", False):
            return
        default_config = validate_network_security_config({})
        if getattr(self, "network_security_config", default_config) != default_config:
            self._network_security_config_loaded_from_config = True
            return
        if getattr(getattr(self, "app", None), "config", {}).get("TESTING"):
            self._network_security_config_loaded_from_config = True
            return
        lock = getattr(self, "_network_security_config_lock", None)
        if lock is None:
            self.network_security_config = self._load_network_security_config()
            self._network_security_config_loaded_from_config = True
            return
        with lock:
            if getattr(self, "_network_security_config_loaded_from_config", False):
                return
            if (
                getattr(self, "network_security_config", default_config)
                != default_config
            ):
                self._network_security_config_loaded_from_config = True
                return
            self.network_security_config = self._load_network_security_config()
            self._network_security_config_loaded_from_config = True

    # ------------------------------------------------------------------
    # IP 访问控制
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_addr(addr_str: str):
        """规范化 IP 地址，将 IPv4-mapped IPv6 转换为纯 IPv4。"""
        addr = ip_address(addr_str)
        if hasattr(addr, "ipv4_mapped") and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return addr

    def _is_ip_allowed(self, client_ip: str) -> bool:
        """根据白名单/黑名单验证客户端 IP 是否允许访问。"""
        cfg = (
            self.network_security_config
            if isinstance(self.network_security_config, dict)
            else {}
        )
        if not cfg.get("access_control_enabled", True):
            return True

        try:
            client_addr = self._normalize_addr(client_ip)

            blocked_ips = cfg.get("blocked_ips", [])
            for blocked_entry in blocked_ips:
                try:
                    if "/" in blocked_entry:
                        if client_addr in ip_network(blocked_entry, strict=False):
                            logger.warning(
                                f"IP {client_ip} 在黑名单网段 {blocked_entry} 中，拒绝访问"
                            )
                            return False
                    else:
                        if client_addr == self._normalize_addr(blocked_entry):
                            logger.warning(f"IP {client_ip} 在黑名单中，拒绝访问")
                            return False
                except (AddressValueError, ValueError, TypeError):
                    continue

            allowed_networks = cfg.get("allowed_networks", ["127.0.0.0/8", "::1/128"])
            for network_str in allowed_networks:
                try:
                    if "/" in network_str:
                        if client_addr in ip_network(network_str, strict=False):
                            return True
                    else:
                        if client_addr == self._normalize_addr(network_str):
                            return True
                except (AddressValueError, ValueError, TypeError) as e:
                    logger.warning(f"无效的网络配置 {network_str}: {e}")
                    continue

            logger.warning(f"IP {client_ip} 不在允许的网络范围内，拒绝访问")
            return False

        except (AddressValueError, ValueError, TypeError) as e:
            # R39 修正：``ipaddress.ip_address()`` 对 ``"abc"`` 这种非 IP 字符串
            # 抛的是 *普通* ``ValueError``，**不是** ``AddressValueError``
            # （AddressValueError 仅用于 ``IPv4Address`` / ``IPv6Address`` 直接
            # 构造时的协议判定失败，``ip_address`` 工厂函数只用基类 ValueError
            # 包装："X does not appear to be an IPv4 or IPv6 address"）。
            #
            # 历史代码只 catch ``AddressValueError``，后果是当 ``REMOTE_ADDR``
            # 异常字段（被反代 / WSGI 层污染成空串、IPv6 格式残缺、或者
            # ``REMOTE_ADDR=None`` 这种 ``TypeError`` 路径）漏到这里时，
            # 整个 ``before_request`` hook 直接 raise，Flask 兜成 500 给 client，
            # 而 *访问控制日志却不会写* —— 运维看到的是 500 风暴而不是
            # "拒掉 1 个非法 IP"，定位成本极高。
            #
            # fail-closed 一致性：黑名单 / 白名单内层循环已经是
            # ``(AddressValueError, ValueError, TypeError)`` 全覆盖，外层
            # 拓宽到一致策略，整个安全判定不再有 raise 路径。
            logger.warning(f"无效的IP地址 {client_ip}: {e}")
            return False

    # ------------------------------------------------------------------
    # X-Forwarded-For / 客户端 IP
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_forwarded_for(forwarded_for: str) -> str:
        """从 X-Forwarded-For 中提取首个客户端 IP。"""
        if not forwarded_for:
            return ""
        return forwarded_for.split(",")[0].strip()

    @classmethod
    def _should_trust_forwarded_for(cls, remote_addr: str) -> bool:
        """仅信任来自本机反向代理的 X-Forwarded-For。"""
        if not remote_addr:
            return False
        try:
            return cls._normalize_addr(remote_addr).is_loopback
        except (AddressValueError, ValueError):
            return False

    def _get_request_client_ip(self, environ: dict[str, Any]) -> str:
        """获取用于访问控制的客户端 IP。"""
        remote_addr = str(environ.get("REMOTE_ADDR", "")).strip()
        forwarded_for = str(environ.get("HTTP_X_FORWARDED_FOR", "")).strip()

        if self._should_trust_forwarded_for(remote_addr):
            forwarded_ip = self._parse_forwarded_for(forwarded_for)
            if forwarded_ip:
                return forwarded_ip

        return remote_addr
