"""mDNS / DNS-SD 辅助工具 — 从 web_ui.py 提取。

R23.2：``psutil`` 为 lazy 导入——唯一使用点 ``_list_non_loopback_ipv4``
只在 mDNS 启用且枚举网卡时触发（daemon thread），cold-start 主线程
100% 不需要；延迟 import 可省 ~3 ms 启动成本，失败仍走空列表降级。
"""

from __future__ import annotations

import socket
from ipaddress import AddressValueError, ip_address
from typing import Any

from ai_intervention_agent.enhanced_logging import EnhancedLogger

logger = EnhancedLogger(__name__)


MDNS_DEFAULT_HOSTNAME = "ai.local"
MDNS_SERVICE_TYPE_HTTP = "_http._tcp.local."


def normalize_mdns_hostname(value: Any) -> str:
    """规范化 mDNS 主机名。"""
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

    return bool(
        any(
            token in name
            for token in ("tun", "tap", "wg", "tailscale", "zerotier", "vpn", "ppp")
        )
    )


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
    """枚举本机非回环 IPv4 地址（优先物理网卡）。"""
    try:
        import psutil

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
    """自动探测适合对外发布的 IPv4 地址。"""
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
