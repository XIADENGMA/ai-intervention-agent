"""R51-B：SSE generator named-event heartbeat + ``_heartbeat_total`` 计数器契约。

关键不变量：

  1. ``_SSEBus`` 暴露 ``_heartbeat_total`` 字段、``bump_heartbeat()`` 方法、
     ``stats_snapshot()['heartbeat_total']`` 字段。
  2. ``bump_heartbeat()`` 是线程安全的（多线程并发 bump 后，最终值 = 总次数）。
  3. ``/api/events`` generator 在 ``q.get`` 超时时 yield 的是 named event
     ``event: heartbeat\\ndata: {...}\\n\\n``，不再是 SSE comment 行。
  4. 静态扫源码：``static/js/multi_task.js`` / ``packages/vscode/extension.ts``
     都注册了 heartbeat listener。
"""

from __future__ import annotations

import json
import re
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes import task as task_module


class TestHeartbeatCounterShape(unittest.TestCase):
    """``_SSEBus`` 必须暴露 ``_heartbeat_total`` / ``bump_heartbeat`` / 快照字段。"""

    def test_bus_has_heartbeat_total_attribute(self) -> None:
        bus = task_module._SSEBus()
        self.assertTrue(hasattr(bus, "_heartbeat_total"))
        self.assertEqual(bus._heartbeat_total, 0)

    def test_bus_has_bump_heartbeat_method(self) -> None:
        bus = task_module._SSEBus()
        self.assertTrue(hasattr(bus, "bump_heartbeat"))
        self.assertTrue(callable(bus.bump_heartbeat))

    def test_bump_heartbeat_increments(self) -> None:
        bus = task_module._SSEBus()
        bus.bump_heartbeat()
        bus.bump_heartbeat()
        bus.bump_heartbeat()
        self.assertEqual(bus._heartbeat_total, 3)

    def test_stats_snapshot_includes_heartbeat_total(self) -> None:
        bus = task_module._SSEBus()
        bus.bump_heartbeat()
        snap = bus.stats_snapshot()
        self.assertIn("heartbeat_total", snap)
        self.assertEqual(snap["heartbeat_total"], 1)


class TestBumpHeartbeatThreadSafety(unittest.TestCase):
    """多线程并发 ``bump_heartbeat`` 不应丢更新。"""

    def test_concurrent_bumps_all_counted(self) -> None:
        bus = task_module._SSEBus()
        threads_count = 8
        bumps_per_thread = 200

        def _worker() -> None:
            for _ in range(bumps_per_thread):
                bus.bump_heartbeat()

        threads = [threading.Thread(target=_worker) for _ in range(threads_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(bus._heartbeat_total, threads_count * bumps_per_thread)


class TestGeneratorYieldsNamedHeartbeat(unittest.TestCase):
    """``/api/events`` generator 必须在 ``q.get`` 超时时 yield named event。

    用静态源码扫描验证（不起 Flask）：
    - generator 体内必须出现 ``event: heartbeat`` 字面量；
    - 不应再出现旧的 SSE comment ``: heartbeat`` 行；
    - 必须调 ``_sse_bus.bump_heartbeat()``。
    """

    def setUp(self) -> None:
        self.src = Path(task_module.__file__).read_text(encoding="utf-8")

    def test_generator_yields_named_heartbeat_event(self) -> None:
        # 把 generator 体框出来：从 ``def generate():`` 起到下一个 ``return Response``
        m = re.search(r"def generate\(\):.*?return Response", self.src, re.DOTALL)
        self.assertIsNotNone(m, "无法定位 generate() 方法体")
        assert m is not None
        body = m.group(0)
        self.assertIn(
            "event: heartbeat",
            body,
            "generator 必须 yield named event ``event: heartbeat``（R51-B）",
        )

    def test_generator_calls_bump_heartbeat(self) -> None:
        m = re.search(r"def generate\(\):.*?return Response", self.src, re.DOTALL)
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        self.assertIn(
            "_sse_bus.bump_heartbeat()",
            body,
            "generator 必须在 yield heartbeat 时调用 _sse_bus.bump_heartbeat()",
        )

    def test_generator_uses_dedicated_heartbeat_payload_formatter(self) -> None:
        m = re.search(
            r"except queue\.Empty:.*?yield f\"event: heartbeat",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        heartbeat_branch = m.group(0)
        self.assertIn(
            "_format_sse_heartbeat_payload()",
            heartbeat_branch,
            "heartbeat 分支应使用专用 formatter，避免每个 idle tick 都走 json.dumps",
        )
        self.assertNotIn(
            "json.dumps(",
            heartbeat_branch,
            "heartbeat payload 是单字段整数 JSON，不应走通用 json.dumps hot path",
        )

    def test_generator_no_longer_uses_comment_heartbeat(self) -> None:
        """旧的 ``: heartbeat`` SSE comment 不应再出现在 generator 里。"""
        m = re.search(r"def generate\(\):.*?return Response", self.src, re.DOTALL)
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        self.assertNotIn(
            ': heartbeat\\n\\n"',
            body,
            "comment heartbeat 已废弃，不应再 yield ``: heartbeat\\n\\n``",
        )


class TestHeartbeatPayloadFormatter(unittest.TestCase):
    """R468：heartbeat payload 是固定单字段整数 JSON，避免通用 JSON encoder。"""

    def test_formatter_returns_parseable_integer_payload_without_json_dumps(
        self,
    ) -> None:
        with patch(
            "ai_intervention_agent.web_ui_routes.task.json.dumps",
            side_effect=AssertionError("heartbeat formatter must not call json.dumps"),
        ):
            payload = task_module._format_sse_heartbeat_payload(1_700_000_000.9)

        self.assertEqual(payload, '{"ts_unix":1700000000}')
        self.assertEqual(json.loads(payload), {"ts_unix": 1_700_000_000})

    def test_formatter_rejects_non_finite_or_non_numeric_time(self) -> None:
        self.assertEqual(task_module._format_sse_heartbeat_payload(float("inf")), "{}")
        self.assertEqual(task_module._format_sse_heartbeat_payload(float("nan")), "{}")
        self.assertEqual(task_module._format_sse_heartbeat_payload("not-time"), "{}")


class TestFrontendHeartbeatListener(unittest.TestCase):
    """``static/js/multi_task.js`` 和 ``packages/vscode/extension.ts`` 都要注册 listener。"""

    def test_multi_task_js_has_heartbeat_listener(self) -> None:
        path = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "static"
            / "js"
            / "multi_task.js"
        )
        src = path.read_text(encoding="utf-8")
        # 引号风格无关：Prettier 默认双引号 + 项目内未强制 singleQuote。锁
        # 住「listener 存在」即可，避免 reformat 整个文件就让回归测假阴。
        self.assertRegex(
            src,
            r"addEventListener\(['\"]heartbeat['\"]",
            "multi_task.js 必须注册 heartbeat listener（R51-B）",
        )

    def test_extension_ts_handles_heartbeat(self) -> None:
        path = REPO_ROOT / "packages" / "vscode" / "extension.ts"
        src = path.read_text(encoding="utf-8")
        self.assertRegex(
            src,
            r"evType === ['\"]heartbeat['\"]",
            "extension.ts 必须处理 evType === heartbeat 分支（R51-B）",
        )
        self.assertIn(
            "sse.heartbeat",
            src,
            "extension.ts heartbeat 分支应当 logger.event('sse.heartbeat', ...)",
        )


if __name__ == "__main__":
    unittest.main()
