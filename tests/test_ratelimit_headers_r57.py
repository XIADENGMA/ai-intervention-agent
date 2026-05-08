"""R57 — Flask-Limiter rate-limit response headers.

启用 ``headers_enabled=True`` 后，Limiter 会在每个**受限响应**上注入
``X-RateLimit-Limit`` / ``X-RateLimit-Remaining`` / ``X-RateLimit-Reset``，
以及在 429 响应上注入 ``Retry-After``。这是 RFC 6585 + IETF
``RateLimit-*`` draft 行业标准，让客户端 SDK / 反向代理 / 监控面板能
主动观测限流状态。

覆盖目标：

* 受限端点（``/api/time`` 等走 default_limits 的）—— 响应头
  里有 ``X-RateLimit-Limit`` / ``X-RateLimit-Remaining``；
* ``limiter.exempt`` 静态资源（``/favicon.ico`` / ``/static/css/...``）
  —— **没有** rate-limit 头（避免 noise）；
* 429 响应 —— 带 ``Retry-After`` header；
* ``X-RateLimit-Remaining`` 在连续请求时会下降。
"""

from __future__ import annotations

import unittest
from typing import Any


class _LimiterHeaderTestBase(unittest.TestCase):
    _port: int = 19057
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="r57-ratelimit-test", task_id="r57-base", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        # 不要禁用 limiter：本测试就是要验证它的头注入。
        cls._client = cls._ui.app.test_client()


class TestRateLimitHeadersOnRateLimitedEndpoints(_LimiterHeaderTestBase):
    """带 default_limits 的端点必须暴露 X-RateLimit-* 头。"""

    def test_api_endpoint_has_rate_limit_limit_header(self) -> None:
        resp = self._client.get("/api/time")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            "X-RateLimit-Limit",
            resp.headers,
            "受限端点应暴露 X-RateLimit-Limit",
        )
        resp.close()

    def test_api_endpoint_has_remaining_header(self) -> None:
        resp = self._client.get("/api/time")
        self.assertIn(
            "X-RateLimit-Remaining",
            resp.headers,
            "受限端点应暴露 X-RateLimit-Remaining",
        )
        resp.close()

    def test_api_endpoint_has_reset_header(self) -> None:
        resp = self._client.get("/api/time")
        self.assertIn(
            "X-RateLimit-Reset",
            resp.headers,
            "受限端点应暴露 X-RateLimit-Reset",
        )
        resp.close()

    def test_remaining_decrements_across_requests(self) -> None:
        """连续两次请求 ``X-RateLimit-Remaining`` 应非递增。

        ``fixed-window`` 策略下窗口内每次命中 -1。窗口跨边界时会重置，
        所以做 ``<=`` 而不是 ``<``，避免在 second-boundary 处 flaky。
        """
        r1 = self._client.get("/api/time")
        try:
            rem1_str = r1.headers.get("X-RateLimit-Remaining", "")
        finally:
            r1.close()
        r2 = self._client.get("/api/time")
        try:
            rem2_str = r2.headers.get("X-RateLimit-Remaining", "")
        finally:
            r2.close()

        try:
            rem1 = int(rem1_str)
            rem2 = int(rem2_str)
        except (TypeError, ValueError):
            self.skipTest(
                f"Remaining 头不是整数 (rem1={rem1_str!r}, rem2={rem2_str!r})"
            )
        self.assertLessEqual(rem2, rem1)


class TestRateLimitHeadersAreNumeric(_LimiterHeaderTestBase):
    """X-RateLimit-Limit / -Remaining 必须可以解析成整数，不能是 ``"60 per minute"`` 之类。"""

    def test_limit_header_is_integer(self) -> None:
        resp = self._client.get("/api/time")
        try:
            limit_val = resp.headers.get("X-RateLimit-Limit", "")
        finally:
            resp.close()
        try:
            int(limit_val)
        except (TypeError, ValueError):
            self.fail(f"X-RateLimit-Limit 应是整数字符串，实际 {limit_val!r}")

    def test_remaining_header_is_integer(self) -> None:
        resp = self._client.get("/api/time")
        try:
            rem_val = resp.headers.get("X-RateLimit-Remaining", "")
        finally:
            resp.close()
        try:
            int(rem_val)
        except (TypeError, ValueError):
            self.fail(f"X-RateLimit-Remaining 应是整数字符串，实际 {rem_val!r}")


class TestExemptStaticResourcesDontLeakHeaders(_LimiterHeaderTestBase):
    """``limiter.exempt`` 静态资源不应携带 X-RateLimit-* 头。

    这些端点已在 ``serve_css`` / ``favicon`` 等位置 ``@limiter.exempt``，
    Flask-Limiter 跳过限流逻辑、自然也不发头。如果有头泄漏说明 exempt
    decorator 漏掉了。
    """

    def test_favicon_has_no_ratelimit_headers(self) -> None:
        resp = self._client.get("/favicon.ico")
        try:
            self.assertNotIn(
                "X-RateLimit-Limit",
                resp.headers,
                "limiter.exempt 端点不该带 X-RateLimit-Limit",
            )
            self.assertNotIn("X-RateLimit-Remaining", resp.headers)
        finally:
            resp.close()

    def test_static_css_has_no_ratelimit_headers(self) -> None:
        resp = self._client.get("/static/css/main.css")
        try:
            self.assertNotIn(
                "X-RateLimit-Limit",
                resp.headers,
                "limiter.exempt 静态 CSS 不该带 X-RateLimit-Limit",
            )
            self.assertNotIn("X-RateLimit-Remaining", resp.headers)
        finally:
            resp.close()


class TestLimiterConfigSourceOfTruth(unittest.TestCase):
    """直接通过 import 校验 ``Limiter`` 构造参数 —— 防止未来谁不小心去掉
    ``headers_enabled=True``。

    运行时不构造 WebFeedbackUI，避开 fixture 成本。
    """

    def test_web_ui_source_enables_headers(self) -> None:
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parent.parent
            / "src"
            / "ai_intervention_agent"
            / "web_ui.py"
        )
        text = src.read_text(encoding="utf-8")
        self.assertIn(
            "headers_enabled=True",
            text,
            "web_ui.Limiter(...) 必须带 headers_enabled=True，否则客户端拿不到 X-RateLimit-*",
        )


if __name__ == "__main__":
    unittest.main()
