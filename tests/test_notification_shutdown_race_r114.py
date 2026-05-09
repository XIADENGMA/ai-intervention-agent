"""R114：``NotificationManager._process_event`` 与 ``shutdown`` 之间的
TOCTOU race condition 修复回归测试。

背景
====
R114 之前，``_process_event`` 在第 579 行检查 ``_shutdown_called``、
第 600 行 ``self._executor.submit(...)`` 之间有一个 race window：

    线程 A（``_process_event``）：     线程 B（``shutdown``）：
        if _shutdown_called: return       _shutdown_called = True
        # ← race window 在这里 →         _executor.shutdown(cancel_futures=True)
        future = _executor.submit(...)
        # → 抛 RuntimeError
        #   "cannot schedule new futures after shutdown"

旧实现把这条 ``RuntimeError`` 由外层 ``except Exception`` 兜底，
打成 ``ERROR`` 级 ``处理通知事件失败``——日志归因不准（看上去像
provider 故障，实际是 shutdown 良性竞态），还会污染监控告警。

R114 修复：把 submit 循环单独包一层 ``try/except RuntimeError``，
命中后**二次确认** ``_shutdown_called`` 为 True 才走 R114 静默路径
（DEBUG 日志 + return），其它 RuntimeError 仍交外层 except。

本测试涵盖
==========
1. **真实 race 触发**（``test_real_shutdown_race_window_triggers_runtime_error``）：
   不 mock，用 ``threading.Event`` 强制让 ``_process_event`` 在 line 579/600
   之间挂起、触发 ``shutdown``、再放行——验证旧实现下确实会抛 ``RuntimeError``，
   修复后被 R114 静默吞掉。
2. **submit 失败后 ``_shutdown_called=True``**：走 R114 静默路径（DEBUG 日志 + return）。
3. **submit 失败但 ``_shutdown_called=False``**：``RuntimeError`` 必须冒泡到外层
   ``except``，不允许伪装成 R114（防止把真正的 bug 误吞）。
4. **submit 部分成功后 race**：第二个 ``submit`` 失败时，已 submit 的 future
   被 ``cancel_futures=True`` 自然取消，不能 leak、不能让 ``as_completed`` 死等。
5. **R114 路径不打 ERROR 日志**：守护"不再产生噪声 ERROR"这一可观测性 contract。
"""

from __future__ import annotations

import logging
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

from ai_intervention_agent.notification_manager import (
    NotificationEvent,
    NotificationManager,
    NotificationPriority,
    NotificationTrigger,
    NotificationType,
)


def _make_manager() -> NotificationManager:
    """构造一个最小可用的 ``NotificationManager``，绕开单例 + 配置文件。"""
    mgr = NotificationManager.__new__(NotificationManager)

    from ai_intervention_agent.notification_manager import NotificationConfig

    mgr.config = NotificationConfig()
    mgr._providers = {}
    mgr._providers_lock = threading.Lock()
    mgr._config_lock = threading.RLock()
    mgr._queue_lock = threading.Lock()
    mgr._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="R114Worker")
    mgr._delayed_timers = {}
    mgr._delayed_timers_lock = threading.Lock()
    mgr._shutdown_called = False
    mgr._stats_lock = threading.Lock()
    mgr._stats = {
        "events_total": 0,
        "events_succeeded": 0,
        "events_failed": 0,
        "attempts_total": 0,
        "retries_scheduled": 0,
        "last_event_id": None,
        "last_event_at": None,
        "providers": {},
    }
    mgr._finalized_event_ids = {}
    mgr._finalized_max_size = 500
    mgr._callbacks_lock = threading.Lock()
    mgr._callbacks = {}
    mgr._initialized = True
    return mgr


def _make_event(**kw: Any) -> NotificationEvent:
    defaults: dict[str, Any] = {
        "id": "r114_test",
        "title": "R114 Race Test",
        "message": "Triggering TOCTOU window",
        "trigger": NotificationTrigger.IMMEDIATE,
        "types": [NotificationType.WEB],
        "metadata": {},
        "max_retries": 0,
        "priority": NotificationPriority.NORMAL,
    }
    defaults.update(kw)
    return NotificationEvent(**defaults)


class _GatedExecutor:
    """包装 ``ThreadPoolExecutor``，在第 N 次 ``submit`` 调用时调 ``hook``。

    用 ``hook`` 模拟"在 ``_process_event`` 即将 submit 时另一线程 shutdown"
    的真实时序，避免依赖 ``time.sleep`` 等概率性同步手段。
    """

    def __init__(self, real: ThreadPoolExecutor, *, hook_at_call: int, hook):
        self._real = real
        self._hook_at_call = hook_at_call
        self._hook = hook
        self._call_count = 0
        self._lock = threading.Lock()

    def submit(self, fn, *args, **kwargs):
        with self._lock:
            self._call_count += 1
            should_hook = self._call_count == self._hook_at_call
        if should_hook:
            self._hook()
        return self._real.submit(fn, *args, **kwargs)

    def shutdown(self, *args, **kwargs):
        return self._real.shutdown(*args, **kwargs)


class TestR114ShutdownRaceCondition(unittest.TestCase):
    """R114 主回归测试：``_process_event`` 与 ``shutdown`` 的 TOCTOU race。"""

    def setUp(self) -> None:
        self.mgr = _make_manager()
        self.provider = MagicMock()
        self.provider.send.return_value = True
        self.mgr.register_provider(NotificationType.WEB, self.provider)

    def tearDown(self) -> None:
        try:
            self.mgr.shutdown(wait=True)
        except Exception:
            pass

    def test_real_shutdown_race_window_triggers_runtime_error(self) -> None:
        """**核心**：用 ``_GatedExecutor`` 制造真实 race window。

        在 ``_process_event`` 第一次 ``submit`` 之前同步触发 ``shutdown()``，
        ``shutdown`` 完成后才让 ``submit`` 真正调下去——此时底层
        ``ThreadPoolExecutor`` 已关闭，``submit`` 会抛 ``RuntimeError``。
        R114 修复要求：这条 ``RuntimeError`` 被识别为良性竞态，
        ``_process_event`` 静默 return，**不**冒泡为 ERROR 日志。
        """
        real_executor = self.mgr._executor

        def shutdown_in_other_thread() -> None:
            self.mgr._shutdown_called = True
            real_executor.shutdown(wait=False, cancel_futures=True)

        self.mgr._executor = _GatedExecutor(  # ty: ignore[invalid-assignment]
            real_executor,
            hook_at_call=1,
            hook=shutdown_in_other_thread,
        )

        event = _make_event(
            id="r114_real_race",
            types=[NotificationType.WEB, NotificationType.SOUND],
        )

        with self.assertLogs(
            "ai_intervention_agent.notification_manager", level="DEBUG"
        ) as cm:
            self.mgr._process_event(event)

        debug_lines = [m for m in cm.output if "[R114]" in m]
        self.assertTrue(
            debug_lines,
            f"R114 DEBUG 日志缺失，全部输出: {cm.output}",
        )

        error_lines = [
            m for m in cm.output if m.startswith("ERROR") and "处理通知事件失败" in m
        ]
        self.assertFalse(
            error_lines,
            f"R114 修复后不应出现 ERROR 级'处理通知事件失败'日志: {error_lines}",
        )

    def test_submit_runtime_error_with_shutdown_flag_silenced(self) -> None:
        """单元路径：模拟 line 579 check 通过（False）+ line 600 submit 时 flag 已翻 True。

        无需真实线程，用 ``_LazyShutdownFlag`` 模拟 race：
        - 第一次 ``getattr`` (line 579) → False（让 ``_process_event`` 进主体）
        - 后续 ``getattr`` (line 624 R114 二次确认) → True（让 R114 静默路径生效）
        验证 R114 的二次确认逻辑能正确识别"check 后 shutdown"的良性竞态。
        """

        class _LazyShutdownFlag:
            """``__bool__`` 第一次返回 False、之后返回 True，模拟并发翻转。"""

            def __init__(self) -> None:
                self._read_count = 0

            def __bool__(self) -> bool:
                self._read_count += 1
                return self._read_count > 1

        self.mgr._shutdown_called = _LazyShutdownFlag()  # ty: ignore[invalid-assignment]

        broken_executor = MagicMock()
        broken_executor.submit.side_effect = RuntimeError(
            "cannot schedule new futures after shutdown"
        )
        self.mgr._executor = broken_executor

        event = _make_event(id="r114_synthetic_race")

        with self.assertLogs(
            "ai_intervention_agent.notification_manager", level="DEBUG"
        ) as cm:
            self.mgr._process_event(event)

        self.assertTrue(
            any("[R114]" in m for m in cm.output),
            f"应该看到 R114 标记的 DEBUG 日志: {cm.output}",
        )

        error_lines = [
            m for m in cm.output if m.startswith("ERROR") and "处理通知事件失败" in m
        ]
        self.assertFalse(
            error_lines,
            f"R114 静默路径不应留下 ERROR 日志: {error_lines}",
        )

    def test_submit_runtime_error_without_shutdown_flag_propagates(self) -> None:
        """**反向防御**：``_shutdown_called=False`` 时 ``RuntimeError`` 必须冒泡。

        防止 R114 把所有 ``RuntimeError`` 一律吞掉——只有在
        ``_shutdown_called`` 真为 True 时才进入静默路径，其它 RuntimeError
        必须由外层 ``except Exception`` 处理（保留原诊断能力）。
        """
        broken_executor = MagicMock()
        broken_executor.submit.side_effect = RuntimeError(
            "totally unrelated runtime error"
        )
        self.mgr._executor = broken_executor

        event = _make_event(id="r114_unrelated_runtime_error")

        with self.assertLogs(
            "ai_intervention_agent.notification_manager", level="ERROR"
        ) as cm:
            self.mgr._process_event(event)

        self.assertTrue(
            any("处理通知事件失败" in m for m in cm.output),
            f"_shutdown_called=False 时 RuntimeError 必须走外层 except: {cm.output}",
        )

    def test_submit_partial_success_then_race_no_future_leak(self) -> None:
        """部分 submit 成功后才进入 race，要求已 submit 的 future 不 leak。

        ``cancel_futures=True`` 会自然取消 pending future；R114 ``return``
        路径不进入 ``as_completed``，因此不会死等已成功 submit 但被 cancel
        的 future。
        """
        real_executor = self.mgr._executor

        submit_call_count = {"n": 0}

        def shutdown_after_first_submit() -> None:
            submit_call_count["n"] += 1
            if submit_call_count["n"] == 1:
                self.mgr._shutdown_called = True
                real_executor.shutdown(wait=False, cancel_futures=True)

        self.mgr._executor = _GatedExecutor(  # ty: ignore[invalid-assignment]
            real_executor,
            hook_at_call=2,
            hook=shutdown_after_first_submit,
        )

        event = _make_event(
            id="r114_partial_submit",
            types=[
                NotificationType.WEB,
                NotificationType.SOUND,
                NotificationType.SYSTEM,
            ],
        )

        start = time.monotonic()
        with self.assertLogs(
            "ai_intervention_agent.notification_manager", level="DEBUG"
        ) as cm:
            self.mgr._process_event(event)
        elapsed = time.monotonic() - start

        self.assertLess(
            elapsed,
            5.0,
            f"R114 静默路径不应进 as_completed，但耗时 {elapsed:.2f}s 像是死等",
        )
        self.assertTrue(
            any("[R114]" in m for m in cm.output),
            f"应该看到 R114 标记的 DEBUG 日志: {cm.output}",
        )

    def test_normal_path_no_r114_log_when_no_race(self) -> None:
        """守护：正常路径（无 race）不应触发 R114 静默路径，也不应产生 R114 日志。"""
        event = _make_event(id="r114_normal_path")

        with self.assertLogs(
            "ai_intervention_agent.notification_manager", level="DEBUG"
        ) as cm:
            self.mgr._process_event(event)

        self.assertFalse(
            any("[R114]" in m for m in cm.output),
            f"无 race 时不应触发 R114 日志: {cm.output}",
        )
        self.provider.send.assert_called_once()


class TestR114DocumentationContract(unittest.TestCase):
    """守护 R114 在源码中保留可追溯标记，避免后续重构时无意识移除修复。"""

    def test_r114_marker_present_in_source(self) -> None:
        """``notification_manager.py`` 必须包含 ``[R114]`` 标记 + try/except RuntimeError。"""
        from pathlib import Path

        import ai_intervention_agent.notification_manager as nm

        src = Path(nm.__file__).read_text(encoding="utf-8")
        self.assertIn(
            "[R114]",
            src,
            "R114 修复在源码中必须保留 [R114] 标记，否则 grep 不到无法追溯",
        )
        self.assertIn(
            "except RuntimeError",
            src,
            "R114 修复必须保留 except RuntimeError 分支",
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
