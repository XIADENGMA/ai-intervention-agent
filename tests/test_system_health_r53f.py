"""R53-F：``GET /api/system/health`` 综合健康检查端点契约。

聚合 sse_bus / task_queue / recent_errors 三个子检查，给监控系统一个单
endpoint 决策。覆盖：

  1. 路由路径、方法、rate-limit 必须正确（120/min）。
  2. handler 必须聚合至少 ``sse_bus`` / ``task_queue`` / ``recent_errors``
     三个 check，每个 check 必含 ``ok`` 字段。
  3. 决策逻辑：
     - 全 ok + 无 backpressure + 无 recent_error → ``healthy`` + HTTP 200
     - 全 ok + backpressure>0 或 recent_errors>0 → ``degraded`` + HTTP 200
     - 任一 check ok=False → ``unhealthy`` + HTTP 503
  4. 不做 loopback gate（K8s probe 必然来自非 loopback IP）。
  5. payload 不应含敏感字段（无 prompt 内容、config 值等）。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes import system as system_module

SOURCE = Path(system_module.__file__).read_text(encoding="utf-8")


class TestRouteShape(unittest.TestCase):
    """端点路由 / 方法 / 限流 必须正确。"""

    def test_route_path_registered(self) -> None:
        self.assertIn(
            '@self.app.route("/api/system/health"',
            SOURCE,
            "/api/system/health 路由未注册（R53-F）",
        )

    def test_route_method_is_get(self) -> None:
        m = re.search(
            r'@self\.app\.route\("/api/system/health",\s*methods=\["GET"\]\)',
            SOURCE,
        )
        self.assertIsNotNone(m, "/api/system/health 必须是 GET")

    def test_rate_limit_is_120_per_minute(self) -> None:
        m = re.search(
            r'@self\.app\.route\("/api/system/health"[^)]*\)\s*'
            r'@self\.limiter\.limit\(["\']120 per minute["\']\)',
            SOURCE,
        )
        self.assertIsNotNone(
            m,
            "/api/system/health 必须 rate-limit 120/min（K8s probe 默认 10s 一次）",
        )

    def test_handler_function_named_system_health(self) -> None:
        # 通过 def 名匹配
        self.assertIn("def system_health() -> ResponseReturnValue:", SOURCE)


class TestNotLoopbackGated(unittest.TestCase):
    """端点必须开放给 K8s probe / 监控（非 loopback）。"""

    def test_handler_does_not_check_loopback(self) -> None:
        m = re.search(
            r"def system_health\(\).*?(?=\n        @self\.app\.route|\nclass )",
            SOURCE,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        self.assertNotIn(
            "_is_loopback_request",
            body,
            "/api/system/health 不应做 loopback gate（K8s probe 必然来自非 loopback IP）",
        )


class TestHandlerAggregatesThreeChecks(unittest.TestCase):
    """handler 必须聚合 sse_bus / task_queue / recent_errors 三个 check。"""

    def setUp(self) -> None:
        m = re.search(
            r"def system_health\(\).*?(?=\n        @self\.app\.route|\nclass )",
            SOURCE,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        self.body = m.group(0)

    def test_aggregates_sse_bus_check(self) -> None:
        self.assertIn('"sse_bus"', self.body)
        self.assertIn("_sse_bus.stats_snapshot()", self.body)

    def test_aggregates_task_queue_check(self) -> None:
        self.assertIn('"task_queue"', self.body)
        self.assertIn("get_task_queue()", self.body)

    def test_aggregates_recent_errors_check(self) -> None:
        self.assertIn('"recent_errors"', self.body)
        self.assertIn("get_recent_error_stats", self.body)


class TestStatusDecisionLogic(unittest.TestCase):
    """status 决策必须三档（healthy / degraded / unhealthy）+ HTTP 503/200。"""

    def setUp(self) -> None:
        m = re.search(
            r"def system_health\(\).*?(?=\n        @self\.app\.route|\nclass )",
            SOURCE,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        self.body = m.group(0)

    def test_three_status_values_present(self) -> None:
        for value in ("healthy", "degraded", "unhealthy"):
            with self.subTest(value=value):
                self.assertIn(
                    f'"{value}"',
                    self.body,
                    f"status enum 必须包含 {value!r}",
                )

    def test_http_503_for_unhealthy(self) -> None:
        # 必须出现 503，且和 unhealthy 关联
        self.assertIn("503", self.body)
        # 表达必须类似 ``http_code = 503 if status == "unhealthy"``
        m = re.search(r'503\s+if\s+status\s*==\s*"unhealthy"', self.body)
        self.assertIsNotNone(m, "503 状态码应当与 status==unhealthy 关联")

    def test_payload_includes_ts_unix(self) -> None:
        """payload 必须含 ts_unix，方便监控判 freshness。"""
        self.assertIn('"ts_unix"', self.body)


class TestSwaggerDocsEntry(unittest.TestCase):
    """端点必须有 OpenAPI/Swagger 文档。"""

    def test_endpoint_has_swagger_docstring(self) -> None:
        m = re.search(
            r"def system_health\(\).*?(?=\n        @self\.app\.route|\nclass )",
            SOURCE,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        self.assertIn("tags:", body)
        self.assertIn("responses:", body)
        self.assertIn("200:", body)
        self.assertIn("503:", body)


class TestPayloadDoesNotLeakSensitive(unittest.TestCase):
    """handler 不应在 payload 里塞 prompt 内容、config 值等敏感数据。"""

    def setUp(self) -> None:
        m = re.search(
            r"def system_health\(\).*?(?=\n        @self\.app\.route|\nclass )",
            SOURCE,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        self.body = m.group(0)

    def test_no_task_prompt_in_payload(self) -> None:
        # handler body 不应直接 access task.prompt（哪怕拿来计算总长度）
        self.assertNotIn(
            "task.prompt",
            self.body,
            "health 端点不应触碰 task.prompt（避免意外泄漏到 payload）",
        )

    def test_no_config_value_passthrough(self) -> None:
        self.assertNotIn(
            "get_config()",
            self.body,
            "health 端点不应直接读 config（监控不需要业务配置）",
        )


if __name__ == "__main__":
    unittest.main()
