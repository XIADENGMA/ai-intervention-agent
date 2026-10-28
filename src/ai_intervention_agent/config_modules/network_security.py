"""Network Security 配置管理 Mixin。"""

from __future__ import annotations

import json
import time
from datetime import datetime
from ipaddress import ip_address
from typing import TYPE_CHECKING, Any, cast

from ai_intervention_agent.config_utils import atomic_write_text
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.web_ui_validators import (
    DEFAULT_BIND_INTERFACE,
    LOOPBACK_ALLOWED_NETWORKS,
    VALID_BIND_INTERFACES,
    blocked_ips_problem,
    parse_bind_interface,
    validate_allowed_networks,
    validate_blocked_ips,
    validate_trusted_hosts,
    validate_trusted_proxy_hops,
)

if TYPE_CHECKING:
    from pathlib import Path
    from threading import RLock

logger = EnhancedLogger(__name__)


def _clean_api_token(raw: Any) -> str:
    """api_token：去掉空白 / 控制字符；短于 16 字符视作未配置；超过 256 字符截断。

    不是字符串（也不是 ``None`` / 空串）视作未配置并记一条 WARNING。
    """
    if not isinstance(raw, str):
        if raw not in (None, ""):
            logger.warning(
                f"network_security.api_token 不是字符串（{type(raw).__name__}），已视作未配置"
            )
        return ""
    cleaned = raw.strip()
    if cleaned and any(ch.isspace() or ord(ch) < 0x20 for ch in cleaned):
        logger.warning(
            "network_security.api_token 含空白 / 控制字符，已清洗（强烈建议"
            "重新生成一个 base64url / hex 安全 token）"
        )
        cleaned = "".join(ch for ch in cleaned if not (ch.isspace() or ord(ch) < 0x20))
    if cleaned and len(cleaned) < 16:
        logger.warning(
            "network_security.api_token 长度 < 16 字符不安全；已视作未配置。"
            '建议生成 ``python -c "import secrets; print(secrets.token_urlsafe(32))"``'
        )
        cleaned = ""
    if len(cleaned) > 256:
        logger.warning(
            "network_security.api_token 长度 > 256 字符，已截断为前 256（header 限制）"
        )
        cleaned = cleaned[:256]
    return cleaned


def _clean_token_rotated_at(raw: Any) -> str:
    """api_token_rotated_at：只收 UTC 的 ISO-8601 时间戳（以 ``Z`` 或 ``+00:00`` 结尾）。

    其它写法、不是字符串的值都视作未设置，各记一条 WARNING。
    """
    if not isinstance(raw, str):
        if raw not in (None, ""):
            logger.warning(
                f"network_security.api_token_rotated_at 不是字符串"
                f"（{type(raw).__name__}），已视作未设置"
            )
        return ""
    ts = raw.strip()
    if not ts:
        return ""
    if not ts.endswith(("Z", "+00:00")):
        logger.warning(
            f"network_security.api_token_rotated_at 不是 UTC 时间戳"
            f" (应以 'Z' 或 '+00:00' 结尾)，已视作未设置: {ts!r}"
        )
        return ""
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        logger.warning(
            f"network_security.api_token_rotated_at 不是合法"
            f" ISO-8601 时间戳，已视作未设置: {ts!r}"
            f" ({type(exc).__name__})"
        )
        return ""
    return ts


class NetworkSecurityMixin:
    """network_security 配置段的校验/读写/缓存管理。"""

    # 磁盘上的配置文件内容加载失败（语法错误、编码不对、结构不合法）。置位期间所有自动写入都
    # 不碰文件：内存里是默认配置或上一份好配置，把它们写回去会覆盖用户的内容（R783）。
    # 由 ``ConfigManager._load_config`` 维护：只在内容错误、且文件非空时置位（读不到文件的
    # OSError 可能是瞬时的——Windows 上杀毒软件或另一个进程刚好占着文件——一次瞬时错误不该
    # 让之后的保存全部作废；0 字节的文件没有可保护的内容），成功加载（用户修好了文件、或
    # 删掉后重新生成）时清除。定义成类属性，只继承这个 mixin、没走 ``__init__`` 的宿主也读得到
    # 默认值。
    _on_disk_config_invalid: bool = False

    # 眼下正在生效的那一份 network_security：成功读到文件、或成功保存之后放在这里，文件读不出来时
    # 就用它（R915）。它不随 ``invalidate_all_caches()`` 清掉——那个方法的用途是逼下一次重新读文件
    # （热重载、令牌轮换要立刻生效），不是让我们忘掉正在生效的配置；而热重载时文件被改成读不了的
    # 样子，恰恰是最需要它的时候。定义成类属性，理由同上：没走 ``__init__`` 的宿主也读得到默认值。
    _network_security_last_good: dict[str, Any] | None = None

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
        def _validate_config_structure(self, content: str) -> None: ...

    def _validate_network_security_config(self, raw: Any) -> dict[str, Any]:
        """强校验并归一化 network_security（与文档/模板对齐，兼容旧字段）。

        IP / 网段 / Host 名单的逐项判断在 ``web_ui_validators`` 里只有一份（R843），
        这里只决定"哪个值进来、出错时退回什么"，再处理只有这一层认识的 ``api_token`` 两项。
        """
        default_ns_raw = self._get_default_config().get("network_security")
        default_ns = (
            cast(dict[str, Any], default_ns_raw)
            if isinstance(default_ns_raw, dict)
            else {}
        )

        if not isinstance(raw, dict):
            # 文件里写成不是表的 network_security 到不了这里：get_network_security_config 先按
            # “读不出来”处理了（R919）；这一行只给直接调用本方法的人兜底
            raw = {}

        def given_or_default(key: str) -> Any:
            """文件里写了这一项就用文件的，没写才用默认配置的。"""
            return raw[key] if key in raw else default_ns.get(key)

        bind_raw = raw.get(
            "bind_interface", default_ns.get("bind_interface", DEFAULT_BIND_INTERFACE)
        )
        bind = parse_bind_interface(
            bind_raw if isinstance(bind_raw, str) else str(bind_raw)
        )
        if bind is None:
            logger.warning(
                f"network_security.bind_interface 无效，回退为 127.0.0.1: {bind_raw}"
            )
            bind = "127.0.0.1"
        elif bind not in VALID_BIND_INTERFACES:
            # 规范写法：保存下来的文本不随输入的缩写 / 大小写变
            bind = str(ip_address(bind))

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

        api_token = _clean_api_token(
            raw.get("api_token", default_ns.get("api_token", ""))
        )
        rotated_at = _clean_token_rotated_at(
            raw.get("api_token_rotated_at", default_ns.get("api_token_rotated_at", ""))
        )
        if not api_token and rotated_at:
            logger.warning(
                "network_security.api_token 已被撤销（空串）但 api_token_rotated_at"
                f" 仍存在 ({rotated_at!r}); 已自动 cascade-clear 时间戳避免"
                " stale ghost 状态。如果需要保留历史 rotation 记录请使用外部"
                " audit log。"
            )
            rotated_at = ""

        return {
            "bind_interface": bind,
            # 配置里写坏了（不是列表）就只放行本机：不能因为一处笔误放开整个内网
            "allowed_networks": validate_allowed_networks(
                given_or_default("allowed_networks"),
                non_list_fallback=LOOPBACK_ALLOWED_NETWORKS,
            ),
            "blocked_ips": validate_blocked_ips(given_or_default("blocked_ips")),
            "trusted_hosts": validate_trusted_hosts(given_or_default("trusted_hosts")),
            "trusted_proxy_hops": validate_trusted_proxy_hops(
                given_or_default("trusted_proxy_hops")
            ),
            "access_control_enabled": access_enabled,
            "api_token": api_token,
            "api_token_rotated_at": rotated_at,
        }

    def _atomic_write_config(self, new_content: str) -> None:
        """原子写入配置文件（tempfile + os.replace），与 _save_config_immediate 保持一致"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.config_file, new_content, keep_existing_mode=True)

    def _save_network_security_config_immediate(self, validated_ns: dict[str, Any]):
        """将 network_security 原子写回配置文件（不走通用保存逻辑，避免被排除）。"""
        if self._on_disk_config_invalid:
            raise RuntimeError(
                f"配置文件无法解析，为避免覆盖你的内容已拒绝写入: {self.config_file}"
            )
        try:
            if not self.config_file.exists():
                self._create_default_config_file()
        except Exception as e:
            try:
                import logging

                logging.getLogger(__name__).debug(
                    "[R119] _save_network_security_config_immediate "
                    f"_create_default_config_file 失败 (将由后续 read 兜底): "
                    f"{type(e).__name__}: {e}"
                )
            except Exception:
                pass

        content = ""
        try:
            if self.config_file.exists():
                content = self.config_file.read_text(encoding="utf-8-sig")
        except Exception as e:
            raise RuntimeError(f"读取配置文件失败: {e}") from e

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
        self.invalidate_all_caches()
        with self._lock:
            self._network_security_cache = validated
            self._network_security_cache_time = time.monotonic()
            self._network_security_last_good = validated
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
        merged = current.copy()

        for k, v in updates.items():
            if k in (
                "bind_interface",
                "allowed_networks",
                "blocked_ips",
                "trusted_hosts",
                "trusted_proxy_hops",
                "api_token",
                "api_token_rotated_at",
            ):
                merged[k] = v
            elif k in ("access_control_enabled", "enable_access_control"):
                merged["access_control_enabled"] = v
            else:
                logger.warning(f"忽略未知的 network_security 字段: {k}")

        validated = self._validate_network_security_config(merged)
        if save:
            self._save_network_security_config_immediate(validated)

        self.invalidate_all_caches()
        with self._lock:
            self._network_security_cache = validated
            self._network_security_cache_time = time.monotonic()
            self._network_security_last_good = validated

        if trigger_callbacks:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def get_network_security_config(self) -> dict[str, Any]:
        """从文件读取 network_security 配置（带 30 秒缓存）。

        文件不存在或没有内容：默认值。文件读不出来、``network_security`` 写成了不是表的东西、或
        ``blocked_ips`` 里有读不懂的东西：见 ``_network_security_when_unreadable``（上一份好配置，
        没有就只放行本机）。
        """
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
                raw_result_obj = default_config.get("network_security")
                raw_result = (
                    cast(dict[str, Any], raw_result_obj)
                    if isinstance(raw_result_obj, dict)
                    else {}
                )
                result = self._validate_network_security_config(raw_result)
                with self._lock:
                    self._network_security_cache = result
                    self._network_security_cache_time = current_time
                return result

            # utf-8-sig：兼容带 BOM 的配置文件，见 ConfigManager._load_config（R784）
            with open(self.config_file, encoding="utf-8-sig") as f:
                content = f.read()

            full_config = self._parse_config_content(content)

            # 只拒绝文件本身的损坏；值写坏了不让整个文件作废，逐项退回安全的值（R913）
            self._validate_config_structure(content)

            network_security_obj = full_config.get("network_security")
            if network_security_obj is not None and not isinstance(
                network_security_obj, dict
            ):
                # 写了，但不是表：不知道用户想要什么，和读不出来的文件一样不能放开任何东西（R919）。
                # 只写类型不写内容：那一行可能是贴错了地方的令牌。（None 是 JSON 里的 null，
                # 和没写一样，走下面的默认值）
                return self._network_security_when_unreadable(
                    ValueError(
                        "network_security 不是表（table），实际类型 "
                        f"{type(network_security_obj).__name__}；要写成 [network_security] "
                        "再在下面写各项"
                    )
                )
            network_security_config = (
                cast(dict[str, Any], network_security_obj)
                if isinstance(network_security_obj, dict)
                else {}
            )

            # 拦截名单里有读不懂的东西：丢掉它，那个地址就没有被拦住。放行名单丢掉一项只是少放行一个，
            # 这里是多放行一个，所以和读不出来的文件一样，不能放开任何东西（R920）。
            block_list_problem = blocked_ips_problem(
                network_security_config.get("blocked_ips")
            )
            if block_list_problem is not None:
                return self._network_security_when_unreadable(
                    ValueError(
                        f"network_security.blocked_ips {block_list_problem}；"
                        "读不懂的地址拦不住，这一段先不当成一份能用的配置"
                    )
                )

            if not network_security_config:
                default_config = self._get_default_config()
                default_network_security_obj = default_config.get("network_security")
                network_security_config = (
                    cast(dict[str, Any], default_network_security_obj)
                    if isinstance(default_network_security_obj, dict)
                    else {}
                )
                logger.debug("配置文件中未找到network_security，使用默认配置")

            validated = self._validate_network_security_config(network_security_config)

            with self._lock:
                self._network_security_cache = validated
                self._network_security_cache_time = current_time
                self._network_security_last_good = validated
                logger.debug("已更新 network_security 配置缓存")

            return validated

        except Exception as e:
            return self._network_security_when_unreadable(e)

    def _network_security_when_unreadable(self, error: Exception) -> dict[str, Any]:
        """文件存在、有内容、却读不出来（TOML 语法错误、重复的键、编码不对、没有权限），或者
        ``network_security`` 写成了不是表的东西（字符串、数字、数组……）、或 ``blocked_ips`` 里有
        读不懂的东西（不是列表、有不是 IP / 网段的条目）时用哪一份（R915、R919、R920）。

        不知道用户想要什么，就不能放开任何东西：

        - 之前读到过好的（服务已经在跑）：继续用它。编辑器自动保存下来的半截文件，不该在两秒内
          清空黑名单、把整个内网放进来，也不该在文件修好之前一直开着；
        - 没有（进程刚启动）：只监听本机、只放行本机访问。多挡了人，用户在日志里看到原因、改好文件
          就恢复；放开了，是别人在用户不知情时拿到访问权。

        文件不存在、或没有内容，不走这里：那是没配置过，用默认值；``network_security = {}`` 或
        ``[network_security]`` 下面什么都没写也一样（那是一张空表）。
        """
        with self._lock:
            last_good = self._network_security_last_good
        if last_good is not None:
            logger.error(
                f"读取 network_security 配置失败，沿用上一次读到的配置，"
                f"{self.config_file} 修好后自动恢复: {error}",
                exc_info=error,
            )
            return last_good
        logger.error(
            f"读取 network_security 配置失败，又没有上一份可用的配置，按最保守的方式运行："
            f"只监听本机（127.0.0.1）、只放行本机访问。{self.config_file} 修好后访问控制"
            f"自动恢复，监听地址在下次启动服务时恢复: {error}",
            exc_info=error,
        )
        return self._validate_network_security_config(
            {
                "bind_interface": "127.0.0.1",
                "allowed_networks": LOOPBACK_ALLOWED_NETWORKS,
            }
        )
