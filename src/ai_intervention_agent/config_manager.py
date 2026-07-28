"""配置管理模块：TOML 配置文件的跨平台加载、读写、热重载。"""

import json
import logging
import os
import platform
import re
import shlex
import shutil
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import tomlkit

from ai_intervention_agent.exceptions import ConfigValidationError
from ai_intervention_agent.rw_lock import ReadWriteLock as ReadWriteLock
from ai_intervention_agent.shared_types import SECTION_MODELS

try:
    from platformdirs import user_config_dir

    PLATFORMDIRS_AVAILABLE = True
except ImportError:
    PLATFORMDIRS_AVAILABLE = False

from ai_intervention_agent.config_modules import (
    FileWatcherMixin,
    IOOperationsMixin,
    NetworkSecurityMixin,
    TomlEngineMixin,
)

logger = logging.getLogger(__name__)


def _is_sensitive_config_key(key: str) -> bool:
    lowered = (key or "").lower()

    return any(
        token in lowered
        for token in (
            "device_key",
            "devicekey",
            "token",
            "secret",
            "password",
            "passwd",
            "api_key",
            "apikey",
            "private_key",
        )
    )


def _sanitize_config_value_for_log(key: str, value: Any) -> str:
    if _is_sensitive_config_key(key):
        return "<redacted>"
    try:
        text = str(value)
    except Exception:
        return "<unprintable>"

    return text if len(text) <= 200 else (text[:200] + "...")


def parse_jsonc(content: str) -> dict[str, Any]:
    """解析 JSONC（带注释的 JSON）为字典，支持 // 单行注释和 /* */ 多行注释。"""
    cleaned_chars = []
    in_string = False
    escape_next = False
    in_single_line_comment = False
    in_multi_line_comment = False

    i = 0
    while i < len(content):
        char = content[i]
        next_char = content[i + 1] if i + 1 < len(content) else ""

        if in_single_line_comment:
            if char == "\n":
                in_single_line_comment = False
                cleaned_chars.append(char)
            i += 1
            continue

        if in_multi_line_comment:
            if char == "*" and next_char == "/":
                in_multi_line_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_string:
            cleaned_chars.append(char)
            if escape_next:
                escape_next = False
            elif char == "\\":
                escape_next = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            cleaned_chars.append(char)
            i += 1
            continue

        if char == "/" and next_char == "/":
            in_single_line_comment = True
            i += 2
            continue

        if char == "/" and next_char == "*":
            in_multi_line_comment = True
            i += 2
            continue

        cleaned_chars.append(char)
        i += 1

    cleaned_content = "".join(cleaned_chars)

    cleaned_content = re.sub(r",\s*([}\]])", r"\1", cleaned_content)

    return cast(dict[str, Any], json.loads(cleaned_content))


def _path_contains_segment(candidate: Path | str, segment: str) -> bool:
    """检测路径中是否包含某个完整的目录段（不会被前缀/后缀误匹配）。"""
    try:
        text = str(candidate)
    except Exception:
        return False
    posix = text.replace("\\", "/")
    needles = (
        f"/{segment}/",
        f"/.{segment}/",
        f"/{segment}-",
    )
    return any(n in posix for n in needles)


_REPO_PKG_LOCAL_MARKERS = ("server.py",)
_REPO_ROOT_MARKERS = ("pyproject.toml",)


def _looks_like_repo_checkout(module_dir: Path) -> bool:
    """模块目录是否是本仓库源码树（``src/ai_intervention_agent/`` 形态）。"""
    pkg_ok = all((module_dir / n).exists() for n in _REPO_PKG_LOCAL_MARKERS)
    if not pkg_ok:
        return False
    try:
        repo_root = module_dir.parent.parent
    except Exception:
        return False
    return all((repo_root / n).exists() for n in _REPO_ROOT_MARKERS)


def _path_under(child: Path, parents: tuple[Path, ...]) -> bool:
    """``child`` 是否位于 ``parents`` 任一目录下（含 child == parent 等价）。"""
    try:
        child_resolved = child.resolve()
    except Exception:
        return False
    for parent in parents:
        try:
            parent_resolved = parent.resolve()
        except Exception:
            continue
        if child_resolved == parent_resolved:
            return True
        if parent_resolved in child_resolved.parents:
            return True
    return False


def _is_isolated_install_runtime() -> bool:
    """启发式检测当前 Python 是否运行在 uv / uvx / uv tool / pipx / pip 隔离环境。"""
    try:
        executable_path = Path(sys.executable).resolve()
    except (OSError, RuntimeError):
        executable_path = Path(sys.executable)

    try:
        module_path = Path(__file__).resolve()
    except Exception:
        module_path = Path(__file__)

    if _path_contains_segment(module_path, "site-packages") or _path_contains_segment(
        module_path, "dist-packages"
    ):
        return True

    env_dirs: list[Path] = []
    for env_name in (
        "UV_TOOL_DIR",
        "UV_CACHE_DIR",
        "UV_PYTHON_INSTALL_DIR",
        "PIPX_HOME",
        "PIPX_LOCAL_VENVS",
    ):
        value = os.environ.get(env_name)
        if value:
            env_dirs.append(Path(value).expanduser())
    if env_dirs and _path_under(executable_path, tuple(env_dirs)):
        return True

    posix_exec = str(executable_path).replace("\\", "/")
    install_segments = (
        "/uvx/",
        "/uv/tools/",
        "/.local/share/uv/tools/",
        "/pipx/venvs/",
        "/.local/share/pipx/venvs/",
        "/.cache/uv/builds-",
    )
    return any(segment in posix_exec for segment in install_segments)


def _is_uvx_mode() -> bool:
    """检测是否应使用"用户配置目录"（uvx / 已安装模式）而非"开发模式"。"""

    def _bool_env(name: str) -> bool:
        raw = os.environ.get(name, "")
        return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}

    if _bool_env("AI_INTERVENTION_AGENT_DEV_MODE"):
        return False

    if _bool_env("AI_INTERVENTION_AGENT_USER_MODE"):
        return True

    if os.environ.get("UVX_PROJECT"):
        return True

    try:
        if _is_isolated_install_runtime():
            return True
    except Exception:
        pass

    try:
        module_dir = Path(__file__).resolve().parent
        if _looks_like_repo_checkout(module_dir):
            repo_root = module_dir.parent.parent
            cwd = Path.cwd().resolve()
            if cwd == repo_root or repo_root in cwd.parents:
                return False
            if cwd == module_dir or module_dir in cwd.parents:
                return False
    except Exception:
        pass

    return True


def _macos_legacy_xdg_config_dir() -> Path | None:
    """**R113** — 返回 macOS 上 ``~/.config/ai-intervention-agent/`` 残留目录。"""
    if platform.system().lower() != "darwin":
        return None
    legacy_dir = Path.home() / ".config" / "ai-intervention-agent"
    if not legacy_dir.is_dir():
        return None
    return legacy_dir


def _retire_legacy_config_file(legacy_file: Path) -> bool:
    """R686：把 legacy 配置文件重命名为 ``<name>.migrated-<时间戳>`` 备份。"""
    try:
        ts = time.strftime("%Y%m%dT%H%M%S")
        backup = legacy_file.with_name(f"{legacy_file.name}.migrated-{ts}")
        legacy_file.rename(backup)
        logger.info(f"[R686] legacy 配置已重命名为备份: {backup}")
        return True
    except OSError as e:
        logger.warning(f"[R686] 重命名 legacy 配置失败（保留原文件）: {e}")
        return False


def _migrate_legacy_config_to_standard(
    legacy_file: Path, standard_dir: Path
) -> Path | None:
    """R686（TODO#4）：把 macOS legacy ``~/.config/...`` 配置迁移到标准目录。"""
    try:
        standard_dir.mkdir(parents=True, exist_ok=True)
        target = standard_dir / legacy_file.name
        if target.exists():
            logger.info(f"[R686] 标准路径已存在 {target.name}，跳过复制")
        else:
            shutil.copy2(legacy_file, target)
        _retire_legacy_config_file(legacy_file)
        logger.info(f"[R686] macOS legacy 配置已自动迁移: {legacy_file} -> {target}")
        return target
    except OSError as e:
        logger.warning(
            f"[R686] 自动迁移 legacy 配置失败，将临时采用 legacy 路径: {e}",
            exc_info=True,
        )
        return None


def _files_have_same_content(a: Path, b: Path) -> bool:
    """比较两个小文件内容是否一致（配置文件 KB 级，直接读全量即可）。"""
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _is_same_physical_file(a: Path, b: Path) -> bool:
    """R703：判断两个路径是否解析到同一物理文件（samefile 优先，降级 resolve）。"""
    try:
        return a.samefile(b)
    except OSError:
        try:
            return a.resolve() == b.resolve()
        except OSError:
            return False


def _resolve_standard_user_config_dir() -> Path:
    """解析"标准用户配置目录"（R703：macOS 上免疫 ``XDG_CONFIG_HOME`` 改写）。"""
    try:
        if not PLATFORMDIRS_AVAILABLE:
            raise ImportError("platformdirs not available")
        resolved = Path(user_config_dir("ai-intervention-agent"))
    except ImportError:
        resolved = _get_user_config_dir_fallback()

    if platform.system().lower() != "darwin":
        return resolved

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if not xdg_config_home:
        return resolved

    try:
        xdg_app_dir = Path(xdg_config_home).expanduser() / "ai-intervention-agent"
        hijacked = resolved == xdg_app_dir
    except Exception:
        hijacked = False
    if not hijacked:
        return resolved

    apple_dir = _get_user_config_dir_fallback()
    logger.info(
        "[R703] macOS 上 platformdirs 受 XDG_CONFIG_HOME 影响返回了 "
        f"{resolved}；本项目在 macOS 上以 Apple 标准路径为准，已改用 "
        f"{apple_dir}（如需自定义位置请配置 AI_INTERVENTION_AGENT_CONFIG_FILE）"
    )
    return apple_dir


def find_config_file(config_filename: str = "config.toml") -> Path:
    """查找配置文件路径，支持环境变量覆盖、uvx / 安装模式和开发模式。"""
    requested_path = Path(config_filename).expanduser()
    if requested_path.is_absolute() or requested_path.parent != Path("."):
        logger.info(f"使用调用方显式给定的绝对/子目录配置路径: {requested_path}")
        return requested_path

    override = os.environ.get("AI_INTERVENTION_AGENT_CONFIG_FILE")
    if override:
        override_path = Path(override).expanduser()
        if override_path.is_dir() or override.endswith(("/", "\\")):
            override_path = override_path / config_filename
        try:
            override_resolved = override_path.resolve()
        except Exception:
            override_resolved = override_path
        logger.info(
            "使用环境变量 AI_INTERVENTION_AGENT_CONFIG_FILE 指定配置文件: "
            f"{override_resolved} (raw={override!r})"
        )
        return override_path

    is_uvx_mode = _is_uvx_mode()

    if is_uvx_mode:
        logger.info(
            "配置路径检测：用户模式（uvx / uv tool / pipx / pip 安装），"
            "仅使用用户配置目录"
        )
    else:
        logger.info(
            "配置路径检测：开发模式（仓库源码树 + cwd 在树内），优先使用当前目录配置"
        )

    _COMPAT_NAMES = ("config.toml", "config.jsonc", "config.json")

    def _pick_existing(directory: Path | None) -> Path | None:
        """在 ``directory`` 中按 TOML > JSONC > JSON 优先返回首个存在的候选。"""
        candidates: list[tuple[str, Path]] = []
        for name in _COMPAT_NAMES:
            target = (directory / name) if directory is not None else Path(name)
            if target.exists():
                candidates.append((name, target))
        if not candidates:
            return None
        first_name, first_path = candidates[0]
        if len(candidates) > 1:
            ignored = ", ".join(name for name, _ in candidates[1:])
            location = directory if directory is not None else "当前目录"
            logger.warning(
                f"{location} 同时存在多种格式: "
                f"{', '.join(name for name, _ in candidates)}；"
                f"已采用 {first_name}，将忽略 {ignored}（如需切换请删除/重命名）"
            )
        return first_path

    if not is_uvx_mode:
        cwd_hit = _pick_existing(None)
        if cwd_hit is not None:
            logger.info(f"使用当前目录的配置文件: {cwd_hit.absolute()}")
            return cwd_hit

    try:
        user_config_dir_path = _resolve_standard_user_config_dir()

        user_hit = _pick_existing(user_config_dir_path)

        legacy_macos_dir = _macos_legacy_xdg_config_dir()
        legacy_macos_hit = (
            _pick_existing(legacy_macos_dir) if legacy_macos_dir is not None else None
        )

        if user_hit is not None:
            if legacy_macos_hit is not None:
                if _is_same_physical_file(user_hit, legacy_macos_hit):
                    logger.info(
                        "[R703] 标准路径与 legacy 路径解析到同一物理文件"
                        f"（symlink 或 XDG 改写）: {user_hit}；跳过 R686 "
                        "退休/迁移逻辑，直接使用该文件"
                    )

                elif _files_have_same_content(user_hit, legacy_macos_hit):
                    if _retire_legacy_config_file(legacy_macos_hit):
                        logger.info(
                            "[R686] macOS legacy 配置与标准路径内容一致，"
                            "已自动重命名为备份，后续不再提示"
                        )
                else:
                    logger.warning(
                        "[R113] macOS 上检测到非标准 XDG 配置路径残留且内容与"
                        f"标准路径不一致: {legacy_macos_hit}。已使用标准路径 "
                        f"{user_hit}；请人工确认后删除非标准路径以避免歧义： "
                        f"`rm -rf {legacy_macos_dir}`"
                    )
            logger.info(f"使用用户配置目录的配置文件: {user_hit}")
            return user_hit

        if legacy_macos_hit is not None:
            assert legacy_macos_dir is not None
            migrated = _migrate_legacy_config_to_standard(
                legacy_macos_hit, user_config_dir_path
            )
            if migrated is not None:
                logger.info(f"使用用户配置目录的配置文件: {migrated}")
                return migrated
            logger.warning(
                "[R113] macOS 上仅在非标准 XDG 路径找到配置且自动迁移失败: "
                f"{legacy_macos_hit}。已临时采用非标准路径；建议手动迁移：\n"
                f"  mkdir -p {shlex.quote(str(user_config_dir_path))}\n"
                f"  mv {shlex.quote(str(legacy_macos_hit))} "
                f"{shlex.quote(str(user_config_dir_path) + '/')}\n"
                f"  rmdir {shlex.quote(str(legacy_macos_dir))}"
            )
            return legacy_macos_hit

        user_config_file = user_config_dir_path / config_filename
        logger.info(f"配置文件不存在，将在用户配置目录创建: {user_config_file}")
        return user_config_file

    except Exception as e:
        logger.warning(
            f"获取用户配置目录失败: {e}，将回退到当前目录 ({Path(config_filename).absolute()})；"
            "若长期使用此路径请配 AI_INTERVENTION_AGENT_CONFIG_FILE 显式锁定",
            exc_info=True,
        )
        return Path(config_filename)


def _get_user_config_dir_fallback() -> Path:
    """platformdirs 不可用时的回退实现，返回跨平台标准配置目录。"""
    system = platform.system().lower()
    home = Path.home()

    if system == "windows":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "ai-intervention-agent"
        else:
            return home / "AppData" / "Roaming" / "ai-intervention-agent"
    elif system == "darwin":
        return home / "Library" / "Application Support" / "ai-intervention-agent"
    else:
        xdg_config_home = os.getenv("XDG_CONFIG_HOME")
        if xdg_config_home:
            return Path(xdg_config_home) / "ai-intervention-agent"
        else:
            return home / ".config" / "ai-intervention-agent"


class ConfigManager(
    TomlEngineMixin,
    NetworkSecurityMixin,
    FileWatcherMixin,
    IOOperationsMixin,
):
    """配置管理器：TOML 配置文件的加载、读写、持久化、热重载。"""

    def __init__(self, config_file: str = "config.toml"):
        """初始化配置管理器：查找配置文件、初始化锁和缓存、加载配置、启动文件监听"""

        req = Path(config_file).expanduser()
        self._explicit_path = req.is_absolute() or req.parent != Path(".")
        self.config_file = find_config_file(config_file)

        self._config: dict[str, Any] = {}

        # 初始化锁机制
        # RLock rationale (R336 contract): set() (config_manager.py:1131)
        # 在持有 self._lock 状态下调用 self._save_config() (line 1167),
        # 后者 → self._schedule_save() → `with self._lock:`
        # 即**同一线程在持锁状态下重入获取同一锁**。Lock 会 self-deadlock,
        # RLock 必需。同理: set_section + set_network_security_config 等
        # mutate API 都走相同 set→_save_config→_schedule_save chain。
        self._lock = threading.RLock()

        self._original_content: str | None = None
        self._last_access_time = time.monotonic()

        self._pending_changes: dict[str, Any] = {}
        self._save_timer: threading.Timer | None = None
        self._save_delay = 3.0
        self._last_save_time: float = 0

        self._network_security_cache: dict[str, Any] | None = None
        self._network_security_cache_time: float = 0
        self._network_security_cache_ttl: float = 30.0

        self._section_cache: dict[str, dict[str, Any]] = {}
        self._section_cache_time: dict[str, float] = {}
        self._section_cache_ttl: float = 10.0

        self._cache_stats = {
            "hits": 0,
            "misses": 0,
            "invalidations": 0,
        }

        self._file_watcher_thread: threading.Thread | None = None
        self._file_watcher_running = False
        self._file_watcher_stop_event = threading.Event()
        self._file_watcher_interval = 2.0
        self._last_file_mtime: float = 0
        self._config_change_callbacks: list[Callable[[], None]] = []

        self._load_config()

        self._update_file_mtime()

    def _get_default_config(self) -> dict[str, Any]:
        """返回默认配置字典（由 Pydantic 段模型的默认值生成，单一真相源）"""
        return {name: model().model_dump() for name, model in SECTION_MODELS.items()}

    @staticmethod
    def _exclude_network_security(config: dict[str, Any]) -> dict[str, Any]:
        """从配置字典中排除 network_security（返回新字典或原地修改）"""
        if "network_security" in config:
            del config["network_security"]
            logger.debug("已从配置中排除 network_security")
        return config

    def _is_toml_file(self) -> bool:
        """判断当前配置文件是否为 TOML 格式"""
        return self.config_file.suffix.lower() == ".toml"

    def _parse_config_content(self, content: str) -> dict[str, Any]:
        """根据当前文件格式解析配置内容（TOML 或降级到 JSON）"""
        if self._is_toml_file():
            return self._parse_toml(content)
        return cast(dict[str, Any], json.loads(content))

    def _migrate_jsonc_to_toml(self) -> bool:
        """将旧的 JSONC/JSON 配置文件迁移为 TOML 格式"""
        old_file = self.config_file
        new_file = old_file.with_suffix(".toml")
        try:
            with open(old_file, encoding="utf-8") as f:
                content = f.read()
            if old_file.suffix.lower() == ".jsonc":
                config_data = parse_jsonc(content)
            else:
                config_data = json.loads(content)
            mdns = config_data.get("mdns")
            if isinstance(mdns, dict) and mdns.get("enabled") is None:
                mdns["enabled"] = "auto"
            template_file = Path(__file__).parent / "config.toml.default"
            if template_file.exists():
                with open(template_file, encoding="utf-8") as f:
                    doc = tomlkit.parse(f.read())
                for sk, sv in config_data.items():
                    if isinstance(sv, dict) and sk in doc:
                        section = doc[sk]
                        if isinstance(section, dict):
                            for k, v in sv.items():
                                section[k] = v
                    elif sk not in doc:
                        doc[sk] = sv
                toml_content = tomlkit.dumps(doc)
            else:
                toml_content = tomlkit.dumps(tomlkit.item(config_data))
            with open(new_file, "w", encoding="utf-8") as f:
                f.write(toml_content)
            backup = old_file.with_suffix(old_file.suffix + ".bak")
            old_file.rename(backup)
            logger.info(
                f"配置已迁移: {old_file.name} -> {new_file.name} (备份: {backup.name})"
            )
            self.config_file = new_file
            return True
        except Exception as e:
            logger.error(f"JSONC->TOML 迁移失败: {e}", exc_info=True)
            return False

    def _load_config(self):
        """从磁盘加载配置文件，排除 network_security，合并默认配置。"""
        with self._lock:
            if self._pending_changes:
                logger.warning(
                    f"reload 时发现 {len(self._pending_changes)} 个未保存的"
                    f"进程内 config 变更，将被外部编辑覆盖（external-edit-wins 策略）："
                    f"{sorted(self._pending_changes)}"
                )
                self._pending_changes.clear()
                if self._save_timer is not None:
                    self._save_timer.cancel()
                    self._save_timer = None

            had_previous_config = bool(self._config)
            previous_config = self._config.copy()
            previous_original_content = self._original_content
            try:
                if (
                    self.config_file.exists()
                    and not self._is_toml_file()
                    and not self._explicit_path
                ):
                    self._migrate_jsonc_to_toml()

                if self.config_file.exists():
                    with open(self.config_file, encoding="utf-8") as f:
                        content = f.read()

                    full_config = self._parse_config_content(content)
                    fmt = self.config_file.suffix.lstrip(".")
                    logger.info(f"{fmt.upper()} 配置文件已加载: {self.config_file}")

                    self._validate_config_structure(full_config, content)

                    self._original_content = content

                    self._config = {}
                    for key, value in full_config.items():
                        if key != "network_security":
                            self._config[key] = value

                    if "network_security" in full_config:
                        logger.debug("network_security 配置已排除，不加载到内存中")
                else:
                    self._config = self._exclude_network_security(
                        self._get_default_config()
                    )
                    self._original_content = None
                    self._create_default_config_file()
                    logger.info(f"创建默认配置文件: {self.config_file}")

                default_config = self._exclude_network_security(
                    self._get_default_config()
                )
                self._config = self._merge_config(default_config, self._config)

            except Exception as e:
                logger.error(f"加载配置文件失败: {e}", exc_info=True)
                if had_previous_config:
                    self._config = previous_config
                    self._original_content = previous_original_content
                    logger.warning(
                        "加载配置失败，已保留上一次成功加载的内存配置（避免回退到默认值）"
                    )
                else:
                    self._config = self._exclude_network_security(
                        self._get_default_config()
                    )
                    self._original_content = None

    def _merge_config(
        self, default: dict[str, Any], current: dict[str, Any]
    ) -> dict[str, Any]:
        """递归合并配置：补充缺失的默认键，保持用户值优先，排除 network_security"""
        result = current.copy()

        for key, default_value in default.items():
            if key == "network_security":
                logger.debug("_merge_config: 跳过 network_security 配置")
                continue

            if key not in result:
                result[key] = default_value
            elif isinstance(result[key], dict) and isinstance(default_value, dict):
                result[key] = self._merge_config(default_value, result[key])

        self._exclude_network_security(result)
        return result

    def _create_default_config_file(self):
        """创建带注释的默认配置文件（使用 TOML 模板）"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            toml_template = Path(__file__).parent / "config.toml.default"

            if self._is_toml_file() and toml_template.exists():
                shutil.copy2(toml_template, self.config_file)
                with open(toml_template, encoding="utf-8") as f:
                    self._original_content = f.read()
                logger.info(f"已从 TOML 模板创建默认配置文件: {self.config_file}")
            else:
                logger.warning("模板文件不存在，使用默认配置创建文件")
                default_config = self._exclude_network_security(
                    self._get_default_config()
                )
                if self._is_toml_file():
                    content = tomlkit.dumps(tomlkit.item(default_config))
                else:
                    content = json.dumps(default_config, indent=2, ensure_ascii=False)
                with open(self.config_file, "w", encoding="utf-8") as f:
                    f.write(content)
                self._original_content = content
                logger.info(f"已创建默认配置文件: {self.config_file}")

        except Exception as e:
            logger.error(f"创建默认配置文件失败: {e}", exc_info=True)
            try:
                default_config = self._exclude_network_security(
                    self._get_default_config()
                )
                content = json.dumps(default_config, indent=2, ensure_ascii=False)
                with open(self.config_file, "w", encoding="utf-8") as f:
                    f.write(content)
                self._original_content = content
                logger.info(f"回退创建 JSON 配置文件成功: {self.config_file}")
            except Exception as fallback_error:
                logger.error(f"回退创建配置文件也失败: {fallback_error}", exc_info=True)
                raise

    def _schedule_save(self):
        """调度延迟保存（默认3秒后执行，多次调用合并为一次保存）"""
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()

            self._save_timer = threading.Timer(self._save_delay, self._delayed_save)

            self._save_timer.daemon = True
            self._save_timer.start()
            logger.debug(f"已调度配置保存，将在 {self._save_delay} 秒后执行")

    def _delayed_save(self):
        """延迟保存定时器回调：应用待保存变更并写入文件"""
        try:
            with self._lock:
                self._save_timer = None

                if self._pending_changes:
                    logger.debug(
                        f"应用 {len(self._pending_changes)} 个待写入的配置变更"
                    )
                    for key, value in self._pending_changes.items():
                        self._set_config_value(key, value)
                    self._pending_changes.clear()

                self._save_config_immediate()
                self._last_save_time = time.monotonic()
                logger.debug("延迟配置保存完成")
        except Exception as e:
            logger.error(f"延迟保存配置失败: {e}", exc_info=True)

    def _set_config_value(self, key: str, value: Any):
        """内部方法：设置配置值（不触发保存，自动创建中间路径）"""
        keys = key.split(".")
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def _save_config(self):
        """触发延迟保存（通过 _schedule_save 调度）"""
        self._schedule_save()

    def _save_config_immediate(self):
        """原子写入配置文件（tempfile + os.replace），防止崩溃导致文件截断/损坏"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            if self._is_toml_file() and self._original_content:
                content = self._save_toml_with_comments(self._config)
            elif self._is_toml_file():
                content = tomlkit.dumps(tomlkit.item(self._config))
            else:
                content = json.dumps(self._config, indent=2, ensure_ascii=False)

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
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    if orig_mode is not None:
                        os.fchmod(f.fileno(), orig_mode)
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(self.config_file))
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            self._original_content = content
            logger.debug(f"配置文件已原子写入: {self.config_file}")

            self._validate_saved_config()

            self._update_file_mtime()

        except Exception as e:
            logger.error(f"保存配置文件失败: {e}", exc_info=True)
            raise

    def _validate_saved_config(self):
        """验证保存的配置文件格式和结构是否正确"""
        try:
            with open(self.config_file, encoding="utf-8") as f:
                content = f.read()

            parsed_config = self._parse_config_content(content)

            self._validate_config_structure(parsed_config, content)

            logger.debug("配置文件验证通过")
        except Exception as e:
            logger.error(f"配置文件验证失败: {e}", exc_info=True)
            raise

    def _validate_config_structure(self, parsed_config: dict[str, Any], content: str):
        """验证配置结构完整性（network_security 格式等）"""
        if not self._is_toml_file():
            lines_list = content.splitlines()
            array_definitions: dict[str, int] = {}
            for i, line in enumerate(lines_list):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if '"allowed_networks"' in stripped and "[" in stripped:
                    if "allowed_networks" in array_definitions:
                        raise ConfigValidationError(
                            f"配置文件格式损坏：重复的数组定义在第{i + 1}行"
                        )
                    array_definitions["allowed_networks"] = i + 1
                if '"blocked_ips"' in stripped and "[" in stripped:
                    if "blocked_ips" in array_definitions:
                        raise ConfigValidationError(
                            f"配置文件格式损坏：重复的数组定义在第{i + 1}行"
                        )
                    array_definitions["blocked_ips"] = i + 1

        if "network_security" in parsed_config:
            ns_config = parsed_config["network_security"]
            if not isinstance(ns_config, dict):
                raise ConfigValidationError("network_security 配置段必须是 object")
            if "allowed_networks" in ns_config:
                allowed_networks = ns_config["allowed_networks"]
                if not isinstance(allowed_networks, list):
                    raise ConfigValidationError(
                        "network_security.allowed_networks 应该是数组类型"
                    )

                for network in allowed_networks:
                    if not isinstance(network, str):
                        raise ConfigValidationError(
                            f"network_security.allowed_networks 包含无效元素: {network}"
                        )

        logger.debug("配置文件结构验证通过")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持点号分隔的嵌套键如 'notification.sound_volume'，线程安全）"""

        with self._lock:
            self._last_access_time = time.monotonic()
            keys = key.split(".")
            value = self._config
            try:
                for k in keys:
                    value = value[k]
                return value
            except (KeyError, TypeError):
                return default

    def set(self, key: str, value: Any, save: bool = True) -> None:
        """设置配置值（支持嵌套键，自动创建中间路径，值变化检测，可选延迟保存）"""

        if key == "network_security":
            if not isinstance(value, dict):
                raise ConfigValidationError("network_security 必须是 object（dict）")
            self.set_network_security_config(cast(dict[str, Any], value), save=save)
            return
        if key.startswith("network_security."):
            field = key[len("network_security.") :]
            if not field or "." in field:
                raise ConfigValidationError(
                    "仅支持设置一级字段：network_security.<field>"
                )
            self.update_network_security_config({field: value}, save=save)
            return

        changed = False
        with self._lock:
            self._last_access_time = time.monotonic()

            current_value = self.get(key)
            if current_value == value:
                logger.debug(
                    f"配置值未变化，跳过更新: {key} = {_sanitize_config_value_for_log(key, value)}"
                )
                return

            if save:
                self._pending_changes[key] = value

                self._set_config_value(key, value)

                self._save_config()
            else:
                self._set_config_value(key, value)

                self._pending_changes.pop(key, None)

            section = key.split(".")[0] if key else ""
            if section == "network_security":
                self.invalidate_all_caches()
            elif section:
                self.invalidate_section_cache(section)
            else:
                self.invalidate_all_caches()

            changed = True
            logger.debug(
                f"配置已更新: {key} = {_sanitize_config_value_for_log(key, value)}"
            )

        if changed:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def update(self, updates: dict[str, Any], save: bool = True) -> None:
        """批量更新配置（仅处理变化项，合并为一次延迟保存，原子操作）"""

        network_security_updates: dict[str, Any] = {}
        non_ns_updates: dict[str, Any] = {}
        for k, v in (updates or {}).items():
            if k == "network_security" and isinstance(v, dict):
                network_security_updates.update(cast(dict[str, Any], v))
            elif isinstance(k, str) and k.startswith("network_security."):
                field = k[len("network_security.") :]
                if field and "." not in field:
                    network_security_updates[field] = v
                else:
                    raise ConfigValidationError(
                        "仅支持更新一级字段：network_security.<field>"
                    )
            else:
                non_ns_updates[k] = v

        if network_security_updates:
            self.update_network_security_config(network_security_updates, save=save)

            if not non_ns_updates:
                return

        changed_sections: set[str] = set()
        changed = False
        with self._lock:
            self._last_access_time = time.monotonic()

            actual_changes = {}
            for key, value in non_ns_updates.items():
                current_value = self.get(key)
                if current_value != value:
                    actual_changes[key] = value

            if not actual_changes:
                logger.debug("批量更新中没有配置变化，跳过保存")
                return

            if save:
                self._pending_changes.update(actual_changes)

                for key, value in actual_changes.items():
                    self._set_config_value(key, value)
                    logger.debug(
                        f"配置已更新: {key} = {_sanitize_config_value_for_log(key, value)}"
                    )

                self._save_config()
            else:
                for key, value in actual_changes.items():
                    self._set_config_value(key, value)

                    self._pending_changes.pop(key, None)
                    logger.debug(
                        f"配置已更新: {key} = {_sanitize_config_value_for_log(key, value)}"
                    )

            for changed_key in actual_changes:
                section = changed_key.split(".")[0] if changed_key else ""
                if section:
                    changed_sections.add(section)

            if "network_security" in changed_sections or not changed_sections:
                self.invalidate_all_caches()
            else:
                for section in changed_sections:
                    self.invalidate_section_cache(section)

            changed = True
            logger.debug(f"批量更新完成，共更新 {len(actual_changes)} 个配置项")

        if changed:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def force_save(self) -> None:
        """强制立即保存配置文件（取消延迟保存，应用所有待保存变更）"""
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None

            if self._pending_changes:
                logger.debug(
                    f"强制保存：应用 {len(self._pending_changes)} 个待写入的配置变更"
                )
                for key, value in self._pending_changes.items():
                    self._set_config_value(key, value)
                self._pending_changes.clear()

            self._save_config_immediate()
            self._last_save_time = time.monotonic()
            logger.debug("强制配置保存完成")

    def get_section(self, section: str, use_cache: bool = True) -> dict[str, Any]:
        """获取配置段的深拷贝（带 Pydantic 校验、缓存优化，network_security 特殊处理）"""
        import copy

        with self._lock:
            current_time = time.monotonic()

            if section == "network_security":
                return copy.deepcopy(self.get_network_security_config())

            if use_cache and section in self._section_cache:
                cache_time = self._section_cache_time.get(section, 0)
                if current_time - cache_time < self._section_cache_ttl:
                    self._cache_stats["hits"] += 1
                    logger.debug(f"缓存命中: section={section}")
                    return copy.deepcopy(self._section_cache[section])

            self._cache_stats["misses"] += 1
            raw = self.get(section)
            result = self._validate_section(section, raw)

            self._section_cache[section] = result
            self._section_cache_time[section] = current_time

            return copy.deepcopy(result)

    @staticmethod
    def _validate_section(section: str, raw: Any) -> dict[str, Any]:
        """通过 Pydantic 模型校验配置段（类型强转 + 钳位），失败时降级返回原始数据"""
        if not isinstance(raw, dict):
            raw = {}
        model_cls = SECTION_MODELS.get(section)
        if model_cls is None:
            return raw.copy()
        try:
            return model_cls.model_validate(raw).model_dump()
        except Exception as e:
            logger.warning(f"配置段 '{section}' Pydantic 校验失败，使用原始值: {e}")
            return raw.copy()

    def update_section(
        self, section: str, updates: dict[str, Any], save: bool = True
    ) -> None:
        """更新配置段（检测变化，触发回调，可选延迟保存）"""
        if section == "network_security":
            if not isinstance(updates, dict):
                raise ConfigValidationError("network_security 更新必须是 dict")
            self.update_network_security_config(updates, save=save)
            return

        changed = False
        with self._lock:
            current_section = self.get_section(section)

            has_changes = False
            for key, new_value in updates.items():
                current_value = current_section.get(key)
                if current_value != new_value:
                    has_changes = True
                    full_key = f"{section}.{key}"
                    logger.debug(
                        f"配置项 '{full_key}' 发生变化: "
                        f"{_sanitize_config_value_for_log(full_key, current_value)} -> "
                        f"{_sanitize_config_value_for_log(full_key, new_value)}"
                    )

            if not has_changes:
                logger.debug(f"配置段 '{section}' 未发生变化，跳过保存")
                return

            current_section.update(updates)

            keys = section.split(".")
            config = self._config
            for k in keys[:-1]:
                if k not in config:
                    config[k] = {}
                config = config[k]
            config[keys[-1]] = current_section

            if save:
                self._save_config()

            self.invalidate_section_cache(section)

            changed = True
            logger.debug(f"配置段已更新: {section}")

        if changed:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def reload(self) -> None:
        """从磁盘重新加载配置文件（覆盖内存配置，失效缓存）"""
        logger.info("重新加载配置文件")
        self._load_config()

        self.invalidate_all_caches()

    def invalidate_section_cache(self, section: str) -> None:
        """失效指定配置段的缓存"""
        with self._lock:
            if section in self._section_cache:
                del self._section_cache[section]
                self._section_cache_time.pop(section, None)
                self._cache_stats["invalidations"] += 1
                logger.debug(f"已失效 section 缓存: {section}")

    def invalidate_all_caches(self) -> None:
        """清空所有配置缓存"""
        with self._lock:
            invalidated_count = len(self._section_cache)
            self._section_cache.clear()
            self._section_cache_time.clear()

            self._network_security_cache = None
            self._network_security_cache_time = 0

            self._cache_stats["invalidations"] += invalidated_count + 1
            logger.debug(f"已失效所有缓存 (共 {invalidated_count + 1} 个)")

    def get_cache_stats(self) -> dict[str, Any]:
        """获取缓存统计（命中/未命中/失效次数、命中率等）"""
        with self._lock:
            total = self._cache_stats["hits"] + self._cache_stats["misses"]
            hit_rate = self._cache_stats["hits"] / total if total > 0 else 0.0

            return {
                **self._cache_stats,
                "hit_rate": round(hit_rate, 4),
                "section_cache_size": len(self._section_cache),
                "network_security_cached": self._network_security_cache is not None,
            }

    def reset_cache_stats(self) -> None:
        """重置缓存统计信息"""
        with self._lock:
            self._cache_stats = {
                "hits": 0,
                "misses": 0,
                "invalidations": 0,
            }
            logger.debug("已重置缓存统计")

    def set_cache_ttl(
        self,
        section_ttl: float | None = None,
        network_security_ttl: float | None = None,
    ) -> None:
        """设置缓存有效期（TTL）"""
        with self._lock:
            if section_ttl is not None:
                self._section_cache_ttl = max(0.1, section_ttl)
                logger.debug(f"section 缓存 TTL 已设置为: {self._section_cache_ttl}s")

            if network_security_ttl is not None:
                self._network_security_cache_ttl = max(1.0, network_security_ttl)
                logger.debug(
                    f"network_security 缓存 TTL 已设置为: {self._network_security_cache_ttl}s"
                )

    def get_all(self) -> dict[str, Any]:
        """获取所有配置的深拷贝（不含 network_security），防止外部修改内部状态"""
        import copy

        with self._lock:
            data = copy.deepcopy(self._config)
            return self._exclude_network_security(data)

    @staticmethod
    def _coerce_bool(value: Any, default: bool = True) -> bool:
        """将常见输入转换为 bool（用于配置兼容性）"""
        try:
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                s = value.strip().lower()
                if s in ("true", "1", "yes", "y", "on"):
                    return True
                if s in ("false", "0", "no", "n", "off"):
                    return False
                return default
            return bool(value)
        except Exception:
            return default

    def get_typed(
        self,
        key: str,
        default: Any,
        value_type: type,
        min_val: Any | None = None,
        max_val: Any | None = None,
    ) -> Any:
        """获取配置值，带类型转换和边界验证"""
        from ai_intervention_agent.config_utils import clamp_value

        raw_value = self.get(key, default)

        try:
            if value_type is bool:
                if isinstance(raw_value, bool):
                    return raw_value
                if isinstance(raw_value, str):
                    return raw_value.lower() in ("true", "1", "yes", "on")
                return bool(raw_value)

            converted = value_type(raw_value)

            if value_type in (int, float) and (
                min_val is not None or max_val is not None
            ):
                if min_val is not None and max_val is not None:
                    return clamp_value(converted, min_val, max_val, key)
                elif min_val is not None:
                    return max(converted, min_val)
                elif max_val is not None:
                    return min(converted, max_val)

            return converted

        except (ValueError, TypeError) as e:
            logger.warning(f"配置 '{key}' 类型转换失败: {e}，使用默认值 {default}")
            return default

    def get_int(
        self,
        key: str,
        default: int = 0,
        min_val: int | None = None,
        max_val: int | None = None,
    ) -> int:
        """获取整数配置值"""
        return cast(int, self.get_typed(key, default, int, min_val, max_val))

    def get_float(
        self,
        key: str,
        default: float = 0.0,
        min_val: float | None = None,
        max_val: float | None = None,
    ) -> float:
        """获取浮点数配置值"""
        return cast(float, self.get_typed(key, default, float, min_val, max_val))

    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置值"""
        return cast(bool, self.get_typed(key, default, bool))

    def get_str(
        self,
        key: str,
        default: str = "",
        max_length: int | None = None,
    ) -> str:
        """获取字符串配置值（可选截断）"""
        from ai_intervention_agent.config_utils import truncate_string

        value = cast(str, self.get_typed(key, default, str))
        if max_length is not None:
            return truncate_string(value, max_length, key, default=default)
        return value


config_manager = ConfigManager()


import atexit  # noqa: E402


def _shutdown_global_config_manager():
    try:
        config_manager.shutdown()
    except Exception:
        pass


atexit.register(_shutdown_global_config_manager)


def get_config() -> ConfigManager:
    """获取全局配置管理器实例（自动启动文件监听）"""

    try:
        if not config_manager.is_file_watcher_running:
            config_manager.start_file_watcher(interval=2.0)
    except Exception:
        pass

    return config_manager
