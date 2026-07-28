"""配置热更新回调 — 从 web_ui.py 提取的纯逻辑。"""

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
    """确保仅注册一次 feedback.auto_resubmit_timeout 热更新回调。

    R702：注册时只记录当前配置基线（_LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT），
    不立即同步已存在任务——同步只在配置真正变更的回调里发生。
    """
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

            with _wu._FEEDBACK_TIMEOUT_CALLBACK_LOCK:
                _wu._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = (
                    _wu._get_default_auto_resubmit_timeout_from_config()
                )
            logger.debug(
                "已注册 feedback.auto_resubmit_timeout 热更新回调（同步已存在任务倒计时）"
            )
        except Exception as e:
            logger.warning(
                f"注册 feedback 配置热更新回调失败（将降级为仅对新任务生效）：{e}",
                exc_info=True,
            )


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
    """配置变更回调：通过 SSE 总线推一个 ``config_changed`` 事件（带 debounce）。"""
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
        logger.warning(
            f"广播 config_changed 事件失败（其它热更新回调不受影响）：{e}",
            exc_info=True,
        )


def _ensure_config_changed_sse_callback_registered() -> None:
    """确保仅注册一次 config_changed SSE 推送回调（R48）。"""
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
