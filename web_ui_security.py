"""安全策略 Mixin — 从 WebFeedbackUI 提取。

提供 IP 访问控制、CSP 安全头注入、网络安全配置加载等方法，
由 WebFeedbackUI 通过 MRO 继承。
"""

from __future__ import annotations

import secrets
from ipaddress import AddressValueError, ip_address, ip_network
from typing import TYPE_CHECKING, Any, Dict

from flask import Response, abort, g, request
from flask.typing import ResponseReturnValue

from config_manager import get_config
from enhanced_logging import EnhancedLogger
from web_ui_validators import validate_network_security_config

if TYPE_CHECKING:
    from flask import Flask

logger = EnhancedLogger(__name__)


class SecurityMixin:
    """IP 访问控制 + HTTP 安全头 + CSP nonce 管理。"""

    if TYPE_CHECKING:
        app: Flask
        network_security_config: Dict[str, Any]
        host: str

    # ------------------------------------------------------------------
    # 安全头 & 访问控制 hook
    # ------------------------------------------------------------------

    def setup_security_headers(self) -> None:
        """注册 before_request / after_request 钩子：IP 访问控制 + 安全头注入。"""

        @self.app.before_request
        def check_ip_and_generate_nonce() -> ResponseReturnValue | None:
            client_ip = self._get_request_client_ip(request.environ)
            if not self._is_ip_allowed(client_ip):
                logger.warning(f"拒绝来自 {client_ip} 的访问请求")
                abort(403)
            g.csp_nonce = secrets.token_urlsafe(16)

        @self.app.after_request
        def add_security_headers(response: Response) -> Response:
            nonce = getattr(g, "csp_nonce", "")
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}'; "
                "style-src 'self' 'unsafe-inline'; "
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

            path = request.path
            if path.startswith("/static/js/") or path.startswith("/static/css/"):
                if request.args.get("v"):
                    response.headers["Cache-Control"] = (
                        "public, max-age=31536000, immutable"
                    )
                else:
                    response.headers["Cache-Control"] = "public, max-age=86400"
            elif path.startswith("/static/lottie/"):
                response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
            elif path.startswith("/fonts/"):
                response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
            elif path.startswith("/sounds/"):
                response.headers["Cache-Control"] = "public, max-age=604800"
            elif path.startswith("/icons/") and not path.endswith(".ico"):
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

    def _load_network_security_config(self) -> Dict:
        """加载并验证 network_security 配置，失败时返回默认值。"""
        try:
            config_mgr = get_config()
            raw_config = config_mgr.get_section("network_security")
            return validate_network_security_config(raw_config)
        except Exception as e:
            logger.warning(f"无法加载网络安全配置，使用默认配置: {e}", exc_info=True)
            return validate_network_security_config({})

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

        except AddressValueError as e:
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

    def _get_request_client_ip(self, environ: Dict[str, Any]) -> str:
        """获取用于访问控制的客户端 IP。"""
        remote_addr = str(environ.get("REMOTE_ADDR", "")).strip()
        forwarded_for = str(environ.get("HTTP_X_FORWARDED_FOR", "")).strip()

        if self._should_trust_forwarded_for(remote_addr):
            forwarded_ip = self._parse_forwarded_for(forwarded_for)
            if forwarded_ip:
                return forwarded_ip

        return remote_addr
