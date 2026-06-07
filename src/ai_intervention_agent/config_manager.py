"""配置管理模块：TOML 配置文件的跨平台加载、读写、热重载。

核心特性：使用可重入锁（RLock）保护共享状态、延迟保存优化、network_security 独立管理、文件变更监听。
旧 JSONC/JSON 文件在首次加载时自动迁移为 TOML。
通过 get_config() 获取全局 ConfigManager 实例。
"""

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
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import tomlkit

from ai_intervention_agent.exceptions import ConfigValidationError
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

# =========================
# 日志脱敏（避免泄露密钥/Token）
# =========================


def _is_sensitive_config_key(key: str) -> bool:
    lowered = (key or "").lower()
    # 只做最小必要的脱敏：Bark device_key 等敏感标识一律不应出现在日志
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
    # 避免日志过长
    return text if len(text) <= 200 else (text[:200] + "...")


class ReadWriteLock:
    """
    读写锁：多读者并发、写者独占，基于 Condition + RLock 实现。

    注意：本类目前未被 ConfigManager 使用（ConfigManager 使用 threading.RLock），
    作为独立工具类保留，供需要读写分离锁场景的调用方使用。
    """

    def __init__(self):
        """初始化读写锁"""
        # RLock rationale (R330 contract): Condition.wait() 内部会 release
        # 然后 re-acquire 锁; 持锁的 reader 线程在 notify_all 后唤醒时需要
        # 重新 acquire (即同一线程 re-entry), 因此必须 RLock 而非 Lock。
        self._read_ready = threading.Condition(threading.RLock())
        self._readers = 0

    @contextmanager
    def read_lock(self) -> Generator[None, None, None]:
        """获取读锁（多读者并发，仅在写者持有锁时阻塞）"""
        self._read_ready.acquire()
        try:
            self._readers += 1
        finally:
            self._read_ready.release()

        try:
            yield
        finally:
            self._read_ready.acquire()
            try:
                self._readers -= 1
                if self._readers == 0:
                    self._read_ready.notify_all()
            finally:
                self._read_ready.release()

    @contextmanager
    def write_lock(self) -> Generator[None, None, None]:
        """获取写锁（独占访问，等待所有读者退出）"""
        self._read_ready.acquire()
        try:
            while self._readers > 0:
                self._read_ready.wait()
            yield
        finally:
            self._read_ready.release()


def parse_jsonc(content: str) -> dict[str, Any]:
    """
    解析 JSONC（带注释的 JSON）为字典，支持 // 单行注释和 /* */ 多行注释。

    异常:
        json.JSONDecodeError: JSON 语法错误时抛出
    """
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

    # JSONC 允许尾部逗号，但 json.loads 不接受，需预处理移除
    cleaned_content = re.sub(r",\s*([}\]])", r"\1", cleaned_content)

    return cast(dict[str, Any], json.loads(cleaned_content))


def _path_contains_segment(candidate: Path | str, segment: str) -> bool:
    """检测路径中是否包含某个完整的目录段（不会被前缀/后缀误匹配）。

    例如 ``/Users/foo/uv-bar`` 不应该被 ``segment="uv"`` 命中——只命中真正
    出现 ``.../uv/...`` 这种完整目录节。同时兼容 Windows 反斜杠与 POSIX
    斜杠。
    """
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


# R76 src/ layout 改造之后，模块本体落在 ``src/ai_intervention_agent/``：
# - 模块同级（即 ``module_dir``）应当含 ``server.py`` —— 包内入口模块；
# - 仓库根（``module_dir.parent.parent``）应当含 ``pyproject.toml`` —— 真正的工程标识。
# 把两者拆开判断，既能正确识别 src layout 的开发树，又不会把 site-packages
# 下"碰巧有一个 server.py"的安装目录误判为开发模式。
_REPO_PKG_LOCAL_MARKERS = ("server.py",)
_REPO_ROOT_MARKERS = ("pyproject.toml",)


def _looks_like_repo_checkout(module_dir: Path) -> bool:
    """模块目录是否是本仓库源码树（``src/ai_intervention_agent/`` 形态）。

    判定条件（必须同时成立）：
    1. ``module_dir`` 内有 ``server.py`` —— 防止 site-packages 误命中；
    2. ``module_dir.parent.parent`` 有 ``pyproject.toml`` —— 表征真正
       的 src layout 仓库根。

    抽出来方便单测 + 增强可读性。
    """
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
    """启发式检测当前 Python 是否运行在 uv / uvx / uv tool / pipx / pip 隔离环境。

    覆盖 2026 年常见的 4 类隔离运行时：

    * **uvx**（``uv tool run``）—— sys.executable 在 uv cache 临时 venv 里，
      路径常见形态 ``~/.cache/uv/builds-v0/<hash>/.venv/bin/python``。
    * **uv tool install**—— sys.executable 在 ``~/.local/share/uv/tools/<name>/.venv/bin/python``
      （或 ``$XDG_DATA_HOME/uv/tools/...``、``%LOCALAPPDATA%\\uv\\tools\\...``）。
    * **pipx install**—— sys.executable 在 ``~/.local/share/pipx/venvs/<name>/bin/python``。
    * **pip install + 全局 / 项目 venv**—— 模块文件本身在 ``site-packages`` 下，
      运行时不需要看 sys.executable。

    任一命中就视为 "已安装到用户环境"，必须走用户配置目录。环境变量
    ``UV_TOOL_DIR`` / ``UV_CACHE_DIR`` / ``PIPX_HOME`` 也会作为路径前缀
    参与匹配，覆盖用户自定义安装目录的情况。
    """
    try:
        executable_path = Path(sys.executable).resolve()
    except (OSError, RuntimeError):
        executable_path = Path(sys.executable)

    try:
        module_path = Path(__file__).resolve()
    except Exception:
        module_path = Path(__file__)

    # 1) 模块本身已被 pip / uv pip / setuptools 安装到 site-packages。
    if _path_contains_segment(module_path, "site-packages") or _path_contains_segment(
        module_path, "dist-packages"
    ):
        return True

    # 2) 启发式：uvx / uv tool / pipx 路径段命中。优先用环境变量配置的目录前缀
    #    （UV_TOOL_DIR / UV_CACHE_DIR / PIPX_HOME / UV_PYTHON_INSTALL_DIR），
    #    没配再用 ``/uv/`` ``/pipx/`` 等通用 segment 兜底。
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

    # 只命中"已安装到用户环境"的具体子目录——不要匹配 ``~/.local/share/uv/python/``
    # 之类的 uv-managed Python interpreter，那不代表项目是已安装；仓库内 ``uv run``
    # 解析出的 sys.executable 经常落在 managed Python 那里，不能误判。
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
    """检测是否应使用"用户配置目录"（uvx / 已安装模式）而非"开发模式"。

    说明
    ----
    * **用户模式（True）**：使用用户配置目录（跨平台标准路径）。
      - uvx 运行（推荐给普通用户）
      - 通过 pip / uv tool / pipx 等任意方式安装后运行
    * **开发模式（False）**：优先使用当前目录配置（从仓库克隆运行时更方便调试）。

    判定优先级（高 → 低，命中即返回）
    ----
    1. ``AI_INTERVENTION_AGENT_DEV_MODE`` 显式启用 → 开发模式（``False``）。
    2. ``AI_INTERVENTION_AGENT_USER_MODE`` 显式启用 → 用户模式（``True``）。
    3. 兼容旧 ``UVX_PROJECT`` → 用户模式。
    4. 启发式检测 :func:`_is_isolated_install_runtime`（uvx / uv tool / pipx
       / site-packages）→ 用户模式。
    5. 仓库检出 + cwd 在仓库内（兼顾仓库内 ``.venv`` 的 isolated runtime
       case）→ 开发模式。
    6. 默认（保守）→ 用户模式。

    任何判定阶段抛异常都降级为用户模式，避免误把"任意 git 仓库 cwd"判为
    开发模式而在那里写 ``config.toml``。

    注：步骤 5 对仓库内 ``.venv``（``./venv`` / ``./.venv`` / ``./uv-venv``
    等开发者本地 venv）做 carve-out——虽然 ``Path(sys.executable)`` 可能
    在 ``./.venv/bin/python``，但只要模块自己仍在仓库源码树（不在
    site-packages）且 cwd 在源码树，就视为 dev。
    """

    def _bool_env(name: str) -> bool:
        raw = os.environ.get(name, "")
        return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}

    # 1) 显式 dev override：开发者主动指定，最高优先级。
    if _bool_env("AI_INTERVENTION_AGENT_DEV_MODE"):
        return False

    # 2) 显式 user override：仓库内调试 "假装是已安装"。
    if _bool_env("AI_INTERVENTION_AGENT_USER_MODE"):
        return True

    # 3) 兼容旧 UVX_PROJECT。
    if os.environ.get("UVX_PROJECT"):
        return True

    # 4) 启发式：模块装在 site-packages 或运行在 uv tool / pipx 隔离 venv 中。
    try:
        if _is_isolated_install_runtime():
            return True
    except Exception:
        pass

    # 5) 仓库源码树 + cwd 在源码树（dev carve-out）。
    # R76 之后包本体在 ``src/ai_intervention_agent/``，仓库根上移两层；
    # cwd 判定要以仓库根为锚（既兼容 ``uv run`` 在 repo root 调用，
    # 也兼容直接在 ``src/`` 子目录下调试）。
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
        # 任何判定异常都降级为用户模式（更安全/更符合文档预期）
        pass

    # 6) 默认保守地走用户模式。
    return True


def _macos_legacy_xdg_config_dir() -> Path | None:
    """**R113** — 返回 macOS 上 ``~/.config/ai-intervention-agent/`` 残留目录。

    macOS 用户配置的标准位置是 ``~/Library/Application Support/ai-intervention-agent/``
    （Apple File System Programming Guide / platformdirs ``user_config_dir`` 的
    macOS 实现都返回此路径）。但实际现场会出现 **macOS 上 `~/.config/ai-intervention-agent/`
    被创建** 的情况，可能来源：

    * **历史早期版本**：早期 ai-intervention-agent 或 platformdirs 早期版本可能
      在 macOS 上误用 XDG 路径。
    * **第三方安装脚本 / 跨平台 dotfiles**：用户从 Linux 迁移过来的 dotfiles
      或者批量配置脚本可能假设 ``.config/`` 是跨平台的。
    * **手动 mkdir + cp**：用户测试 / 调试时手动复制了 config。
    * **进程在错误的 cwd 下启动**：某个调用方把 ``find_config_file`` 在
      ``~/.config/ai-intervention-agent/`` 当 cwd 启动时，dev 模式分支会在该 cwd
      创建 ``config.toml``。

    R113 在 macOS 上探测此目录是否存在，以便：

    1. **向后兼容**：标准路径还没有 config 但 ``.config/`` 已有 → 优先用 legacy
       路径，避免用户的旧配置静默被新 default 覆盖。
    2. **fail-loud warn**：标准路径和 legacy 同时存在 → warn 让用户知道有歧义；
       仅 legacy 存在 → 强 warn 给出 ``mv`` 一键迁移命令。

    返回：
        macOS 上目录存在 → ``Path``；其他情况（非 macOS / 目录不存在）→ ``None``。
    """
    if platform.system().lower() != "darwin":
        # 仅 macOS 触发；Linux 上 `.config/` 是标准（XDG），Windows 上根本不会有
        return None
    legacy_dir = Path.home() / ".config" / "ai-intervention-agent"
    if not legacy_dir.is_dir():
        return None
    return legacy_dir


def find_config_file(config_filename: str = "config.toml") -> Path:
    """查找配置文件路径，支持环境变量覆盖、uvx / 安装模式和开发模式。

    检测路径以单个 ``logger.info`` 行可追溯地表达——每次冷启动都能从日志反查
    出"为什么用了这个路径"。

    优先级（高 → 低）
    ----
    1. ``config_filename`` 自身是绝对路径或带子目录 → 原样返回，跳过所有探测。
    2. ``AI_INTERVENTION_AGENT_CONFIG_FILE`` 环境变量 → 显式 override；目录形态
       会自动追加 ``config_filename``。
    3. :func:`_is_uvx_mode` 命中 → 仅在用户配置目录搜索 + 创建。
    4. 否则：当前目录 > 用户配置目录。

    格式探测
    ----
    每个候选目录都按 TOML > JSONC > JSON 的次序尝试，用于向后兼容历史
    JSONC/JSON 用户。**同目录里同时存在多种格式时只采用排序首位**——
    这一行为会显式 warn，避免静默忽略 user-edited JSONC。

    跨平台配置目录
    ----
    * Linux：``$XDG_CONFIG_HOME/ai-intervention-agent`` 或 ``~/.config/ai-intervention-agent``
    * macOS：``~/Library/Application Support/ai-intervention-agent``
    * Windows：``%APPDATA%\\ai-intervention-agent``

    macOS 兼容性（R113）
    ----
    在 macOS 上**额外**检查 ``~/.config/ai-intervention-agent/`` 是否有残留 config
    （历史版本 / 第三方脚本 / 手动 mkdir 都可能创建）。规则：

    * 标准路径 + ``.config/`` 都有 → 用标准路径，warn 提示 legacy 残留
    * 仅 ``.config/`` 有 → **优先用 legacy**（不丢用户配置），强 warn 给出 ``mv``
      迁移命令
    * 仅标准路径或都没有 → 行为不变

    Linux 上 ``.config/`` 是 XDG 标准，本逻辑不触发。

    错误处理
    ----
    用户配置目录探测失败（``platformdirs`` 都不可用 + 自家 fallback 也 raise）
    最终降级为 ``Path(config_filename)``——但会把 ``warning`` 日志带上完整堆栈
    便于排查权限 / 只读 home 等问题。
    """
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

    # 向后兼容的候选文件名列表（TOML 优先）
    _COMPAT_NAMES = ("config.toml", "config.jsonc", "config.json")

    def _pick_existing(directory: Path | None) -> Path | None:
        """在 ``directory`` 中按 TOML > JSONC > JSON 优先返回首个存在的候选。

        ``directory=None`` 表示使用进程级当前目录（``Path(name)`` 隐式相对
        cwd 解析），保留与历史 ``Path(name).exists()`` 行为兼容的 mock 表面：
        老测试通过 ``patch('config_manager.Path')`` 替换全局 Path 类来注入
        虚拟候选，``Path(name).exists()`` 仍然能命中。

        当目录里**同时**存在多种格式时把后面被忽略的格式 warn 出来，便于用户
        反查"我的 config.jsonc 怎么没生效"。
        """
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
        # 开发模式：检查当前工作目录（``directory=None`` 让 Path(name) 走进程
        # 级 cwd 解析；保留对老式 ``patch('config_manager.Path')`` 测试的兼容性）。
        cwd_hit = _pick_existing(None)
        if cwd_hit is not None:
            logger.info(f"使用当前目录的配置文件: {cwd_hit.absolute()}")
            return cwd_hit

    try:
        try:
            if not PLATFORMDIRS_AVAILABLE:
                raise ImportError("platformdirs not available")
            user_config_dir_path = Path(user_config_dir("ai-intervention-agent"))
        except ImportError:
            user_config_dir_path = _get_user_config_dir_fallback()

        user_hit = _pick_existing(user_config_dir_path)

        # R113: macOS 上额外探测 `~/.config/ai-intervention-agent/` 残留 config。
        # 仅 macOS 触发；Linux 上 .config/ 已经是 XDG 标准（user_config_dir_path
        # 本身就指向那里），不会进入此分支。
        legacy_macos_dir = _macos_legacy_xdg_config_dir()
        legacy_macos_hit = (
            _pick_existing(legacy_macos_dir) if legacy_macos_dir is not None else None
        )

        if user_hit is not None:
            if legacy_macos_hit is not None:
                logger.warning(
                    "[R113] macOS 上检测到非标准 XDG 配置路径残留: "
                    f"{legacy_macos_hit}。已使用标准路径 {user_hit}；"
                    "建议删除非标准路径以避免歧义： "
                    f"`rm -rf {legacy_macos_dir}`"
                )
            logger.info(f"使用用户配置目录的配置文件: {user_hit}")
            return user_hit

        if legacy_macos_hit is not None:
            # 向后兼容：标准路径无 config 但 .config/ 有，用 .config/ 不丢用户配置；
            # 强 warn 给出可一键复制的 mv 迁移命令。
            logger.warning(
                "[R113] macOS 上仅在非标准 XDG 路径找到配置: "
                f"{legacy_macos_hit}。标准路径 {user_config_dir_path} 暂无配置。"
                "已临时采用非标准路径以兼容历史用户；强烈建议立即迁移到标准位置：\n"
                f"  mkdir -p {shlex.quote(str(user_config_dir_path))}\n"
                f"  mv {shlex.quote(str(legacy_macos_hit))} "
                f"{shlex.quote(str(user_config_dir_path) + '/')}\n"
                f"  rmdir {shlex.quote(str(legacy_macos_dir))}"
            )
            return legacy_macos_hit

        # 都不存在，返回 TOML 路径（用于创建默认配置）
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
    """
    platformdirs 不可用时的回退实现，返回跨平台标准配置目录。

    Windows: %APPDATA%、macOS: ~/Library/Application Support、Linux: $XDG_CONFIG_HOME 或 ~/.config。
    """
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
    """
    配置管理器：TOML 配置文件的加载、读写、持久化、热重载。

    核心特性：使用可重入锁（RLock）保护共享状态、延迟保存优化、network_security 独立管理（带缓存）、
    文件变更监听、配置导入导出。通过模块级 config_manager 全局实例访问。

    支持格式：TOML（主格式）。旧 JSONC/JSON 文件在首次加载时自动迁移为 TOML。

    路由通过 Mixin 拆分（各 Mixin 定义在 config_modules/ 下）：
    - TomlEngineMixin: TOML 格式解析/保存（保留注释）
    - NetworkSecurityMixin: network_security 段校验/读写
    - FileWatcherMixin: 文件监听/回调/shutdown
    - IOOperationsMixin: 配置导出/导入/备份/恢复
    """

    def __init__(self, config_file: str = "config.toml"):
        """初始化配置管理器：查找配置文件、初始化锁和缓存、加载配置、启动文件监听"""
        # 判断是否为显式路径（绝对/含目录层级）——仅自动发现的旧文件才做 JSONC→TOML 迁移
        req = Path(config_file).expanduser()
        self._explicit_path = req.is_absolute() or req.parent != Path(".")
        self.config_file = find_config_file(config_file)

        # 初始化配置字典
        self._config: dict[str, Any] = {}

        # 初始化锁机制
        # RLock rationale (R336 contract): set() (config_manager.py:1131)
        # 在持有 self._lock 状态下调用 self._save_config() (line 1167),
        # 后者 → self._schedule_save() → `with self._lock:`
        # 即**同一线程在持锁状态下重入获取同一锁**。Lock 会 self-deadlock,
        # RLock 必需。同理: set_section + set_network_security_config 等
        # mutate API 都走相同 set→_save_config→_schedule_save chain。
        self._lock = threading.RLock()

        # 初始化文件内容和访问时间
        self._original_content: str | None = None  # 保存原始文件内容（用于保留注释）
        self._last_access_time = time.monotonic()  # 跟踪最后访问时间

        # 性能优化：配置写入缓冲机制
        self._pending_changes: dict[str, Any] = {}  # 待写入的配置变更
        self._save_timer: threading.Timer | None = None  # 延迟保存定时器
        self._save_delay = 3.0  # 延迟保存时间（秒）
        self._last_save_time: float = 0  # 上次保存时间（monotonic）

        # 【性能优化】network_security 配置缓存
        self._network_security_cache: dict[str, Any] | None = None
        self._network_security_cache_time: float = 0  # monotonic
        self._network_security_cache_ttl: float = 30.0  # 30 秒缓存有效期

        # 【性能优化】通用 section 缓存层
        self._section_cache: dict[str, dict[str, Any]] = {}
        self._section_cache_time: dict[str, float] = {}
        self._section_cache_ttl: float = 10.0  # section 缓存有效期（秒）

        # 【性能优化】缓存统计
        self._cache_stats = {
            "hits": 0,  # 缓存命中次数
            "misses": 0,  # 缓存未命中次数
            "invalidations": 0,  # 缓存失效次数
        }

        # 【新增】文件监听相关属性
        self._file_watcher_thread: threading.Thread | None = None
        self._file_watcher_running = False
        self._file_watcher_stop_event = threading.Event()  # 用于优雅停止
        self._file_watcher_interval = 2.0  # 检查间隔（秒）
        self._last_file_mtime: float = 0  # 上次文件修改时间
        self._config_change_callbacks: list[
            Callable[[], None]
        ] = []  # 配置变更回调函数列表

        # 加载配置文件
        self._load_config()

        # 初始化文件修改时间
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
            mdns = config_data.get("mdns", {})
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
        """从磁盘加载配置文件，排除 network_security，合并默认配置。

        【External-edit-wins 策略】
        当 ``reload()`` / file_watcher 触发本方法时，若内存中还有
        ``_pending_changes``（进程内 ``set()`` 调用产生、3s 延迟保存窗口内
        未落盘），必须**清空**这些 pending 并取消 ``_save_timer``，否则会
        发生悄悄的 last-write-wins race：

            T=0    ProcessThread  cfg.set("notification.bark_url", "A")
                                  → _pending_changes["notification.bark_url"] = "A"
                                  → schedule timer at +3s
            T=1.5  ExternalEditor user saves config.toml with bark_url = "B"
            T=2    FileWatcher    detects mtime change → calls reload()
                                  → _load_config() reads "B" into self._config
            T=3    SaveTimer      fires → _delayed_save() applies
                                  _pending_changes["A"] over self._config
                                  → writes "A" back to disk

        净效果：用户的外部编辑（"B"）被进程内 stale-set 默默覆盖，no warning。
        修复：reload 阶段清空 ``_pending_changes`` 并取消 ``_save_timer``，
        日志 WARNING 提示丢弃的变更（让外部编辑赢，符合"我改了配置文件就该
        生效"的用户直觉）。``__init__`` 调用本方法时 ``_pending_changes`` 必为
        空字典，分支 no-op，所以这个清理对初次加载零影响。
        """
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

            # 【可靠性】加载失败时回滚到上一次成功配置，避免“编辑中间态/损坏文件”导致回退到默认值
            had_previous_config = bool(self._config)
            previous_config = self._config.copy()
            previous_original_content = self._original_content
            try:
                # 自动迁移旧 JSONC/JSON 格式（仅自动发现的文件，显式路径不迁移）
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

                    # 【健壮性】加载时也做结构校验（重复数组定义/类型错误），避免静默吞掉损坏配置
                    self._validate_config_structure(full_config, content)

                    # 保存原始内容（用于保留注释）——仅在解析与结构校验成功后更新
                    self._original_content = content

                    # 完全排除 network_security，不加载到内存中
                    self._config = {}
                    for key, value in full_config.items():
                        if key != "network_security":
                            self._config[key] = value

                    if "network_security" in full_config:
                        logger.debug("network_security 配置已排除，不加载到内存中")
                else:
                    # 创建默认配置文件
                    self._config = self._exclude_network_security(
                        self._get_default_config()
                    )
                    self._original_content = None
                    self._create_default_config_file()
                    logger.info(f"创建默认配置文件: {self.config_file}")

                # 合并默认配置（确保新增的配置项存在）
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
        result = current.copy()  # 以当前配置为基础

        # 只添加缺失的默认键，不修改现有值
        for key, default_value in default.items():
            # 额外安全措施：确保不合并 network_security
            if key == "network_security":
                logger.debug("_merge_config: 跳过 network_security 配置")
                continue

            if key not in result:
                # 缺失的键，使用默认值
                result[key] = default_value
            elif isinstance(result[key], dict) and isinstance(default_value, dict):
                # 递归合并嵌套字典，但保持现有值优先
                result[key] = self._merge_config(default_value, result[key])

        # 确保结果中不包含 network_security
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
            # 取消之前的保存定时器
            if self._save_timer is not None:
                self._save_timer.cancel()

            # 设置新的延迟保存定时器
            self._save_timer = threading.Timer(self._save_delay, self._delayed_save)
            # 【可靠性】Timer 默认非守护线程，可能导致测试/进程退出被阻塞
            self._save_timer.daemon = True
            self._save_timer.start()
            logger.debug(f"已调度配置保存，将在 {self._save_delay} 秒后执行")

    def _delayed_save(self):
        """延迟保存定时器回调：应用待保存变更并写入文件"""
        try:
            with self._lock:
                self._save_timer = None
                # 应用待写入的变更
                if self._pending_changes:
                    logger.debug(
                        f"应用 {len(self._pending_changes)} 个待写入的配置变更"
                    )
                    for key, value in self._pending_changes.items():
                        self._set_config_value(key, value)
                    self._pending_changes.clear()

                # 执行实际保存
                self._save_config_immediate()
                self._last_save_time = time.monotonic()
                logger.debug("延迟配置保存完成")
        except Exception as e:
            logger.error(f"延迟保存配置失败: {e}", exc_info=True)

    def _set_config_value(self, key: str, value: Any):
        """内部方法：设置配置值（不触发保存，自动创建中间路径）"""
        keys = key.split(".")
        config = self._config

        # 导航到目标位置
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        # 设置值
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

            # 保留原文件权限（mkstemp 默认 0o600，可能不同于原文件）
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
            # 更新 mtime 缓存，避免文件监听器将本次写入误判为外部变更
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

            # 额外验证：检查是否存在重复的数组元素（格式损坏的标志）
            self._validate_config_structure(parsed_config, content)

            logger.debug("配置文件验证通过")
        except Exception as e:
            logger.error(f"配置文件验证失败: {e}", exc_info=True)
            raise

    def _validate_config_structure(self, parsed_config: dict[str, Any], content: str):
        """验证配置结构完整性（network_security 格式等）

        TOML 解析器会自动拒绝重复键，此处仅对 JSON 降级格式做额外校验。
        """
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

        # 验证network_security配置（如果存在）应该格式正确
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

                # 检查数组元素是否有效
                for network in allowed_networks:
                    if not isinstance(network, str):
                        raise ConfigValidationError(
                            f"network_security.allowed_networks 包含无效元素: {network}"
                        )

        logger.debug("配置文件结构验证通过")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持点号分隔的嵌套键如 'notification.sound_volume'，线程安全）"""
        # 说明：为避免多锁交错导致的竞态/死锁，这里统一使用 _lock 保护共享状态
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
        # network_security 特殊处理：必须走专用更新/落盘路径，避免写入内存但无法持久化
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

            # 性能优化：检查当前值是否与新值相同
            current_value = self.get(key)
            if current_value == value:
                logger.debug(
                    f"配置值未变化，跳过更新: {key} = {_sanitize_config_value_for_log(key, value)}"
                )
                return

            # 性能优化：使用缓冲机制
            if save:
                # 将变更添加到待写入队列
                self._pending_changes[key] = value
                # 立即更新内存中的配置
                self._set_config_value(key, value)
                # 调度延迟保存
                self._save_config()
            else:
                # 直接更新内存中的配置，不保存到文件
                self._set_config_value(key, value)
                # 清除 pending 中的同 key 旧值，防止 _delayed_save 回写覆盖
                self._pending_changes.pop(key, None)

            # 【缓存优化】失效相关 section 缓存，避免 get_section() 返回旧值
            section = key.split(".")[0] if key else ""
            if section == "network_security":
                # network_security 有独立缓存层，直接清空所有缓存更稳妥
                self.invalidate_all_caches()
            elif section:
                self.invalidate_section_cache(section)
            else:
                self.invalidate_all_caches()

            changed = True
            logger.debug(
                f"配置已更新: {key} = {_sanitize_config_value_for_log(key, value)}"
            )

        # 【热更新】配置在内存中更新后，触发回调通知其他模块（在锁外执行，避免死锁）
        if changed:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def update(self, updates: dict[str, Any], save: bool = True) -> None:
        """批量更新配置（仅处理变化项，合并为一次延迟保存，原子操作）"""
        # network_security 特殊处理：先剥离并走专用更新/落盘路径，避免进入 _config/_pending_changes
        network_security_updates: dict[str, Any] = {}
        non_ns_updates: dict[str, Any] = {}
        for k, v in (updates or {}).items():
            if k == "network_security" and isinstance(v, dict):
                # 视为整段覆盖（仍会被验证与归一化）
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
            # 若仅更新 network_security，则无需走通用 update 流程
            if not non_ns_updates:
                return

        changed_sections: set[str] = set()
        changed = False
        with self._lock:
            self._last_access_time = time.monotonic()

            # 性能优化：过滤出真正有变化的配置项
            actual_changes = {}
            for key, value in non_ns_updates.items():
                current_value = self.get(key)
                if current_value != value:
                    actual_changes[key] = value

            if not actual_changes:
                logger.debug("批量更新中没有配置变化，跳过保存")
                return

            # 性能优化：使用批量缓冲机制
            if save:
                # 将所有变更添加到待写入队列
                self._pending_changes.update(actual_changes)
                # 立即更新内存中的配置
                for key, value in actual_changes.items():
                    self._set_config_value(key, value)
                    logger.debug(
                        f"配置已更新: {key} = {_sanitize_config_value_for_log(key, value)}"
                    )
                # 调度延迟保存（只调度一次）
                self._save_config()
            else:
                # 直接更新内存中的配置，不保存到文件
                for key, value in actual_changes.items():
                    self._set_config_value(key, value)
                    # 清除 pending 中的同 key 旧值，防止 _delayed_save 回写覆盖
                    self._pending_changes.pop(key, None)
                    logger.debug(
                        f"配置已更新: {key} = {_sanitize_config_value_for_log(key, value)}"
                    )

            # 【缓存优化】失效涉及到的 section 缓存，避免 get_section() 返回旧值
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

        # 【热更新】配置在内存中更新后，触发回调通知其他模块（在锁外执行，避免死锁）
        if changed:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def force_save(self) -> None:
        """强制立即保存配置文件（取消延迟保存，应用所有待保存变更）"""
        with self._lock:
            # 取消延迟保存定时器
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None

            # 应用所有待写入的变更
            if self._pending_changes:
                logger.debug(
                    f"强制保存：应用 {len(self._pending_changes)} 个待写入的配置变更"
                )
                for key, value in self._pending_changes.items():
                    self._set_config_value(key, value)
                self._pending_changes.clear()

            # 立即保存
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
            raw = self.get(section, {})
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
            return dict(raw)
        try:
            return model_cls.model_validate(raw).model_dump()
        except Exception as e:
            logger.warning(f"配置段 '{section}' Pydantic 校验失败，使用原始值: {e}")
            return dict(raw)

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

            # 检查是否有任何值真的发生了变化
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

            # 应用更新
            current_section.update(updates)

            # 直接更新配置并保存，避免重复的值比较
            keys = section.split(".")
            config = self._config
            for k in keys[:-1]:
                if k not in config:
                    config[k] = {}
                config = config[k]
            config[keys[-1]] = current_section

            if save:
                self._save_config()

            # 【缓存优化】失效该 section 的缓存
            self.invalidate_section_cache(section)

            changed = True
            logger.debug(f"配置段已更新: {section}")

        # 【热更新】配置段更新后触发回调（在锁外执行，避免死锁）
        if changed:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def reload(self) -> None:
        """从磁盘重新加载配置文件（覆盖内存配置，失效缓存）"""
        logger.info("重新加载配置文件")
        self._load_config()
        # 【缓存优化】重新加载后失效所有缓存
        self.invalidate_all_caches()

    # ========================================================================
    # 缓存管理方法
    # ========================================================================

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
            # 清空 section 缓存
            invalidated_count = len(self._section_cache)
            self._section_cache.clear()
            self._section_cache_time.clear()

            # 清空 network_security 缓存
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
                self._section_cache_ttl = max(0.1, section_ttl)  # 最小 0.1 秒
                logger.debug(f"section 缓存 TTL 已设置为: {self._section_cache_ttl}s")

            if network_security_ttl is not None:
                self._network_security_cache_ttl = max(
                    1.0, network_security_ttl
                )  # 最小 1 秒
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

    # network_security 方法通过 NetworkSecurityMixin 提供（config_modules/network_security.py）

    # ========================================================================
    # 类型安全的配置获取方法
    # ========================================================================

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
            # 布尔类型特殊处理
            if value_type is bool:
                if isinstance(raw_value, bool):
                    return raw_value
                if isinstance(raw_value, str):
                    return raw_value.lower() in ("true", "1", "yes", "on")
                return bool(raw_value)

            # 其他类型转换
            converted = value_type(raw_value)

            # 边界验证（仅对数值类型）
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

    # 文件监听方法通过 FileWatcherMixin 提供（config_modules/file_watcher.py）
    # 配置导出/导入方法通过 IOOperationsMixin 提供（config_modules/io_operations.py）


# 全局配置管理器实例
config_manager = ConfigManager()

# 【资源生命周期】进程退出时尽量清理后台资源（文件监听/Timer）
# - 避免测试环境出现“退出卡住/资源未释放”类问题
# - shutdown() 本身幂等，重复调用安全
import atexit  # noqa: E402


def _shutdown_global_config_manager():
    try:
        config_manager.shutdown()
    except Exception:
        # 退出阶段不再抛异常
        pass


atexit.register(_shutdown_global_config_manager)


def get_config() -> ConfigManager:
    """获取全局配置管理器实例（自动启动文件监听）"""
    # 【配置热更新】默认启用文件监听（2 秒轮询，按你的选择 A + C）
    # 目的：外部编辑 config.toml 后无需重启即可生效
    try:
        if not config_manager.is_file_watcher_running:
            config_manager.start_file_watcher(interval=2.0)
    except Exception:
        # 配置系统属于基础设施：监听启动失败不应影响主流程
        pass

    return config_manager
