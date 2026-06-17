"""配置热更新回调 — 从 web_ui.py 提取的纯逻辑。

管理 feedback.auto_resubmit_timeout 和 network_security 配置变更后
对运行中任务/Web UI 实例的同步逻辑。

设计约束：
- 模块级状态变量保留在 web_ui.py（测试通过 web_ui.XXX 读写）
- get_config / get_task_queue 通过 lazy import web_ui 获取
  → 测试 @patch("web_ui.get_config") 即可生效，无需修改
"""

from __future__ import annotations

import threading
import time

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.runtime_constants import AUTO_RESUBMIT_TIMEOUT_DEFAULT
from ai_intervention_agent.web_ui_validators import validate_auto_resubmit_timeout

logger = EnhancedLogger(__name__)


def _get_default_auto_resubmit_timeout_from_config() -> int:
    """从配置文件读取默认 auto_resubmit_timeout（保持向后兼容）"""
    import ai_intervention_agent.web_ui as _wu

    config_mgr = _wu.get_config()
    feedback_config = config_mgr.get_section("feedback")
    raw_timeout = feedback_config.get(
        "frontend_countdown",
        feedback_config.get("auto_resubmit_timeout", AUTO_RESUBMIT_TIMEOUT_DEFAULT),
    )
    try:
        return validate_auto_resubmit_timeout(int(raw_timeout))
    except Exception:
        return AUTO_RESUBMIT_TIMEOUT_DEFAULT


def _sync_existing_tasks_timeout_from_config() -> None:
    """配置变更回调：将新的默认倒计时同步到所有未完成任务"""
    import ai_intervention_agent.web_ui as _wu

    try:
        new_timeout = _wu._get_default_auto_resubmit_timeout_from_config()

        with _wu._FEEDBACK_TIMEOUT_CALLBACK_LOCK:
            if new_timeout == _wu._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT:
                return
            _wu._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = new_timeout

        task_queue = _wu.get_task_queue()
        updated = task_queue.update_auto_resubmit_timeout_for_all(new_timeout)
        if updated > 0:
            logger.info(
                f"配置变更：已将 {updated} 个未完成任务的 auto_resubmit_timeout 同步为 {new_timeout} 秒"
            )

        inst = _wu._CURRENT_WEB_UI_INSTANCE
        if inst is not None and not getattr(
            inst, "_single_task_timeout_explicit", True
        ):
            try:
                lock = getattr(inst, "_state_lock", None)
                if lock is not None:
                    with lock:
                        inst.current_auto_resubmit_timeout = new_timeout
                else:
                    inst.current_auto_resubmit_timeout = new_timeout
            except Exception:
                inst.current_auto_resubmit_timeout = new_timeout
    except Exception as e:
        logger.warning(f"配置变更回调执行失败（同步任务倒计时）：{e}", exc_info=True)


def _sync_network_security_from_config() -> None:
    """配置变更回调：同步运行中 Web UI 的 network_security 配置。"""
    import ai_intervention_agent.web_ui as _wu

    inst = _wu._CURRENT_WEB_UI_INSTANCE
    if inst is None:
        return
    try:
        loader = getattr(inst, "_load_network_security_config", None)
        if not callable(loader):
            return
        new_cfg = loader()
        if not isinstance(new_cfg, dict):
            return
        lock = getattr(inst, "_state_lock", None)
        if lock is not None:
            with lock:
                inst.network_security_config = new_cfg
                inst._network_security_config_loaded_from_config = True
        else:
            inst.network_security_config = new_cfg
            inst._network_security_config_loaded_from_config = True
    except Exception as e:
        logger.warning(f"配置变更回调执行失败（同步网络安全配置）：{e}", exc_info=True)


def _ensure_network_security_hot_reload_callback_registered() -> None:
    """确保仅注册一次 network_security 配置热更新回调。"""
    import ai_intervention_agent.web_ui as _wu

    if _wu._NETWORK_SECURITY_CALLBACK_REGISTERED:
        return
    with _wu._NETWORK_SECURITY_CALLBACK_LOCK:
        if _wu._NETWORK_SECURITY_CALLBACK_REGISTERED:
            return
        try:
            cfg = _wu.get_config()
            cfg.register_config_change_callback(_sync_network_security_from_config)
            _wu._NETWORK_SECURITY_CALLBACK_REGISTERED = True
            _sync_network_security_from_config()
            logger.debug("已注册 network_security 热更新回调（同步访问控制配置）")
        except Exception as e:
            logger.warning(
                f"注册 network_security 配置热更新回调失败（将仅在启动时生效）：{e}",
                exc_info=True,
            )


def _ensure_feedback_timeout_hot_reload_callback_registered() -> None:
    """确保仅注册一次 feedback.auto_resubmit_timeout 热更新回调。"""
    import ai_intervention_agent.web_ui as _wu

    if _wu._FEEDBACK_TIMEOUT_CALLBACK_REGISTERED:
        return
    with _wu._FEEDBACK_TIMEOUT_CALLBACK_LOCK:
        if _wu._FEEDBACK_TIMEOUT_CALLBACK_REGISTERED:
            return
        try:
            config_mgr = _wu.get_config()
            config_mgr.register_config_change_callback(
                _sync_existing_tasks_timeout_from_config
            )
            _wu._FEEDBACK_TIMEOUT_CALLBACK_REGISTERED = True
            _sync_existing_tasks_timeout_from_config()
            logger.debug(
                "已注册 feedback.auto_resubmit_timeout 热更新回调（同步已存在任务倒计时）"
            )
        except Exception as e:
            logger.warning(
                f"注册 feedback 配置热更新回调失败（将降级为仅对新任务生效）：{e}",
                exc_info=True,
            )


# ============================================================================
# R48: config_changed SSE 推送
#
# 设计动机：项目里已经有 ``ConfigManager.start_file_watcher`` + 一组 ``register_
# config_change_callback`` 在做"运行时热更新"——但用户视角下的反馈缺位：
#
#   - 改了 ``notification.bark_url``：要么走 ``_invalidate_runtime_caches_on_config_change``
#     无声生效，要么压根不在热更新白名单里（多数复杂字段都是后者）。
#   - 用户没有任何 UI 反馈，只能"改完配置 → 等 / 重启 → 试试看"；非常容易踩
#     "我以为我改了，但其实是 cwd 错了 / 文件被自动迁移了"的坑。
#
# 解决方式：所有 config 变更都额外推一个 ``config_changed`` SSE 事件，让前端
# （浏览器 PWA / VSCode Webview / VSCode 状态栏）能主动弹一行提示
# "配置已变更，按 Ctrl+R 重载页面"。客户端不强制 reload，因为：
#
#   1. 已经热更新的字段（feedback / network_security）是无感生效的，
#      用户重载只是为了看 UI 上的当前值；
#   2. 还没热更新的字段（如 ``mcp.tool_metadata``）只能等下一次重启 server
#      才能体现，重载页面也无济于事；
#   3. 让客户端自己决定是 toast 还是 silent log 更合理。
#
# 安全性：``_sse_bus.emit`` 自身已经是线程安全 + backpressure-aware，
# 即使每秒 10 次 mtime 变更也不会让 SSE 链路炸掉；保险起见我们的回调
# 也只发一个 lightweight 字典，不带任何敏感配置内容。
# ============================================================================


_CONFIG_CHANGED_EMIT_DEBOUNCE_S: float = 0.25
"""``_emit_config_changed_to_sse_bus`` 的 leading-edge debounce 窗口（秒）。

设计取舍 (R50-B)：
- 用户一次 ``Cmd+S`` 通常会让编辑器把 config.toml 写两到三次（先 truncate
  再 fsync），mtime 跳变两到三轮 → ``ConfigManager._trigger_config_change_callbacks``
  会在 ~50 ms 内被连击 2-3 次，回调一遍跑下来本来会发 2-3 个 SSE 事件。
- ``_HISTORY_MAXLEN=128`` 可以容纳得了，但前端 toast / VSCode 状态栏
  会闪 2-3 次，看起来像 "为啥它一直在喊配置变了"。
- 250 ms 的 leading-edge 设计：第一次 callback 立刻 emit，
  紧随其后的 callback 在 250 ms 内全部跳过，250 ms 之后又是新一轮。
  这样保证 "立刻有提示" 但 "不刷屏"。

为什么不用 trailing-edge：trailing-edge 需要 ``threading.Timer`` 排程一个
延迟回调，进程退出时若 timer 还在 pending、其 callback 可能在 SSE bus
已 shut 后跑，造成 ``ValueError: I/O on closed file``。leading-edge 没有
timer 状态，整体可靠性更好。
"""

_last_emit_monotonic: float = 0.0
_emit_debounce_lock: threading.Lock = threading.Lock()


def _emit_config_changed_to_sse_bus() -> None:
    """配置变更回调：通过 SSE 总线推一个 ``config_changed`` 事件（带 debounce）。

    所有已连接的 client（浏览器 PWA / VSCode Webview）都会立刻收到这个
    事件，UI 自行决定是 toast 提示还是 silent log。

    R50-B：leading-edge debounce 防止 mtime 风暴下 SSE 事件刷屏。
    详见 ``_CONFIG_CHANGED_EMIT_DEBOUNCE_S`` 注释。
    """
    global _last_emit_monotonic
    with _emit_debounce_lock:
        now = time.monotonic()
        if now - _last_emit_monotonic < _CONFIG_CHANGED_EMIT_DEBOUNCE_S:
            logger.debug(
                f"config_changed 事件被 debounce 抑制"
                f"（距上次 emit {(now - _last_emit_monotonic) * 1000:.0f} ms < "
                f"{_CONFIG_CHANGED_EMIT_DEBOUNCE_S * 1000:.0f} ms 窗口）"
            )
            return
        _last_emit_monotonic = now

    try:
        # lazy import：避免模块加载阶段就拖入 web_ui_routes / Flask 等。
        # ``_sse_bus`` 是 module-level singleton，import 不会有副作用。
        from ai_intervention_agent.web_ui_routes.task import _sse_bus

        _sse_bus.emit(
            "config_changed",
            {
                "reason": "config_file_modified",
                "hint": (
                    "Configuration file changed. Reload the page to see the latest values."
                ),
            },
        )
        logger.debug("config_changed 事件已通过 SSE 总线广播")
    except Exception as e:
        # 推送失败不应影响主热更新流程；其它已注册的 callback 还会跑。
        logger.warning(
            f"广播 config_changed 事件失败（其它热更新回调不受影响）：{e}",
            exc_info=True,
        )


def _ensure_config_changed_sse_callback_registered() -> None:
    """确保仅注册一次 config_changed SSE 推送回调（R48）。

    与 ``_ensure_*_hot_reload_callback_registered`` 同样的 idempotent
    模式：模块级 flag + lock 双检，保证不重复注册同一个 callback。
    注册失败 → 降级到"只在重启时生效"，记录 warning 但不抛异常。
    """
    import ai_intervention_agent.web_ui as _wu

    if _wu._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED:
        return
    with _wu._CONFIG_CHANGED_SSE_CALLBACK_LOCK:
        if _wu._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED:
            return
        try:
            config_mgr = _wu.get_config()
            config_mgr.register_config_change_callback(_emit_config_changed_to_sse_bus)
            _wu._CONFIG_CHANGED_SSE_CALLBACK_REGISTERED = True
            logger.debug(
                "已注册 config_changed SSE 推送回调（让 client 在配置变更时主动提示）"
            )
        except Exception as e:
            logger.warning(
                f"注册 config_changed SSE 推送回调失败（client 将无法收到变更提示）：{e}",
                exc_info=True,
            )
