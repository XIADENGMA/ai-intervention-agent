"""R118 · ``service_manager`` 静默失败的 debug 级可观测性兜底回归测试。

设计目标
========

R118 是 R117 silent-failure 系列的延续，把审计范围从 ``notification_*``
扩到 ``service_manager.py``。原项目对 ``except Exception: pass`` 的态度
不一致——R107-R110 系列已经把"silent skip"当作高优先级 anti-pattern
处理（fail-loud 政策），R114 / R117 把同 family 的 race / cleanup 静默
失败逐一改成 debug 级可观测兜底。

R118 修了 ``service_manager.py`` 里 3 处真正风险的 ``except Exception:
pass``：

1. ``_invalidate_runtime_caches_on_config_change()`` 第一段
   （``_config_cache_lock`` 失败）—— 静默会让 ``get_config()`` 返回
   stale 配置，热重载等于失效。
2. 同函数第二段（``_http_client_lock`` + httpx client close 失败）——
   静默会让新请求继续走老 client（老 base_url / 老 timeout / 老
   headers），且连接池资源累积泄漏。
3. ``cleanup_http_clients()`` 同步 client close 失败——shutdown 路径
   上**唯一**清理同步连接池的入口，静默会留 FD / TIME_WAIT。

第 4 处 ``service_manager.py:505-508``（``_cleanup_process_resources``
按 stdin/stdout/stderr 逐 handle close）**故意保留** 内部 ``pass``——
外层已有 ``except Exception as e: logger.error``，内部循环静默是为了
"任一 handle 失败不影响其他 handle 清理"，符合"只在没有上层日志兜底
时才加 debug" 的 R117 设计原则。

本测试守护「debug 日志在异常路径上确实被发出」 + 「正常路径不噪音」
两条 invariant，避免未来 refactor 把 ``logger.debug`` 又改回 ``pass``。
"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from ai_intervention_agent import service_manager


class TestInvalidateConfigCacheSegmentR118(unittest.TestCase):
    """守护 ``_invalidate_runtime_caches_on_config_change`` 第一段
    （``_config_cache_lock``）的 R118 debug 日志。
    """

    def test_segment_1_silences_config_cache_lock_exception(self) -> None:
        """``_config_cache_lock`` 抛异常时，函数不能扩散到 ``ConfigManager``
        回调注册中心（其他回调还要继续跑）。
        """
        broken_lock = MagicMock()
        broken_lock.__enter__ = MagicMock(side_effect=RuntimeError("lock busted"))
        broken_lock.__exit__ = MagicMock(return_value=False)

        try:
            with patch.object(service_manager, "_config_cache_lock", broken_lock):
                service_manager._invalidate_runtime_caches_on_config_change()
        except Exception as exc:
            self.fail(
                f"R118 invariant 破坏：_invalidate_runtime_caches_on_config_change "
                f"把 lock 异常扩散到了 ConfigManager 回调注册中心 "
                f"({type(exc).__name__}: {exc}) —— 会让其他 callback 跟着断"
            )

    def test_segment_1_emits_r118_debug_log(self) -> None:
        """异常路径必须 emit 含 ``[R118]`` 标记的 debug 日志，且日志包含
        段名 + 异常类型 + "热重载可能不生效" 用户可见症状提示。
        """
        broken_lock = MagicMock()
        broken_lock.__enter__ = MagicMock(side_effect=ValueError("simulated"))
        broken_lock.__exit__ = MagicMock(return_value=False)

        with self.assertLogs(
            "ai_intervention_agent.service_manager", level="DEBUG"
        ) as cm:
            with patch.object(service_manager, "_config_cache_lock", broken_lock):
                service_manager._invalidate_runtime_caches_on_config_change()

        joined = "\n".join(cm.output)
        self.assertIn("[R118]", joined, f"R118 标记缺失: {joined!r}")
        self.assertIn(
            "_config_cache_lock 段失败",
            joined,
            f"日志应该指明哪一段失败: {joined!r}",
        )
        self.assertIn("ValueError", joined, f"日志应该包含异常类型: {joined!r}")


class TestInvalidateHttpClientSegmentR118(unittest.TestCase):
    """守护 ``_invalidate_runtime_caches_on_config_change`` 第二段
    （``_http_client_lock``）的 R118 debug 日志。
    """

    def test_segment_2_silences_http_client_lock_exception(self) -> None:
        """``_http_client_lock`` 抛异常时，函数不能扩散给 ``ConfigManager``
        回调注册中心。
        """
        broken_lock = MagicMock()
        broken_lock.__enter__ = MagicMock(side_effect=RuntimeError("lock busted"))
        broken_lock.__exit__ = MagicMock(return_value=False)

        try:
            with patch.object(service_manager, "_http_client_lock", broken_lock):
                service_manager._invalidate_runtime_caches_on_config_change()
        except Exception as exc:
            self.fail(
                f"R118 invariant 破坏：_invalidate_runtime_caches_on_config_change "
                f"把 http_client_lock 异常扩散到了上层 "
                f"({type(exc).__name__}: {exc})"
            )

    def test_segment_2_emits_r118_debug_log_with_resource_leak_warning(self) -> None:
        """异常路径必须 emit 含 ``[R118]`` 标记 + 用户可见症状提示
        ("新请求可能仍走老 client") 的 debug 日志。
        """
        broken_lock = MagicMock()
        broken_lock.__enter__ = MagicMock(side_effect=OSError("fd exhausted"))
        broken_lock.__exit__ = MagicMock(return_value=False)

        with self.assertLogs(
            "ai_intervention_agent.service_manager", level="DEBUG"
        ) as cm:
            with patch.object(service_manager, "_http_client_lock", broken_lock):
                service_manager._invalidate_runtime_caches_on_config_change()

        joined = "\n".join(cm.output)
        self.assertIn("[R118]", joined, f"R118 标记缺失: {joined!r}")
        self.assertIn(
            "_http_client_lock 段失败",
            joined,
            f"日志应该指明哪一段失败: {joined!r}",
        )
        self.assertIn(
            "新请求可能仍走老 client",
            joined,
            f"日志应该包含用户可见症状提示，便于反向排查: {joined!r}",
        )
        self.assertIn("OSError", joined, f"日志应该包含异常类型: {joined!r}")


class TestCleanupHttpClientsSilentFailureR118(unittest.TestCase):
    """守护 ``cleanup_http_clients()`` 在 ``_sync_client.close()`` 抛异常时
    emit ``debug`` 级日志，且不让异常扩散打断 async client 清理。
    """

    def setUp(self) -> None:
        # 备份全局 client 引用，测试结束后恢复，避免污染其他用例
        self._original_sync = service_manager._sync_client
        self._original_async = service_manager._async_client

    def tearDown(self) -> None:
        service_manager._sync_client = self._original_sync
        service_manager._async_client = self._original_async

    def test_close_exception_does_not_break_async_cleanup(self) -> None:
        """``_sync_client.close()`` 抛异常时，``cleanup_http_clients()`` 不能
        扩散——后面 ``_async_client`` 清理还要继续跑。
        """
        sync_mock = MagicMock()
        sync_mock.is_closed = False
        sync_mock.close = MagicMock(side_effect=RuntimeError("transport broken"))
        async_mock = MagicMock()
        async_mock.is_closed = False
        async_mock.aclose = MagicMock()

        service_manager._sync_client = sync_mock
        service_manager._async_client = async_mock

        try:
            service_manager.cleanup_http_clients()
        except Exception as exc:
            self.fail(
                f"R118 invariant 破坏：cleanup_http_clients 把 _sync_client "
                f"异常扩散到 server.cleanup_services 上游 "
                f"({type(exc).__name__}: {exc})"
            )

        # async client 应该已经被设为 None（chain 没断）
        self.assertIsNone(
            service_manager._async_client,
            "R118 invariant 破坏：sync close 失败后 async cleanup chain 也断了",
        )

    def test_close_exception_emits_r118_debug_log(self) -> None:
        """``_sync_client.close()`` 异常必须 emit 含 ``[R118]`` 标记 +
        FD 泄漏症状提示的 debug 日志。
        """
        sync_mock = MagicMock()
        sync_mock.is_closed = False
        sync_mock.close = MagicMock(side_effect=ConnectionError("pool corrupted"))
        service_manager._sync_client = sync_mock

        with self.assertLogs(
            "ai_intervention_agent.service_manager", level="DEBUG"
        ) as cm:
            service_manager.cleanup_http_clients()

        joined = "\n".join(cm.output)
        self.assertIn("[R118]", joined, f"R118 标记缺失: {joined!r}")
        self.assertIn(
            "cleanup_http_clients",
            joined,
            f"日志应该指明 cleanup_http_clients 函数: {joined!r}",
        )
        self.assertIn(
            "FD may leak",
            joined,
            f"日志应该包含 FD 泄漏症状提示: {joined!r}",
        )
        self.assertIn(
            "ConnectionError",
            joined,
            f"日志应该包含异常类型: {joined!r}",
        )

    def test_normal_close_does_not_emit_r118_log(self) -> None:
        """正常 close 路径不应该出现 R118 debug 噪音。

        反向断言：避免 R118 误把每次 cleanup 都打成 debug 噪音，让真正的
        close 异常反而被淹没。
        """
        sync_mock = MagicMock()
        sync_mock.is_closed = False
        sync_mock.close = MagicMock()  # 默认不抛异常
        service_manager._sync_client = sync_mock

        log_handler_records: list[logging.LogRecord] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_handler_records.append(record)

        logger_obj = logging.getLogger("ai_intervention_agent.service_manager")
        handler = _CaptureHandler(level=logging.DEBUG)
        logger_obj.addHandler(handler)
        logger_obj.setLevel(logging.DEBUG)
        try:
            service_manager.cleanup_http_clients()
        finally:
            logger_obj.removeHandler(handler)

        r118_records = [r for r in log_handler_records if "[R118]" in r.getMessage()]
        self.assertEqual(
            r118_records,
            [],
            f"R118 invariant 破坏：正常 close 路径产生了 R118 debug 噪音: "
            f"{[r.getMessage() for r in r118_records]!r}",
        )


class TestR118DocumentationContract(unittest.TestCase):
    """守护源码 ``[R118]`` 标记不被未来 refactor 抹掉。

    与 R114 / R116 / R117 同 spirit：grep ``R118`` 必须能定位到修复点，
    否则 code review 时无法快速追溯「为什么这里用 debug 而不是 pass」。
    """

    def test_r118_marker_present_in_service_manager(self) -> None:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "service_manager.py"
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("R118", content, f"{path} 必须保留 R118 标记")

    def test_r118_logger_debug_calls_present(self) -> None:
        """三个修复点必须都有 logger.debug 调用，不能回到 ``pass``。"""
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "service_manager.py"
        )
        content = path.read_text(encoding="utf-8")

        # 三个修复点的 debug log 标识字符串
        markers = [
            "_config_cache_lock 段失败",
            "_http_client_lock 段失败",
            "FD may leak",
        ]
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertIn(
                    marker,
                    content,
                    f"R118 修复点 marker 缺失: {marker!r}（"
                    "可能被回退到 except Exception: pass）",
                )


if __name__ == "__main__":
    unittest.main()
