"""网络安全配置验证 & 超时校验 — 从 web_ui.py 提取的纯函数。

``network_security`` 里"一条 IP / 网段算不算有效、写成什么样"只在这里判断一次：
Web UI 的访问控制用这些函数，``ConfigManager`` 保存和读取配置时也用它们
（``config_modules.network_security``），两边不会各养一份慢慢走样的拷贝（R843）。
"""

from __future__ import annotations

from ipaddress import AddressValueError, ip_address, ip_network
from typing import Any

from ai_intervention_agent.config_utils import clamp_value
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.runtime_constants import (
    AUTO_RESUBMIT_TIMEOUT_MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN,
)

logger = EnhancedLogger(__name__)


VALID_BIND_INTERFACES = {"0.0.0.0", "127.0.0.1", "localhost", "::1", "::"}

# 配置里没写 bind_interface 时 Web UI 监听的地址：只监听本机（R918）。要让手机、别的电脑访问，
# 自己写 "0.0.0.0"（所有网卡）或某个具体的网卡地址。
DEFAULT_BIND_INTERFACE = "127.0.0.1"

# 白名单为空 / 全部无效时的兜底：只放行本机回环。宁可锁住远程访问，也不在配置写坏时放大范围
LOOPBACK_ALLOWED_NETWORKS = ["127.0.0.0/8", "::1/128"]

DEFAULT_ALLOWED_NETWORKS = [
    *LOOPBACK_ALLOWED_NETWORKS,
    "192.168.0.0/16",
    "10.0.0.0/8",
    "172.16.0.0/12",
]

# 同机反向代理那一层：X-Forwarded-For 里从右数第几项是客户端（R849）。
# 0 = 不信任这个头；1 = 一层代理（最常见，也是没配置时的行为）。
DEFAULT_TRUSTED_PROXY_HOPS = 1
MAX_TRUSTED_PROXY_HOPS = 8


def validate_auto_resubmit_timeout(value: int) -> int:
    """验证并限制 auto_resubmit_timeout 范围。"""
    if value <= 0:
        return 0

    return clamp_value(
        value,
        AUTO_RESUBMIT_TIMEOUT_MIN,
        AUTO_RESUBMIT_TIMEOUT_MAX,
        "auto_resubmit_timeout",
    )


def parse_bind_interface(value: object) -> str | None:
    """监听地址（去掉首尾空白）；不是特殊值 / IP 字面量时返回 ``None``。不记日志。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text in VALID_BIND_INTERFACES:
        return text
    try:
        ip_address(text)
    except ValueError:
        return None
    return text


def validate_bind_interface(value: object) -> str:
    """验证绑定接口，无效时返回 127.0.0.1"""
    if not value or not isinstance(value, str):
        logger.warning("bind_interface 值无效，使用默认值 127.0.0.1")
        return "127.0.0.1"

    parsed = parse_bind_interface(value)
    if parsed is None:
        logger.warning(f"bind_interface '{value.strip()}' 无效，使用默认值 127.0.0.1")
        return "127.0.0.1"

    if parsed == "0.0.0.0":
        logger.info("bind_interface 设置为 0.0.0.0（允许所有网络接口）")
    elif parsed not in VALID_BIND_INTERFACES:
        logger.info(f"bind_interface 设置为自定义地址: {parsed}")
    return parsed


def validate_network_cidr(network_str: Any) -> bool:
    """验证 CIDR 或 IP 格式是否有效"""
    if not network_str or not isinstance(network_str, str):
        return False

    try:
        if "/" in network_str:
            ip_network(network_str, strict=False)
        else:
            ip_address(network_str)
        return True
    except (AddressValueError, ValueError):
        return False


def _normalize_ip_str(addr_str: str) -> str:
    """将 IP 地址字符串规范化（处理 IPv4-mapped IPv6 → IPv4、非标准缩写 → 标准形式）。"""
    addr = ip_address(addr_str)
    if hasattr(addr, "ipv4_mapped") and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return str(addr)


def _canonical_ip_entry(entry: str) -> str:
    """名单里一项（单个 IP 或 CIDR）的规范写法；不是 IP / 网段时抛 ``ValueError``。

    单个 IP 里的 IPv4-mapped IPv6（``::ffff:10.0.0.1``）写成 IPv4：访问控制比较之前对客户端
    地址也是这么处理的，名单里的写法不一致就匹配不上。CIDR 取 ``ip_network(strict=False)``
    的结果（``10.0.0.5/8`` 记成 ``10.0.0.0/8``）。"""
    if "/" in entry:
        return str(ip_network(entry, strict=False))
    return _normalize_ip_str(entry)


def normalize_ip_entries(items: list[Any], field: str) -> list[str]:
    """把 allowed_networks / blocked_ips 这类名单整理成规范、去重、保序的字符串列表。

    - 首尾空白去掉；空串和纯空白静默跳过
    - 不是字符串、不是 IP / 网段的条目跳过，各记一条带字段名 ``field`` 的 WARNING
    - 规范化之后重复的只留第一个（``10.0.0.5/8`` 和 ``10.0.0.0/8`` 是同一项）
    """
    valid: list[str] = []
    seen: set[str] = set()
    for item in items:
        canonical = _judge_ip_entry(item)
        if canonical is None:
            shown = item.strip() if isinstance(item, str) else repr(item)
            logger.warning(f"{field} 无效条目已忽略: {shown}")
            continue
        if canonical and canonical not in seen:
            seen.add(canonical)
            valid.append(canonical)
    return valid


def _judge_ip_entry(item: Any) -> str | None:
    """名单里一项算什么：``normalize_ip_entries`` 和 ``unusable_ip_entries`` 共用这一份判断。

    返回规范写法（能用）；``""``（只有空白，静默跳过）；``None``（不是字符串，或不是 IP / 网段）。
    """
    if not isinstance(item, str):
        return None
    text = item.strip()
    if not text:
        return ""
    try:
        return _canonical_ip_entry(text)
    except ValueError:
        return None


def unusable_ip_entries(items: list[Any]) -> list[int]:
    """名单里 ``normalize_ip_entries`` 会丢掉（并各记一条 WARNING）的条目的位置，从 0 数起。

    只有位置，没有内容：读不懂的那一项可能是贴错了地方的令牌，不该被写进日志。
    """
    return [i for i, item in enumerate(items) if _judge_ip_entry(item) is None]


def validate_allowed_networks(
    networks: Any, *, non_list_fallback: list[str] | None = None
) -> list[str]:
    """验证并规范化 allowed_networks；空列表 / 全部无效时只放行本机回环。

    ``networks`` 不是列表时改用 ``non_list_fallback``（缺省为 ``DEFAULT_ALLOWED_NETWORKS``）。
    ``ConfigManager`` 读写配置文件时传 ``LOOPBACK_ALLOWED_NETWORKS``：文件里写成了字符串之类的
    错误，不该因此放开整个内网。
    """
    if not isinstance(networks, list):
        fallback = (
            DEFAULT_ALLOWED_NETWORKS if non_list_fallback is None else non_list_fallback
        )
        logger.warning(f"allowed_networks 不是列表，改用: {', '.join(fallback)}")
        return fallback.copy()

    valid = normalize_ip_entries(networks, "allowed_networks")
    if not valid:
        if networks:
            logger.warning("allowed_networks 全部无效，自动改为仅本机回环")
        valid = LOOPBACK_ALLOWED_NETWORKS.copy()
    return valid


def validate_blocked_ips(ips: Any) -> list[str]:
    """验证并规范化 blocked_ips（单个 IP 或 CIDR）；不是列表时按空名单处理。"""
    if not isinstance(ips, list):
        if ips is not None:
            logger.warning("blocked_ips 不是列表，已忽略")
        return []
    return normalize_ip_entries(ips, "blocked_ips")


def blocked_ips_problem(ips: Any) -> str | None:
    """``blocked_ips`` 里有 ``validate_blocked_ips`` 会丢掉的东西时，返回一句说明；没有就是 ``None``。

    拦截名单丢掉一项，那个地址就没有被拦住；放行名单丢掉一项只是少放行一个。所以读配置文件的
    一侧（``ConfigManager.get_network_security_config``）遇到这样的名单，不把这一段当成一份能用的
    配置（R920）。没写（``None``）、空列表、只有空白的条目都不是问题。说明里只有类型和位置，
    没有内容：读不懂的那一项可能是贴错了地方的令牌。
    """
    if ips is None:
        return None
    if not isinstance(ips, list):
        return (
            f"不是列表（实际类型 {type(ips).__name__}），"
            '要写成 blocked_ips = ["10.0.0.5", "192.168.9.0/24"]'
        )
    bad = unusable_ip_entries(ips)
    if not bad:
        return None
    where = "、".join(str(i + 1) for i in bad[:5])
    lead = f"第 {where} 项" if len(bad) <= 5 else f"第 {where} 项等共 {len(bad)} 项"
    return f"{lead}不是 IP 地址或网段（名单共 {len(ips)} 项）"


def validate_trusted_hosts(hosts: Any) -> list[str]:
    """Validate explicit Host allowlist entries while preserving hostname form."""
    if not isinstance(hosts, list):
        if hosts is not None:
            logger.warning("trusted_hosts 不是列表，已忽略")
        return []

    valid_hosts: list[str] = []
    invalid_hosts: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        if not isinstance(host, str):
            invalid_hosts.append(str(host))
            continue
        stripped = host.strip()
        if not stripped or "*" in stripped or stripped.startswith("."):
            invalid_hosts.append(str(host))
            continue
        if stripped in seen:
            continue
        valid_hosts.append(stripped)
        seen.add(stripped)

    if invalid_hosts:
        logger.warning(
            f"以下 trusted_hosts 条目无效，已跳过: {', '.join(invalid_hosts)}"
        )
    return valid_hosts


def validate_trusted_proxy_hops(value: Any) -> int:
    """``trusted_proxy_hops``：0 到 ``MAX_TRUSTED_PROXY_HOPS`` 的整数。

    没写（``None``）是 1，不作声；写坏了（布尔、字符串、小数、越界）也按 1 处理并记一条
    WARNING，与没配置时的行为一致（R849）。
    """
    if value is None:
        return DEFAULT_TRUSTED_PROXY_HOPS
    if type(value) is int and 0 <= value <= MAX_TRUSTED_PROXY_HOPS:
        return value
    logger.warning(
        f"network_security.trusted_proxy_hops 必须是 0 到 {MAX_TRUSTED_PROXY_HOPS} "
        f"的整数，已改用默认值 {DEFAULT_TRUSTED_PROXY_HOPS}: {value!r:.40}"
    )
    return DEFAULT_TRUSTED_PROXY_HOPS


def validate_network_security_config(config: Any) -> dict[str, Any]:
    """验证并清理 network_security 配置"""
    if not isinstance(config, dict):
        config = {}

    blocked_ips_raw = config.get("blocked_ips")
    trusted_hosts_raw = config.get("trusted_hosts")

    validated = {
        "bind_interface": validate_bind_interface(
            config.get("bind_interface", DEFAULT_BIND_INTERFACE)
        ),
        "allowed_networks": validate_allowed_networks(
            config.get("allowed_networks", DEFAULT_ALLOWED_NETWORKS)
        ),
        "blocked_ips": validate_blocked_ips(blocked_ips_raw),
        "trusted_hosts": validate_trusted_hosts(trusted_hosts_raw),
        "trusted_proxy_hops": validate_trusted_proxy_hops(
            config.get("trusted_proxy_hops")
        ),
        "access_control_enabled": bool(
            config.get(
                "access_control_enabled",
                config.get("enable_access_control", True),
            )
        ),
    }

    return validated
