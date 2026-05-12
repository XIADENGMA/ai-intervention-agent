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

from ai_intervention_agent.config_manager import get_config
from ai_intervention_agent.enhanced_logging import EnhancedLogger

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


# ---------------------------------------------------------------------------
# R121-A: /api/system/health 增强辅助函数
#
# 设计原则：
# 1. **不在 ``system_health()`` 函数体内 import / 调 ``get_config()``** —— R53-F
#    的 ``test_no_config_value_passthrough`` 把 "handler 不应直接读 config"
#    编码成机器化测试，所以读 config 的逻辑必须搬出 handler，由 helper 间接
#    完成。这是契约不是约定。
# 2. **每个 helper 都 swallow exception 并返回 ``None`` / 安全默认值** —— health
#    端点必须高可用，任何子项探测异常都不能让整端点 5xx；handler 那一层只
#    汇总 ``ok`` 标记并把整体 status 降到 ``unhealthy``。
# 3. **payload 只放数值 / enum / 路径** —— 绝不回传 config 字段值（password /
#    token / bark url ...），路径本身已经通过 ``/api/system/open-config-file/info``
#    暴露过，不构成新的泄漏面。
# ---------------------------------------------------------------------------


def _safe_uptime_seconds() -> float | None:
    """返回进程启动至今的秒数；任何错误返回 None。"""
    try:
        from ai_intervention_agent import server

        started = getattr(server, "_PROCESS_STARTED_AT_UNIX", None)
        if not isinstance(started, int | float):
            return None
        return round(time.time() - float(started), 3)
    except Exception:
        return None


def _safe_project_version() -> str | None:
    """返回项目版本号；任何错误返回 None。"""
    try:
        from ai_intervention_agent.web_ui import get_project_version

        v = get_project_version()
        return str(v) if v else None
    except Exception:
        return None


def _safe_config_file_path() -> str | None:
    """返回当前配置文件绝对路径（仅路径，不读值）；任何错误返回 None。

    路径本身在 ``/api/system/open-config-file/info`` 已经暴露过，所以从
    health 端点也透出不构成新的泄漏面——但反之它对 K8s probe / 监控仪
    表板非常有价值（"我连的对了吗？"）。
    """
    try:
        cfg = get_config()
        config_file = getattr(cfg, "config_file", None)
        return str(config_file) if config_file else None
    except Exception:
        return None


def _safe_web_ui_env_overrides() -> dict[str, str] | None:
    """返回当前生效的 ``web_ui`` env override 名单（含值），便于运维 / K8s
    probe 一眼看出 "这个进程的 host/port/language 是不是被 env 覆盖了"。

    使用场景
    ----
    * 用户在 systemd unit 里写错 ``AI_INTERVENTION_AGENT_WEB_UI_PORT=80``
      （非数字 / 越界），server 会 fallback 到 ``config.toml`` 值——监控
      仪表板看 ``port`` 字段以为正常，但用户实际期望 80。本端点的
      ``web_ui_env_overrides`` 字段会让运维立刻看到 "env 设了，但 fallback
      了"——配合 stderr WARNING 形成双重证据链。
    * 多实例滚动升级：``config.toml`` 一致但 env vars 不同时，本字段帮
      仪表板区分实例。

    返回语义
    ----
    * ``{}``（空 dict）：当前进程**无** web_ui env override 生效，所有
      值来自 ``config.toml`` / 默认值；
    * ``{env_name: value, ...}``：当前生效的 env var 名 + 字符串值（明文
      暴露——host/port/language 都不是敏感信息，与 ``config_file_path``
      的暴露层级一致）；
    * ``None``：探测失败（``service_manager`` 模块异常 / ``os.environ``
      访问异常等）。

    安全
    ----
    * 仅暴露 web_ui 三个明确白名单 env var（HOST/PORT/LANGUAGE），不会
      泄漏 secret / token 类敏感 env vars；
    * 仅读 env，**不**触碰 ``config.toml`` 真实值——与 R53-F
      ``test_no_config_value_passthrough`` 契约一致。
    """
    try:
        from ai_intervention_agent import service_manager as _sm

        active: dict[str, str] = {}
        # 白名单：仅 web_ui 三个 env override，避免悄悄扩面到敏感 env
        for env_name in (
            _sm._ENV_WEB_UI_HOST,
            _sm._ENV_WEB_UI_PORT,
            _sm._ENV_WEB_UI_LANGUAGE,
        ):
            raw = os.environ.get(env_name)
            if raw is None:
                continue
            stripped = raw.strip()
            if stripped:
                active[env_name] = stripped
        return active
    except Exception:
        return None


def _safe_build_info() -> dict[str, str] | None:
    """返回 ``{git_commit, git_branch, git_dirty}`` build 元信息；失败返回 None。

    R132：把 R63 已有的 ``server._resolve_build_info()`` 投影到 health
    端点。比 ``version`` 字段精确（``v1.5.45`` 可能对应过 100 个 commit，
    ``git_commit=fa6f49d`` 只对应一份代码）；监控做 PR rollout 时立刻
    能区分「新版本上线了吗 / 这个实例还在跑老 commit 吗 / 是 dirty 工作
    树吗」三个问题。

    实现策略：
    1. ``_resolve_build_info`` 是 lazy + module-level cache，第一次调
       fork 3 个 ``git`` subprocess，后续只是 dict 浅拷贝——监控按
       10 s 一次 K8s probe 拉这个端点，性能开销可忽略；
    2. pip install / docker / pyinstaller 等没有 ``.git`` 的部署，
       cache 里全是 ``"unknown"``，handler 仍然返回 dict 而不是
       None——「unknown 不是失败」是 R63 的契约；只有 import 阶段
       炸了（罕见）才返回 None；
    3. 任何错误一律 swallow（与 ``_safe_notification_summary`` /
       ``_safe_uptime_seconds`` / ``_safe_project_version`` 同款防
       御策略）。
    """
    try:
        from ai_intervention_agent import server

        info = server._resolve_build_info()
        if not isinstance(info, dict):
            return None
        return {
            "git_commit": str(info.get("git_commit", "unknown")),
            "git_branch": str(info.get("git_branch", "unknown")),
            "git_dirty": str(info.get("git_dirty", "unknown")),
        }
    except Exception:
        return None


# R142：health 端点暴露 4 家 provider 的 per-provider 统计快照。
# 顺序固定，与 ``NotificationType`` 同源；缺失的 provider（既未注册也没失败计数）
# 用 ``None`` 占位，方便监控用 stable 的 key 集合做 dashboard 模板。
_HEALTH_PER_PROVIDER_KEYS: tuple[str, ...] = ("bark", "web", "sound", "system")

# R143：last_error class normalization —— per_provider.last_error_class 的取值
# 是 5 个稳定字符串之一，与 ``last_error_present`` boolean 互补：boolean 答
# "上次最近一次失败有没有 error 信息"，class 答"是哪一类"。监控 dashboard
# 可以做 stack-bar："这个 provider 最近 N 次失败，4xx 占多少 / 5xx 占多少
# / network 占多少"，比单个 boolean 信号丰富 5 倍。
#
# 关键：所有取值都是 **泛化的错误类**，不含具体 URL / device_key / token /
# error message —— PII 边界与 R142 一致。
_HEALTH_ERROR_CLASS_VALUES: tuple[str, ...] = (
    "client_error",  # 4xx HTTP / 设备密钥错 / 鉴权失败
    "server_error",  # 5xx HTTP / Bark / 推送平台自身故障
    "network_error",  # connection refused / DNS 失败 / 网络中断
    "timeout",  # 请求超时
    "not_registered",  # provider 没在 NotificationManager 注册
    "unknown",  # 无法归类的字符串（兜底）
)


def _classify_last_error(last_error: str | None) -> str | None:
    """R143：把 NotificationManager 写入的 ``last_error`` 字符串归一化成
    一个稳定的错误类。

    输入约定（来自 ``NotificationManager._send_to_provider`` line 1117-1126）：

    * Bark：``str(dict)``，含 ``status_code`` / ``detail`` 子键，如
      ``"{'status_code': 401, 'detail': 'Bark API returned 401...'}"``
    * provider not registered：固定字符串 ``"provider_not_registered"``
    * 其他 provider 暂未写 last_error，None / "" 都会回 None

    设计契约：

    * **永不暴露原文本** —— 只看模式特征 (HTTP status code / 关键字)，
      返回 ``_HEALTH_ERROR_CLASS_VALUES`` 之一。
    * **决定性** —— 同一 last_error 字符串在任何环境都返回同一类。
    * **5xx > 4xx > timeout > network > not_registered > unknown** 的优先
      级，避免一个 error 同时落到多类（如 "Connection timeout" 优先归
      timeout 不是 network）。
    * ``None`` / ``""`` → ``None`` —— 与 ``last_error_present`` 同语义。
    """
    if not last_error:
        return None

    s = str(last_error)
    s_lower = s.lower()

    if "provider_not_registered" in s_lower:
        return "not_registered"

    # 提取 HTTP status code —— 限定在明确的 HTTP 上下文里，不做裸数字
    # 兜底（避免 "Connection refused on port 443" 中的 ``443`` 被误判为
    # 4xx → client_error）。两条路径：
    # 1. ``'status_code': NNN`` —— NotificationManager 写入 Bark dict
    #    的固定 repr 模式
    # 2. ``HTTP NNN`` / ``http nnn`` —— 自由文本中的 HTTP layer 标识
    import re

    sc_match = re.search(
        r"(?:status[_\s]*code['\":\s]+|http\s+|http/[\d.]+\s+)(\d{3})", s_lower
    )
    if not sc_match:
        # 第三条：以 ``NNN <文字>`` 开头的常见 HTTP 错误格式，如
        # ``500 Internal Server Error from upstream``。只匹配 4xx/5xx
        # 数字 + 空格 + 字母 + 字母/空格 这种结构，避免 ``443 port`` /
        # ``80 abc`` 这种 port 编号被误判。
        sc_match = re.match(r"\s*([4-5]\d\d)\s+[a-z][a-z ]+", s_lower)

    if sc_match:
        try:
            sc = int(sc_match.group(1))
        except (ValueError, IndexError):
            sc = 0
        if 500 <= sc < 600:
            return "server_error"
        if 400 <= sc < 500:
            return "client_error"

    # 没拿到 status code —— 按关键字匹配
    if "timeout" in s_lower or "timed out" in s_lower:
        return "timeout"

    if any(
        kw in s_lower
        for kw in (
            "connection refused",
            "connectionerror",
            "connecterror",
            "network",
            "dns",
            "name resolution",
            "unreachable",
        )
    ):
        return "network_error"

    return "unknown"


def _safe_per_provider_snapshot(
    providers_stats: dict[str, Any], now: float
) -> dict[str, dict[str, object] | None]:
    """R142：把 ``stats.providers`` 整理成「监控/dashboard 友好」的安全摘要。

    输入是 ``notification_manager.get_status()['stats']['providers']``——
    每个 provider 已经是 dict（包含 attempts/success/failure/last_*_at 等）。
    本函数刻意 **不** 透出 ``last_error`` 原始字符串：

    * Bark 的 ``last_error`` 来自 BarkProvider 写到 ``event.metadata
      ["bark_error"]`` 的运行时错误（虽然已经在 NotificationManager 内
      truncate 到 800 字符，但仍可能含有 device_key / 服务器 URL 这种
      不希望出现在 ``/api/system/health`` 公共端点的 PII）。
    * 改成 ``last_error_present: bool``——告诉调用方"最近一次失败有没
      有 error 信息"，详情仍然要回 logs 看。

    其他字段都已经是聚合量或时间戳，直接转为 ``last_*_age_seconds``
    （相对 ``now``）暴露，而不是绝对时间——绝对时间在跨机器/跨时区
    的多副本场景里没意义，age 是更稳定的语义。
    """
    out: dict[str, dict[str, object] | None] = {}
    for ptype in _HEALTH_PER_PROVIDER_KEYS:
        pstats_raw = providers_stats.get(ptype)
        if not isinstance(pstats_raw, dict):
            out[ptype] = None
            continue

        attempts = int(pstats_raw.get("attempts", 0) or 0)
        success = int(pstats_raw.get("success", 0) or 0)
        failure = int(pstats_raw.get("failure", 0) or 0)

        success_rate_raw = pstats_raw.get("success_rate")
        success_rate = (
            float(success_rate_raw)
            if isinstance(success_rate_raw, int | float)
            else None
        )
        avg_latency_raw = pstats_raw.get("avg_latency_ms")
        avg_latency_ms = (
            float(avg_latency_raw) if isinstance(avg_latency_raw, int | float) else None
        )

        last_success_at = pstats_raw.get("last_success_at")
        last_failure_at = pstats_raw.get("last_failure_at")
        last_success_age_seconds = (
            round(max(now - float(last_success_at), 0.0), 2)
            if isinstance(last_success_at, int | float) and last_success_at
            else None
        )
        last_failure_age_seconds = (
            round(max(now - float(last_failure_at), 0.0), 2)
            if isinstance(last_failure_at, int | float) and last_failure_at
            else None
        )

        last_error_raw = pstats_raw.get("last_error")
        last_error_str: str | None
        if isinstance(last_error_raw, str):
            last_error_str = last_error_raw
        elif last_error_raw is None:
            last_error_str = None
        else:
            # NotificationManager line 1117-1126 写入的 last_error 是 dict，
            # 读 status 时已做 ``str(...)`` truncate；这里 defensive 兜底
            last_error_str = str(last_error_raw)

        # R145: success_streak / failure_streak —— 连续成功 / 连续失败计数。
        # 监控可以在 dashboard 上对 ``failure_streak >= N`` 直接 alert，
        # 比"成功率< X%"更早发现「这家 provider 突然全挂」。
        # 非法类型（字符串 / 列表 / None）→ 兜底 0，永不抛 exception。
        try:
            success_streak = int(pstats_raw.get("success_streak", 0) or 0)
        except (TypeError, ValueError):
            success_streak = 0
        try:
            failure_streak = int(pstats_raw.get("failure_streak", 0) or 0)
        except (TypeError, ValueError):
            failure_streak = 0

        out[ptype] = {
            "attempts": attempts,
            "success": success,
            "failure": failure,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency_ms,
            "last_success_age_seconds": last_success_age_seconds,
            "last_failure_age_seconds": last_failure_age_seconds,
            "last_error_present": bool(last_error_str),
            # R143：把 last_error 字符串归一成 5 类之一；详见
            # ``_classify_last_error``。``None`` 当且仅当
            # ``last_error_present=False``。
            "last_error_class": _classify_last_error(last_error_str),
            # R145: 连续成功 / 连续失败计数（互斥 —— 同时只一个 > 0）。
            "success_streak": success_streak,
            "failure_streak": failure_streak,
        }

    return out


def _safe_notification_summary() -> dict[str, object] | None:
    """从全局 ``notification_manager`` 提取 health 端点需要的安全字段。

    刻意 **不** 透出 ``config`` 子树（含 token / bark_secret 等敏感字段），
    只暴露 enabled、providers 数量、queue 积压、delivery_success_rate 这种
    监控真正会用的聚合量。

    R142：增加 ``per_provider`` 字段——bark/web/sound/system 各自的
    attempts/success/failure/success_rate/avg_latency_ms/last_*_age_seconds
    /last_error_present 摘要，让 K8s 探针/Datadog/Grafana 能 **定位**
    具体哪家 provider 在故障，而不仅"全局成功率掉了"。``last_error``
    原文本不暴露（防 PII），只暴露 boolean。
    """
    try:
        from ai_intervention_agent.notification_manager import notification_manager

        status = notification_manager.get_status()
        if not isinstance(status, dict):
            return None

        providers = status.get("providers", [])
        providers_count = len(providers) if isinstance(providers, list) else 0

        stats = status.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}

        success_rate_raw = stats.get("delivery_success_rate")
        if isinstance(success_rate_raw, int | float):
            delivery_success_rate: float | None = float(success_rate_raw)
        else:
            delivery_success_rate = None

        finalized_raw = stats.get("events_finalized", 0)
        events_finalized = (
            int(finalized_raw) if isinstance(finalized_raw, int | float) else 0
        )
        in_flight_raw = stats.get("events_in_flight", 0)
        events_in_flight = (
            int(in_flight_raw) if isinstance(in_flight_raw, int | float) else 0
        )

        providers_stats_raw = stats.get("providers", {})
        if not isinstance(providers_stats_raw, dict):
            providers_stats_raw = {}
        per_provider = _safe_per_provider_snapshot(providers_stats_raw, time.time())

        return {
            "enabled": bool(status.get("enabled", False)),
            "providers_count": providers_count,
            "queue_size": int(status.get("queue_size", 0) or 0),
            "delivery_success_rate": delivery_success_rate,
            "events_finalized": events_finalized,
            "events_in_flight": events_in_flight,
            "per_provider": per_provider,
        }
    except Exception:
        return None


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

    # 同时允许默认模板，方便用户从 UI 跳过去对照。
    # R76：本模块在 ``src/ai_intervention_agent/web_ui_routes/system.py``，所以仓库根
    # 是 ``parent.parent.parent.parent``（system.py → web_ui_routes → ai_intervention_agent
    # → src → repo_root）。模板既可能在仓库根（开发环境），也可能在包内
    # （wheel 安装到 site-packages 的旧布局），两种都加进候选避免 UI 找不到。
    # R76 同时移除了 ``config.jsonc.default`` 模板（v1.4 之前的 JSONC 配置仍由
    # ``config_manager`` auto-migrate 兼容，但不再随包发布独立样例）。
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent.parent
    pkg_root = here.parent.parent
    for base in (repo_root, pkg_root):
        p = (base / "config.toml.default").resolve()
        if p.exists():
            candidates.append(p)
            break

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
                import ai_intervention_agent.server_config as server_config

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
                    latency_ms:
                      type: object
                      description: |
                        R134：emit→deliver 延迟分布快照（基于 ring buffer
                        最近 ≤512 个样本）。p50_ms / p95_ms 是 ms float（2
                        位小数），count == 0 时两者均为 null（刚启动还没数据）。
                      properties:
                        p50_ms:
                          type: number
                          description: 50 分位延迟（ms, float）
                        p95_ms:
                          type: number
                          description: 95 分位延迟（ms, float）
                        count:
                          type: integer
                          description: 当前 ring buffer 实际样本数
            """
            try:
                from ai_intervention_agent.web_ui_routes.task import _sse_bus

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
            """综合健康检查端点（R53-F + R121-A），适合 K8s liveness/readiness probe / 监控仪表板。

            ---
            tags:
              - System
            description: |
                聚合 SSE bus / TaskQueue / 最近日志 / 通知子系统 四个维度的健康
                指标，用一份简单 JSON 给监控系统消费。**不包含敏感信息**（无
                prompt 内容、无 config 字段值），所有字段都是数值 / enum / 路径，
                可直接对接 Datadog / Prometheus / 自建监控。

                ## 响应规约

                * ``status``：整体健康度的 enum：

                  - ``healthy``：所有子系统正常；
                  - ``degraded``：有 ERROR 级日志、backpressure 累计、或通知投递
                    成功率明显偏低（<80% 且 finalized 样本 ≥30），但服务仍在跑，
                    监控可以告警但不应自动重启；
                  - ``unhealthy``：任何子系统拉取失败 / 内部异常，监控应当 page
                    on-call。

                * ``checks``：各子检查的 ``{ok: bool, ...}`` 详情，方便定位问题。

                * ``ts_unix``：本次 health 评估时刻（int 秒），监控可基于它检测
                  端点本身的 freshness。

                * ``version``（R121-A）：项目版本号，用于滚动升级时区分实例；
                  探测失败为 ``null``。

                * ``uptime_seconds``（R121-A）：进程启动至今秒数（float, 3 位小数），
                  监控可借此判 "异常重启" / "init 卡死"；探测失败为 ``null``。

                * ``config_file_path``（R121-A）：当前加载的配置文件绝对路径
                  （**仅路径，不暴露字段值**），监控可据此发现 "加载了错配置"
                  这类故障；探测失败或未配置为 ``null``。

                * ``web_ui_env_overrides``（CR#15 续）：当前生效的 web_ui
                  env override 名单。``{}`` = 无 env 覆盖（值来自
                  ``config.toml`` / 默认值）；``{env_name: value, ...}`` =
                  有 env 覆盖（明文值，host/port/language 都不敏感）；
                  ``null`` = 探测失败。配合 ``AI_INTERVENTION_AGENT_WEB_UI_*``
                  env vars，让运维一眼看出 "为什么 port 不是 config.toml
                  里写的那个"。

                * ``build``（R132）：``{git_commit, git_branch, git_dirty}`` 三
                  字段元信息，比 ``version`` 字符串精确——``v1.5.45`` 可能对应
                  过 100 个 commit，``git_commit`` 只对应一份代码。监控做 PR
                  rollout 时可借此立刻区分"新版本上线了吗 / 这个实例还在跑老
                  commit 吗 / 是 dirty 工作树吗"三个问题；pip install / docker /
                  pyinstaller 等没有 ``.git`` 的部署里字段值是 ``"unknown"``，
                  探测整体失败为 ``null``。

                * ``checks.notification.per_provider``（R142）：``bark`` /
                  ``web`` / ``sound`` / ``system`` 四家 provider 的独立摘要。
                  每家结构 ``{attempts, success, failure, success_rate,
                  avg_latency_ms, last_success_age_seconds,
                  last_failure_age_seconds, last_error_present,
                  last_error_class}``；从未尝试投递的 provider（也未
                  注册）为 ``null``。``last_error_present`` 是 boolean——
                  刻意 **不** 暴露 ``last_error`` 原始字符串（防
                  device_key / 服务器 URL 等 PII 泄漏到公共健康端点）；
                  详情仍然要回 logs 看。R142 与 R141 的 ``POST
                  /api/system/notifications/test`` 形成「触发 → 定位」
                  闭环：self-test 跑完后立刻 GET 本端点就能知道哪家
                  provider 挂、最近一次失败距今多久、平均延迟漂没漂。

                * ``last_error_class``（R143）：把 ``last_error`` 归一化成
                  一个稳定字符串（``client_error`` / ``server_error`` /
                  ``network_error`` / ``timeout`` / ``not_registered`` /
                  ``unknown``），与 ``last_error_present`` boolean 互
                  补。监控可基于此做 stack-bar："这个 provider 最近
                  N 次失败，4xx / 5xx / network / timeout 各占多少"，
                  比单 boolean 信号丰富 5 倍。优先级 5xx > 4xx >
                  timeout > network > not_registered > unknown 避免
                  一个 error 同时落多类。``None`` 当且仅当
                  ``last_error_present=False``。所有取值都不含具体
                  URL / device_key / token / error message——PII 边界
                  与 R142 一致。

                * ``success_streak`` / ``failure_streak``（R145）：连
                  续成功 / 连续失败计数（互斥——同时只有一个 > 0）。
                  比"成功率掉到 X% 之下"更早发现「这家 provider 突然
                  全挂」型故障——监控对 ``failure_streak >= N`` 直接
                  alert，避免等待 finalized sample 累积到 30 才识别异
                  常。第一次成功 / 失败时分别累加自己的 streak，并把
                  另一边 streak 归 0。``provider_not_registered``（route
                  到 ``last_error_class=not_registered``）和异常路径
                  都计为 failure，累加 failure_streak。

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
                from ai_intervention_agent.web_ui_routes.task import _sse_bus

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
                from ai_intervention_agent.task_queue_singleton import get_task_queue

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
                from ai_intervention_agent.enhanced_logging import get_recent_logs

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

            # R121-A: notification subsystem 健康摘要
            #
            # 不是所有部署都启用通知（默认 enabled=False），所以"未启用"不算
            # degraded。只有"启用 + 有足够样本 + 成功率明显偏低"才升级到
            # degraded。门槛 30 条 finalized 是经验值：太低（5 条）会被冷启
            # 动早期的瞬时 0% 误判，太高（100 条）对刚上线的部署一直探测
            # 不到任何降级。30 大约是一个工作日的通知量级。
            notification_summary = _safe_notification_summary()
            if notification_summary is None:
                checks["notification"] = {"ok": False, "error": "summary unavailable"}
            else:
                checks["notification"] = {"ok": True, **notification_summary}

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

            # R121-A: notification 子健康度也参与 degraded 判定
            #
            # 触发条件（同时满足）：
            #   1. notification check 内部 ok=True（即 summary 拿到了）
            #   2. enabled=True（关闭通知的部署不该被这个降级）
            #   3. events_finalized >= 30（足够样本，避免冷启动早期误判）
            #   4. delivery_success_rate < 0.8（80% 是个权衡：太高过敏，
            #      太低不敏感）
            notif_check = checks.get("notification", {})
            notif_degraded = False
            if isinstance(notif_check, dict) and notif_check.get("ok"):
                enabled = bool(notif_check.get("enabled", False))
                finalized_raw = notif_check.get("events_finalized", 0)
                finalized = (
                    int(finalized_raw) if isinstance(finalized_raw, int | float) else 0
                )
                rate_raw = notif_check.get("delivery_success_rate")
                if (
                    enabled
                    and finalized >= 30
                    and isinstance(rate_raw, int | float)
                    and float(rate_raw) < 0.8
                ):
                    notif_degraded = True

            if not all_ok:
                status = "unhealthy"
            elif backpressure > 0 or recent_err_count > 0 or notif_degraded:
                status = "degraded"
            else:
                status = "healthy"

            # R121-A: 顶层 metadata —— version / uptime_seconds / config_file_path
            #
            # 三个字段都对 K8s probe / 监控仪表板有价值：
            # - version：滚动升级时区分实例
            # - uptime_seconds：检测异常重启 / 进程"卡 init"
            # - config_file_path：检测"加载错配置"（典型场景：env var 漂移）
            #
            # CR#15 续：再加一个 web_ui_env_overrides 字段——配合本周期新增
            # 的 ``AI_INTERVENTION_AGENT_WEB_UI_HOST/PORT/LANGUAGE`` env
            # override，让 K8s probe / 仪表板能立刻看出"port 字段是 8080
            # 因为 env=8080，还是 config.toml 写的"。空 dict {} 表示无
            # override（正常状态）；非空 dict 是 env var 名 → 字符串值。
            #
            # 配置访问全部通过模块级 helper 间接完成（避免 handler body 直接
            # 触碰配置 API），保留 R53-F 的 test_no_config_value_passthrough
            # 契约。
            payload: dict[str, object] = {
                "status": status,
                "ts_unix": ts,
                "checks": checks,
                "version": _safe_project_version(),
                "uptime_seconds": _safe_uptime_seconds(),
                "config_file_path": _safe_config_file_path(),
                "web_ui_env_overrides": _safe_web_ui_env_overrides(),
                # R132：build info（git commit / branch / dirty）。
                # ``_safe_build_info`` 复用 R63 的 lazy cache，10 s K8s probe
                # 周期性拉取 health 时不会炸 fork 风暴。pip 部署没 .git 时
                # 字段全是 "unknown"，handler 不当作错误——保留 R63 契约。
                "build": _safe_build_info(),
            }
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
                from ai_intervention_agent.enhanced_logging import (
                    _LOG_RING_MAXLEN,
                    get_recent_logs,
                )

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
