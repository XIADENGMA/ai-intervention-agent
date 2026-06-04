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
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

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


def _safe_notification_latency_histograms() -> dict[str, dict[str, Any]]:
    """R191 / Cycle 5：从全局 ``notification_manager`` 提取 provider latency
    histogram 状态。

    与 ``_safe_notification_summary`` 同款防御策略：任何错误（import 失败、
    单例还没初始化、histogram 字段不存在）一律 swallow + 返回空 dict。让
    /metrics 端点宁可少一组 metrics 也不要 5xx。

    返回形态与 ``get_provider_latency_histograms_snapshot()`` 完全对齐：

    .. code-block:: python

        {
            "bark": {
                "count": 42,
                "sum_seconds": 187.4,
                "buckets": {0.1: 5, 0.5: 18, ..., float("inf"): 42},
            },
            ...
        }
    """
    try:
        from ai_intervention_agent.notification_manager import notification_manager

        snap = notification_manager.get_provider_latency_histograms_snapshot()
        return snap if isinstance(snap, dict) else {}
    except Exception:
        return {}


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


def _compute_age_seconds_from_iso(rotated_at: object) -> int | None:
    """计算给定 ISO8601 时间戳到现在的秒数；失败 / 异常 → ``None``。

    R208 / Cycle 10 · F-204-2 (CR#22 §4 Important) 新增。**统一两处
    verbatim duplicated 的 token age 计算**:

    1. R199 ``GET /api/system/api-token-info`` endpoint 的 ``age_seconds`` 字段;
    2. R204 ``_safe_token_age_seconds()`` helper (Prom gauge 数据源)。

    在 R208 之前，两处都各自 ``rotated_at.replace("Z", "+00:00")`` +
    ``fromisoformat`` + clock skew 检查，bug fix 必须同步 (R204
    ``TestEndpointMetricParity`` invariant 在运行时验证两路结果一致)。
    R208 把算法提到 module-level 单一 helper，消除 source-level
    drift 风险。**契约严格保持与原两份实现一致**:

    - 输入非 ``str`` / 空串 → ``None``;
    - ``rotated_at`` 解析失败 (脏数据) → ``None``;
    - ``age`` < 0 (系统时钟跳变 / config 里时间戳来自未来) → ``None``
      (0 也不合适, dashboard 看到 0 会误以为刚轮换);
    - 正常情况 → ``int`` (秒, ≥ 0)。

    helper 是 **pure function** (无 log、无 I/O), 让 caller 自由决定
    是否在 None 时记 log / 返回 fallback。R199 endpoint 在 R208 重构
    时一并删除 ``logger.debug`` (debug log 不是公共契约的一部分; helper
    silent 与 ``_safe_uptime_seconds`` 等其他 ``_safe_*`` helper 风格
    一致)。

    Args:
        rotated_at: ISO8601 时间戳字符串 (典型: ``"2026-01-15T00:00:00Z"``)，
            非 str / 空串 → 返回 None。**注意** 类型签名是 ``object``,
            让 caller 不必预先 isinstance check (helper 内部统一处理),
            R199 endpoint + R204 helper 调用点都简化。
    """
    if not isinstance(rotated_at, str) or not rotated_at:
        return None
    try:
        from datetime import UTC, datetime

        ts = rotated_at.replace("Z", "+00:00")
        rotated_dt = datetime.fromisoformat(ts)
        age = int((datetime.now(UTC) - rotated_dt).total_seconds())
    except (ValueError, TypeError):
        return None
    return age if age >= 0 else None


def _safe_token_age_seconds() -> int | None:
    """读 ``[network_security].api_token_rotated_at`` 计算当前 token age (秒)。

    R204 / Cycle 9 · F-203-1 (CR#21 §4.3) 新增。**逻辑契约与 R199
    ``GET /api/system/api-token-info`` endpoint 的 ``age_seconds`` 字段
    完全一致**：

    - 无 token (``api_token`` 缺失 / 长度 < 16) → ``None`` (Prom 端
      不输出 metric，与 ``_safe_uptime_seconds`` 等 helper 同款契约);
    - 无 / 解析失败 / 未来时间戳的 ``api_token_rotated_at`` → ``None`` (
      详见 ``_compute_age_seconds_from_iso`` docstring)。

    R208 / Cycle 10 · F-204-2 把算法部分抽到 ``_compute_age_seconds_
    from_iso`` 共享 helper，与 R199 endpoint 共用同一份实现, 消除
    verbatim duplicated drift 风险。本函数现仅负责 config 读取 + token
    validity check, age 计算委托 helper。
    """
    try:
        cfg = get_config()
        ns = cfg.get_network_security_config()
    except Exception:
        return None
    if not isinstance(ns, dict):
        return None
    token = ns.get("api_token", "")
    if not (isinstance(token, str) and token and len(token) >= 16):
        return None
    return _compute_age_seconds_from_iso(ns.get("api_token_rotated_at", ""))


# ---------------------------------------------------------------------------
# T1 (cycle 4): Prometheus exposition format helpers for /api/system/metrics
#
# 设计要点（与 /api/system/health JSON 端点互补）：
# 1. **零新依赖**：手写 prom 0.0.4 exposition format，不引入 prometheus_client
#    库（避免增加 4 MB+ 的额外 wheel 体积 + multiprocess registry 这种本项目
#    用不上的复杂度）。
# 2. **复用现有 _safe_* helper**：所有数据源都走已经存在的安全收集函数
#    （_safe_uptime_seconds / _safe_build_info / _safe_notification_summary
#    / _sse_bus.stats_snapshot），保证与 /api/system/health 同步 + 一旦
#    R53-F 契约更新两个端点一起改。
# 3. **命名规约**：``aiia_<subsystem>_<name>[_unit][_total]`` 前缀。监控
#    系统看到 ``aiia_*`` 就知道是本项目暴露的指标，避免命名冲突；
#    ``_total`` 后缀仅 counter 用，遵循 OpenMetrics / Prometheus 官方指南。
# 4. **PII 边界**：与 /api/system/health 一致——只暴露数值 / enum / 路径，
#    绝不透出 config 字段值（password / token / device_key）；
#    last_error 原文本不出现。
# 5. **失败优雅降级**：任何子项探测失败都跳过对应 metric 行，不让整个
#    端点 5xx；最坏情况返回空 payload（监控仪表板会自动忽略 stale）。
# ---------------------------------------------------------------------------


# Prometheus exposition format spec：label value 内字符需 escape 反斜杠、
# 双引号、换行。详见 https://github.com/prometheus/docs/blob/main/content/docs/instrumenting/exposition_formats.md
_PROM_LABEL_ESCAPES = (("\\", "\\\\"), ('"', '\\"'), ("\n", "\\n"))


def _escape_prom_label_value(value: str) -> str:
    """转义 Prometheus label value 中的反斜杠 / 双引号 / 换行。"""
    out = value
    for old, new in _PROM_LABEL_ESCAPES:
        out = out.replace(old, new)
    return out


def _format_prom_labels(labels: dict[str, str] | None) -> str:
    """把 ``{k: v, ...}`` 渲染成 ``{k="v",k2="v2"}``；空 dict → 空串。

    label 键顺序按字典插入顺序（Python 3.7+ 有序）—— caller 想要稳定
    顺序就传入有序 dict，本函数不做隐式排序，避免每次 scrape 输出
    抖动让 diff 工具误判。
    """
    if not labels:
        return ""
    parts = [f'{k}="{_escape_prom_label_value(str(v))}"' for k, v in labels.items()]
    return "{" + ",".join(parts) + "}"


def _format_prom_value(value: int | float) -> str:
    """把单个数值渲染成 Prometheus 接受的字符串。

    ``int`` 直接 str()；``float`` 用 repr() 避免 ``str(0.1+0.2)`` 那种精度
    损失；``inf`` / ``nan`` 渲染为 Prometheus 标准的 ``+Inf`` / ``-Inf`` /
    ``NaN``。
    """
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value == float("inf"):
            return "+Inf"
        if value == float("-inf"):
            return "-Inf"
        return repr(value)
    return str(int(value))


def _format_prom_metric(
    name: str,
    value: int | float,
    *,
    help_text: str,
    metric_type: str,
    labels: dict[str, str] | None = None,
) -> str:
    """渲染单条 Prometheus metric（含 HELP / TYPE / 值行三行）。

    ``metric_type``：``counter`` / ``gauge`` / ``histogram`` / ``summary``。
    本项目当前只用 counter + gauge；histogram/summary 需要 _bucket / _sum /
    _count 配套，暂不实现以保持手写格式化器的简单性。

    **同一 metric name 多 label 场景**：用 :func:`_format_prom_metric_family`
    一次性发完整的「family」（HELP/TYPE 各只出现一次 + 多个 value 行），
    避免严格 Prometheus parser 因为「second TYPE for metric」报错。本函数
    只适合「一个 metric name 只发一个 value」的场景。
    """
    label_str = _format_prom_labels(labels)
    value_str = _format_prom_value(value)
    return (
        f"# HELP {name} {help_text}\n"
        f"# TYPE {name} {metric_type}\n"
        f"{name}{label_str} {value_str}\n"
    )


def _format_prom_metric_family(
    name: str,
    *,
    help_text: str,
    metric_type: str,
    samples: list[tuple[dict[str, str] | None, int | float]],
) -> str:
    """渲染同一 metric name 的 family（HELP + TYPE 各只出现一次 + N 个 value 行）。

    Prometheus exposition format 规约：**同一个 metric name 的 HELP/TYPE
    最多出现一次**——重复 TYPE 行会让 strict parser（VictoriaMetrics、
    Cortex、最新版 prom）报 ``second TYPE for metric`` 错误。R186 初版
    在 ``aiia_notification_*`` per-provider 循环里对每条样本都 emit
    HELP+TYPE，是一个 latent bug，本函数在 R187 follow-up 修掉。

    ``samples``：``[(labels, value), ...]``。``labels=None`` 视作无 label
    样本（一个 family 内一般不混用，但允许）。空 samples 列表返回空串。
    """
    if not samples:
        return ""
    out_lines: list[str] = [
        f"# HELP {name} {help_text}\n",
        f"# TYPE {name} {metric_type}\n",
    ]
    for labels, value in samples:
        label_str = _format_prom_labels(labels)
        value_str = _format_prom_value(value)
        out_lines.append(f"{name}{label_str} {value_str}\n")
    return "".join(out_lines)


def _format_prom_histogram_family(
    name: str,
    *,
    help_text: str,
    observations: list[
        tuple[
            dict[str, str] | None,  # base labels (e.g. {"tool": ..., "status": ...})
            dict[float, int],  # cumulative buckets: {0.1: n, ..., float("inf"): n}
            int,  # count（== buckets[+Inf]，作为冗余校验显式传入）
            float,  # sum_seconds
        ]
    ],
) -> str:
    """渲染同一 metric name 的 histogram family（R190 foundational）。

    Prometheus histogram exposition format 规约（见
    https://prometheus.io/docs/concepts/metric_types/#histogram）：

    .. code-block:: text

        # HELP <name> <help_text>
        # TYPE <name> histogram
        <name>_bucket{le="0.1",<other_labels>} 1
        <name>_bucket{le="0.5",<other_labels>} 5
        <name>_bucket{le="1.0",<other_labels>} 12
        ...
        <name>_bucket{le="+Inf",<other_labels>} 42
        <name>_sum{<other_labels>} 187.4
        <name>_count{<other_labels>} 42

    关键约束：

    - ``HELP`` / ``TYPE`` 在 family 内**只出现一次**（与 counter family
      同理，R187 已经踩过这个坑）；
    - ``_bucket`` 行必须按 ``le`` 升序，``+Inf`` 在末尾；
    - 同一 (其他 labels) 组合的 ``_bucket`` / ``_sum`` / ``_count`` 三个
      子指标的非-le 标签必须**完全一致**；
    - ``_count`` 必然 == 最后一个 ``_bucket`` (le="+Inf") 的值——本函数
      接受冗余 ``count`` 参数作为 caller-side sanity check，**不**自动
      推断，避免渲染时静默修复数据 bug。

    ``observations``：每个元组对应一个独立的「label 组合 + 直方图」。空
    列表返回空串（与 ``_format_prom_metric_family`` 行为一致）。

    本函数为 R190 / R191 / R192 / 未来所有 histogram 类指标共享。
    """
    if not observations:
        return ""
    out_lines: list[str] = [
        f"# HELP {name} {help_text}\n",
        f"# TYPE {name} histogram\n",
    ]
    for base_labels, buckets, count, sum_value in observations:
        # bucket 排序：有限值升序 + +Inf 在末尾。``float("inf")`` 在
        # Python ``sorted()`` 下天然排在所有有限数之后，所以一次排序
        # 即可，但我们显式校验「最后一个 key 就是 +Inf」避免 caller
        # 漏传 +Inf 桶导致 metric 不完整。
        sorted_keys = sorted(buckets.keys())
        if not sorted_keys or sorted_keys[-1] != float("inf"):
            # caller bug：缺 +Inf 桶。补上一个等于 count 的 +Inf 桶，
            # 保证渲染出的 metric 仍然形式合法；strict parser 不会因
            # 此 reject。本路径走不到时只能说明本函数 caller 提交的
            # data 已经 violate 了 docstring 约定——log 不在这里发，由
            # caller 端的契约测试守护。
            buckets = dict(buckets)
            buckets[float("inf")] = count
            sorted_keys = sorted(buckets.keys())

        for le in sorted_keys:
            le_label_value = "+Inf" if le == float("inf") else f"{le}"
            merged_labels = {"le": le_label_value, **(base_labels or {})}
            label_str = _format_prom_labels(merged_labels)
            out_lines.append(
                f"{name}_bucket{label_str} {_format_prom_value(buckets[le])}\n"
            )

        base_label_str = _format_prom_labels(base_labels)
        out_lines.append(
            f"{name}_sum{base_label_str} {_format_prom_value(sum_value)}\n"
        )
        out_lines.append(f"{name}_count{base_label_str} {_format_prom_value(count)}\n")
    return "".join(out_lines)


def _render_prometheus_metrics() -> str:
    """收集所有可观测指标并按 Prometheus 0.0.4 exposition format 渲染。

    返回 ``str``（``text/plain; version=0.0.4; charset=utf-8``）。任何子项
    探测失败都被跳过——caller 应当把整体 payload 直接当响应体回，不要再
    包装 JSON envelope。
    """
    lines: list[str] = []

    # --- 进程级 ---
    uptime = _safe_uptime_seconds()
    if uptime is not None:
        lines.append(
            _format_prom_metric(
                "aiia_uptime_seconds",
                uptime,
                help_text="Process uptime in seconds since the AI Intervention Agent server started.",
                metric_type="gauge",
            )
        )

    version = _safe_project_version()
    build = _safe_build_info()
    if version or build:
        labels: dict[str, str] = {}
        if version:
            labels["version"] = version
        if build:
            labels["git_commit"] = build.get("git_commit", "unknown")
            labels["git_branch"] = build.get("git_branch", "unknown")
            labels["git_dirty"] = build.get("git_dirty", "unknown")
        lines.append(
            _format_prom_metric(
                "aiia_build_info",
                1,
                help_text="Static labels carrying build metadata; value is always 1 (info-style gauge).",
                metric_type="gauge",
                labels=labels,
            )
        )

    # --- SSE bus ---
    try:
        from ai_intervention_agent.web_ui_routes.task import _sse_bus

        snap = _sse_bus.stats_snapshot()
    except Exception:
        snap = None

    if isinstance(snap, dict):
        sse_counter_fields = (
            ("aiia_sse_emit_total", "emit_total", "Total SSE events emitted."),
            (
                "aiia_sse_gap_warnings_total",
                "gap_warnings_emitted",
                "Total gap_warning events sent because subscribe(after_id=...) was past the history window.",
            ),
            (
                "aiia_sse_backpressure_discards_total",
                "backpressure_discards",
                "Total times emit() dropped a subscriber due to queue Full / backlog over threshold.",
            ),
            (
                "aiia_sse_heartbeat_total",
                "heartbeat_total",
                'Total SSE heartbeat (": heartbeat\\n\\n") frames pushed.',
            ),
            (
                "aiia_sse_oversize_drops_total",
                "oversize_drops",
                "Total events dropped because their serialized payload exceeded the per-event size cap.",
            ),
        )
        for prom_name, key, help_text in sse_counter_fields:
            raw = snap.get(key)
            if isinstance(raw, int | float):
                lines.append(
                    _format_prom_metric(
                        prom_name,
                        int(raw),
                        help_text=help_text,
                        metric_type="counter",
                    )
                )

        emit_by_type_raw = snap.get("emit_by_type")
        if isinstance(emit_by_type_raw, dict) and emit_by_type_raw:
            # R202 / Cycle 8 · 方案 B：新增「按 event_type 维度」counter
            # ``aiia_sse_emit_by_type_total{event_type="..."}``，与现有未
            # 标签化的 ``aiia_sse_emit_total`` 并存（**不**用 label 覆盖原
            # metric——Prometheus 不允许同一 name 在不同 series 间切换
            # label set，会破坏 Grafana 历史曲线 + 触发 strict parser 的
            # ``inconsistent labels for metric family`` 错误）。
            #
            # 不变量：``sum(aiia_sse_emit_by_type_total) == aiia_sse_emit_total``，
            # 由 ``_SSEBus.emit()`` 同一锁内 ``_emit_total += 1`` 与
            # ``_emit_by_type[event_type] += 1`` 紧贴保证，AST guard 在
            # ``tests/test_sse_emit_by_type_counter_r202.py`` 锁结构。
            #
            # event_type 按字符串字典序排序，让 exposition 输出 deterministic
            # ——Prometheus parser 不要求顺序，但 deterministic 输出方便
            # smoke test 直接 string-equality assertion + diff-friendly。
            emit_by_type_samples: list[tuple[dict[str, str] | None, int | float]] = [
                ({"event_type": str(et)}, int(count))
                for et, count in sorted(emit_by_type_raw.items())
                if isinstance(count, int | float)
            ]
            if emit_by_type_samples:
                lines.append(
                    _format_prom_metric_family(
                        "aiia_sse_emit_by_type_total",
                        help_text=(
                            "Total SSE events emitted, partitioned by event_type "
                            "(sum of all event_type series equals aiia_sse_emit_total)."
                        ),
                        metric_type="counter",
                        samples=emit_by_type_samples,
                    )
                )

        sse_gauge_fields = (
            (
                "aiia_sse_subscriber_count",
                "subscriber_count",
                "Current active SSE subscribers (instantaneous).",
            ),
            (
                "aiia_sse_history_size",
                "history_size",
                "Current SSE history deque length (instantaneous, ≤ _HISTORY_MAXLEN).",
            ),
            (
                "aiia_sse_latest_event_id",
                "latest_event_id",
                "Monotonically increasing ID of the last SSE event emitted.",
            ),
        )
        for prom_name, key, help_text in sse_gauge_fields:
            raw = snap.get(key)
            if isinstance(raw, int | float):
                lines.append(
                    _format_prom_metric(
                        prom_name,
                        int(raw),
                        help_text=help_text,
                        metric_type="gauge",
                    )
                )

        # R134 latency snapshot → prom summary-style 用 quantile 标签的 gauge
        # （不是 prom 的 summary type，因为没有 _sum/_count 配套；用 gauge
        # 加 quantile label 是 prom 社区广泛接受的"approximation"模式）。
        latency = snap.get("latency_ms")
        if isinstance(latency, dict):
            for quantile_key, quantile_label in (
                ("p50_ms", "0.5"),
                ("p95_ms", "0.95"),
            ):
                raw = latency.get(quantile_key)
                if isinstance(raw, int | float):
                    lines.append(
                        _format_prom_metric(
                            "aiia_sse_emit_to_deliver_ms",
                            float(raw),
                            help_text="emit→deliver latency snapshot in ms (gauge with quantile label; R134 ring buffer ≤512 samples).",
                            metric_type="gauge",
                            labels={"quantile": quantile_label},
                        )
                    )

        # R207 / Cycle 10 · F-205-2: SSE schema validation violation counter.
        # Mirrors stats_snapshot()['schema_violation_total'] (set by R205
        # _SSEBus.emit() when AIIA_SSE_SCHEMA_VALIDATE=warn|strict).
        #
        # Omit-when-off contract（与 R204 `aiia_token_age_seconds` 同款
        # omit-vs-NaN philosophy）：
        # - mode == "off"：metric **不出现** → alertmanager 用 `absent(
        #   aiia_sse_schema_violation_total)` 即可分清 "validation off"
        #   vs "validation on with 0 violations"，两类 ops 状态用不同
        #   alert 路由处理；
        # - mode in {warn, strict}：metric 出现 (value ≥ 0)，alertmanager
        #   用 `rate(aiia_sse_schema_violation_total[5m]) > 0` 检测新
        #   violation 出现，或 `aiia_sse_schema_violation_total{...} > 100`
        #   检测违规累积超阈值。
        #
        # Sum invariant 与 R205 一致：一条 emit 多字段错也只算 1 次
        # violation（matches _schema_violation_total += 1 once per emit，
        # 无论 violations list 长度）——避免噪声膨胀。
        mode_raw = snap.get("schema_validate_mode")
        violation_raw = snap.get("schema_violation_total")
        if (
            isinstance(mode_raw, str)
            and mode_raw in {"warn", "strict"}
            and isinstance(violation_raw, int)
        ):
            lines.append(
                _format_prom_metric(
                    "aiia_sse_schema_violation_total",
                    violation_raw,
                    help_text=(
                        "Total SSE emit payload schema violations detected "
                        "by R205 AIIA_SSE_SCHEMA_VALIDATE=warn|strict "
                        "toggle (R207 / Cycle 10 · F-205-2). Omitted when "
                        "toggle is off — use 'absent(...)' rule to "
                        "distinguish 'monitoring off' vs 'monitoring on "
                        "with 0 violations'. Multi-field violations on "
                        "one emit count as 1."
                    ),
                    metric_type="counter",
                )
            )

    # --- Security / API token age (R204 / Cycle 9 · F-203-1) ---
    token_age = _safe_token_age_seconds()
    if token_age is not None:
        lines.append(
            _format_prom_metric(
                "aiia_token_age_seconds",
                token_age,
                help_text=(
                    "Seconds since the API token "
                    "(network_security.api_token) was last rotated; mirrors "
                    "GET /api/system/api-token-info age_seconds field "
                    "(R204 / Cycle 9 · F-203-1). Omitted when no token is "
                    "configured or api_token_rotated_at is unparseable / "
                    "in the future; use for alertmanager rules like "
                    "'aiia_token_age_seconds > 90 * 86400' for stale-token "
                    "detection per NIST SP 800-63B rotation guidance."
                ),
                metric_type="gauge",
            )
        )

    # --- TaskQueue ---
    try:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        tq = get_task_queue()
        count_dict = tq.get_task_count()
        total = count_dict.get("total")
        if isinstance(total, int | float):
            lines.append(
                _format_prom_metric(
                    "aiia_task_queue_size",
                    int(total),
                    help_text="Current TaskQueue size (instantaneous, includes pending + active + completed-not-yet-evicted).",
                    metric_type="gauge",
                )
            )
        max_tasks = getattr(tq, "max_tasks", None)
        if isinstance(max_tasks, int | float):
            lines.append(
                _format_prom_metric(
                    "aiia_task_queue_max",
                    int(max_tasks),
                    help_text="Configured TaskQueue capacity (max_tasks).",
                    metric_type="gauge",
                )
            )
    except Exception:
        # [R-186] /metrics 是 monitoring scrape 路径，TaskQueue 子系统任何
        # 内部异常（singleton 还未初始化、attr 缺失、import 死循环）都不
        # 应该让整端点 5xx——监控会通过 staleness 自动 alert。
        pass

    # --- 最近 5 分钟 ERROR 日志计数 ---
    try:
        from ai_intervention_agent.enhanced_logging import get_recent_logs

        cutoff = time.time() - 300
        recent = get_recent_logs()
        error_count = sum(
            1
            for entry in recent
            if entry.get("level_no", 0) >= 40 and entry.get("ts_unix", 0) >= cutoff
        )
        lines.append(
            _format_prom_metric(
                "aiia_recent_errors_5min",
                error_count,
                help_text="Number of ERROR/CRITICAL log entries in the last 5 minutes (rolling).",
                metric_type="gauge",
            )
        )
    except Exception:
        # [R-186] enhanced_logging.get_recent_logs() 任何内部异常（环形
        # 缓冲读取冲突、字段缺失、Timestamp 解析失败）都不应让 /metrics
        # 整端点 5xx；丢失一行 ``aiia_recent_errors_5min`` gauge 比让
        # Prometheus scrape 失败把整个 ai-intervention-agent target 标
        # red 更可接受。
        pass

    # --- Notification 子系统（含 per-provider 标签） ---
    # R186 fix：与其他子系统保持一致，整体包 try/except，
    # 防止 notification_manager 内部任何异常（包括 _safe_notification_summary
    # 自身、provider 字典 iteration、未预期的字段类型）让 /metrics 5xx。
    try:
        notif = _safe_notification_summary()
    except Exception:
        notif = None
    if isinstance(notif, dict):
        lines.append(
            _format_prom_metric(
                "aiia_notification_enabled",
                1 if notif.get("enabled") else 0,
                help_text="Whether the notification subsystem is enabled (1) or disabled (0).",
                metric_type="gauge",
            )
        )
        queue_size_raw = notif.get("queue_size")
        if isinstance(queue_size_raw, int | float):
            lines.append(
                _format_prom_metric(
                    "aiia_notification_queue_size",
                    int(queue_size_raw),
                    help_text="Current backlog size of the notification delivery queue.",
                    metric_type="gauge",
                )
            )
        success_rate_raw = notif.get("delivery_success_rate")
        if isinstance(success_rate_raw, int | float):
            lines.append(
                _format_prom_metric(
                    "aiia_notification_delivery_success_rate",
                    float(success_rate_raw),
                    help_text="Aggregated notification delivery success rate (0.0–1.0).",
                    metric_type="gauge",
                )
            )
        finalized = notif.get("events_finalized")
        if isinstance(finalized, int | float):
            lines.append(
                _format_prom_metric(
                    "aiia_notification_events_finalized_total",
                    int(finalized),
                    help_text="Total notification events that have reached a terminal state (success or final failure).",
                    metric_type="counter",
                )
            )
        in_flight = notif.get("events_in_flight")
        if isinstance(in_flight, int | float):
            lines.append(
                _format_prom_metric(
                    "aiia_notification_events_in_flight",
                    int(in_flight),
                    help_text="Notification events currently in flight (between submit and terminal state).",
                    metric_type="gauge",
                )
            )

        # per_provider metrics（每个 provider 一行，用 provider 标签区分）
        #
        # R187 follow-up bug fix：旧实现对每个 (provider, metric_suffix)
        # 单独调 ``_format_prom_metric``，让同一 ``aiia_notification_<suffix>``
        # name 的 HELP / TYPE 行重复出现 N 次（N = provider 数），strict
        # Prometheus parser（VictoriaMetrics / Cortex / 最新 prom）会报
        # ``second TYPE for metric`` 错误。改用 ``_format_prom_metric_family``
        # 一次性发完整 family：HELP/TYPE 各一行 + N 个 value 行。
        per_provider = notif.get("per_provider")
        if isinstance(per_provider, dict):
            # 字段定义：(metric_suffix, source_key, help_text, metric_type)
            _per_provider_field_specs: tuple[tuple[str, str, str, str], ...] = (
                (
                    "attempts_total",
                    "attempts",
                    "Notification attempts per provider.",
                    "counter",
                ),
                (
                    "success_total",
                    "success",
                    "Notification successful deliveries per provider.",
                    "counter",
                ),
                (
                    "failure_total",
                    "failure",
                    "Notification failed deliveries per provider.",
                    "counter",
                ),
                (
                    "success_rate",
                    "success_rate",
                    "Per-provider notification delivery success rate (0.0–1.0).",
                    "gauge",
                ),
                (
                    "avg_latency_ms",
                    "avg_latency_ms",
                    "Per-provider average notification delivery latency in ms.",
                    "gauge",
                ),
                (
                    "success_streak",
                    "success_streak",
                    "Consecutive successful deliveries per provider (R145).",
                    "gauge",
                ),
                (
                    "failure_streak",
                    "failure_streak",
                    "Consecutive failed deliveries per provider (R145).",
                    "gauge",
                ),
            )
            for metric_suffix, key, help_text, metric_type in _per_provider_field_specs:
                # 为这一个 metric name 收集所有 provider 的 sample
                samples: list[tuple[dict[str, str] | None, int | float]] = []
                for provider_name, stats in per_provider.items():
                    if not isinstance(provider_name, str) or not isinstance(
                        stats, dict
                    ):
                        continue
                    # ty 0.0.34: ``per_provider = notif.get("per_provider")``
                    # 把 ``stats`` 推为 ``Any``, isinstance(stats, dict) narrow
                    # 之后变 ``dict[Never, Never]``——``stats.get(key)`` 拿
                    # ``Literal["attempts" | ...]`` 当 key 就报 invalid-
                    # argument-type。``cast`` 把 narrow 后的 stats 重新声
                    # 明为 ``dict[str, Any]`` (这正是 R142 _safe_per_provider_
                    # snapshot 的实际输出类型, 见 system.py:309).
                    stats_typed = cast("dict[str, Any]", stats)
                    raw = stats_typed.get(key)
                    if isinstance(raw, int | float):
                        value: int | float = (
                            float(raw)
                            if metric_type == "gauge"
                            and metric_suffix in ("success_rate", "avg_latency_ms")
                            else int(raw)
                        )
                        samples.append(({"provider": provider_name}, value))
                if samples:
                    lines.append(
                        _format_prom_metric_family(
                            f"aiia_notification_{metric_suffix}",
                            help_text=help_text,
                            metric_type=metric_type,
                            samples=samples,
                        )
                    )

    # --- R191 / Cycle 5: Notification send duration histogram (per-provider) ---
    # ``aiia_notification_send_duration_seconds{provider}`` 让运维仪表板能
    # 画「provider P95 send 耗时」「按 provider 拆分的耗时分布」。R142
    # 的 ``last_latency_ms`` + ``latency_ms_total`` / ``count`` 只能算最近
    # 一次 + 平均；histogram 才能算 percentile。
    try:
        provider_latencies = _safe_notification_latency_histograms()
    except Exception:
        # [R-191] 与上面的 stats 路径同档容错——provider histogram 故障
        # 不应让 /metrics 5xx。
        provider_latencies = {}
    if isinstance(provider_latencies, dict) and provider_latencies:
        notif_hist_observations: list[
            tuple[dict[str, str] | None, dict[float, int], int, float]
        ] = []
        for provider_name, state in provider_latencies.items():
            if not isinstance(provider_name, str) or not isinstance(state, dict):
                continue
            buckets = state.get("buckets")
            count = state.get("count", 0)
            sum_seconds = state.get("sum_seconds", 0.0)
            if not isinstance(buckets, dict) or not isinstance(count, int):
                continue
            if not isinstance(sum_seconds, int | float):
                continue
            notif_hist_observations.append(
                (
                    {"provider": provider_name},
                    buckets,
                    count,
                    float(sum_seconds),
                )
            )
        if notif_hist_observations:
            lines.append(
                _format_prom_histogram_family(
                    "aiia_notification_send_duration_seconds",
                    help_text=(
                        "Notification send duration distribution per provider "
                        "(R191 / Cycle 5). Buckets aligned with MCP tool "
                        "latency: 0.1s → 600s, covers human-in-the-loop "
                        "feedback semantics."
                    ),
                    observations=notif_hist_observations,
                )
            )

    # --- R187 / T2: MCP tool call counter ---
    # ``aiia_mcp_tool_calls_total{tool,status}`` 给监控仪表板做
    # request_rate / error_rate / SLO success_ratio = success / (success +
    # failure) 的分子分母——配合 R37 ``get_mcp_error_stats()`` 的
    # ``{error_type}:{method}`` 计数可以做"哪类 tool 错最多 + 错的是
    # 什么类型"的二维下钻。
    try:
        from ai_intervention_agent.mcp_tool_call_metrics import (
            get_mcp_tool_call_stats,
        )

        tool_stats = get_mcp_tool_call_stats()
    except Exception:
        # [R-187] mcp_tool_call_metrics 任何 import / 调用异常都不应让
        # /metrics 5xx——丢失一行 tool counter 比让 Prometheus 把整个
        # ai-intervention-agent target 标 red 更可接受（与其他子系统
        # block 的优雅降级模式一致）。
        tool_stats = {}

    if isinstance(tool_stats, dict) and tool_stats:
        mcp_samples: list[tuple[dict[str, str] | None, int | float]] = []
        for tool_name, statuses in tool_stats.items():
            if not isinstance(tool_name, str) or not isinstance(statuses, dict):
                continue
            for status in ("success", "failure"):
                raw = statuses.get(status)
                if isinstance(raw, int | float):
                    mcp_samples.append(
                        ({"tool": tool_name, "status": status}, int(raw))
                    )
        if mcp_samples:
            lines.append(
                _format_prom_metric_family(
                    "aiia_mcp_tool_calls_total",
                    help_text=(
                        "Total MCP tool invocations by tool name and outcome "
                        "(R187 / T2; partner of get_mcp_error_stats's "
                        "error_type:method breakdown)."
                    ),
                    metric_type="counter",
                    samples=mcp_samples,
                )
            )

    # R190 / Cycle 5 · MCP tool 调用耗时 histogram
    # ----------------------------------------------------------------
    # ``aiia_mcp_tool_call_duration_seconds{tool,status}`` 让监控能画
    # 「P95 工具耗时」、「按 tool 拆分的耗时分布」、「success vs failure
    # 耗时对比」等仪表板（CR#18 §4.1 → §7 item 2 deliverable）。R187
    # 的 counter 是分子分母，R190 的 histogram 是 SLO 延迟侧——两者
    # 合在一起才是完整的 RED（Rate / Errors / Duration）三件套。
    try:
        from ai_intervention_agent.mcp_tool_call_metrics import (
            get_mcp_tool_call_latency_snapshot,
        )

        tool_latency = get_mcp_tool_call_latency_snapshot()
    except Exception:
        # [R-187] 与上面的 stats 路径同档容错——histogram 故障不应让
        # /metrics 5xx；丢失一行 latency 比 Prometheus 把整个 target
        # 标 red 更可接受。
        tool_latency = {}

    if isinstance(tool_latency, dict) and tool_latency:
        hist_observations: list[
            tuple[dict[str, str] | None, dict[float, int], int, float]
        ] = []
        for (tool_name, status), state in tool_latency.items():
            if not isinstance(tool_name, str) or not isinstance(state, dict):
                continue
            buckets = state.get("buckets")
            count = state.get("count", 0)
            sum_seconds = state.get("sum_seconds", 0.0)
            if not isinstance(buckets, dict) or not isinstance(count, int):
                continue
            if not isinstance(sum_seconds, int | float):
                continue
            hist_observations.append(
                (
                    {"tool": tool_name, "status": status},
                    buckets,
                    count,
                    float(sum_seconds),
                )
            )
        if hist_observations:
            lines.append(
                _format_prom_histogram_family(
                    "aiia_mcp_tool_call_duration_seconds",
                    help_text=(
                        "MCP tool invocation duration distribution by tool name "
                        "and outcome (R190 / Cycle 5). Buckets chosen for "
                        "human-in-the-loop feedback latency: 0.1s (instant) "
                        "→ 600s (long research round)."
                    ),
                    observations=hist_observations,
                )
            )

    return "".join(lines)


def _get_client_ip() -> str:
    """读取 Flask 请求的真实客户端 IP（不信任 X-Forwarded-* 头）。"""
    return request.remote_addr or ""


def _is_loopback_request() -> bool:
    """仅本机来源（127.0.0.1 / ::1）的请求允许执行打开命令。"""
    return _get_client_ip() in _resolve_loopback_ips()


# ---------------------------------------------------------------------------
# R189 / T4: 可选 API token 认证（配合 non-loopback hardening）
# ---------------------------------------------------------------------------


_API_TOKEN_HEADER = "X-API-Token"
"""项目自定义 header，与 Bearer token 互补。``Authorization: Bearer <token>``
是 IETF 标准，但 ``X-API-Token: <token>`` 让 ``curl -H "X-API-Token: ..."``
书写更直观，PWA fetch 也省一道 ``Authorization`` 的 cors preflight 路径。"""

_MIN_API_TOKEN_LEN = 16
"""配置侧已经强制 ≥ 16 char（见 ``_validate_network_security_config``），
本常量是 endpoint 侧的 belt-and-suspenders 复查——一旦 config validator
被未来 refactor 出 bug 让短 token 漏过，endpoint 仍然不接受弱 token。"""


def _get_configured_api_token() -> str:
    """读取 ``network_security.api_token``——空字符串表示未配置（关闭认证）。

    config 加载失败时返回空串，与「未配置」等价；不让 config 故障扩大成
    端点 500 错误。Token 字符串本身仅在 endpoint 路径内对比，**不**写日志、
    **不**写错误响应（避免被 stderr / response body 泄漏到 PII 通道）。
    """
    try:
        cfg = get_config()
        ns = cfg.get_network_security_config()
    except Exception:
        return ""
    if not isinstance(ns, dict):
        return ""
    raw = ns.get("api_token", "")
    return str(raw) if isinstance(raw, str) else ""


def _extract_request_api_token() -> str:
    """从当前 Flask 请求里提取 client 提交的 API token。

    优先级（first-match-wins）：

    1. ``Authorization: Bearer <token>``——IETF RFC 6750 标准格式，监控
       仪表板 / 第三方工具默认走这条；
    2. ``X-API-Token: <token>``——curl / Postman 手写更直观，PWA 走
       ``fetch`` 时也可以省掉 ``Authorization`` 的 CORS preflight 开销。

    返回空串表示没附带 token；不引发异常，让 caller 决定 401 / 403 / 200。
    """
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get(_API_TOKEN_HEADER, "").strip()


def _is_api_token_authorized() -> bool:
    """当请求附带与 config 一致的 API token 时返回 True。

    使用 :func:`secrets.compare_digest` 做 constant-time 比较，避免按字符串
    timing 推断 token 前缀（Web 上有公开 PoC 演示 1-byte 累计时间差能推
    50 字节 token）。

    返回 False 的情形：
    - config 未配置 token（``api_token == ""``）—— 此时本函数不能授权任何
      请求，调用者需要回退到 loopback gate；
    - client 没附带 token；
    - client 附带的 token 与 config 不匹配。

    本函数**不**记日志，避免错误的 token 字符串被脱敏器漏过进 stderr。
    """
    configured = _get_configured_api_token()
    if not configured or len(configured) < _MIN_API_TOKEN_LEN:
        return False
    presented = _extract_request_api_token()
    if not presented:
        return False
    # constant-time compare；compare_digest 对长度不同的输入会 fast-fail，
    # 不会泄漏长度差异
    return secrets.compare_digest(configured, presented)


def _is_authorized() -> bool:
    """统一的「敏感端点准入」判定：loopback 来源 **或** 带有效 API token。

    设计原则：

    - 默认行为不变：``api_token`` 未配置时，仅 loopback 通过——所有现有
      loopback-only 端点的语义完全保留；
    - 配置 ``api_token`` 后**叠加**而不是**替换** loopback——本机用户不
      被迫在 curl 里粘 token，反向代理 / LAN PWA 等 non-loopback 场景拿
      token 即可通过；
    - 不引入「token-only 模式」：避免 fail-closed 配置错误把本机管理员
      锁在门外。如果未来确实需要严格 token-only，再加新字段
      ``api_token_strict = true`` 显式 opt-in。

    用法：所有原本 ``if not _is_loopback_request(): return 403`` 的端点
    都换成 ``if not _is_authorized(): return 403``。
    """
    return _is_loopback_request() or _is_api_token_authorized()


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
            if not _is_authorized():
                logger.warning(
                    f"open-config-file 拒绝未授权请求: client={_get_client_ip()!r}"
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                "Only loopback callers or requests with a valid "
                                "API token (Authorization: Bearer / X-API-Token) "
                                "are allowed."
                            ),
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

        # NOTE(feat-remove-test): 设置页"活动面板"已下线（见 ``templates/web_ui.html``
        # 中说明注释 + ``tests/test_feat_remove_test_uis_removed.py``）。
        # 此 endpoint 仍**保留**供性能基线脚本、dev 调试、监控 dashboards
        # 程序化拉取 SSE 总线指标。删除前请先 grep ``/api/system/sse-stats``。
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

        # NOTE(feat-remove-test): 设置页"活动面板"已下线（同上）。
        # 此 endpoint 仍**保留** —— 实际 release 必备：Prometheus exporter /
        # k8s liveness probe / 通知自检结果 probe（POST /api/system/notifications/test
        # 之后的二次校验）都依赖它。**绝不可** 因为 UI 下线就删该 route。
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

        @self.app.route("/api/system/metrics", methods=["GET"])
        @self.limiter.limit("120 per minute")
        def system_metrics() -> ResponseReturnValue:
            """T1 (cycle 4)：Prometheus exposition format `/metrics` 端点。

            ---
            tags:
              - System
            produces:
              - text/plain
            description: |
                Prometheus 0.0.4 exposition format 输出，与 ``/api/system/health``
                JSON 端点同一份数据，**面向 monitoring scrape**（Prometheus / Grafana
                Agent / VictoriaMetrics / Datadog OpenMetrics ingestor 等都直接吃这种
                格式）。

                **使用**：在 Prometheus ``scrape_configs:`` 加一条：

                ```yaml
                - job_name: ai-intervention-agent
                  metrics_path: /api/system/metrics
                  static_configs:
                    - targets: ['localhost:8765']
                  scrape_interval: 15s
                ```

                **暴露的 metric 类别**（HELP 字符串带具体含义）：

                * 进程：``aiia_uptime_seconds``，``aiia_build_info{version,git_*}``
                * SSE：``aiia_sse_emit_total`` / ``aiia_sse_subscriber_count`` /
                  ``aiia_sse_emit_to_deliver_ms{quantile=0.5|0.95}`` 等 8 个，
                  外加 **R202 / Cycle 8** 新增的 ``aiia_sse_emit_by_type_total
                  {event_type="..."}`` 按 R198 schema 4 个 event_type
                  (``task_changed`` / ``config_changed`` /
                  ``log_level_changed`` / ``oversize_drop``) 维度统计 emit
                  次数，与未标签化的 ``aiia_sse_emit_total`` 并存（向后兼
                  容 + 提供 per-type breakdown），不变量 ``sum(by_type) ==
                  overall``
                * Security：``aiia_token_age_seconds``（R204 / Cycle 9 · F-203-1）
                  ——当前 API token 自上次 rotation 经过的秒数，mirror
                  ``GET /api/system/api-token-info`` 的 ``age_seconds``
                  字段，让 alertmanager 不必 scrape JSON 即可设阈值告
                  警（如 ``aiia_token_age_seconds > 90 * 86400`` 提醒
                  rotation per NIST SP 800-63B）。无 token / rotated_at
                  解析失败时该 metric 不出现（与 ``aiia_uptime_seconds``
                  等其他 ``_safe_*`` helper 同款契约，让 Grafana 显示
                  "no data" 触发不同告警策略）
                * SSE schema 验证（R207 / Cycle 10 · F-205-2）：
                  ``aiia_sse_schema_violation_total`` counter ——
                  R205 ``AIIA_SSE_SCHEMA_VALIDATE=warn|strict`` 开关检测到
                  的 emit-site schema 违规累计次数（mirror
                  ``stats_snapshot()['schema_violation_total']``）。**omit
                  when off**：开关 == "off" 时 metric **不出现**，
                  alertmanager 用 ``absent(aiia_sse_schema_violation_total)``
                  可分清"validation off"（不在监控）vs "validation on with
                  0 violations"（监控中但无违规），两类 ops 状态走不同
                  alert 路由处理；warn/strict mode 时 metric 出现 (value ≥ 0)。
                  一条 emit 多字段错只算 1 次违规（matches R205 不噪声
                  膨胀契约）。
                * TaskQueue：``aiia_task_queue_size`` / ``aiia_task_queue_max``
                * 错误日志：``aiia_recent_errors_5min``
                * Notification：``aiia_notification_enabled`` /
                  ``aiia_notification_attempts_total{provider="bark|web|sound|system"}``
                  及 success/failure/streak 配套

                **PII 边界**：与 ``/api/system/health`` 一致——所有 metric 值
                都是数值或 enum，绝不暴露 config 字段值 / token / device_key /
                last_error 原始字符串。

                **失败优雅降级**：任何子项探测失败，对应 metric 直接被跳过；
                整端点永远 200，最坏情况返回空 body 让监控发现 "metric 消失"
                而不是 5xx 拖累 scrape budget。

                rate-limit 120/min（与 health 端点同档），覆盖 Prometheus 默认
                15 s 抓取 + 多副本余量。
            responses:
              200:
                description: Prometheus exposition format（``text/plain; version=0.0.4``）
            """
            from flask import Response

            payload = _render_prometheus_metrics()
            return Response(
                payload,
                status=200,
                mimetype="text/plain; version=0.0.4; charset=utf-8",
            )

        @self.app.route("/api/system/log-level", methods=["GET"])
        @self.limiter.limit("60 per minute")
        def system_log_level_get() -> ResponseReturnValue:
            """T3 (cycle 4) / R188：查询当前运行时日志级别。

            ---
            tags:
              - System
            description: |
                返回 root logger + ``ai_intervention_agent`` 命名空间的当前
                有效日志级别，以及可被 ``POST`` 接受的 enum 值清单（让 client
                UI 渲染下拉菜单时不用硬编码）。

                **任意来源** 的请求都允许查询——返回的只是 enum + level 名，
                没有 PII / 敏感信息。rate-limit 60/min 比 POST 宽松（查询无副
                作用），但仍设了下限避免被滥用做 health-probe substitute。
            responses:
              200:
                description: 当前日志级别快照
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    root_level:
                      type: string
                      description: root logger 的 effective level（如 "INFO"）
                    aiia_level:
                      type: string
                      description: ai_intervention_agent 命名空间的 effective level
                    valid_levels:
                      type: array
                      description: POST 接受的 5 个 enum 值
                      items:
                        type: string
            """
            try:
                from ai_intervention_agent.enhanced_logging import (
                    get_current_log_level,
                )

                snapshot = get_current_log_level()
            except Exception as exc:
                logger.error(
                    f"GET /api/system/log-level 内部错误: {type(exc).__name__}: {exc}"
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"internal error: {type(exc).__name__}",
                        }
                    ),
                    500,
                )
            return jsonify({"success": True, **snapshot}), 200

        @self.app.route("/api/system/log-level", methods=["POST"])
        @self.limiter.limit("30 per minute")
        def system_log_level_post() -> ResponseReturnValue:
            """T3 (cycle 4) / R188：运行时修改 root logger 日志级别。

            ---
            tags:
              - System
            description: |
                让运维 / 调试场景下不重启 server 就能临时把日志级别拉高
                （``DEBUG`` 排查具体问题）或拉低（事后恢复 ``WARNING`` 避免
                stderr 爆量）。

                **安全约束**：

                * 仅 ``loopback`` 来源（``127.0.0.1`` / ``::1``）允许调用——
                  与 ``open-config-file`` 同档安全级别，避免远程主机通过
                  web UI 把日志炸到磁盘满；
                * 只接受 ``DEBUG`` / ``INFO`` / ``WARNING`` / ``ERROR`` /
                  ``CRITICAL`` 5 个 enum 值（大小写不敏感）；其他值返回 400；
                * 只改 root logger + 所有 handler 级别——**不接受**任意
                  ``logger_name`` 参数（攻击面最小化）；
                * 修改**不持久化**：只影响当前进程，重启后回到 env var /
                  config 控制的初始级别。运维忘记关回去也不会污染 config。

                rate-limit 30/min（与 ``recent-logs`` 同档）—— 这是一个
                "偶尔切换" 而不是 "高频调用" 的运维端点。
            parameters:
              - in: body
                name: body
                required: true
                schema:
                  type: object
                  required:
                    - level
                  properties:
                    level:
                      type: string
                      description: 目标日志级别，5 个 enum 值之一
                      enum: [DEBUG, INFO, WARNING, ERROR, CRITICAL]
            responses:
              200:
                description: 修改成功
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    old_level:
                      type: string
                    new_level:
                      type: string
                    logger:
                      type: string
                      description: 始终为 "root"（本端点只支持 root logger）
              400:
                description: payload 无效或 level 不在 enum 内
              403:
                description: 非 loopback 来源
            """
            if not _is_authorized():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                "log-level changes require loopback caller or "
                                "valid API token (Authorization: Bearer / X-API-Token)"
                            ),
                        }
                    ),
                    403,
                )

            payload: dict[str, Any] = request.get_json(silent=True) or {}
            level = payload.get("level")
            if not isinstance(level, str):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "missing or non-string `level` field",
                        }
                    ),
                    400,
                )

            try:
                from ai_intervention_agent.enhanced_logging import (
                    apply_runtime_log_level,
                )

                result = apply_runtime_log_level(level)
            except ValueError as exc:
                return (
                    jsonify({"success": False, "error": str(exc)}),
                    400,
                )
            except Exception as exc:
                logger.error(
                    f"POST /api/system/log-level 内部错误: {type(exc).__name__}: {exc}"
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"internal error: {type(exc).__name__}",
                        }
                    ),
                    500,
                )

            # R192 / Cycle 5：把变更广播到 SSE bus，让 activity dashboard /
            # PWA 状态栏 / 监控仪表板能实时看到「root logger 从 INFO 切到
            # DEBUG by 127.0.0.1 at 14:35:22」。多操作员部署场景下尤其
            # 重要——操作员 A 切到 DEBUG 排查问题忘了切回，操作员 B
            # 看到 stderr 爆量但不知道是「正常排查」还是「有 bug」。
            # 失败兜底：SSE 推送故障**不影响** 200 响应——日志级别已经
            # 改成功，配套通知失败只是降级到「无横幅展示」，没有数据丢失。
            try:
                from ai_intervention_agent.web_ui_routes.task import _sse_bus

                _sse_bus.emit(
                    "log_level_changed",
                    {
                        "old_level": result.get("old_level"),
                        "new_level": result.get("new_level"),
                        "logger": result.get("logger", "root"),
                        "changed_by": _get_client_ip() or "unknown",
                    },
                )
            except Exception as exc:  # [R-192]
                # SSE bus 不可用 / emit raise → 安静降级，
                # log 一行 debug 方便定位但**不**让端点失败。
                logger.debug(
                    f"log_level_changed SSE emit failed: {type(exc).__name__}: {exc}"
                )

            return jsonify({"success": True, **result}), 200

        @self.app.route("/api/system/rotate-api-token", methods=["POST"])
        @self.limiter.limit("5 per hour")
        def rotate_api_token() -> ResponseReturnValue:
            """R195 / Cycle 5：本机管理员请求**轮换** ``api_token``（用于
            常规凭据 rotation，符合 NIST SP 800-63B 推荐的 30-90 天周期）。

            ---
            tags:
              - System
            description: |
                生成新的 32-byte URL-safe random token（约 43 字符），写入
                ``config.toml`` 的 ``[network_security].api_token`` 字段
                （保留注释 + 原子替换），并通过响应体返回**一次**新 token。

                **同步写入 ``api_token_rotated_at``**（R199 / Cycle 7 起）：
                同一次 ``update_network_security_config`` 调用里把
                ``[network_security].api_token_rotated_at`` 设为本次 rotation
                的 ISO-8601 UTC 时间戳（``...Z`` 后缀，与响应体 ``rotated_at``
                完全一致——见函数体内的「先生成时间戳再写 config」注释）。
                ``GET /api/system/api-token-info`` 端点（R199）从 config
                读取这个字段，配合 wall-clock 算出 token age，用于驱动
                dashboard 按 NIST SP 800-63B 30-90 天周期发轮换告警。
                如果 admin 后续手动把 ``api_token`` 清空（撤销），R200
                cascade-clear 会**自动**同步清空 ``api_token_rotated_at``，
                避免「has_token=false 但 rotated_at 仍是上次时间戳」的
                「stale ghost」状态。

                **安全约束**：

                * **仅 loopback 来源**（``127.0.0.1`` / ``::1``）允许调用。
                  ``_is_authorized()`` 用「loopback OR token」复合鉴权 ——
                  但这个端点**强制**要求 loopback。**不能**用旧 token 直
                  接换新 token，避免「token 已经泄漏 → 攻击者自动续期」
                  这条攻击路径（业界普遍叫做 「token rotation hijacking」）。
                * **rate-limit 5/hour**：admin 工具偶尔调，攻击者高频尝试
                  立即被限流。
                * **响应体含明文 token**：这是 rotation 端点的**唯一**返
                  回时机——admin 必须当场把它复制到 secret manager。后续
                  ``GET /api/system/...`` 端点**都不**再透出 token。
                * **R53-F 契约自动覆盖**：``network_security`` 段已经在
                  ``ConfigManager.get_all()`` 边界被过滤，rotation 写入
                  后 ``/api/system/health`` / ``--print-config`` 都不会
                  暴露新 token。
                * **R193 即时生效**：写入触发 ``invalidate_all_caches()``，
                  下一次 ``_is_authorized()`` 就**只**接受新 token（旧
                  token 立刻失效，与传统 rotation 「new token starts
                  working at T+0，old token stops at T+0」一致）。

                **失败兜底**：写入失败（磁盘满 / 权限错 / config 文件不
                可写）时返回 500 + ``error`` 字段，旧 token 仍然有效，
                不会让管理员被锁在门外。
            responses:
              200:
                description: 轮换成功，响应体含新 token（仅此一次返回明文）
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    api_token:
                      type: string
                      description: 新生成的 token；**立即记录到 secret manager**
                    token_length:
                      type: integer
                    rotated_at:
                      type: string
                      description: ISO-8601 UTC timestamp
              403:
                description: 非 loopback 来源（rotation 强制只允许本机）
              500:
                description: 写入 config 失败
              429:
                description: 速率超限（5/hour）
            """
            # 注意：本端点**不**用 ``_is_authorized()``——后者允许 token
            # 通过鉴权，但 rotation 必须强制 loopback only（见 docstring
            # 「token rotation hijacking」段落）。
            if not _is_loopback_request():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                "API token rotation requires loopback caller "
                                "(127.0.0.1 / ::1). Token-based auth is "
                                "deliberately rejected here to prevent "
                                "token-rotation-hijacking attacks."
                            ),
                        }
                    ),
                    403,
                )

            new_token = secrets.token_urlsafe(32)
            # R199 / Cycle 7：rotation 时间戳，写入 config + 响应同步
            # 返回。在调用 update_network_security_config **之前**生成
            # （而不是之后），让磁盘里的 rotated_at 跟响应里的字符串
            # 完全一致——后续 GET /api/system/api-token-info 读取 config
            # 时就能算出准确的 age。
            from datetime import UTC, datetime

            rotated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            try:
                cfg = get_config()
                cfg.update_network_security_config(
                    {"api_token": new_token, "api_token_rotated_at": rotated_at}
                )
            except Exception as exc:
                logger.error(
                    f"rotate-api-token 写入 config 失败: {type(exc).__name__}: {exc}"
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                "Failed to persist new token; old token "
                                "remains active. Check disk space / file "
                                "permissions / config.toml writability."
                            ),
                        }
                    ),
                    500,
                )

            return jsonify(
                {
                    "success": True,
                    "api_token": new_token,
                    "token_length": len(new_token),
                    "rotated_at": rotated_at,
                }
            ), 200

        @self.app.route("/api/system/api-token-info", methods=["GET"])
        @self.limiter.limit("30 per minute")
        def api_token_info() -> ResponseReturnValue:
            """R199 / Cycle 7：返回 API token 的**元数据**（不含 token 本身）。

            ---
            tags:
              - System
            description: |
                给 admin 工具 / dashboard 查询 token age 信息，配合
                NIST SP 800-63B 推荐的 30-90 天轮换周期发 alert。

                **响应字段**：

                - ``has_token``: ``bool`` —— config 里 ``api_token`` 是否已
                  设置（非空 + 长度 ≥ 16）。
                - ``token_length``: ``int | None`` —— token 字符长度，
                  ``has_token=false`` 时为 ``null``。
                - ``rotated_at``: ``str`` —— 上次轮换的 ISO-8601 UTC 时间戳
                  （由 ``POST /api/system/rotate-api-token`` 写入），从未
                  轮换则为空串。
                - ``age_seconds``: ``int | None`` —— 当前时刻 -
                  ``rotated_at`` 的秒差。``rotated_at`` 为空 → ``null``。

                **安全约束**：

                * **仅 loopback 来源**——跟 ``rotate-api-token`` 同款。
                  虽然本端点**不**透出 token，但 token age 仍是敏感信息
                  （攻击者知道 token 已经用了 89 天可以预测下次 rotation
                  时机）。
                * **rate-limit 30/min**：admin 工具可能 poll，单端点
                  30/min 足够 + 防滥用。

                **不会返回 token 本身**——rotation 端点是唯一返回明文
                token 的时机。如果你忘了存上次返回的 token，唯一恢复
                路径是 ``POST /api/system/rotate-api-token`` 再轮换一次。
            responses:
              200:
                description: token 元数据
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    has_token:
                      type: boolean
                    token_length:
                      type: integer
                    rotated_at:
                      type: string
                    age_seconds:
                      type: integer
              403:
                description: 非 loopback 来源
            """
            # 跟 rotate-api-token 同款 loopback gate（token age 是元数据
            # 不是 secret 但仍敏感, 保持与 rotation 一致的访问门槛）
            if not _is_loopback_request():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                "API token info endpoint requires loopback "
                                "caller (127.0.0.1 / ::1). Token age is "
                                "sensitive metadata."
                            ),
                        }
                    ),
                    403,
                )

            try:
                cfg = get_config()
                ns = cfg.get_network_security_config()
            except Exception as exc:
                logger.error(
                    f"api-token-info 读取 config 失败: {type(exc).__name__}: {exc}"
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Failed to read network_security config.",
                        }
                    ),
                    500,
                )

            token = ns.get("api_token", "") if isinstance(ns, dict) else ""
            has_token = bool(token) and len(token) >= 16
            token_length = len(token) if has_token else None
            rotated_at = (
                ns.get("api_token_rotated_at", "") if isinstance(ns, dict) else ""
            )

            # R208 / Cycle 10 · F-204-2: 共享 helper 算 age, 与 R204
            # `_safe_token_age_seconds` / `aiia_token_age_seconds` Prom
            # gauge 同一份实现. helper silent, 无脏数据 debug log——R199
            # 测试不依赖该 log; pure function 风格与 _safe_uptime_seconds
            # 等保持一致.
            age_seconds = _compute_age_seconds_from_iso(rotated_at)

            return (
                jsonify(
                    {
                        "success": True,
                        "has_token": has_token,
                        "token_length": token_length,
                        "rotated_at": rotated_at if isinstance(rotated_at, str) else "",
                        "age_seconds": age_seconds,
                    }
                ),
                200,
            )

        # NOTE(feat-remove-test): 设置页"活动面板"已下线（同上）。
        # 此 endpoint 仍**保留**供 CI 调试、用户支持工单时手动 curl 查看
        # 最近日志（``curl /api/system/recent-logs?limit=50``）。
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
            if not _is_authorized():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                "Only loopback callers or requests with a valid "
                                "API token are allowed."
                            ),
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
