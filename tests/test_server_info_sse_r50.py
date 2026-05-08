"""R50 SSE 子块 + config_changed debounce 回归契约。

R50 是 R47/R48 的"打磨"周期：

A. ``aiia://server/info`` 资源新增 ``sse_bus`` 子块，让 MCP client UI
   不需要单独打 ``/api/system/sse-stats`` 也能在自检页里直接看到 SSE
   总线的健康度（emit_total / gap_warnings_emitted / 等等）。
B. ``_emit_config_changed_to_sse_bus`` 加 leading-edge debounce
   (250ms)，吸收 mtime 风暴，避免一次 ``Cmd+S`` 让 toast 闪 3 次。

设计原则：
- A 用 ``httpx`` mock 验证 best-effort HTTP 调用契约（实际不起 web_ui）；
- B 用 ``monotonic`` 时间逻辑直接 reset/inspect ``_last_emit_monotonic``
  全局状态，确保 debounce 边界精确。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ai_intervention_agent.server as server
import ai_intervention_agent.web_ui_config_sync as web_ui_config_sync

# ============================================================================
# A. server_info_resource 的 sse_bus 子块
# ============================================================================


class TestServerInfoSseBusBlockShape(unittest.TestCase):
    """``aiia://server/info`` 必须在新位置暴露 ``sse_bus`` 子块。"""

    def test_sse_bus_key_present(self) -> None:
        info = server.server_info_resource()
        self.assertIn(
            "sse_bus",
            info,
            "server_info_resource 应当暴露 sse_bus 子块（R50-A）",
        )

    def test_sse_bus_block_is_dict(self) -> None:
        info = server.server_info_resource()
        block = info["sse_bus"]
        self.assertIsInstance(block, dict)


class TestServerInfoSseBusWebUINotRunning(unittest.TestCase):
    """web_ui 不在跑时 ``sse_bus`` 子块返回 ``available=False`` + 原因。"""

    def test_unavailable_when_web_ui_not_running(self) -> None:
        # 强制 web_ui_info["running"]=False：让上一段（web_ui block）
        # 探测端口失败。我们 mock is_web_service_running 返回 False。
        with patch(
            "ai_intervention_agent.server.is_web_service_running", return_value=False
        ):
            info = server.server_info_resource()
        block = cast(dict[str, Any], info["sse_bus"])
        self.assertIn(
            "available",
            block,
            "web_ui 不在跑时，sse_bus 块应当显式 available 字段为 False",
        )
        self.assertFalse(block.get("available"))
        self.assertIn("reason", block)


class TestServerInfoSseBusWebUIRunningOK(unittest.TestCase):
    """web_ui 在跑且 ``/api/system/sse-stats`` 返回成功 → 字段透传。"""

    def setUp(self) -> None:
        # R54-A：清 cache，避免上一个测试用例的成功结果污染本用例。
        with server._sse_stats_cache_lock:
            server._sse_stats_cache.clear()
            server._sse_stats_cache_ts = 0.0

    def test_counters_reflected_when_endpoint_returns_success(self) -> None:
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "success": True,
            "emit_total": 42,
            "latest_event_id": 42,
            "gap_warnings_emitted": 1,
            "backpressure_discards": 0,
            "subscriber_count": 3,
            "history_size": 42,
        }
        with (
            patch(
                "ai_intervention_agent.server.is_web_service_running", return_value=True
            ),
            patch("httpx.get", return_value=fake_resp),
        ):
            info = server.server_info_resource()
        block = cast(dict[str, Any], info["sse_bus"])
        self.assertEqual(block.get("emit_total"), 42)
        self.assertEqual(block.get("gap_warnings_emitted"), 1)
        self.assertEqual(block.get("subscriber_count"), 3)
        # success 字段不应被复制到 sse_bus 子块（它是 transport-level wrapper，
        # 与计数器语义无关）
        self.assertNotIn("success", block)


class TestServerInfoSseBusWebUIRunningFailureModes(unittest.TestCase):
    """各种异常路径都必须降级到 ``error`` 字段，绝不抛异常。"""

    def setUp(self) -> None:
        # R54-A：每个用例前清 cache，否则前一个用例（possibly success path）写入
        # 的 cache 会在 TTL 内被本用例命中，本用例的失败 mock 永远跑不到。
        with server._sse_stats_cache_lock:
            server._sse_stats_cache.clear()
            server._sse_stats_cache_ts = 0.0

    def test_http_500_falls_back_to_error(self) -> None:
        fake_resp = MagicMock()
        fake_resp.status_code = 500
        with (
            patch(
                "ai_intervention_agent.server.is_web_service_running", return_value=True
            ),
            patch("httpx.get", return_value=fake_resp),
        ):
            info = server.server_info_resource()
        block = cast(dict[str, Any], info["sse_bus"])
        self.assertIn("error", block)
        self.assertIn("500", str(block["error"]))

    def test_httpx_exception_falls_back_to_error(self) -> None:
        with (
            patch(
                "ai_intervention_agent.server.is_web_service_running", return_value=True
            ),
            patch("httpx.get", side_effect=RuntimeError("simulated network error")),
        ):
            info = server.server_info_resource()
        block = cast(dict[str, Any], info["sse_bus"])
        self.assertIn("error", block)
        self.assertIn("RuntimeError", str(block["error"]))

    def test_response_without_success_field_falls_back_to_error(self) -> None:
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"foo": "bar"}  # no "success"
        with (
            patch(
                "ai_intervention_agent.server.is_web_service_running", return_value=True
            ),
            patch("httpx.get", return_value=fake_resp),
        ):
            info = server.server_info_resource()
        block = cast(dict[str, Any], info["sse_bus"])
        self.assertIn("error", block)


# ============================================================================
# B. _emit_config_changed_to_sse_bus 的 debounce
# ============================================================================


class TestEmitConfigChangedDebounce(unittest.TestCase):
    """``_emit_config_changed_to_sse_bus`` 必须 250 ms leading-edge debounce。"""

    def setUp(self) -> None:
        # 重置 debounce state：每个用例从一个干净的 monotonic baseline 起
        web_ui_config_sync._last_emit_monotonic = 0.0
        # 同时挽住 ``time.monotonic`` 让它返回我们注入的值
        self._mono_value = 1000.0  # 任意基线

    def _mono(self) -> float:
        return self._mono_value

    def test_first_call_passes_through(self) -> None:
        with (
            patch("time.monotonic", side_effect=self._mono),
            patch("ai_intervention_agent.web_ui_routes.task._sse_bus") as fake_bus,
        ):
            web_ui_config_sync._emit_config_changed_to_sse_bus()
        fake_bus.emit.assert_called_once()

    def test_second_call_within_window_is_suppressed(self) -> None:
        with (
            patch("time.monotonic", side_effect=self._mono),
            patch("ai_intervention_agent.web_ui_routes.task._sse_bus") as fake_bus,
        ):
            web_ui_config_sync._emit_config_changed_to_sse_bus()  # t=1000.0
            self._mono_value += 0.1  # 100ms 后
            web_ui_config_sync._emit_config_changed_to_sse_bus()  # t=1000.1
            self._mono_value += 0.1  # 又 100ms 后
            web_ui_config_sync._emit_config_changed_to_sse_bus()  # t=1000.2
        # 250 ms 内的 3 次调用，只有第一次能 emit
        self.assertEqual(fake_bus.emit.call_count, 1)

    def test_call_after_window_passes_through(self) -> None:
        with (
            patch("time.monotonic", side_effect=self._mono),
            patch("ai_intervention_agent.web_ui_routes.task._sse_bus") as fake_bus,
        ):
            web_ui_config_sync._emit_config_changed_to_sse_bus()  # t=1000.0
            self._mono_value += 0.3  # 300ms 后（> 250ms 窗口）
            web_ui_config_sync._emit_config_changed_to_sse_bus()  # t=1000.3
        self.assertEqual(fake_bus.emit.call_count, 2)

    def test_burst_of_10_within_window_emits_only_once(self) -> None:
        """模拟 mtime 风暴：50 ms 内 10 次 callback。"""
        with (
            patch("time.monotonic", side_effect=self._mono),
            patch("ai_intervention_agent.web_ui_routes.task._sse_bus") as fake_bus,
        ):
            for _ in range(10):
                self._mono_value += 0.005  # 每 5ms 一次
                web_ui_config_sync._emit_config_changed_to_sse_bus()
        # 50ms 总耗时 << 250ms 窗口，所以只 emit 一次
        self.assertEqual(fake_bus.emit.call_count, 1)

    def test_debounce_window_constant_is_at_least_100ms(self) -> None:
        """debounce 窗口太短（< 100ms）会让 mtime 风暴不被压实。"""
        self.assertGreaterEqual(
            web_ui_config_sync._CONFIG_CHANGED_EMIT_DEBOUNCE_S,
            0.1,
            "debounce 窗口应当 ≥ 100ms 以应对常见 ``Cmd+S`` truncate-then-fsync 双 mtime 跳变",
        )

    def test_debounce_window_constant_is_under_2s(self) -> None:
        """debounce 窗口太长（> 2s）会让"用户连续两次保存"被合并成一次。"""
        self.assertLessEqual(
            web_ui_config_sync._CONFIG_CHANGED_EMIT_DEBOUNCE_S,
            2.0,
            "debounce 窗口太长会让用户感到 UI 反应迟缓；保留 ≤ 2s",
        )


class TestDebounceLockExists(unittest.TestCase):
    """``_emit_debounce_lock`` 必须存在并且是 ``threading.Lock`` 实例。"""

    def test_lock_attribute_present(self) -> None:
        self.assertTrue(hasattr(web_ui_config_sync, "_emit_debounce_lock"))

    def test_lock_is_threading_lock(self) -> None:
        import threading

        # threading.Lock() 返回的是 ``_thread.lock``，但有 ``acquire`` / ``release``
        lock = web_ui_config_sync._emit_debounce_lock
        self.assertTrue(hasattr(lock, "acquire"))
        self.assertTrue(hasattr(lock, "release"))
        # 也允许是 RLock —— 一次 tuple isinstance 涵盖两类
        lock_classes = (type(threading.Lock()), threading.RLock)
        self.assertIsInstance(lock, lock_classes)


if __name__ == "__main__":
    unittest.main()
