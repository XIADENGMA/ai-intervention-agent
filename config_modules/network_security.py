"""Network Security 配置管理 Mixin。

提供 ConfigManager 中与 network_security 段相关的
校验、读取、写入、增量更新能力。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from ipaddress import AddressValueError, ip_address, ip_network
from typing import TYPE_CHECKING, Any, cast

from enhanced_logging import EnhancedLogger

if TYPE_CHECKING:
    from pathlib import Path
    from threading import RLock

logger = EnhancedLogger(__name__)


class NetworkSecurityMixin:
    """network_security 配置段的校验/读写/缓存管理。"""

    if TYPE_CHECKING:
        _lock: RLock
        config_file: Path
        _original_content: str | None
        _network_security_cache: dict[str, Any] | None
        _network_security_cache_time: float
        _network_security_cache_ttl: float

        def _get_default_config(self) -> dict[str, Any]: ...
        @staticmethod
        def _coerce_bool(value: Any, default: bool = True) -> bool: ...
        def _create_default_config_file(self) -> None: ...
        def _is_toml_file(self) -> bool: ...
        def _save_network_security_toml(self, ns_config: dict[str, Any]) -> str: ...
        def _update_file_mtime(self) -> None: ...
        def invalidate_all_caches(self) -> None: ...
        def _trigger_config_change_callbacks(self) -> None: ...
        def _parse_config_content(self, content: str) -> dict[str, Any]: ...
        def _validate_config_structure(
            self, parsed_config: dict[str, Any], content: str
        ) -> None: ...

    def _validate_network_security_config(self, raw: Any) -> dict[str, Any]:
        """强校验并归一化 network_security（与文档/模板对齐，兼容旧字段）"""
        default_ns = cast(
            dict[str, Any],
            self._get_default_config().get("network_security", {}),
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
                    if "/" in t:
                        blocked_list.append(str(ip_network(t, strict=False)))
                    else:
                        blocked_list.append(str(ip_address(t)))
                except (AddressValueError, Exception):
                    logger.warning(f"blocked_ips 无效条目已忽略: {t}")
        else:
            logger.warning("blocked_ips 不是列表，使用默认值")
            blocked_list = []

        blocked_list = _dedupe_keep_order(blocked_list)

        access_enabled = self._coerce_bool(
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

    def _atomic_write_config(self, new_content: str) -> None:
        """原子写入配置文件（tempfile + os.replace），与 _save_config_immediate 保持一致"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        orig_mode = None
        if hasattr(os, "fchmod"):
            try:
                orig_mode = os.stat(str(self.config_file)).st_mode
            except OSError:
                pass

        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            dir=str(self.config_file.parent),
        )
        try:
            if orig_mode is not None:
                os.fchmod(fd, orig_mode)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(self.config_file))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _save_network_security_config_immediate(self, validated_ns: dict[str, Any]):
        """将 network_security 原子写回配置文件（不走通用保存逻辑，避免被排除）"""
        try:
            if not self.config_file.exists():
                self._create_default_config_file()
        except Exception:
            pass

        content = ""
        try:
            if self.config_file.exists():
                content = self.config_file.read_text(encoding="utf-8")
        except Exception as e:
            raise RuntimeError(f"读取配置文件失败: {e}") from e

        # TOML 格式
        if self._is_toml_file():
            base = content or (self._original_content or "")
            if base:
                new_content = self._save_network_security_toml(validated_ns)
            else:
                import tomlkit as _tk

                doc = _tk.document()
                doc["network_security"] = validated_ns
                new_content = _tk.dumps(doc)
            try:
                self._atomic_write_config(new_content)
            except Exception as e:
                raise RuntimeError(f"写入配置文件失败: {e}") from e
            with self._lock:
                self._original_content = new_content
            self._update_file_mtime()
            return

        # JSON 格式（降级兼容）
        try:
            full = json.loads(content) if content.strip() else {}
            if not isinstance(full, dict):
                full = {}
        except Exception:
            full = {}
        full["network_security"] = validated_ns
        new_content = json.dumps(full, indent=2, ensure_ascii=False)
        try:
            self._atomic_write_config(new_content)
        except Exception as e:
            raise RuntimeError(f"写入配置文件失败: {e}") from e
        with self._lock:
            self._original_content = new_content
        self._update_file_mtime()

    def set_network_security_config(
        self, config: dict[str, Any], save: bool = True, trigger_callbacks: bool = True
    ) -> None:
        """设置并持久化 network_security（强校验 + 单一路径写回）"""
        validated = self._validate_network_security_config(config)
        if save:
            self._save_network_security_config_immediate(validated)
        with self._lock:
            self._network_security_cache = validated
            self._network_security_cache_time = time.monotonic()
        self.invalidate_all_caches()
        if trigger_callbacks:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def update_network_security_config(
        self, updates: dict[str, Any], save: bool = True, trigger_callbacks: bool = True
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

        with self._lock:
            self._network_security_cache = validated
            self._network_security_cache_time = time.monotonic()

        self.invalidate_all_caches()
        if trigger_callbacks:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def get_network_security_config(self) -> dict[str, Any]:
        """从文件读取 network_security 配置（带 30 秒缓存，失败返回默认配置）"""
        current_time = time.monotonic()
        with self._lock:
            if (
                self._network_security_cache is not None
                and current_time - self._network_security_cache_time
                < self._network_security_cache_ttl
            ):
                logger.debug("使用缓存的 network_security 配置")
                return self._network_security_cache

        try:
            if not self.config_file.exists():
                default_config = self._get_default_config()
                raw_result = cast(
                    dict[str, Any], default_config.get("network_security", {})
                )
                result = self._validate_network_security_config(raw_result)
                with self._lock:
                    self._network_security_cache = result
                    self._network_security_cache_time = current_time
                return result

            with open(self.config_file, encoding="utf-8") as f:
                content = f.read()

            full_config = self._parse_config_content(content)

            self._validate_config_structure(full_config, content)

            network_security_config = cast(
                dict[str, Any], full_config.get("network_security", {})
            )

            if not network_security_config:
                default_config = self._get_default_config()
                network_security_config = cast(
                    dict[str, Any], default_config.get("network_security", {})
                )
                logger.debug("配置文件中未找到network_security，使用默认配置")

            validated = self._validate_network_security_config(network_security_config)

            with self._lock:
                self._network_security_cache = validated
                self._network_security_cache_time = current_time
                logger.debug("已更新 network_security 配置缓存")

            return validated

        except Exception as e:
            logger.error(f"读取 network_security 配置失败: {e}", exc_info=True)
            with self._lock:
                if self._network_security_cache is not None:
                    logger.warning(
                        "读取 network_security 配置失败，返回缓存的上一次成功配置",
                        exc_info=True,
                    )
                    return self._network_security_cache

            default_config = self._get_default_config()
            raw_default = cast(
                dict[str, Any], default_config.get("network_security", {})
            )
            return self._validate_network_security_config(raw_default)
