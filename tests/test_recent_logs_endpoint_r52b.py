"""R52-B：``GET /api/system/recent-logs`` 端点契约。

让 PWA / VS Code 状态面板可以独立拉 R51-C ring buffer，不依赖 MCP。
本测试用静态扫源码 + 单元行为两层覆盖：

  1. 路由 path / method / rate-limit / 调用 ``get_recent_logs`` 的契约
     —— 静态源码扫描，避免起 Flask app（`web_ui` 的 ``create_app`` 有
     副作用，单测不能依赖）。
  2. ``get_recent_logs(limit=...)`` 在 ``limit`` 边界条件下的行为
     —— 直接调函数验证。
  3. 端点不应做 loopback 限制（与 ``sse-stats`` 一致，PWA / LAN 可用）。
"""

from __future__ import annotations

import logging
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ai_intervention_agent.enhanced_logging as enhanced_logging
from ai_intervention_agent.web_ui_routes import system as system_module

SOURCE = Path(system_module.__file__).read_text(encoding="utf-8")


class TestRouteShape(unittest.TestCase):
    """端点的路由 / 方法 / 限流 / 处理函数都必须存在。"""

    def test_route_path_registered(self) -> None:
        self.assertIn(
            '@self.app.route("/api/system/recent-logs"',
            SOURCE,
            "/api/system/recent-logs 路由未注册（R52-B）",
        )

    def test_route_method_is_get(self) -> None:
        # 路由声明里必须含 methods=["GET"]
        m = re.search(
            r'@self\.app\.route\("/api/system/recent-logs",\s*methods=\["GET"\]\)',
            SOURCE,
        )
        self.assertIsNotNone(m, "/api/system/recent-logs 必须是 GET")

    def test_rate_limit_present(self) -> None:
        """端点必须 explicit rate-limit，不能用默认或 exempt。

        理由：日志条目较大（500 字节×200 条 ≈ 100 KB），未限流会被滥用做
        日志爬取。30/min 给运维仪表板足够余量。"""
        m = re.search(
            r'@self\.app\.route\("/api/system/recent-logs"[^)]*\)\s*'
            r'@self\.limiter\.limit\(["\'](\d+ per minute)["\']\)',
            SOURCE,
        )
        self.assertIsNotNone(m, "recent-logs 端点必须有 rate-limit 装饰器")

    def test_handler_calls_get_recent_logs(self) -> None:
        # 在 recent-logs 端点 handler 里必须调 enhanced_logging.get_recent_logs
        m = re.search(
            r"def recent_logs\(\).*?(?=\n        @self\.app\.route|\nclass )",
            SOURCE,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "找不到 recent_logs handler 函数体")
        assert m is not None
        body = m.group(0)
        self.assertIn(
            "get_recent_logs",
            body,
            "handler 必须调 enhanced_logging.get_recent_logs",
        )


class TestNotLoopbackGated(unittest.TestCase):
    """端点不应做 ``_is_loopback_request`` 限制（与 sse-stats 一致）。"""

    def test_no_loopback_check(self) -> None:
        m = re.search(
            r"def recent_logs\(\).*?(?=\n        @self\.app\.route|\nclass )",
            SOURCE,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        self.assertNotIn(
            "_is_loopback_request",
            body,
            "recent-logs 不应做 loopback gate（PWA / LAN 也要能查）",
        )


class TestGetRecentLogsAPISupportsLimit(unittest.TestCase):
    """``get_recent_logs(limit=N)`` 必须按 N 截断；超过 buffer 容量时只返回 buffer 满。"""

    def setUp(self) -> None:
        enhanced_logging.clear_recent_logs()
        for i in range(150):
            enhanced_logging._record_to_ring(logging.WARNING, "src", f"msg-{i}")

    def test_limit_50_returns_50(self) -> None:
        entries = enhanced_logging.get_recent_logs(limit=50)
        self.assertEqual(len(entries), 50)
        # 应该是 most-recent 50 条（msg-100..149）
        self.assertEqual(entries[0]["message"], "msg-100")
        self.assertEqual(entries[-1]["message"], "msg-149")

    def test_limit_at_buffer_max_returns_all_entries(self) -> None:
        # buffer 里实际就 150 条
        entries = enhanced_logging.get_recent_logs(
            limit=enhanced_logging._LOG_RING_MAXLEN
        )
        self.assertEqual(len(entries), 150)

    def test_limit_greater_than_buffer_returns_all_entries(self) -> None:
        # caller 要 999 条，但 buffer 只 150 条 → 实际返回 150
        entries = enhanced_logging.get_recent_logs(limit=999)
        self.assertEqual(len(entries), 150)


class TestSwaggerDocsEntry(unittest.TestCase):
    """端点必须有 OpenAPI/Swagger 文档（dict 格式 yaml/swag 解析）。"""

    def test_endpoint_has_swagger_docstring(self) -> None:
        m = re.search(
            r"def recent_logs\(\).*?(?=\n        @self\.app\.route|\nclass )",
            SOURCE,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        # 必须有 ``tags:`` 和 ``responses:`` 标记 ―― swagger spec 的最小子集
        self.assertIn("tags:", body)
        self.assertIn("responses:", body)
        self.assertIn("System", body)


if __name__ == "__main__":
    unittest.main()
