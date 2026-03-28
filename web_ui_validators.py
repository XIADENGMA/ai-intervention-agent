"""网络安全配置验证 & 超时校验 — 从 web_ui.py 提取的纯函数。

所有函数均为无状态、无副作用（仅日志）的验证/规范化工具，
可安全地在测试、CLI、配置热更新等场景复用。
"""

from __future__ import annotations

from ipaddress import AddressValueError, ip_address, ip_network
from typing import Any

from config_utils import clamp_value
from enhanced_logging import EnhancedLogger
from server_config import (
    AUTO_RESUBMIT_TIMEOUT_MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN,
)

logger = EnhancedLogger(__name__)

# ============================================================================
# 常量
# ============================================================================

VALID_BIND_INTERFACES = {"0.0.0.0", "127.0.0.1", "localhost", "::1", "::"}

DEFAULT_ALLOWED_NETWORKS = [
    "127.0.0.0/8",
    "::1/128",
    "192.168.0.0/16",
    "10.0.0.0/8",
    "172.16.0.0/12",
]


# ============================================================================
# 超时验证
# ============================================================================


def validate_auto_resubmit_timeout(value: int) -> int:
    """验证并限制 auto_resubmit_timeout 范围。

    - 0 / 负值 → 禁用（返回 0）
    - 低于 AUTO_RESUBMIT_TIMEOUT_MIN → 提升至下限
    - 高于 AUTO_RESUBMIT_TIMEOUT_MAX → 截断至上限
    """
    if value <= 0:
        return 0

    return clamp_value(
        value,
        AUTO_RESUBMIT_TIMEOUT_MIN,
        AUTO_RESUBMIT_TIMEOUT_MAX,
        "auto_resubmit_timeout",
    )


# ============================================================================
# 网络验证
# ============================================================================


def validate_bind_interface(value: object) -> str:
    """验证绑定接口，无效时返回 127.0.0.1"""
    if not value or not isinstance(value, str):
        logger.warning("bind_interface 值无效，使用默认值 127.0.0.1")
        return "127.0.0.1"

    value = value.strip()

    if value in VALID_BIND_INTERFACES:
        if value == "0.0.0.0":
            logger.info("bind_interface 设置为 0.0.0.0（允许所有网络接口）")
        return value

    try:
        ip = ip_address(value)
        if ip.version in (4, 6):
            logger.info(f"bind_interface 设置为自定义地址: {value}")
            return value
    except (AddressValueError, ValueError):
        pass

    logger.warning(f"bind_interface '{value}' 无效，使用默认值 127.0.0.1")
    return "127.0.0.1"


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


def validate_allowed_networks(networks: Any) -> list[str]:
    """验证并过滤 allowed_networks，空列表时添加回环地址。"""
    if not isinstance(networks, list):
        logger.warning("allowed_networks 不是列表，使用默认值")
        return DEFAULT_ALLOWED_NETWORKS.copy()

    valid_networks: list[str] = []
    invalid_networks: list[str] = []

    for network in networks:
        if validate_network_cidr(network):
            valid_networks.append(str(network))
        else:
            invalid_networks.append(str(network))

    if invalid_networks:
        logger.warning(f"以下网络配置无效，已跳过: {', '.join(invalid_networks)}")

    if not valid_networks:
        logger.warning("allowed_networks 为空或全部无效，自动添加本地回环地址")
        valid_networks = ["127.0.0.0/8", "::1/128"]

    return valid_networks


def validate_blocked_ips(ips: Any) -> list[str]:
    """验证并清理 blocked_ips 列表（支持单个 IP 和 CIDR）。"""
    if not isinstance(ips, list):
        return []

    valid_ips: list[str] = []
    invalid_ips: list[str] = []

    for ip in ips:
        if isinstance(ip, str):
            try:
                if "/" in ip:
                    ip_network(ip, strict=False)
                else:
                    ip_address(ip)
                valid_ips.append(ip)
            except (AddressValueError, ValueError):
                invalid_ips.append(ip)
        else:
            invalid_ips.append(str(ip))

    if invalid_ips:
        logger.warning(f"以下黑名单条目无效，已跳过: {', '.join(invalid_ips)}")

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
