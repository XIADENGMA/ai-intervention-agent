"""安全策略 Mixin — 从 WebFeedbackUI 提取。

提供 IP 访问控制、CSP 安全头注入、网络安全配置加载等方法，
由 WebFeedbackUI 通过 MRO 继承。
"""

from __future__ import annotations

import functools
import json
import re
import secrets
import warnings
from collections.abc import Callable, Collection
from ipaddress import (
    AddressValueError,
    IPv4Address,
    IPv6Address,
    ip_address,
    ip_network,
)
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from flask import Response, abort, g, has_request_context, request
from flask.typing import ResponseReturnValue

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.web_ui_mdns_utils import (
    MDNS_DEFAULT_HOSTNAME,
    normalize_mdns_hostname,
)
from ai_intervention_agent.web_ui_validators import validate_network_security_config

if TYPE_CHECKING:
    from flask import Flask

logger = EnhancedLogger(__name__)

_WILDCARD_BIND_HOSTS: frozenset[str] = frozenset({"0.0.0.0", "::", "[::]"})
_LOOPBACK_TRUSTED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")
_DEFAULT_ALLOWED_NETWORKS: tuple[str, ...] = ("127.0.0.0/8", "::1/128")
_MISSING_CSP_NONCE = object()
_MISSING_APP_CONFIG = object()


def _normalize_trusted_host_candidate(value: object) -> str | None:
    """Return a Flask ``TRUSTED_HOSTS`` exact host value, or ``None``.

    The input may be a hostname, IP literal, host:port, bracketed IPv6 literal,
    or an absolute URL such as ``https://ai.example.com:8443``. Wildcard bind
    addresses are excluded because they are listen addresses, not request
    authority values.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None

    host = ""
    if "://" in raw:
        try:
            host = urlsplit(raw).hostname or ""
        except ValueError:
            return None
    elif raw.startswith("["):
        end = raw.find("]")
        if end == -1:
            return None
        host = raw[1:end]
    elif raw.count(":") == 1:
        maybe_host, maybe_port = raw.rsplit(":", 1)
        host = maybe_host if maybe_port.isdigit() else raw
    else:
        host = raw

    host = host.strip().lower()
    if not host:
        return None
    if host.startswith("."):
        return None
    host = host.rstrip(".")
    if "*" in host:
        return None
    if host in _WILDCARD_BIND_HOSTS:
        return None

    try:
        parsed_ip = ip_address(host)
    except ValueError:
        return host
    if parsed_ip.version == 6:
        return f"[{parsed_ip.compressed}]"
    return str(parsed_ip)


def build_trusted_hosts(
    *,
    host: str,
    mdns_hostname: str | None = MDNS_DEFAULT_HOSTNAME,
    external_base_url: str = "",
    configured_trusted_hosts: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Build the concrete host allowlist for Flask ``TRUSTED_HOSTS``."""
    candidates: list[object] = [*_LOOPBACK_TRUSTED_HOSTS, host]

    normalized_mdns = normalize_mdns_hostname(mdns_hostname)
    if normalized_mdns:
        candidates.append(normalized_mdns)
    if external_base_url:
        candidates.append(external_base_url)
    if configured_trusted_hosts:
        candidates.extend(configured_trusted_hosts)

    trusted_hosts: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_trusted_host_candidate(candidate)
        if normalized is None or normalized in seen:
            continue
        trusted_hosts.append(normalized)
        seen.add(normalized)
    return trusted_hosts


_SAFE_HTTP_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})
# GET handlers that read *and clear* state. A cross-site ``<img src=...>`` runs
# them just as well as a form runs a POST handler, so they are treated like writes.
_STATE_CONSUMING_GET_PATHS: frozenset[str] = frozenset({"/api/feedback"})


def _may_change_state(method: str, path: str) -> bool:
    """Does a request with this method and path run a handler that changes state?

    ``OPTIONS`` is answered by Flask / CORS itself and never reaches a view; every
    other method except GET / HEAD is a write; GET / HEAD count only for the paths
    in ``_STATE_CONSUMING_GET_PATHS``.
    """
    method = method.upper()
    if method == "OPTIONS":
        return False
    return method not in _SAFE_HTTP_METHODS or path in _STATE_CONSUMING_GET_PATHS


def _origin_parts(value: str) -> tuple[str, str] | None:
    """``(scheme, host[:port])`` of an origin or base URL; ``None`` if it is not an http(s) origin.

    The host is lower-cased and the scheme's default port dropped, so
    ``http://Example.com:80`` and ``http://example.com`` compare equal. ``null``
    (a sandboxed frame, a cross-origin redirect chain) and non-http schemes such
    as ``vscode-webview://`` give ``None``.
    """
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    default_port = {"http": 80, "https": 443}.get(scheme)
    if default_port is None or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == default_port:
        return scheme, host
    return scheme, f"{host}:{port}"


def _origin_is_allowed(
    origin: str,
    host: str,
    allowed_origins: Collection[str | re.Pattern[str]],
) -> bool:
    """Is ``origin`` the Web UI's own origin (same ``Host``) or in ``allowed_origins``?"""
    parts = _origin_parts(origin)
    for entry in allowed_origins:
        if isinstance(entry, re.Pattern):
            if entry.match(origin):
                return True
        elif parts is not None and _origin_parts(entry) == parts:
            return True
    if parts is None:
        return False
    host_parts = _origin_parts(f"{parts[0]}://{host}")
    return host_parts is not None and host_parts[1] == parts[1]


def is_cross_origin_write(
    *,
    method: str,
    origin: str | None,
    fetch_site: str | None,
    host: str,
    allowed_origins: Collection[str | re.Pattern[str]] = (),
    path: str = "",
) -> bool:
    """Should this request be refused because a page of another origin caused it? (R787)

    A page on any web site can make the visitor's browser send a ``POST`` to
    ``http://127.0.0.1:<port>``: a form with ``enctype="multipart/form-data"`` or
    ``application/x-www-form-urlencoded`` needs no CORS preflight, and CORS only
    decides whether the page may *read* the answer, not whether the server acts on
    the request. ``/api/submit`` takes exactly those two body types, so such a
    page could answer the agent's question in the user's name.

    Requests that cannot change state (``GET`` / ``HEAD`` / ``OPTIONS``, except the
    read-and-clear ``GET /api/feedback``) are never refused. For the others, in
    this order:

    * ``Sec-Fetch-Site: same-origin`` / ``none`` is the browser's own statement
      (a page cannot set it) that the request came from this very origin: allowed,
      whatever a proxy did to ``Host``.
    * Neither ``Origin`` nor ``Sec-Fetch-Site``: not a browser (the MCP server's
      httpx, ``curl``, Node ``fetch`` in the VS Code extension host): allowed.
    * ``Sec-Fetch-Site`` without ``Origin``: a browser calling a request
      cross-site, with nothing to identify it by: refused.
    * Otherwise the ``Origin`` must be this server's own (same authority as
      ``Host``) or one of ``allowed_origins`` (the CORS allow-list: the page's own
      ``localhost`` / ``127.0.0.1`` origins and the VS Code webview). ``null`` is
      refused.
    """
    if not _may_change_state(method, path):
        return False
    site = (fetch_site or "").strip().lower()
    if site in ("same-origin", "none"):
        return False
    origin = (origin or "").strip()
    if not origin:
        return bool(site)
    return not _origin_is_allowed(origin, host, allowed_origins)


def _bracketed_address(value: str) -> IPv4Address | IPv6Address | None:
    """The address inside a leading ``[...]``; anything after ``]`` is ignored."""
    if not value.startswith("["):
        return None
    end = value.find("]")
    if end == -1:
        return None
    try:
        return ip_address(value[1:end])
    except ValueError:
        return None


def _host_is_trusted_with_ipv6(original: Callable[..., bool]) -> Callable[..., bool]:
    """Wrap Werkzeug's ``host_is_trusted`` so a bracketed IPv6 entry can match.

    Werkzeug 3.1.9 keeps a ``Host`` header such as ``[::1]:8080`` in one piece
    but still cuts every allowlist entry at its first colon, so a ``[::1]`` entry
    turns into ``[`` and nothing matches it (pallets/werkzeug#3312: fixed on
    main, not released yet). The wrapper only adds a way to be trusted: it
    returns what Werkzeug returns, and when that is a refusal it accepts a
    ``Host`` value that Werkzeug itself validates, that is a bracketed IPv6
    literal, and that names the same address as a bracketed entry of the list.
    """

    @functools.wraps(original)
    def host_is_trusted(
        hostname: str | None, trusted_list: Collection[str] | None = None
    ) -> bool:
        if original(hostname, trusted_list):
            return True
        if not hostname:
            return False
        host_address = _bracketed_address(hostname)
        if host_address is None or not original(hostname, None):
            return False
        entries = [trusted_list] if isinstance(trusted_list, str) else trusted_list
        return any(_bracketed_address(entry) == host_address for entry in entries or ())

    return host_is_trusted


_WERKZEUG_HOST_CHECK = "host_is_trusted"


def ensure_ipv6_trusted_hosts_support() -> bool:
    """Make ``TRUSTED_HOSTS`` usable for bracketed IPv6 literals; ``True`` if patched.

    Probes Werkzeug with the loopback entry this module always trusts and wraps
    ``werkzeug.sansio.utils.host_is_trusted`` only when the probe is refused, so
    a release that matches (or that fixed pallets/werkzeug#3312) is left alone,
    and so is our own wrapper: calling this again is a no-op. A helper that is
    missing or fails the probe is left alone too.
    """
    from werkzeug.sansio import utils as werkzeug_utils

    current: Any = getattr(werkzeug_utils, _WERKZEUG_HOST_CHECK, None)
    try:
        with warnings.catch_warnings():
            # Werkzeug 3.2 deprecates this helper; probing it must stay silent.
            warnings.simplefilter("ignore")
            if current("[::1]:80", ["[::1]"]):
                return False
    except Exception:
        return False
    setattr(werkzeug_utils, _WERKZEUG_HOST_CHECK, _host_is_trusted_with_ipv6(current))
    logger.info(
        "Werkzeug 拒绝带方括号的 IPv6 受信主机，已启用兼容包装（pallets/werkzeug#3312）"
    )
    return True


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

        @self.app.before_request
        def reject_cross_origin_writes() -> ResponseReturnValue | None:
            if not _may_change_state(request.method, request.path):
                return None
            origin = request.headers.get("Origin")
            fetch_site = request.headers.get("Sec-Fetch-Site")
            if not is_cross_origin_write(
                method=request.method,
                origin=origin,
                fetch_site=fetch_site,
                host=request.host,
                allowed_origins=self._allowed_write_origins(),
                path=request.path,
            ):
                return None
            logger.warning(
                f"拒绝跨源写请求: {request.method} {request.path}"
                f"（Origin={(origin or '')[:200]!r}, Host={request.host!r}, "
                f"Sec-Fetch-Site={fetch_site!r}）；Web UI 若在改写 Host 的反向代理之后，"
                "请把 web_ui.external_base_url 设为浏览器访问的对外地址"
            )
            return Response(
                json.dumps(
                    {
                        "success": False,
                        "error": "cross_origin_write_blocked",
                        "message": (
                            "State-changing requests must come from the Web UI's "
                            "own origin. Behind a reverse proxy that rewrites Host, "
                            "set web_ui.external_base_url to the public address."
                        ),
                    }
                ),
                status=403,
                mimetype="application/json",
            )

        @self.app.after_request
        def add_security_headers(response: Response) -> Response:
            nonce = getattr(g, "csp_nonce", "")
            response.headers["Content-Security-Policy"] = self._build_csp_header(nonce)
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"

            response.headers["X-XSS-Protection"] = "0"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

            response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
            response.headers["Permissions-Policy"] = (
                "geolocation=(), microphone=(), camera=(), "
                "payment=(), usb=(), magnetometer=(), gyroscope=()"
            )

            path = request.path
            cache_policy: str | None = None
            if path.startswith(("/static/js/", "/static/css/", "/static/locales/")):
                if request.args.get("v"):
                    cache_policy = "public, max-age=31536000, immutable"
                else:
                    cache_policy = "public, max-age=86400"
            elif path.startswith(("/static/lottie/", "/fonts/")):
                cache_policy = "public, max-age=2592000, immutable"
            elif path.startswith("/sounds/") or (
                path.startswith("/icons/") and not path.endswith(".ico")
            ):
                cache_policy = "public, max-age=604800"

            if cache_policy is not None:
                # The long lifetimes are for files that were served. An error
                # (a 429 for a font, a 404 for a missing extension, a 5xx) given
                # the same header is kept by the browser for a day, or a year
                # for a ``?v=`` URL, so one failed request turned into a file
                # that stayed missing until the cache was cleared by hand.
                response.headers["Cache-Control"] = (
                    cache_policy if response.status_code < 400 else "no-store"
                )

            return response

    def _allowed_write_origins(self) -> list[str | re.Pattern[str]]:
        """Origins besides the server's own that may send state-changing requests.

        The CORS allow-list set up in ``WebFeedbackUI.__init__``, plus the
        ``external_base_url`` the operator gave (constructor argument or the live
        ``web_ui.external_base_url`` setting, which also covers the WSGI factory):
        behind a proxy that rewrites ``Host``, that is the origin the browser uses.
        """
        allowed: list[str | re.Pattern[str]] = list(
            getattr(self, "_write_origin_allowlist", ())
        )
        external_urls = [getattr(self, "external_base_url", "")]
        try:
            external_urls.append(
                get_config().get_section("web_ui").get("external_base_url", "")
            )
        except Exception as exc:
            logger.debug(f"读取 web_ui.external_base_url 失败，只用构造参数: {exc}")
        for url in external_urls:
            if isinstance(url, str) and _origin_parts(url) is not None:
                allowed.append(url)
        return allowed

    def _get_csp_nonce(self) -> str:
        """获取当前请求的 CSP nonce；非请求上下文时生成临时随机值。"""
        try:
            if has_request_context():
                nonce = getattr(g, "csp_nonce", _MISSING_CSP_NONCE)
                if nonce is not _MISSING_CSP_NONCE:
                    return str(nonce)
                return secrets.token_urlsafe(16)
        except RuntimeError:
            pass
        return secrets.token_urlsafe(16)

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
        app = getattr(self, "app", None)
        app_config = getattr(app, "config", _MISSING_APP_CONFIG)
        if app_config is not _MISSING_APP_CONFIG and cast("Any", app_config).get(
            "TESTING"
        ):
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

            blocked_ips_raw = cfg.get("blocked_ips")
            blocked_ips = (
                blocked_ips_raw if isinstance(blocked_ips_raw, (list, tuple)) else ()
            )
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

            allowed_networks = cfg.get("allowed_networks", _DEFAULT_ALLOWED_NETWORKS)
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
            logger.warning(f"无效的IP地址 {client_ip}: {e}")
            return False

    @staticmethod
    def _parse_forwarded_for(forwarded_for: str) -> str:
        """从 X-Forwarded-For 中提取首个客户端 IP。"""
        if not forwarded_for:
            return ""
        return forwarded_for.partition(",")[0].strip()

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

        if self._should_trust_forwarded_for(remote_addr):
            forwarded_for = str(environ.get("HTTP_X_FORWARDED_FOR", "")).strip()
            forwarded_ip = self._parse_forwarded_for(forwarded_for)
            if forwarded_ip:
                return forwarded_ip

        return remote_addr
