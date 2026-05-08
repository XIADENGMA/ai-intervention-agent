"""R54-A：``server._fetch_sse_stats_cached`` 的 1.0s TTL 缓存契约。

为什么单独锁这一层：

- ``server_info_resource`` 暴露 ``sse_bus`` 子块的代价是一次跨进程 ``httpx.get
  /api/system/sse-stats``。client UI（PWA / VSCode webview）会按 sub-second
  cadence poll self-info（fast refresh / status badge tick），如果不缓存，
  Web UI 端 ``/api/system/sse-stats`` 的 60/min 限流会在 ~1 秒 client 请求
  burst 内就被打穿——self-info 自检页变成"sse_bus 一直显示 429"，反而比没
  这块还糟。
- 同时这个 cache 不能"假新鲜"——如果 web_ui 真的发生了 backpressure /
  history evict 等需要紧急人工介入的事件，self-info 必须能在秒级时间内反映
  出来。所以 TTL 选 1.0s（既低于 60/min 撞限流的窗口，又不会让人类感到
  滞后）。
- 锁粒度精细：``threading.Lock`` 只护 cache dict + 时间戳读写；``httpx.get``
  在锁外，避免一个慢请求把所有并发 caller 都阻塞（thundering-herd 风险已被
  cache 命中天然抑制——下一个 1.0s 内的所有 caller 都直接读 cache）。

测试组织：

1. ``TestCacheHitMiss`` — fresh cache 触发 HTTP；命中 cache 不再 fire；
   过 TTL 后再次 fire；写 cache 仅在 success 时发生。
2. ``TestCacheCopyIsolation`` — 返回值永远是新 dict，外部修改不污染 cache。
3. ``TestCacheNotPoisonedByErrors`` — HTTP 失败 / JSON 解析失败 / 4xx / 网络
   异常都不写 cache；下次调用必然重发请求。
4. ``TestServerInfoUsesCachedFetcher`` — ``server_info_resource`` 实际调用
   ``_fetch_sse_stats_cached``（用 monkeypatch 锁住调用关系）。
5. ``TestThreadSafety`` — 多线程并发 fetch 同一 host:port，httpx 真实调用
   次数受 cache 抑制（不严格断 1 次，抗 race 但断 ≤ N）。
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ai_intervention_agent.server as server


def _reset_cache() -> None:
    """每个用例前清理 cache，避免相互干扰。"""
    with server._sse_stats_cache_lock:
        server._sse_stats_cache.clear()
        server._sse_stats_cache_ts = 0.0


def _make_ok_response(payload: dict[str, object] | None = None) -> MagicMock:
    if payload is None:
        payload = {
            "success": True,
            "emit_total": 100,
            "latest_event_id": 50,
            "gap_warnings_emitted": 0,
            "backpressure_discards": 0,
            "subscriber_count": 1,
            "history_size": 50,
            "heartbeat_total": 5,
        }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


# ============================================================================
# 1. cache 命中 / 未命中
# ============================================================================


class TestCacheHitMiss(unittest.TestCase):
    """fresh cache 必发 HTTP；后续命中 cache 不再发；过 TTL 后再发。"""

    def setUp(self) -> None:
        _reset_cache()

    def test_first_call_fires_http(self) -> None:
        with patch("httpx.get", return_value=_make_ok_response()) as fake_get:
            result = server._fetch_sse_stats_cached("127.0.0.1", 8080)
        fake_get.assert_called_once()
        self.assertNotIn("error", result)
        self.assertEqual(result["emit_total"], 100)
        # 首次调用不会带 cached 标记
        self.assertNotIn("cached", result)

    def test_second_call_within_ttl_hits_cache(self) -> None:
        with patch("httpx.get", return_value=_make_ok_response()) as fake_get:
            server._fetch_sse_stats_cached("127.0.0.1", 8080)
            second = server._fetch_sse_stats_cached("127.0.0.1", 8080)
        # 第二次必须不再发 HTTP
        self.assertEqual(fake_get.call_count, 1)
        # 命中 cache 时返回值带标记
        self.assertTrue(second.get("cached"))
        self.assertIn("cache_age_s", second)
        self.assertEqual(second["emit_total"], 100)

    def test_call_after_ttl_expires_fires_http_again(self) -> None:
        # 先发一次填 cache
        with patch("httpx.get", return_value=_make_ok_response()) as fake_get:
            server._fetch_sse_stats_cached("127.0.0.1", 8080)
            self.assertEqual(fake_get.call_count, 1)

            # 把 cache 时间戳人工往前拨 2 秒（> TTL）
            with server._sse_stats_cache_lock:
                server._sse_stats_cache_ts -= 2.0

            second = server._fetch_sse_stats_cached("127.0.0.1", 8080)

        # 过了 TTL 必须重新发 HTTP
        self.assertEqual(fake_get.call_count, 2)
        self.assertNotIn("cached", second)


# ============================================================================
# 2. cache 副本隔离
# ============================================================================


class TestCacheCopyIsolation(unittest.TestCase):
    """返回值永远是新 dict，外部修改不污染 cache。"""

    def setUp(self) -> None:
        _reset_cache()

    def test_returned_dict_is_independent_of_cache(self) -> None:
        with patch("httpx.get", return_value=_make_ok_response()):
            first = server._fetch_sse_stats_cached("127.0.0.1", 8080)
            first["malicious"] = "payload"
            first["emit_total"] = -999

            second = server._fetch_sse_stats_cached("127.0.0.1", 8080)

        # cache 没被外部改污
        self.assertNotIn("malicious", second)
        self.assertEqual(second["emit_total"], 100)


# ============================================================================
# 3. cache 不被错误污染
# ============================================================================


class TestCacheNotPoisonedByErrors(unittest.TestCase):
    """HTTP 异常 / 4xx / JSON 解析失败 都不应写 cache。"""

    def setUp(self) -> None:
        _reset_cache()

    def test_network_exception_does_not_write_cache(self) -> None:
        with patch("httpx.get", side_effect=ConnectionError("net down")) as fake_get:
            result1 = server._fetch_sse_stats_cached("127.0.0.1", 8080)
            result2 = server._fetch_sse_stats_cached("127.0.0.1", 8080)
        # 两次都重发（cache 未写）
        self.assertEqual(fake_get.call_count, 2)
        self.assertIn("error", result1)
        self.assertIn("error", result2)

    def test_http_4xx_does_not_write_cache(self) -> None:
        bad_resp = MagicMock()
        bad_resp.status_code = 429
        with patch("httpx.get", return_value=bad_resp) as fake_get:
            result1 = server._fetch_sse_stats_cached("127.0.0.1", 8080)
            result2 = server._fetch_sse_stats_cached("127.0.0.1", 8080)
        self.assertEqual(fake_get.call_count, 2)
        self.assertIn("HTTP 429", str(result1.get("error", "")))
        self.assertIn("HTTP 429", str(result2.get("error", "")))

    def test_json_decode_failure_does_not_write_cache(self) -> None:
        bad_resp = MagicMock()
        bad_resp.status_code = 200
        bad_resp.json.side_effect = ValueError("malformed json")
        with patch("httpx.get", return_value=bad_resp) as fake_get:
            result1 = server._fetch_sse_stats_cached("127.0.0.1", 8080)
            result2 = server._fetch_sse_stats_cached("127.0.0.1", 8080)
        self.assertEqual(fake_get.call_count, 2)
        self.assertIn("json decode", str(result1.get("error", "")))

    def test_response_not_success_does_not_write_cache(self) -> None:
        weird_resp = _make_ok_response({"success": False, "reason": "x"})
        with patch("httpx.get", return_value=weird_resp) as fake_get:
            result1 = server._fetch_sse_stats_cached("127.0.0.1", 8080)
            result2 = server._fetch_sse_stats_cached("127.0.0.1", 8080)
        self.assertEqual(fake_get.call_count, 2)
        self.assertIn("not success", str(result1.get("error", "")))


# ============================================================================
# 4. server_info_resource 真的走 cached fetcher
# ============================================================================


class TestServerInfoUsesCachedFetcher(unittest.TestCase):
    """``server_info_resource`` 必须调用 ``_fetch_sse_stats_cached``。"""

    def setUp(self) -> None:
        _reset_cache()

    def test_resource_calls_cached_fetcher(self) -> None:
        # 让 web_ui 探测器返回 running，使 sse_bus 块走 fetch 路径。
        # ``is_web_service_running`` 来自 service_manager。
        with (
            patch(
                "ai_intervention_agent.server.is_web_service_running", return_value=True
            ),
            patch(
                "ai_intervention_agent.server._fetch_sse_stats_cached",
                return_value={"emit_total": 1, "latest_event_id": 1},
            ) as fake_fetch,
        ):
            info = server.server_info_resource()
        fake_fetch.assert_called_once()
        self.assertIn("sse_bus", info)


# ============================================================================
# 5. 多线程并发不重复打 HTTP（cache 命中）
# ============================================================================


class TestThreadSafety(unittest.TestCase):
    """多线程并发 fetch 同一 host:port 时，cache 命中后不再重复打 HTTP。"""

    def setUp(self) -> None:
        _reset_cache()

    def test_concurrent_fetch_respects_cache_after_first(self) -> None:
        threads_count = 8
        call_count = {"n": 0}
        call_lock = threading.Lock()

        def fake_get(*_args, **_kwargs):
            with call_lock:
                call_count["n"] += 1
            return _make_ok_response()

        results: list[dict[str, object]] = []
        results_lock = threading.Lock()

        def worker():
            res = server._fetch_sse_stats_cached("127.0.0.1", 8080)
            with results_lock:
                results.append(res)

        with patch("httpx.get", side_effect=fake_get):
            # 串行先打一次填 cache（确保后续并发命中）
            server._fetch_sse_stats_cached("127.0.0.1", 8080)
            self.assertEqual(call_count["n"], 1)
            threads = [threading.Thread(target=worker) for _ in range(threads_count)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        # 所有并发 fetch 命中 cache，httpx 总调用次数仍是 1
        self.assertEqual(call_count["n"], 1)
        self.assertEqual(len(results), threads_count)
        for r in results:
            self.assertTrue(r.get("cached"))


# ============================================================================
# 6. cache TTL 常量
# ============================================================================


class TestCacheTTLConstant(unittest.TestCase):
    """``_SSE_STATS_CACHE_TTL_S`` 应在合理范围（0.5s ~ 5s）。"""

    def test_ttl_is_within_reasonable_bounds(self) -> None:
        self.assertGreaterEqual(server._SSE_STATS_CACHE_TTL_S, 0.5)
        self.assertLessEqual(server._SSE_STATS_CACHE_TTL_S, 5.0)


if __name__ == "__main__":
    unittest.main()
