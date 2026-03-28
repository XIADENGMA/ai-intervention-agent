"""配置热更新回调 — 从 web_ui.py 提取的纯逻辑。

管理 feedback.auto_resubmit_timeout 和 network_security 配置变更后
对运行中任务/Web UI 实例的同步逻辑。

设计约束：
- 模块级状态变量保留在 web_ui.py（测试通过 web_ui.XXX 读写）
- get_config / get_task_queue 通过 lazy import web_ui 获取
  → 测试 @patch("web_ui.get_config") 即可生效，无需修改
"""

from __future__ import annotations

from enhanced_logging import EnhancedLogger
from server_config import AUTO_RESUBMIT_TIMEOUT_DEFAULT
from web_ui_validators import validate_auto_resubmit_timeout

logger = EnhancedLogger(__name__)


def _get_default_auto_resubmit_timeout_from_config() -> int:
    """从配置文件读取默认 auto_resubmit_timeout（保持向后兼容）"""
    import web_ui as _wu

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
    import web_ui as _wu

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
    import web_ui as _wu

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
        else:
            inst.network_security_config = new_cfg
    except Exception as e:
        logger.warning(f"配置变更回调执行失败（同步网络安全配置）：{e}", exc_info=True)


def _ensure_network_security_hot_reload_callback_registered() -> None:
    """确保仅注册一次 network_security 配置热更新回调。"""
    import web_ui as _wu

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
    import web_ui as _wu

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
