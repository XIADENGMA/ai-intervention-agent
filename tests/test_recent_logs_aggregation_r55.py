"""R55 — 跨进程 recent_logs 聚合测试。

覆盖：

* ``_fetch_recent_logs_cached`` 的 cache hit / TTL 过期 / 不同 limit；
* HTTP 各种失败路径（网络异常 / 4xx / json decode / 非 success body）；
* ``server_info_resource`` 把 mcp + web_ui entries 按 ts_unix 升序合并并
  加 ``source`` 标签的行为；
* web_ui 不在线 / web_ui 拉取失败时的 graceful degradation。
"""

from __future__ import annotations

import time
import unittest
from typing import Any, cast
from unittest.mock import MagicMock, patch

import ai_intervention_agent.server as server


def _ok_resp(entries: list[dict] | None = None) -> MagicMock:
    return MagicMock(
        status_code=200,
        json=MagicMock(
            return_value={
                "success": True,
                "entries": entries if entries is not None else [{"x": 1}],
            }
        ),
    )


class TestRecentLogsCacheBehavior(unittest.TestCase):
    """``_fetch_recent_logs_cached`` 自身的 cache / TTL 行为。"""

    def setUp(self) -> None:
        with server._recent_logs_cache_lock:
            server._recent_logs_cache.clear()
            server._recent_logs_cache_ts = 0.0

    def test_first_call_hits_network(self) -> None:
        with patch("httpx.get", return_value=_ok_resp()) as fake_get:
            r = server._fetch_recent_logs_cached("127.0.0.1", 41111)
        self.assertEqual(fake_get.call_count, 1)
        self.assertEqual(r["count"], 1)
        self.assertNotIn("cached", r)
        self.assertNotIn("error", r)

    def test_second_call_within_ttl_returns_cached(self) -> None:
        with patch("httpx.get", return_value=_ok_resp()) as fake_get:
            server._fetch_recent_logs_cached("127.0.0.1", 41111)
            r2 = server._fetch_recent_logs_cached("127.0.0.1", 41111)
        self.assertEqual(fake_get.call_count, 1)
        self.assertTrue(r2.get("cached"))
        self.assertIn("cache_age_s", r2)

    def test_ttl_expiry_refetches(self) -> None:
        with patch("httpx.get", return_value=_ok_resp(entries=[])) as fake_get:
            server._fetch_recent_logs_cached("127.0.0.1", 41111)
            with server._recent_logs_cache_lock:
                server._recent_logs_cache_ts = time.monotonic() - 10.0
            server._fetch_recent_logs_cached("127.0.0.1", 41111)
            self.assertEqual(fake_get.call_count, 2)

    def test_different_limit_invalidates_cache(self) -> None:
        with patch("httpx.get", return_value=_ok_resp(entries=[])) as fake_get:
            server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=20)
            server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=50)
            self.assertEqual(fake_get.call_count, 2)

    def test_cache_returns_isolated_copy(self) -> None:
        with patch("httpx.get", return_value=_ok_resp()):
            server._fetch_recent_logs_cached("127.0.0.1", 41111)
            r2 = server._fetch_recent_logs_cached("127.0.0.1", 41111)
        # 篡改 r2 不能污染 cache 中的 list reference 或后续 call。
        r2["entries"] = "polluted"
        with patch("httpx.get", return_value=_ok_resp()):
            r3 = server._fetch_recent_logs_cached("127.0.0.1", 41111)
        self.assertIsInstance(r3.get("entries"), list)


class TestRecentLogsCacheErrorPaths(unittest.TestCase):
    """各种失败路径都应返回 ``error`` 字段，绝不抛异常。"""

    def setUp(self) -> None:
        with server._recent_logs_cache_lock:
            server._recent_logs_cache.clear()
            server._recent_logs_cache_ts = 0.0

    def test_network_exception(self) -> None:
        with patch("httpx.get", side_effect=RuntimeError("boom")):
            r = server._fetch_recent_logs_cached("127.0.0.1", 41111)
        self.assertIn("error", r)

    def test_http_4xx(self) -> None:
        bad_resp = MagicMock(status_code=429)
        with patch("httpx.get", return_value=bad_resp):
            r = server._fetch_recent_logs_cached("127.0.0.1", 41111)
        self.assertIn("error", r)
        self.assertIn("429", str(r["error"]))

    def test_json_decode_failure(self) -> None:
        bad_resp = MagicMock(status_code=200)
        bad_resp.json.side_effect = ValueError("bad json")
        with patch("httpx.get", return_value=bad_resp):
            r = server._fetch_recent_logs_cached("127.0.0.1", 41111)
        self.assertIn("error", r)

    def test_response_not_success(self) -> None:
        weird_resp = MagicMock(
            status_code=200, json=MagicMock(return_value={"success": False})
        )
        with patch("httpx.get", return_value=weird_resp):
            r = server._fetch_recent_logs_cached("127.0.0.1", 41111)
        self.assertIn("error", r)


class TestServerInfoRecentLogsAggregation(unittest.TestCase):
    """``server_info_resource`` 跨进程合并逻辑。

    ``web_ui`` block 由 server.py 内联构造（``get_config()`` + ``is_web_service_running``），
    所以这里我们 patch ``server.is_web_service_running`` 控制 running 字段、
    patch ``httpx.get`` 控制 web_ui /api/system/recent-logs 返回值，让真实
    config 提供 host/port。

    ``recent_logs`` 块还要 patch ``enhanced_logging.get_recent_logs`` 控制 mcp 自身条目。
    """

    def setUp(self) -> None:
        with server._recent_logs_cache_lock:
            server._recent_logs_cache.clear()
            server._recent_logs_cache_ts = 0.0
        with server._sse_stats_cache_lock:
            server._sse_stats_cache.clear()
            server._sse_stats_cache_ts = 0.0

    def test_mcp_only_when_web_ui_offline(self) -> None:
        with (
            patch(
                "ai_intervention_agent.server.is_web_service_running",
                return_value=False,
            ),
            patch(
                "ai_intervention_agent.enhanced_logging.get_recent_logs",
                return_value=[
                    {"level": "ERROR", "message": "mcp boom", "ts_unix": 100.0},
                ],
            ),
        ):
            info = server.server_info_resource()
        rl = cast(dict[str, Any], info["recent_logs"])
        self.assertEqual(rl["mcp_count"], 1)
        self.assertEqual(rl["web_ui_count"], 0)
        self.assertEqual(rl["count"], 1)
        meta = cast(dict[str, Any], rl["web_ui_meta"])
        self.assertFalse(meta["available"])
        entries = cast(list[dict[str, Any]], rl["entries"])
        self.assertEqual(entries[0]["source"], "mcp")

    def test_merge_mcp_and_web_ui_sorted_by_ts(self) -> None:
        # /api/system/recent-logs 走 cache，所以 patch 一次就够。
        # /api/system/sse-stats 也会被 server_info 调用——这次也是同一个 httpx.get
        # mock，只能让它兼顾两类请求：用 side_effect 按 URL 匹配。
        def _fake_get(url, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            if "recent-logs" in url:
                return _ok_resp(
                    entries=[
                        {"level": "WARNING", "message": "ui-A", "ts_unix": 50.0},
                        {"level": "ERROR", "message": "ui-B", "ts_unix": 200.0},
                    ]
                )
            # sse-stats 路径：返回最小成功 body，server_info 该块就会成功填充。
            return MagicMock(
                status_code=200,
                json=MagicMock(return_value={"success": True}),
            )

        with (
            patch(
                "ai_intervention_agent.server.is_web_service_running", return_value=True
            ),
            patch(
                "ai_intervention_agent.enhanced_logging.get_recent_logs",
                return_value=[
                    {"level": "ERROR", "message": "mcp-1", "ts_unix": 100.0},
                ],
            ),
            patch("httpx.get", side_effect=_fake_get),
        ):
            info = server.server_info_resource()

        rl = cast(dict[str, Any], info["recent_logs"])
        self.assertEqual(rl["mcp_count"], 1)
        self.assertEqual(rl["web_ui_count"], 2)
        self.assertEqual(rl["count"], 3)
        entries = cast(list[dict[str, Any]], rl["entries"])
        self.assertEqual([e["ts_unix"] for e in entries], [50.0, 100.0, 200.0])
        self.assertEqual([e["source"] for e in entries], ["web_ui", "mcp", "web_ui"])

    def test_web_ui_fetch_error_is_recorded_but_mcp_still_returned(self) -> None:
        def _fake_get(url, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            if "recent-logs" in url:
                raise RuntimeError("net down")
            # sse-stats fallback 也让其失败：测试只关心 recent_logs 块。
            raise RuntimeError("net down")

        with (
            patch(
                "ai_intervention_agent.server.is_web_service_running", return_value=True
            ),
            patch(
                "ai_intervention_agent.enhanced_logging.get_recent_logs",
                return_value=[
                    {"level": "ERROR", "message": "mcp-only", "ts_unix": 1.0},
                ],
            ),
            patch("httpx.get", side_effect=_fake_get),
        ):
            info = server.server_info_resource()

        rl = cast(dict[str, Any], info["recent_logs"])
        self.assertEqual(rl["mcp_count"], 1)
        self.assertEqual(rl["web_ui_count"], 0)
        meta = cast(dict[str, Any], rl["web_ui_meta"])
        self.assertIn("error", meta)
        entries = cast(list[dict[str, Any]], rl["entries"])
        self.assertEqual(entries[0]["message"], "mcp-only")
        self.assertEqual(entries[0]["source"], "mcp")


class TestRecentLogsTtlConstantBounds(unittest.TestCase):
    """TTL 常量保持在合理范围。"""

    def test_ttl_is_short_for_responsiveness(self) -> None:
        self.assertLess(server._RECENT_LOGS_CACHE_TTL_S, 5.0)
        self.assertGreaterEqual(server._RECENT_LOGS_CACHE_TTL_S, 0.5)


if __name__ == "__main__":
    unittest.main()
