"""mDNS / DNS-SD 辅助工具 — 从 web_ui.py 提取。

包含主机名规范化、虚拟网卡过滤、IPv4 地址探测等纯函数，
由 WebFeedbackUI 的 mDNS 功能调用。
"""

from __future__ import annotations

import socket
from ipaddress import AddressValueError, ip_address
from typing import Any

import psutil

from enhanced_logging import EnhancedLogger

logger = EnhancedLogger(__name__)

# ============================================================================
# 常量
# ============================================================================

MDNS_DEFAULT_HOSTNAME = "ai.local"
MDNS_SERVICE_TYPE_HTTP = "_http._tcp.local."


# ============================================================================
# 主机名
# ============================================================================


def normalize_mdns_hostname(value: Any) -> str:
    """规范化 mDNS 主机名。

    - 非字符串 / 空 → 默认 ai.local
    - 末尾 '.' 移除（zeroconf 内部会追加 FQDN 点号）
    - 不含 '.' 的短名 → 追加 '.local'
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


# ============================================================================
# 网卡 / IPv4 探测
# ============================================================================


def _is_probably_virtual_interface(ifname: str) -> bool:
    """启发式过滤虚拟网卡（避免优先选到 docker0 / veth 等）"""
    name = (ifname or "").lower()
    if name == "lo":
        return True

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

    if any(
        token in name
        for token in ("tun", "tap", "wg", "tailscale", "zerotier", "vpn", "ppp")
    ):
        return True

    return False


def _get_default_route_ipv4() -> str | None:
    """通过路由选择的方式获取"默认出口"IPv4（不实际发包）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
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


def _list_non_loopback_ipv4(prefer_physical: bool = True) -> list[str]:
    """枚举本机非回环 IPv4 地址（优先物理网卡）"""
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception:
        return []

    result: list[str] = []

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

    seen: set[str] = set()
    uniq: list[str] = []
    for ip in result:
        if ip in seen:
            continue
        seen.add(ip)
        uniq.append(ip)

    uniq.sort(key=lambda x: 0 if ip_address(x).is_private else 1)
    return uniq


def detect_best_publish_ipv4(bind_interface: str) -> str | None:
    """自动探测适合对外发布的 IPv4 地址。

    优先级：
    1) bind_interface 为具体 IPv4（非 0.0.0.0/回环）→ 直接使用
    2) 默认路由推断
    3) 物理网卡枚举
    4) 所有非回环地址兜底
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
