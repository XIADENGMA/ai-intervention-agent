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
import time
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
                # R72-B (CodeQL py/stack-trace-exposure #46)：不把 OSError
                # 的 errno / filename 等系统细节回传给客户端。运维需要这些
                # 时去看服务器日志（已经 exc_info=True 完整记录）。
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                "Failed to launch editor; check server logs "
                                "for details."
                            ),
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

        @self.app.route("/api/system/network-base-url-status", methods=["GET"])
        @self.limiter.limit("60 per minute")
        def network_base_url_status() -> ResponseReturnValue:
            """返回当前 Web UI 的对外 base_url 诊断信息。

            ---
            tags:
              - System
            description: |
                设置面板（Bark / 跨设备通知）用本接口判断 ``effective_base_url``
                是否回环、并展示 ``suggested_lan_base_url`` 推荐值，引导用户配
                ``web_ui.external_base_url`` 或调整 ``web_ui.host``。

                **任意来源** 的请求都允许查询 —— LAN 上 PWA 设置面板也需要看到
                这个状态。所有字段都是诊断元数据，不暴露内部敏感配置。
            responses:
              200:
                description: 诊断快照
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    effective_base_url:
                      type: string
                      description: |
                        ``resolve_external_base_url(for_external_use=False)`` 的结果，
                        即"通常会展示给用户的 base_url"。可能是 loopback。
                    is_loopback:
                      type: boolean
                      description: |
                        ``effective_base_url`` 是否命中 ``is_loopback_url``。
                        ``true`` 表示跨设备点击通知**会失败**。
                    external_safe_base_url:
                      type: string
                      description: |
                        ``for_external_use=True`` 模式的结果——loopback 时为空串，
                        Bark 推送链路实际用这个。
                    suggested_lan_base_url:
                      type: string
                      description: |
                        ``suggest_lan_base_url`` 探测结果（``http://<lan-ip>:<port>``）。
                        探测失败 / 离线返回空串。
                    recommendation:
                      type: string
                      description: |
                        ``configure_external_base_url`` / ``bind_lan_interface`` /
                        ``ok``，对应不同的修复建议（前端可选择性国际化）。
                    port:
                      type: integer
            """
            try:
                import server_config

                effective = server_config.resolve_external_base_url() or ""
                external_safe = (
                    server_config.resolve_external_base_url(for_external_use=True) or ""
                )
                is_loopback = bool(
                    effective and server_config.is_loopback_url(effective)
                )

                cfg = get_config()
                web_section = cfg.get_section("web_ui") or {}
                try:
                    port = int(web_section.get("port", 8080))
                except (TypeError, ValueError):
                    port = 8080

                suggested_lan: str = ""
                if is_loopback or not external_safe:
                    suggested_lan = server_config.suggest_lan_base_url(port) or ""

                if not is_loopback and external_safe:
                    recommendation = "ok"
                elif suggested_lan:
                    recommendation = "configure_external_base_url"
                else:
                    recommendation = "bind_lan_interface"

                return jsonify(
                    {
                        "success": True,
                        "effective_base_url": effective,
                        "is_loopback": is_loopback,
                        "external_safe_base_url": external_safe,
                        "suggested_lan_base_url": suggested_lan,
                        "recommendation": recommendation,
                        "port": port,
                    }
                )
            except Exception as exc:
                logger.warning(
                    f"network-base-url-status 探测失败: {exc}", exc_info=True
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Failed to resolve base url status",
                        }
                    ),
                    500,
                )

        @self.app.route("/api/system/sse-stats", methods=["GET"])
        @self.limiter.limit("60 per minute")
        def sse_stats() -> ResponseReturnValue:
            """返回 SSE 总线运行时计数器（R47）。

            ---
            tags:
              - System
            description: |
                给运维 / VS Code 状态栏 / Web UI 状态面板提供 ``_SSEBus`` 的健康指标快照：
                ``emit_total`` / ``latest_event_id`` / ``gap_warnings_emitted`` /
                ``backpressure_discards`` / ``subscriber_count`` / ``history_size``。

                所有字段都是单调累计或瞬时值；caller 可以记两次快照算速率。
                **任意来源** 的请求都允许查询——这是只读诊断元数据，不暴露任何
                敏感配置 / 用户内容（payload 只含计数）。
            responses:
              200:
                description: SSE 总线指标快照
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    emit_total:
                      type: integer
                      description: emit() 被调用的累计次数
                    latest_event_id:
                      type: integer
                      description: 最近一次 emit 分配的 id
                    gap_warnings_emitted:
                      type: integer
                      description: subscribe(after_id=...) 命中 evict 分支的累计次数
                    backpressure_discards:
                      type: integer
                      description: emit() 因 queue Full / 积压超阈值踢 subscriber 的累计次数
                    subscriber_count:
                      type: integer
                      description: 当前活跃 SSE 订阅者数（瞬时值）
                    history_size:
                      type: integer
                      description: 当前 history deque 长度（瞬时值，≤ _HISTORY_MAXLEN）
            """
            try:
                from web_ui_routes.task import _sse_bus

                snapshot = _sse_bus.stats_snapshot()
                return jsonify({"success": True, **snapshot})
            except Exception as exc:
                logger.warning(f"sse-stats 探测失败: {exc}", exc_info=True)
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Failed to read SSE stats snapshot",
                        }
                    ),
                    500,
                )

        @self.app.route("/api/system/health", methods=["GET"])
        @self.limiter.limit("120 per minute")
        def system_health() -> ResponseReturnValue:
            """综合健康检查端点（R53-F），适合 K8s liveness/readiness probe / 监控仪表板。

            ---
            tags:
              - System
            description: |
                聚合 SSE bus / TaskQueue / 最近日志 三个维度的健康指标，用一份
                简单 JSON 给监控系统消费。**不包含敏感信息**（无 prompt 内容、
                无 config 值），所有字段都是数值或 enum，可直接对接 Datadog /
                Prometheus / 自建监控。

                ## 响应规约

                * ``status``：整体健康度的 enum：

                  - ``healthy``：所有子系统正常；
                  - ``degraded``：有 ERROR 级日志或 backpressure 累计但服务仍在跑，
                    监控可以告警但不应自动重启；
                  - ``unhealthy``：任何子系统拉取失败 / 内部异常，监控应当 page
                    on-call。

                * ``checks``：各子检查的 ``{ok: bool, ...}`` 详情，方便定位问题。

                * ``ts_unix``：本次 health 评估时刻（int 秒），监控可基于它检测
                  端点本身的 freshness。

                ## HTTP 状态码

                * 200 — ``healthy`` / ``degraded``：服务可用；
                * 503 — ``unhealthy``：服务有内部问题，K8s readiness probe 应据此
                  判定不发流量给本实例。

                rate-limit 120/min（高于 sse-stats 60/min 和 recent-logs 30/min），
                因为 K8s probe 默认 10 s 一次，120/min 给两实例共用足够余量。
            responses:
              200:
                description: 服务健康（healthy 或 degraded）
              503:
                description: 服务不健康（任意子检查内部异常）
            """
            ts = int(time.time())
            checks: dict[str, dict[str, object]] = {}
            try:
                from web_ui_routes.task import _sse_bus

                snap = _sse_bus.stats_snapshot()
                checks["sse_bus"] = {
                    "ok": True,
                    "subscriber_count": snap.get("subscriber_count", 0),
                    "backpressure_discards": snap.get("backpressure_discards", 0),
                    "gap_warnings_emitted": snap.get("gap_warnings_emitted", 0),
                }
            except Exception as exc:
                checks["sse_bus"] = {"ok": False, "error": str(exc)}

            try:
                from task_queue_singleton import get_task_queue

                tq = get_task_queue()
                # ``get_task_count`` 返回 ``{"total": int, ...}``
                count_dict = tq.get_task_count()
                checks["task_queue"] = {
                    "ok": True,
                    "total": count_dict.get("total", 0),
                    "max_tasks": tq.max_tasks,
                }
            except Exception as exc:
                checks["task_queue"] = {"ok": False, "error": str(exc)}

            try:
                from enhanced_logging import get_recent_logs

                # 数最近 5 分钟内的 ERROR 数量。5 分钟是个权衡：太短(1m)
                # 容易因为 cron job 的瞬时 spike 误判，太长(30m)无法反映
                # 当下健康度。监控可结合多次采样判趋势。
                cutoff = ts - 300
                recent = get_recent_logs()
                error_count = sum(
                    1
                    for entry in recent
                    if entry.get("level_no", 0) >= 40  # ERROR=40, CRITICAL=50
                    and entry.get("ts_unix", 0) >= cutoff
                )
                checks["recent_errors"] = {
                    "ok": True,
                    "count_last_5min": error_count,
                    "buffer_total": len(recent),
                }
            except Exception as exc:
                checks["recent_errors"] = {"ok": False, "error": str(exc)}

            # 整体 status 决策
            all_ok = all(check.get("ok") for check in checks.values())
            # ``checks[*]`` 的 value 是 ``dict[str, object]``，子 .get(...) 因此返回
            # ``object``，``int()`` 拒绝直接转。改用本地变量 + ``isinstance`` 守
            # 卫：拿到 int / 数值就用，否则降级为 0（说明该子检查挂了，直接当
            # 没观测到来抑制误判）。
            sse_check = checks.get("sse_bus", {})
            re_check = checks.get("recent_errors", {})
            bp_raw = (
                sse_check.get("backpressure_discards", 0)
                if isinstance(sse_check, dict)
                else 0
            )
            err_raw = (
                re_check.get("count_last_5min", 0) if isinstance(re_check, dict) else 0
            )
            backpressure = bp_raw if isinstance(bp_raw, int) else 0
            recent_err_count = err_raw if isinstance(err_raw, int) else 0

            if not all_ok:
                status = "unhealthy"
            elif backpressure > 0 or recent_err_count > 0:
                status = "degraded"
            else:
                status = "healthy"

            payload = {"status": status, "ts_unix": ts, "checks": checks}
            http_code = 503 if status == "unhealthy" else 200
            return jsonify(payload), http_code

        @self.app.route("/api/system/recent-logs", methods=["GET"])
        @self.limiter.limit("30 per minute")
        def recent_logs() -> ResponseReturnValue:
            """返回 ``enhanced_logging`` ring buffer 里最近 N 条 WARN/ERROR（R52-B）。

            ---
            tags:
              - System
            description: |
                给运维 / 状态面板拉取最近的 WARNING/ERROR 日志摘要，**已脱敏**
                （password / sk- key / ghp_ token 等被 ``LogSanitizer`` 替换为
                ``***REDACTED***``）、单条 message 截断到 500 字符。

                ``limit`` query 参数可选，默认 50，上限 200（即 ring buffer 容量）；
                返回顺序按时间正序（旧 → 新）。

                ``aiia://server/info`` 资源已经默认带了最新 20 条；本端点存在的
                意义是：(1) 让 PWA / VS Code 状态面板可以独立拉日志而不依赖
                MCP；(2) ``server_info`` 默认 20 条不够时可以拿更多。

                **任意来源** 的请求都允许查询——payload 已脱敏，无敏感信息。
                rate-limit 30/min 比 sse-stats 更紧（500 字节/条 × 200 条 ≈ 100KB
                相对昂贵），避免被滥用做日志爬取。
            parameters:
              - in: query
                name: limit
                description: 返回最近 N 条；默认 50，1 ≤ limit ≤ 200
                required: false
                type: integer
            responses:
              200:
                description: 最近 N 条日志快照
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    count:
                      type: integer
                      description: 实际返回条数（≤ limit）
                    entries:
                      type: array
                      description: 按时间正序的日志条目数组
                      items:
                        type: object
                        properties:
                          ts_unix:
                            type: integer
                          level_no:
                            type: integer
                          level_name:
                            type: string
                          logger_name:
                            type: string
                          message:
                            type: string
            """
            try:
                from enhanced_logging import _LOG_RING_MAXLEN, get_recent_logs

                # 解析 limit query：默认 50，上限即 buffer 容量。
                raw_limit = request.args.get("limit", "")
                limit = 50
                if raw_limit:
                    try:
                        candidate = int(str(raw_limit).strip())
                        if 1 <= candidate <= _LOG_RING_MAXLEN:
                            limit = candidate
                    except (ValueError, TypeError):
                        # 非法 limit 用默认 50；不直接 400，避免轻易因输入错被拒
                        pass

                entries = get_recent_logs(limit=limit)
                return jsonify(
                    {
                        "success": True,
                        "count": len(entries),
                        "entries": entries,
                    }
                )
            except Exception as exc:
                logger.warning(f"recent-logs 探测失败: {exc}", exc_info=True)
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Failed to read recent logs ring buffer",
                        }
                    ),
                    500,
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
