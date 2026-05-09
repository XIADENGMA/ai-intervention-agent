"""R117 · 静默失败的 debug 级可观测性兜底回归测试。

设计目标
========

R117 修复了项目中**最高影响**的两处 ``except Exception: pass`` 静默失败：

1. ``BarkNotificationProvider.close()``（``notification_providers.py``）—
   ``httpx.Client.close()`` 是 shutdown / atexit 路径上**唯一**承担
   连接池清理的调用，静默失败意味着 TCP socket / keep-alive 连接 /
   HTTP/2 stream 状态泄漏却没有任何信号。
2. ``NotificationManager._mark_event_finalized()``（``notification_manager.py``）
   — ``self._stats["events_succeeded" / "events_failed"]`` 与
   ``_finalized_event_ids`` LRU 集合是 ``get_stats()`` 计算
   ``delivery_success_rate`` 的唯一来源，静默失败导致统计数字永久偏移。

修复策略：保持 try/except 不让异常扩散打断调用方（resp. shutdown chain
和 ``_process_event`` flow），但把 exception 写到 ``debug`` 级日志——正常
运行时不噪音，需要排查时打开 debug 立刻看到 root cause。

本测试守护「debug 日志在异常路径上确实被发出」这条 invariant，避免未来
有人 refactor 时把 ``logger.debug`` 又改回 ``pass``（重新失明）。

测试也包含**反向断言**：正常路径下不应该出现这条 debug 日志，避免 R117
误把每一次 close / finalize 都打成 debug 噪音。
"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from ai_intervention_agent.notification_manager import (
    NotificationConfig,
    NotificationManager,
)
from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationTrigger,
    NotificationType,
)
from ai_intervention_agent.notification_providers import BarkNotificationProvider


def _make_minimal_config(**overrides) -> NotificationConfig:
    """返回最小 NotificationConfig，参数全部走默认值。

    单独抽出 helper 是因为 NotificationConfig 字段超过 30 个，每个测试
    都从零写一遍既冗余又脆弱（一加字段全部断）。
    """
    return NotificationConfig(**overrides)


class TestBarkProviderCloseDebugLoggingR117(unittest.TestCase):
    """守护 ``BarkNotificationProvider.close()`` 在 ``httpx.Client.close()``
    抛异常时 emit ``debug`` 级日志，且不让异常扩散。
    """

    def _make_provider(self) -> BarkNotificationProvider:
        """返回一个 BarkNotificationProvider，session 字段会被测试单独 mock。"""
        config = _make_minimal_config(bark_enabled=True)
        provider = BarkNotificationProvider(config)
        return provider

    def test_close_silences_session_close_exception_propagation(self) -> None:
        """``httpx.Client.close()`` 抛异常时，``close()`` 不能扩散到调用方。

        注意 ``close()`` 在 shutdown 链上被多个 provider 串行调用——任一
        ``close()`` raise 就会让后面所有 provider 没机会清理资源（见
        ``notification_manager.shutdown()`` 的循环逻辑）。
        """
        provider = self._make_provider()
        provider.session = MagicMock()
        provider.session.close = MagicMock(side_effect=RuntimeError("simulated"))

        try:
            provider.close()
        except Exception as exc:
            self.fail(
                f"R117 invariant 破坏：close() 把 httpx 异常扩散到了上层 "
                f"shutdown chain（{type(exc).__name__}: {exc}）—— "
                "回到 R117 之前会静默 pass，扩散更糟糕"
            )

    def test_close_emits_debug_log_with_r117_marker(self) -> None:
        """``close()`` 异常路径必须 emit 含 ``[R117]`` 标记的 debug 日志。

        正向断言：未来 refactor 把 ``logger.debug`` 改回 ``pass`` 时，
        本断言立刻 fail，避免回到「失明」状态。
        """
        provider = self._make_provider()
        provider.session = MagicMock()
        provider.session.close = MagicMock(side_effect=ConnectionError("pool busted"))

        with self.assertLogs(
            "ai_intervention_agent.notification_providers", level="DEBUG"
        ) as cm:
            provider.close()

        joined = "\n".join(cm.output)
        self.assertIn("[R117]", joined, f"R117 标记缺失: {joined!r}")
        self.assertIn(
            "BarkNotificationProvider.close()",
            joined,
            f"日志应该指明 close 函数: {joined!r}",
        )
        self.assertIn(
            "ConnectionError",
            joined,
            f"日志应该包含原始异常类型: {joined!r}",
        )

    def test_close_log_sanitizes_sensitive_token_in_exception_message(self) -> None:
        """异常消息里若出现 APNs device token / 长 hex，必须先经过
        ``_sanitize_error_text`` 才进 debug 日志，避免泄漏到日志聚合系统。
        """
        provider = self._make_provider()
        provider.session = MagicMock()

        # 这串 hex 必须 ≥ 32 字符以触发 ``_LONG_HEX_RE``
        leaky_token = "a" * 40
        provider.session.close = MagicMock(
            side_effect=RuntimeError(f"closed with token={leaky_token}")
        )

        with self.assertLogs(
            "ai_intervention_agent.notification_providers", level="DEBUG"
        ) as cm:
            provider.close()

        joined = "\n".join(cm.output)
        self.assertNotIn(
            leaky_token,
            joined,
            f"R117 invariant 破坏：原始 token 泄漏到 debug 日志: {joined!r}",
        )
        self.assertIn(
            "<redacted_hex>",
            joined,
            f"_sanitize_error_text 未被调用 / 已漂移: {joined!r}",
        )

    def test_close_normal_path_does_not_emit_r117_log(self) -> None:
        """``httpx.Client.close()`` 正常返回时，**不应该**出现 R117 debug 日志。

        反向断言：避免 R117 误把每一次 close 都打成 debug 噪音，让真正的
        异常 close 反而被淹没。
        """
        provider = self._make_provider()
        provider.session = MagicMock()
        # 默认 MagicMock.close 返回 None 不抛异常 — 正常路径

        # 即使 capture 了 DEBUG，正常路径也不该有 [R117] 行——但
        # ``assertNoLogs`` 只在 ≥3.10 可用，这里手动 capture 后断言
        # 没有 [R117] marker 出现。
        log_handler_records: list[logging.LogRecord] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_handler_records.append(record)

        logger_obj = logging.getLogger("ai_intervention_agent.notification_providers")
        handler = _CaptureHandler(level=logging.DEBUG)
        logger_obj.addHandler(handler)
        logger_obj.setLevel(logging.DEBUG)
        try:
            provider.close()
        finally:
            logger_obj.removeHandler(handler)

        r117_records = [r for r in log_handler_records if "[R117]" in r.getMessage()]
        self.assertEqual(
            r117_records,
            [],
            f"R117 invariant 破坏：正常 close 路径产生了 R117 debug 噪音: "
            f"{[r.getMessage() for r in r117_records]!r}",
        )


class TestMarkEventFinalizedDebugLoggingR117(unittest.TestCase):
    """守护 ``NotificationManager._mark_event_finalized()`` 在 stats 更新
    抛异常时 emit ``debug`` 级日志，且不让异常扩散到 ``_process_event``。
    """

    def _make_manager(self) -> NotificationManager:
        """返回一个 NotificationManager；测试只用 ``_mark_event_finalized``，
        所以不需要 register provider / 注册 callback。"""
        config = _make_minimal_config()
        # NotificationManager 单例化，需要绕过 ``__new__`` 的缓存
        # 直接复用全局实例（不调 shutdown，测试本身不影响别的 case，因为
        # 我们只调 ``_mark_event_finalized`` 不入队任何事件）。
        from ai_intervention_agent.notification_manager import notification_manager

        notification_manager.config = config
        # 重置 finalized 集合让测试可重复
        with notification_manager._stats_lock:
            notification_manager._finalized_event_ids.clear()
            notification_manager._stats["events_succeeded"] = 0
            notification_manager._stats["events_failed"] = 0
        return notification_manager

    def _make_event(self, event_id: str = "test-r117") -> NotificationEvent:
        """构造最小 NotificationEvent。``trigger`` 是 pydantic 必填字段。"""
        return NotificationEvent(
            id=event_id,
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.WEB],
        )

    def test_mark_event_finalized_silences_lock_acquire_exception(self) -> None:
        """``_stats_lock`` 在 acquire 时抛异常的极端情况下，
        ``_mark_event_finalized`` 不能扩散到 ``_process_event``。

        模拟方式：mock ``_stats_lock`` 让 ``__enter__`` 抛 RuntimeError
        （比如某种死锁检测器在 lock acquire 时主动抛异常）。
        """
        manager = self._make_manager()
        event = self._make_event("test-lock-fail")

        # 把 _stats_lock 替换成一个 __enter__ raise 的 mock
        broken_lock = MagicMock()
        broken_lock.__enter__ = MagicMock(side_effect=RuntimeError("lock broken"))
        broken_lock.__exit__ = MagicMock(return_value=False)

        try:
            with patch.object(manager, "_stats_lock", broken_lock):
                manager._mark_event_finalized(event, succeeded=True)
        except Exception as exc:
            self.fail(
                f"R117 invariant 破坏：_mark_event_finalized 把 lock 异常 "
                f"扩散到 _process_event flow（{type(exc).__name__}: {exc}）"
            )

    def test_mark_event_finalized_emits_debug_log_with_r117_marker(self) -> None:
        """异常路径必须 emit 含 ``[R117]`` 标记的 debug 日志，且日志包含
        ``event_id`` / ``succeeded`` / 异常类型，便于排查 stats 偏移。
        """
        manager = self._make_manager()
        event = self._make_event("test-debug-log")

        broken_lock = MagicMock()
        broken_lock.__enter__ = MagicMock(side_effect=ValueError("simulated"))
        broken_lock.__exit__ = MagicMock(return_value=False)

        with self.assertLogs(
            "ai_intervention_agent.notification_manager", level="DEBUG"
        ) as cm:
            with patch.object(manager, "_stats_lock", broken_lock):
                manager._mark_event_finalized(event, succeeded=False)

        joined = "\n".join(cm.output)
        self.assertIn("[R117]", joined, f"R117 标记缺失: {joined!r}")
        self.assertIn(
            "_mark_event_finalized",
            joined,
            f"日志应该指明 _mark_event_finalized 函数: {joined!r}",
        )
        self.assertIn("test-debug-log", joined, f"日志应该包含 event_id: {joined!r}")
        self.assertIn(
            "succeeded=False",
            joined,
            f"日志应该包含 succeeded 标志: {joined!r}",
        )
        self.assertIn("ValueError", joined, f"日志应该包含异常类型: {joined!r}")

    def test_mark_event_finalized_silences_dict_iteration_race(self) -> None:
        """模拟 ``next(iter(self._finalized_event_ids))`` 在 LRU 容量淘汰时
        遇到 ``RuntimeError: dictionary changed size during iteration`` 这种
        真实并发故障——R117 要保证 debug 路径覆盖到这条具体异常。
        """
        manager = self._make_manager()
        event = self._make_event("test-dict-mutation")

        # 把 _finalized_event_ids 替换成一个 ``__contains__`` 抛异常的 dict-like
        # mock，这样在 try 块的第一行 ``if event.id in self._finalized_event_ids``
        # 就会触发，覆盖最容易踩的并发路径
        class _ExplodingDict:
            def __contains__(self, _):
                raise RuntimeError("dictionary changed size during iteration")

        with patch.object(manager, "_finalized_event_ids", _ExplodingDict()):
            with self.assertLogs(
                "ai_intervention_agent.notification_manager", level="DEBUG"
            ) as cm:
                manager._mark_event_finalized(event, succeeded=True)

        joined = "\n".join(cm.output)
        self.assertIn("[R117]", joined)
        self.assertIn("RuntimeError", joined)

    def test_mark_event_finalized_normal_path_does_not_emit_r117_log(self) -> None:
        """正常路径不应该出现 R117 debug 噪音（避免淹没真正的异常 close 日志）。"""
        manager = self._make_manager()
        event = self._make_event("test-normal-path")

        log_handler_records: list[logging.LogRecord] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_handler_records.append(record)

        logger_obj = logging.getLogger("ai_intervention_agent.notification_manager")
        handler = _CaptureHandler(level=logging.DEBUG)
        logger_obj.addHandler(handler)
        logger_obj.setLevel(logging.DEBUG)
        try:
            manager._mark_event_finalized(event, succeeded=True)
        finally:
            logger_obj.removeHandler(handler)

        r117_records = [r for r in log_handler_records if "[R117]" in r.getMessage()]
        self.assertEqual(
            r117_records,
            [],
            f"R117 invariant 破坏：正常路径产生了 R117 debug 噪音: "
            f"{[r.getMessage() for r in r117_records]!r}",
        )

    def test_mark_event_finalized_real_race_no_silent_skip(self) -> None:
        """**端到端验证**：在真实 OrderedDict 容量淘汰边界（_finalized_max_size
        刚刚被超过、while 循环正在 pop 的瞬间），多线程 ``_mark_event_finalized``
        不应该抛异常或产生 stats 偏移；如果抛了，本测试会经由 R117 debug
        日志（而不是静默 pass）观察到。

        本测试不刻意 mock 出 race，而是顺序模拟 LRU 边界 pop 路径，确保
        ``next(iter(...))`` + ``del`` 组合在 OrderedDict 上语义符合预期。
        """
        manager = self._make_manager()
        # 把 LRU 上限调小，让我们能精准触发 pop
        original_max = manager._finalized_max_size
        manager._finalized_max_size = 3
        try:
            for i in range(5):
                event = self._make_event(f"event-{i}")
                manager._mark_event_finalized(event, succeeded=(i % 2 == 0))

            # 断言 LRU 边界正确：只剩 3 个，最早的 2 个已淘汰
            with manager._stats_lock:
                self.assertEqual(
                    len(manager._finalized_event_ids),
                    3,
                    "LRU 边界破坏：_finalized_event_ids 应该被淘汰到 max_size",
                )
                # stats 应该精确累加（不被 R117 try/except 静默吞掉）
                self.assertEqual(
                    manager._stats["events_succeeded"],
                    3,
                    "stats events_succeeded 偏移：应该是 3 (i=0,2,4)",
                )
                self.assertEqual(
                    manager._stats["events_failed"],
                    2,
                    "stats events_failed 偏移：应该是 2 (i=1,3)",
                )
        finally:
            manager._finalized_max_size = original_max


class TestR117DocumentationContract(unittest.TestCase):
    """守护源码 ``[R117]`` 标记不被未来 refactor 抹掉。

    与 R114 / R116 同 spirit：grep ``R117`` 必须能定位到修复点，否则
    code review 时无法快速追溯「为什么这里用 debug 而不是 pass / warn」。
    """

    def test_r117_marker_present_in_notification_providers(self) -> None:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "notification_providers.py"
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("R117", content, f"{path} 必须保留 R117 标记")
        self.assertIn(
            "logger.debug",
            content,
            "BarkNotificationProvider.close() 必须用 logger.debug，"
            "不能回到 ``except Exception: pass``",
        )

    def test_r117_marker_present_in_notification_manager(self) -> None:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "notification_manager.py"
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn(
            "R117",
            content,
            f"{path} 必须保留 R117 标记（_mark_event_finalized 修复处）",
        )


if __name__ == "__main__":
    unittest.main()
