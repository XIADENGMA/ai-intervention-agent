"""R186 / T1 · ``GET /api/system/metrics`` Prometheus exposition endpoint 契约。

背景
----
R132 让 ``/api/system/health`` 暴露了顶层 ``build`` / ``version`` /
``uptime_seconds`` 等 JSON 字段，监控仪表板可以直接 ``curl | jq``。
但 K8s / Prometheus / Grafana / Datadog 等监控栈的"标准方言"是
**Prometheus 0.0.4 exposition format** —— 一种纯文本格式：

    # HELP <metric_name> <description>
    # TYPE <metric_name> <counter|gauge|...>
    <metric_name>{<label>="<value>",...} <numeric_value>

JSON health 端点对 dashboard 友好，但要把它接进 Prometheus 还得另起
一个 sidecar exporter。T1 在 ``/api/system/metrics`` 直接以 Prometheus
格式输出（与 health 共享数据源），让 ``scrape_configs`` 加一条即接入。

为什么不用 ``prometheus_client``：
- 4 MB+ wheel 体积换来的特性（multiprocess registry / push gateway /
  HTTP server）本项目用不上（已经在 Flask 里），手写 exposition format
  ~250 行代码就够；
- 避免额外依赖让 ``pip install ai-intervention-agent`` 变重。

设计约束
--------
1. **零新依赖** — 手写 prom 0.0.4 exposition format。
2. **复用既有 _safe_* helper** — 数据源与 ``/api/system/health`` 完全
   同步，杜绝两个端点 stale 不一致。
3. **命名规约** — 所有指标 ``aiia_<subsystem>_<name>[_unit][_total]``
   前缀，counter 必带 ``_total`` 后缀（OpenMetrics 官方建议）。
4. **PII 边界** — 与 health 一致，绝不暴露 ``bark_device_key`` /
   ``api_key`` / ``token`` / ``password`` / ``last_error`` 原文本。
5. **失败优雅降级** — 任何子系统探测失败时跳过对应 metric，整端点
   永远 200，最坏情况返回空 body（监控会 alert metric staleness）。
6. **rate-limit 120/min** — 与 health 端点同档，覆盖 Prometheus 默认
   15 s 抓取 + 多副本余量。

测试覆盖
--------
1. **Prometheus 格式化 helpers**（10 cases）
   - ``_escape_prom_label_value``：反斜杠 / 双引号 / 换行三件套转义
   - ``_format_prom_labels``：空 dict / 单 label / 多 label / 顺序保持
   - ``_format_prom_metric``：HELP/TYPE/value 三行结构、int/float、
     特殊值（inf/-inf/NaN）、带 / 不带 labels

2. **``_render_prometheus_metrics`` 整体输出**（5 cases）
   - 默认情形非空 + 含 ``aiia_uptime_seconds`` / ``aiia_build_info``
   - 所有 metric 名都以 ``aiia_`` 开头（namespace 一致性）
   - 任何子系统 ``_safe_*`` helper 抛异常时不让整体崩溃
   - PII 不出现在输出中（``bark_device_key`` / ``api_key`` 等关键字）
   - 每条 metric 都有配套 ``# HELP`` + ``# TYPE`` 行

3. **HTTP 端点契约**（4 cases）
   - ``GET /api/system/metrics`` 返回 200
   - Content-Type 是 ``text/plain; version=0.0.4; charset=utf-8``
   - body 含 ``# HELP aiia_uptime_seconds`` 等关键 metric 标记
   - 限流 ``120 per minute`` 装饰器存在（不真跑限流，那是 Flask-Limiter 自测）

4. **回归保护**（2 cases）
   - handler docstring 显式提到 R186 / T1 标记，方便未来 grep 定位
   - handler 不直接 import ``prometheus_client``（保持零依赖契约）
"""

from __future__ import annotations

import math
import re
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes import system as system_module

SOURCE = Path(system_module.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Prometheus 格式化 helpers — 字符级单元测试
# ---------------------------------------------------------------------------


class TestEscapePromLabelValue(unittest.TestCase):
    """``_escape_prom_label_value`` 是 PII 安全的最后一道屏障——任何
    label value 必须先走它再嵌入 ``{key="..."}``，否则注入换行就能
    伪造一行新的 metric 行欺骗 Prometheus parser。
    """

    def test_escapes_backslash(self) -> None:
        self.assertEqual(
            system_module._escape_prom_label_value(r"path\to\file"),
            r"path\\to\\file",
        )

    def test_escapes_double_quote(self) -> None:
        self.assertEqual(
            system_module._escape_prom_label_value('say "hi"'),
            'say \\"hi\\"',
        )

    def test_escapes_newline(self) -> None:
        self.assertEqual(
            system_module._escape_prom_label_value("line1\nline2"),
            "line1\\nline2",
        )

    def test_escapes_all_three_together(self) -> None:
        raw = 'path\\with"quote\nand newline'
        out = system_module._escape_prom_label_value(raw)
        self.assertEqual(out, 'path\\\\with\\"quote\\nand newline')

    def test_empty_string_pass_through(self) -> None:
        self.assertEqual(system_module._escape_prom_label_value(""), "")


class TestFormatPromLabels(unittest.TestCase):
    def test_empty_dict_returns_empty_string(self) -> None:
        self.assertEqual(system_module._format_prom_labels({}), "")

    def test_none_returns_empty_string(self) -> None:
        self.assertEqual(system_module._format_prom_labels(None), "")

    def test_single_label(self) -> None:
        self.assertEqual(
            system_module._format_prom_labels({"version": "1.7.0"}),
            '{version="1.7.0"}',
        )

    def test_multiple_labels_preserve_insertion_order(self) -> None:
        result = system_module._format_prom_labels(
            {"version": "1.7.0", "git_commit": "abc123"}
        )
        # insertion order 必须保留——避免每次 scrape 输出抖动让 diff 工具误判
        self.assertEqual(result, '{version="1.7.0",git_commit="abc123"}')

    def test_label_value_is_escaped(self) -> None:
        result = system_module._format_prom_labels({"path": 'C:\\foo "bar"'})
        self.assertEqual(result, '{path="C:\\\\foo \\"bar\\""}')


class TestFormatPromMetric(unittest.TestCase):
    def test_counter_emits_three_lines(self) -> None:
        out = system_module._format_prom_metric(
            "aiia_test_total",
            42,
            help_text="A test counter.",
            metric_type="counter",
        )
        lines = out.splitlines()
        self.assertEqual(lines[0], "# HELP aiia_test_total A test counter.")
        self.assertEqual(lines[1], "# TYPE aiia_test_total counter")
        self.assertEqual(lines[2], "aiia_test_total 42")

    def test_gauge_with_labels(self) -> None:
        out = system_module._format_prom_metric(
            "aiia_test_gauge",
            3.14,
            help_text="A test gauge.",
            metric_type="gauge",
            labels={"env": "prod"},
        )
        self.assertIn('aiia_test_gauge{env="prod"} 3.14', out)
        self.assertIn("# TYPE aiia_test_gauge gauge", out)

    def test_int_value_renders_as_integer(self) -> None:
        out = system_module._format_prom_metric(
            "aiia_x", 100, help_text="x", metric_type="counter"
        )
        self.assertIn("aiia_x 100\n", out)

    def test_float_inf_renders_as_plus_inf(self) -> None:
        out = system_module._format_prom_metric(
            "aiia_x",
            math.inf,
            help_text="x",
            metric_type="gauge",
        )
        self.assertIn("aiia_x +Inf\n", out)

    def test_float_negative_inf_renders_as_minus_inf(self) -> None:
        out = system_module._format_prom_metric(
            "aiia_x",
            -math.inf,
            help_text="x",
            metric_type="gauge",
        )
        self.assertIn("aiia_x -Inf\n", out)

    def test_float_nan_renders_as_nan(self) -> None:
        out = system_module._format_prom_metric(
            "aiia_x",
            math.nan,
            help_text="x",
            metric_type="gauge",
        )
        self.assertIn("aiia_x NaN\n", out)


# ---------------------------------------------------------------------------
# 2. _render_prometheus_metrics 整体行为
# ---------------------------------------------------------------------------


class TestRenderPrometheusMetrics(unittest.TestCase):
    """``_render_prometheus_metrics`` 是端点的核心——必须在任何
    子系统状态下都输出合规、可被 Prometheus parser 接受的 payload。
    """

    def test_render_returns_non_empty_payload_by_default(self) -> None:
        out = system_module._render_prometheus_metrics()
        self.assertIsInstance(out, str)
        self.assertGreater(
            len(out),
            0,
            "默认情形下至少应能渲染 uptime / build_info 等基础 metric",
        )

    def test_contains_core_uptime_and_build_info_metrics(self) -> None:
        out = system_module._render_prometheus_metrics()
        self.assertIn("# TYPE aiia_uptime_seconds gauge", out)
        self.assertIn("# TYPE aiia_build_info gauge", out)
        self.assertIn("aiia_uptime_seconds ", out)

    def test_all_metric_names_use_aiia_namespace(self) -> None:
        # 解析所有 ``# TYPE <name> <type>`` 行，断言全部以 ``aiia_`` 开头
        # —— 命名一致是监控仪表板按 dashboard 模板批量配规则的前提
        out = system_module._render_prometheus_metrics()
        type_lines = re.findall(r"^# TYPE (\S+) ", out, re.MULTILINE)
        self.assertGreater(len(type_lines), 0)
        for name in type_lines:
            self.assertTrue(
                name.startswith("aiia_"),
                f"metric {name!r} 必须以 aiia_ 前缀（命名空间一致性契约）",
            )

    def test_every_metric_has_help_and_type_pair(self) -> None:
        # Prometheus 不强制要求 HELP + TYPE，但缺少时 Grafana auto-suggest
        # 会失效。手写 exporter 要保证每条 metric 都有完整三件套。
        out = system_module._render_prometheus_metrics()
        help_names = set(re.findall(r"^# HELP (\S+) ", out, re.MULTILINE))
        type_names = set(re.findall(r"^# TYPE (\S+) ", out, re.MULTILINE))
        self.assertEqual(
            help_names,
            type_names,
            f"HELP 和 TYPE 行必须一一对应，HELP-only={help_names - type_names} / TYPE-only={type_names - help_names}",
        )

    def test_render_does_not_explode_when_subsystem_fails(self) -> None:
        # 模拟 SSE bus / notification subsystem / task queue 都炸的极端情形
        # —— /metrics 必须依然返回字符串（可能很短），不能 raise
        with (
            patch(
                "ai_intervention_agent.web_ui_routes.task._sse_bus",
                side_effect=RuntimeError("simulated bus failure"),
            ),
            patch.object(
                system_module,
                "_safe_notification_summary",
                side_effect=RuntimeError("simulated notif failure"),
            ),
        ):
            try:
                out = system_module._render_prometheus_metrics()
            except Exception as exc:
                self.fail(f"_render_prometheus_metrics 不应该 raise：{exc!r}")
            self.assertIsInstance(out, str)

    def test_payload_does_not_leak_pii_keys(self) -> None:
        # 关键 PII 字段名不该出现在 metric 输出里——哪怕是 label name
        # 也不行（label key 也是公开的 metric metadata）
        out = system_module._render_prometheus_metrics()
        for pii_keyword in ("bark_device_key", "api_key", "password", "token"):
            self.assertNotIn(
                pii_keyword,
                out,
                f"PII 关键字 {pii_keyword!r} 不能出现在 /metrics 输出中",
            )


# ---------------------------------------------------------------------------
# 3. HTTP 端点契约
# ---------------------------------------------------------------------------


class _SystemRouteBase(unittest.TestCase):
    """复用 ``test_web_ui_routes_system.py`` 的限流关闭 + 测试客户端 fixture。"""

    _port: int = 19186
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="metrics route test", task_id="metrics-rt", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


class TestPrometheusEndpoint(_SystemRouteBase):
    def test_get_metrics_returns_200(self) -> None:
        resp = self._client.get("/api/system/metrics")
        self.assertEqual(resp.status_code, 200, "Prometheus scrape 必须返回 200")

    def test_content_type_is_prometheus_exposition_format(self) -> None:
        resp = self._client.get("/api/system/metrics")
        ctype = resp.headers.get("Content-Type", "")
        # Prometheus parser 通过 Content-Type 决定怎么 parse；version=0.0.4
        # 是当前 stable exposition format 标识
        self.assertIn("text/plain", ctype)
        self.assertIn("version=0.0.4", ctype)
        self.assertIn("charset=utf-8", ctype)

    def test_body_contains_uptime_help_marker(self) -> None:
        resp = self._client.get("/api/system/metrics")
        body = resp.get_data(as_text=True)
        # 至少要有 uptime metric 的 HELP/TYPE/value 三件套
        self.assertIn("# HELP aiia_uptime_seconds", body)
        self.assertIn("# TYPE aiia_uptime_seconds gauge", body)

    def test_body_does_not_include_json_envelope(self) -> None:
        # 与 health 端点不同，/metrics 输出是纯文本 prom 格式
        # —— 任何 ``{"success": true...}`` 风格 envelope 都是 bug
        resp = self._client.get("/api/system/metrics")
        body = resp.get_data(as_text=True)
        self.assertFalse(
            body.lstrip().startswith("{"),
            "/metrics body 必须是纯 prom 文本，不能是 JSON envelope",
        )


# ---------------------------------------------------------------------------
# 4. 回归保护
# ---------------------------------------------------------------------------


class TestSourceLevelRegressions(unittest.TestCase):
    """source-level 契约保护——避免重构时把 R186 关键设计点弄丢。"""

    def test_handler_has_t1_or_r186_marker_in_docstring(self) -> None:
        # 让未来 ``rg "T1|R186" src/`` 能秒定位到这块功能
        self.assertRegex(
            SOURCE,
            r"system_metrics\(\)[^\n]*\n[^\n]*\"\"\"[\s\S]*?(R186|T1)",
            "system_metrics handler docstring 必须显式提到 R186 或 T1 标记",
        )

    def test_module_does_not_import_prometheus_client(self) -> None:
        # 零依赖契约——出现 prometheus_client import 就说明有人偷懒
        # 引入了我们想要避免的 4MB+ wheel
        self.assertNotIn(
            "import prometheus_client",
            SOURCE,
            "system.py 不能 import prometheus_client（手写 exposition format 是 R186 设计前提）",
        )
        self.assertNotIn(
            "from prometheus_client",
            SOURCE,
            "system.py 不能 from prometheus_client（手写 exposition format 是 R186 设计前提）",
        )

    def test_rate_limit_120_per_min_decorator_present(self) -> None:
        # 端点必须显式装饰 @self.limiter.limit("120 per minute")
        # —— 与 health 端点同档，覆盖 Prometheus 默认 15s 抓 + 多副本余量
        m = re.search(
            r'@self\.limiter\.limit\("120 per minute"\)\s*\n\s*def system_metrics',
            SOURCE,
        )
        self.assertIsNotNone(
            m,
            "system_metrics 必须用 @self.limiter.limit('120 per minute') 装饰",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
