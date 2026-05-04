"""系统集成路由 Mixin — 让 Web UI 能调用本机命令打开配置文件等。

设计要点（TODO #4）：
- 仅响应 ``loopback``（127.0.0.1 / ::1）来源的请求，避免远程主机通过本机
  Web UI 触发任意命令执行；这是首层安全保护。
- 仅允许"已知配置文件"被打开（白名单：当前配置 + ``config.toml.default``），
  绝不接受外部传入的任意路径，杜绝路径穿越/任意文件打开攻击。
- 选择 IDE 的优先级：``AI_INTERVENTION_AGENT_OPEN_WITH`` 环境变量 →
  请求体 ``editor`` 参数 → 自动探测（cursor / code / windsurf / subl /
  webstorm / pycharm）→ 系统默认 (``open`` / ``xdg-open`` / ``start``)。
- 命令以参数列表方式传入 ``subprocess.Popen``，``shell=False``，
  避免 shell 注入。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flask import jsonify, request
from flask.typing import ResponseReturnValue

from config_manager import get_config
from enhanced_logging import EnhancedLogger

if TYPE_CHECKING:
    from flask import Flask

logger = EnhancedLogger(__name__)

# 自动探测时按优先级尝试的编辑器命令名（保留与 mcp.json 中常见 IDE 的呼应）
_AUTO_DETECT_EDITORS: tuple[tuple[str, list[str]], ...] = (
    # (命令名, 该命令打开文件时使用的额外参数)
    ("cursor", ["--reuse-window"]),
    ("code", ["--reuse-window"]),
    ("code-insiders", ["--reuse-window"]),
    ("windsurf", ["--reuse-window"]),
    ("zed", []),
    ("subl", []),  # Sublime Text
    ("mate", []),  # TextMate
    ("webstorm", []),
    ("pycharm", []),
    ("idea", []),
)

# 客户端可以通过 editor 参数显式指定，受白名单约束
_ALLOWED_EDITOR_NAMES = frozenset(name for name, _ in _AUTO_DETECT_EDITORS) | frozenset(
    {"system", "default"}
)


def _resolve_loopback_ips() -> set[str]:
    """所有视为本机环回的客户端 IP（IPv4 / IPv6 兼容）。"""
    return {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


def _get_client_ip() -> str:
    """读取 Flask 请求的真实客户端 IP（不信任 X-Forwarded-* 头）。"""
    return request.remote_addr or ""


def _is_loopback_request() -> bool:
    """仅本机来源（127.0.0.1 / ::1）的请求允许执行打开命令。"""
    return _get_client_ip() in _resolve_loopback_ips()


def _resolve_allowed_paths() -> list[Path]:
    """生成本次请求允许打开的配置文件路径白名单。"""
    candidates: list[Path] = []
    try:
        cfg = get_config()
        config_file = getattr(cfg, "config_file", None)
        if config_file:
            candidates.append(Path(str(config_file)).resolve())
    except Exception as exc:
        logger.warning(f"获取当前配置文件路径失败: {exc}")

    # 同时允许默认模板，方便用户从 UI 跳过去对照
    repo_root = Path(__file__).resolve().parent.parent
    for default_name in ("config.toml.default", "config.jsonc.default"):
        p = (repo_root / default_name).resolve()
        if p.exists():
            candidates.append(p)

    # 去重
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def _detect_default_editor() -> tuple[str | None, list[str]]:
    """自动探测可用的编辑器，返回 (绝对路径, 额外参数)。"""
    # 环境变量优先
    env_choice = os.environ.get("AI_INTERVENTION_AGENT_OPEN_WITH", "").strip()
    if env_choice:
        env_path = shutil.which(env_choice)
        if env_path:
            return env_path, []
        logger.warning(
            f"AI_INTERVENTION_AGENT_OPEN_WITH={env_choice!r} 不在 PATH 中，已忽略"
        )

    for name, extra in _AUTO_DETECT_EDITORS:
        cmd_path = shutil.which(name)
        if cmd_path:
            return cmd_path, list(extra)
    return None, []


def _system_open_command(target: Path) -> list[str] | None:
    """返回以系统默认应用打开文件的命令。失败返回 None。"""
    target_str = str(target)
    if sys.platform == "darwin":
        opener = shutil.which("open")
        if opener:
            return [opener, target_str]
    elif sys.platform.startswith("win"):
        # Windows 用 cmd /c start "" "<path>"，第一个 "" 是 start 的窗口标题占位
        comspec = os.environ.get("COMSPEC") or shutil.which("cmd")
        if comspec:
            return [comspec, "/c", "start", "", target_str]
    else:
        for opener_name in ("xdg-open", "gio"):
            opener = shutil.which(opener_name)
            if opener:
                if opener_name == "gio":
                    return [opener, "open", target_str]
                return [opener, target_str]
    return None


class SystemRoutesMixin:
    """系统集成路由：当前仅 1 个 endpoint，后续可扩展（如打开 logs 目录）。"""

    if TYPE_CHECKING:
        app: Flask
        limiter: Any

    def _setup_system_routes(self) -> None:
        @self.app.route("/api/system/open-config-file", methods=["POST"])
        @self.limiter.limit("20 per minute")
        def open_config_file() -> ResponseReturnValue:
            """用本机 IDE / 默认应用打开当前配置文件
            ---
            tags:
              - System
            consumes:
              - application/json
            parameters:
              - in: body
                name: body
                required: false
                schema:
                  type: object
                  properties:
                    path:
                      type: string
                      description: |
                        要打开的配置文件路径；若省略则使用当前进程读取的配置文件。
                        必须命中后端白名单（当前配置文件或仓库内的 default 模板），
                        否则返回 403。
                    editor:
                      type: string
                      description: |
                        手动指定编辑器（如 cursor / code / system）。
                        留空时自动探测；不在白名单中的取值会被忽略并回退到自动探测。
            responses:
              200:
                description: 已经触发外部进程打开（不保证窗口聚焦成功）
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    path:
                      type: string
                      description: 实际打开的文件路径
                    editor:
                      type: string
                      description: 实际使用的命令（基名），"system" 表示系统默认
              400:
                description: 路径不存在或编辑器不可用
              403:
                description: 来源非环回地址，或路径不在白名单中
              500:
                description: 启动子进程失败
            """
            if not _is_loopback_request():
                logger.warning(
                    f"open-config-file 拒绝非环回请求: client={_get_client_ip()!r}"
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Only loopback (127.0.0.1) callers are allowed.",
                        }
                    ),
                    403,
                )

            payload: dict[str, Any] = {}
            try:
                if request.data:
                    payload = request.get_json(silent=True) or {}
            except Exception:
                payload = {}

            allowed_paths = _resolve_allowed_paths()
            if not allowed_paths:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Server has no resolvable config file path.",
                        }
                    ),
                    400,
                )

            requested_raw = payload.get("path")
            target: Path | None = None
            if requested_raw:
                if not isinstance(requested_raw, str):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "`path` must be a string when provided.",
                            }
                        ),
                        400,
                    )
                try:
                    candidate = Path(requested_raw).expanduser().resolve()
                except Exception:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Cannot resolve the provided path.",
                            }
                        ),
                        400,
                    )
                if candidate not in allowed_paths:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": (
                                    "Provided path is not in the server-side "
                                    "allow-list of config files."
                                ),
                            }
                        ),
                        403,
                    )
                target = candidate
            else:
                target = allowed_paths[0]

            assert target is not None
            if not target.exists():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Config file does not exist: {target}",
                        }
                    ),
                    400,
                )

            # 选择编辑器：显式 editor 字段（白名单约束） → 环境变量 → 自动探测 → 系统默认
            editor_choice = str(payload.get("editor") or "").strip().lower()
            editor_path: str | None = None
            extra_args: list[str] = []
            editor_basename: str = ""

            if editor_choice and editor_choice not in _ALLOWED_EDITOR_NAMES:
                logger.warning(
                    f"open-config-file 收到未知 editor={editor_choice!r}，已忽略"
                )
                editor_choice = ""

            if editor_choice in {"system", "default"}:
                editor_path = None  # 走 system fallback
            elif editor_choice:
                editor_path = shutil.which(editor_choice)
                if editor_path:
                    for name, extra in _AUTO_DETECT_EDITORS:
                        if name == editor_choice:
                            extra_args = list(extra)
                            break
                else:
                    logger.info(
                        f"显式 editor={editor_choice!r} 未在 PATH 中，回退到自动探测"
                    )

            if editor_path is None and editor_choice not in {"system", "default"}:
                editor_path, extra_args = _detect_default_editor()

            if editor_path:
                editor_basename = Path(editor_path).name
                cmd: list[str] = [editor_path, *extra_args, str(target)]
            else:
                fallback = _system_open_command(target)
                if fallback is None:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": (
                                    "No editor found in PATH and no system "
                                    "default opener available."
                                ),
                            }
                        ),
                        500,
                    )
                cmd = fallback
                editor_basename = "system"

            try:
                # close_fds=True / start_new_session=True 让子进程独立于本服务，
                # 避免在 Web UI 重启时把 IDE 也带走。
                subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                    shell=False,
                )
            except FileNotFoundError as exc:
                logger.error(f"启动编辑器失败（可执行文件丢失）: {exc}")
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Editor command vanished between detection and exec.",
                        }
                    ),
                    500,
                )
            except OSError as exc:
                logger.error(f"启动编辑器失败: {exc}", exc_info=True)
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Failed to launch editor: {exc}",
                        }
                    ),
                    500,
                )

            logger.info(f"已请求 {editor_basename!r} 打开配置文件: {target}")
            return jsonify(
                {
                    "success": True,
                    "path": str(target),
                    "editor": editor_basename,
                }
            )

        @self.app.route("/api/system/open-config-file/info", methods=["GET"])
        @self.limiter.exempt
        def open_config_file_info() -> ResponseReturnValue:
            """返回当前可用的编辑器与允许打开的配置文件路径。

            前端用这个 endpoint 决定按钮是否可点、是否提示用户配置环境变量。
            """
            if not _is_loopback_request():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Only loopback (127.0.0.1) callers are allowed.",
                        }
                    ),
                    403,
                )

            editor_path, _extra = _detect_default_editor()
            allowed = _resolve_allowed_paths()
            return jsonify(
                {
                    "success": True,
                    "editor": Path(editor_path).name if editor_path else None,
                    "editor_available": bool(editor_path),
                    "system_fallback_available": _system_open_command(
                        allowed[0] if allowed else Path(".")
                    )
                    is not None,
                    "allowed_paths": [str(p) for p in allowed],
                    "primary_path": str(allowed[0]) if allowed else None,
                }
            )
