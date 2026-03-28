"""mDNS 生命周期 Mixin — 从 WebFeedbackUI 提取。

封装 mDNS/DNS-SD 服务的发现、注册、注销逻辑，
由 WebFeedbackUI 通过 MRO 继承。
"""

from __future__ import annotations

import inspect
import socket
from typing import TYPE_CHECKING, Any

from config_manager import get_config
from enhanced_logging import EnhancedLogger
from web_ui_mdns_utils import (
    MDNS_DEFAULT_HOSTNAME,
    MDNS_SERVICE_TYPE_HTTP,
    detect_best_publish_ipv4,
    normalize_mdns_hostname,
)

if TYPE_CHECKING:
    from flask import Flask

logger = EnhancedLogger(__name__)


class MdnsMixin:
    """mDNS/Zeroconf 服务发布与注销。"""

    if TYPE_CHECKING:
        app: Flask
        host: str
        port: int
        _mdns_zeroconf: Any
        _mdns_service_info: Any
        _mdns_hostname: str | None
        _mdns_publish_ip: str | None

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
        enabled_raw = mdns_config.get("enabled")
        if isinstance(enabled_raw, bool):
            return enabled_raw
        return self.host not in {"127.0.0.1", "localhost", "::1"}

    def _start_mdns_if_needed(self) -> None:
        """启动 mDNS 发布（失败则降级，不影响 Web UI 启动）"""
        if self._mdns_zeroconf is not None:
            return

        mdns_config = self._get_mdns_config()
        if not self._should_enable_mdns(mdns_config):
            return

        if self.host in {"127.0.0.1", "localhost", "::1"}:
            logger.warning(
                "mDNS 已配置启用，但 bind_interface 为本地回环地址，外部设备无法访问，已跳过发布"
            )
            return

        try:
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
            kwargs: dict[str, Any] = {}
            try:
                params = inspect.signature(zc.register_service).parameters
                if "allow_name_change" in params:
                    kwargs["allow_name_change"] = True
                elif "allow_rename" in params:
                    kwargs["allow_rename"] = True
            except Exception:
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
