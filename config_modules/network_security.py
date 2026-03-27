"""Network Security 配置管理 Mixin。

提供 ConfigManager 中与 network_security 段相关的
校验、读取、写入、增量更新能力。
"""

from __future__ import annotations

import json
import time
from ipaddress import AddressValueError, ip_address, ip_network
from typing import Any, Dict, cast

from enhanced_logging import EnhancedLogger

logger = EnhancedLogger(__name__)


class NetworkSecurityMixin:
    """network_security 配置段的校验/读写/缓存管理。"""

    def _validate_network_security_config(self, raw: Any) -> Dict[str, Any]:
        """强校验并归一化 network_security（与文档/模板对齐，兼容旧字段）"""
        default_ns = cast(
            Dict[str, Any],
            self._get_default_config().get("network_security", {}),  # type: ignore[attr-defined]
        )

        if not isinstance(raw, dict):
            raw = {}

        bind_raw = raw.get(
            "bind_interface", default_ns.get("bind_interface", "0.0.0.0")
        )
        bind = "127.0.0.1"
        try:
            if isinstance(bind_raw, str):
                s = bind_raw.strip()
                if s in ("0.0.0.0", "127.0.0.1", "localhost", "::1", "::"):
                    bind = s
                else:
                    bind = str(ip_address(s))
            else:
                bind = str(ip_address(str(bind_raw).strip()))
        except Exception:
            logger.warning(
                f"network_security.bind_interface 无效，回退为 127.0.0.1: {bind_raw}"
            )
            bind = "127.0.0.1"

        def _dedupe_keep_order(items: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for x in items:
                if x in seen:
                    continue
                seen.add(x)
                out.append(x)
            return out

        allowed_raw = raw.get(
            "allowed_networks", default_ns.get("allowed_networks", [])
        )
        allowed_list: list[str] = []
        if isinstance(allowed_raw, list):
            for item in allowed_raw:
                if not isinstance(item, str):
                    continue
                t = item.strip()
                if not t:
                    continue
                try:
                    if "/" in t:
                        allowed_list.append(str(ip_network(t, strict=False)))
                    else:
                        allowed_list.append(str(ip_address(t)))
                except Exception:
                    logger.warning(f"allowed_networks 无效条目已忽略: {t}")
        else:
            logger.warning("allowed_networks 不是列表，使用默认值")
            allowed_list = []

        allowed_list = _dedupe_keep_order(allowed_list)
        if not allowed_list:
            allowed_list = ["127.0.0.0/8", "::1/128"]

        blocked_raw = raw.get("blocked_ips", default_ns.get("blocked_ips", []))
        blocked_list: list[str] = []
        if isinstance(blocked_raw, list):
            for item in blocked_raw:
                if not isinstance(item, str):
                    continue
                t = item.strip()
                if not t:
                    continue
                try:
                    blocked_list.append(str(ip_address(t)))
                except AddressValueError:
                    logger.warning(f"blocked_ips 无效条目已忽略: {t}")
                except Exception:
                    logger.warning(f"blocked_ips 无效条目已忽略: {t}")
        else:
            logger.warning("blocked_ips 不是列表，使用默认值")
            blocked_list = []

        blocked_list = _dedupe_keep_order(blocked_list)

        access_enabled = self._coerce_bool(  # type: ignore[attr-defined]
            raw.get(
                "access_control_enabled",
                raw.get(
                    "enable_access_control",
                    default_ns.get("access_control_enabled", True),
                ),
            ),
            default=True,
        )

        return {
            "bind_interface": bind,
            "allowed_networks": allowed_list,
            "blocked_ips": blocked_list,
            "access_control_enabled": access_enabled,
        }

    def _save_network_security_config_immediate(self, validated_ns: Dict[str, Any]):
        """将 network_security 写回配置文件（不走通用保存逻辑，避免被排除）"""
        try:
            if not self.config_file.exists():  # type: ignore[attr-defined]
                self._create_default_config_file()  # type: ignore[attr-defined]
        except Exception:
            pass

        content = ""
        try:
            if self.config_file.exists():  # type: ignore[attr-defined]
                content = self.config_file.read_text(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception as e:
            raise RuntimeError(f"读取配置文件失败: {e}") from e

        # TOML 格式
        if self._is_toml_file():  # type: ignore[attr-defined]
            base = content or (self._original_content or "")  # type: ignore[attr-defined]
            if base:
                new_content = self._save_network_security_toml(validated_ns)  # type: ignore[attr-defined]
            else:
                import tomlkit as _tk

                doc = _tk.document()
                doc["network_security"] = validated_ns
                new_content = _tk.dumps(doc)
            try:
                self.config_file.write_text(new_content, encoding="utf-8")  # type: ignore[attr-defined]
            except Exception as e:
                raise RuntimeError(f"写入配置文件失败: {e}") from e
            with self._lock:  # type: ignore[attr-defined]
                self._original_content = new_content  # type: ignore[attr-defined]
            self._update_file_mtime()  # type: ignore[attr-defined]
            return

        # JSON 格式（非 JSONC）
        if not self._is_jsonc_file():  # type: ignore[attr-defined]
            try:
                full = json.loads(content) if content.strip() else {}
                if not isinstance(full, dict):
                    full = {}
            except Exception:
                full = {}
            full["network_security"] = validated_ns
            new_content = json.dumps(full, indent=2, ensure_ascii=False)
            try:
                self.config_file.write_text(new_content, encoding="utf-8")  # type: ignore[attr-defined]
            except Exception as e:
                raise RuntimeError(f"写入配置文件失败: {e}") from e
            with self._lock:  # type: ignore[attr-defined]
                self._original_content = new_content  # type: ignore[attr-defined]
            self._update_file_mtime()  # type: ignore[attr-defined]
            return

        # JSONC 格式（向后兼容）
        base_content = content
        if not base_content and self._original_content:  # type: ignore[attr-defined]
            base_content = self._original_content  # type: ignore[attr-defined]
        if not base_content:
            full = {"network_security": validated_ns}
            new_content = json.dumps(full, indent=2, ensure_ascii=False)
            try:
                self.config_file.write_text(new_content, encoding="utf-8")  # type: ignore[attr-defined]
            except Exception as e:
                raise RuntimeError(f"写入配置文件失败: {e}") from e
            with self._lock:  # type: ignore[attr-defined]
                self._original_content = new_content  # type: ignore[attr-defined]
            self._update_file_mtime()  # type: ignore[attr-defined]
            return

        lines = base_content.split("\n")
        result_lines = lines.copy()
        ns_range = self._find_network_security_range(lines)  # type: ignore[attr-defined]

        if ns_range[0] == -1:
            from config_manager import parse_jsonc

            try:
                full_cfg = parse_jsonc(base_content)
                if not isinstance(full_cfg, dict):
                    full_cfg = {}
            except Exception:
                full_cfg = {}
            full_cfg["network_security"] = validated_ns
            new_content = json.dumps(full_cfg, indent=2, ensure_ascii=False)
            try:
                self.config_file.write_text(new_content, encoding="utf-8")  # type: ignore[attr-defined]
            except Exception as e:
                raise RuntimeError(f"写入配置文件失败: {e}") from e
            with self._lock:  # type: ignore[attr-defined]
                self._original_content = new_content  # type: ignore[attr-defined]
            self._update_file_mtime()  # type: ignore[attr-defined]
            return

        self._jsonc_process_config_section_only_in_range(  # type: ignore[attr-defined]
            validated_ns, result_lines, ns_range
        )
        new_content = "\n".join(result_lines)
        try:
            self.config_file.write_text(new_content, encoding="utf-8")  # type: ignore[attr-defined]
        except Exception as e:
            raise RuntimeError(f"写入配置文件失败: {e}") from e
        with self._lock:  # type: ignore[attr-defined]
            self._original_content = new_content  # type: ignore[attr-defined]
        self._update_file_mtime()  # type: ignore[attr-defined]

    def set_network_security_config(
        self, config: Dict[str, Any], save: bool = True, trigger_callbacks: bool = True
    ) -> None:
        """设置并持久化 network_security（强校验 + 单一路径写回）"""
        validated = self._validate_network_security_config(config)
        if save:
            self._save_network_security_config_immediate(validated)
        with self._lock:  # type: ignore[attr-defined]
            self._network_security_cache = validated  # type: ignore[attr-defined]
            self._network_security_cache_time = time.time()  # type: ignore[attr-defined]
        self.invalidate_all_caches()  # type: ignore[attr-defined]
        if trigger_callbacks:
            try:
                self._trigger_config_change_callbacks()  # type: ignore[attr-defined]
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def update_network_security_config(
        self, updates: Dict[str, Any], save: bool = True, trigger_callbacks: bool = True
    ) -> None:
        """增量更新并持久化 network_security（只允许白名单字段）"""
        if not isinstance(updates, dict):
            raise ValueError("network_security 更新必须是 dict")

        current = self.get_network_security_config()
        merged = dict(current)

        for k, v in updates.items():
            if k in ("bind_interface", "allowed_networks", "blocked_ips"):
                merged[k] = v
            elif k in ("access_control_enabled", "enable_access_control"):
                merged["access_control_enabled"] = v
            else:
                logger.warning(f"忽略未知的 network_security 字段: {k}")

        validated = self._validate_network_security_config(merged)
        if save:
            self._save_network_security_config_immediate(validated)

        with self._lock:  # type: ignore[attr-defined]
            self._network_security_cache = validated  # type: ignore[attr-defined]
            self._network_security_cache_time = time.time()  # type: ignore[attr-defined]

        self.invalidate_all_caches()  # type: ignore[attr-defined]
        if trigger_callbacks:
            try:
                self._trigger_config_change_callbacks()  # type: ignore[attr-defined]
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def get_network_security_config(self) -> Dict[str, Any]:
        """从文件读取 network_security 配置（带 30 秒缓存，失败返回默认配置）"""
        current_time = time.time()
        with self._lock:  # type: ignore[attr-defined]
            if (
                self._network_security_cache is not None  # type: ignore[attr-defined]
                and current_time - self._network_security_cache_time  # type: ignore[attr-defined]
                < self._network_security_cache_ttl  # type: ignore[attr-defined]
            ):
                logger.debug("使用缓存的 network_security 配置")
                return self._network_security_cache  # type: ignore[attr-defined]

        try:
            if not self.config_file.exists():  # type: ignore[attr-defined]
                default_config = self._get_default_config()  # type: ignore[attr-defined]
                raw_result = cast(
                    Dict[str, Any], default_config.get("network_security", {})
                )
                result = self._validate_network_security_config(raw_result)
                with self._lock:  # type: ignore[attr-defined]
                    self._network_security_cache = result  # type: ignore[attr-defined]
                    self._network_security_cache_time = current_time  # type: ignore[attr-defined]
                return result

            with open(self.config_file, "r", encoding="utf-8") as f:  # type: ignore[attr-defined]
                content = f.read()

            full_config = self._parse_config_content(content)  # type: ignore[attr-defined]

            self._validate_config_structure(full_config, content)  # type: ignore[attr-defined]

            network_security_config = cast(
                Dict[str, Any], full_config.get("network_security", {})
            )

            if not network_security_config:
                default_config = self._get_default_config()  # type: ignore[attr-defined]
                network_security_config = cast(
                    Dict[str, Any], default_config.get("network_security", {})
                )
                logger.debug("配置文件中未找到network_security，使用默认配置")

            validated = self._validate_network_security_config(network_security_config)

            with self._lock:  # type: ignore[attr-defined]
                self._network_security_cache = validated  # type: ignore[attr-defined]
                self._network_security_cache_time = current_time  # type: ignore[attr-defined]
                logger.debug("已更新 network_security 配置缓存")

            return validated

        except Exception as e:
            logger.error(f"读取 network_security 配置失败: {e}", exc_info=True)
            with self._lock:  # type: ignore[attr-defined]
                if self._network_security_cache is not None:  # type: ignore[attr-defined]
                    logger.warning(
                        "读取 network_security 配置失败，返回缓存的上一次成功配置",
                        exc_info=True,
                    )
                    return self._network_security_cache  # type: ignore[attr-defined]

            default_config = self._get_default_config()  # type: ignore[attr-defined]
            raw_default = cast(
                Dict[str, Any], default_config.get("network_security", {})
            )
            return self._validate_network_security_config(raw_default)
