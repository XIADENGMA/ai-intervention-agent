"""R154 — System-endpoint payload contract: server fields ↔ JS consumers.

Background (the R152 → R153 lesson)
-----------------------------------
R152 shipped the Activity Dashboard wiring six rows from four
``/api/system/...`` endpoints.  Its 52-case test suite covered the
JS function-existence surface, constant values, DOM contract, i18n
parity, CSS class definitions, and the < 700 LoC envelope — but
**not** the payload field-name contract.  Result: ``_formatLogs``
read ``logs.logs`` while ``web_ui_routes/system.py::recent_logs``
shipped the array under ``entries`` — the logs row stayed
permanently ``stale`` whenever the endpoint responded.  R153 fixed
the field name + added a regression test for the *one* drifted field
inside ``_formatLogs``.  R154 generalises the protection: lock the
**whole** field surface (every consumer-visible JSON field on every
endpoint the dashboard reads) so the same class of regression cannot
ship again on a *different* row in the future.

What this suite locks
---------------------
For every endpoint the Activity Dashboard polls
(``/api/system/health``, ``/api/system/sse-stats``, ``/api/tasks``,
``/api/system/recent-logs``):

1.  **Server contract** — the Flask handler in
    ``web_ui_routes/system.py`` (or ``web_ui_routes/task.py``)
    actually emits the documented top-level keys via ``jsonify({...})``
    or a TypedDict ``stats_snapshot`` shape.  Caught by literal
    substring assertions on the source code.
2.  **Client contract** — ``static/js/activity_dashboard.js`` reads
    those keys, *not* a stale alias.  Caught by literal substring
    assertions on the field accessor (``logs.entries`` /
    ``sse.emit_total`` / ``tasks.stats`` / ``health.status`` /
    ``health.checks`` etc.).
3.  **Negative pin** — known-stale field aliases that previously
    shipped (``logs.logs`` from R152, hypothetically ``stats.tasks``
    if someone renames) **must not** appear in the JS source.

Why this isn't redundant with R153's bug-fix test
-------------------------------------------------
R153's ``test_format_logs_reads_entries_field`` locks *one*
positive + one negative assertion on *one* field.  R154 covers the
full quadruple-endpoint surface: tasks (`stats.{pending,active,
completed,total}`), sse-stats (`emit_total`, `subscriber_count`,
`heartbeat_total`, `latency_ms.{p50_ms,p95_ms,count}`), health
(`status`, `checks.notification.per_provider.<name>.{success_streak,
failure_streak}`), and recent-logs (`entries[].{level,ts_iso,
message}`).  When the next contributor renames any of these on
either side, this suite turns red at test-collection time rather
than five releases later when a user reports "the dashboard's been
showing all dashes for a week".

Maintenance hint
----------------
If a future endpoint *legitimately* renames a field, update both
sides + the assertion in this file in lockstep.  Do **not** weaken
the assertion to "either form is OK" — the whole point is that the
two sides are pinned together.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PY = ROOT / "src/ai_intervention_agent/web_ui_routes/system.py"
TASK_PY = ROOT / "src/ai_intervention_agent/web_ui_routes/task.py"
ACTIVITY_JS = ROOT / "src/ai_intervention_agent/static/js/activity_dashboard.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestR154RecentLogsContract(unittest.TestCase):
    """``/api/system/recent-logs`` ↔ JS ``_formatLogs`` field pinning."""

    def setUp(self) -> None:
        self.server = _read(SYSTEM_PY)
        self.client = _read(ACTIVITY_JS)

    def test_server_emits_entries_field(self) -> None:
        # ``jsonify({... "entries": entries ...})`` literal
        self.assertIn(
            '"entries": entries,',
            self.server,
            "recent_logs handler 必须 jsonify 出 ``entries`` 字段",
        )

    def test_server_emits_success_and_count(self) -> None:
        self.assertIn(
            '"success": True,',
            self.server,
            "recent_logs handler 必须 jsonify 出 ``success`` 字段",
        )
        self.assertIn(
            '"count": len(entries),',
            self.server,
            "recent_logs handler 必须 jsonify 出 ``count`` 字段",
        )

    def test_client_reads_entries_field(self) -> None:
        self.assertIn(
            "var entries = logs.entries;",
            self.client,
            "activity_dashboard.js 必须读 ``logs.entries``（R152 → R153 bug fix 教训）",
        )

    def test_client_never_reads_logs_dot_logs(self) -> None:
        # 旧的 R152 bug shape 不能再出现
        import re

        m = re.search(
            r"^\s*var\s+entries\s*=\s*logs\.logs\b", self.client, re.MULTILINE
        )
        self.assertIsNone(
            m,
            "activity_dashboard.js 不再有 ``var entries = logs.logs`` 这种 buggy 取值",
        )

    def test_log_entry_message_field(self) -> None:
        self.assertIn(
            "e.message",
            self.client,
            "log entry 渲染必须读 ``message`` 字段（server-side _build_entry 输出）",
        )

    def test_log_entry_level_field(self) -> None:
        self.assertIn(
            "e.level",
            self.client,
            "log entry 渲染必须读 ``level`` 字段",
        )

    def test_log_entry_ts_iso_field(self) -> None:
        self.assertIn(
            "e.ts_iso",
            self.client,
            "log entry 渲染必须读 ``ts_iso`` 字段",
        )


class TestR154SseStatsContract(unittest.TestCase):
    """``/api/system/sse-stats`` ↔ JS ``_formatSse`` / ``_formatLatency`` 字段."""

    def setUp(self) -> None:
        self.task_src = _read(TASK_PY)
        self.client = _read(ACTIVITY_JS)

    def test_server_emits_emit_total_subscriber_heartbeat(self) -> None:
        # _SSEBusStatsSnapshot TypedDict 字段（server-side 源代码）
        for field in (
            "emit_total: int",
            "subscriber_count: int",
            "heartbeat_total: int",
            "latency_ms: SSELatencySnapshot",
        ):
            self.assertIn(
                field,
                self.task_src,
                f"_SSEBusStatsSnapshot TypedDict 必须有 {field!r}",
            )

    def test_client_reads_emit_total(self) -> None:
        self.assertIn(
            "sse.emit_total",
            self.client,
            "activity_dashboard.js 必须读 ``sse.emit_total``",
        )

    def test_client_reads_subscriber_count(self) -> None:
        self.assertIn(
            "sse.subscriber_count",
            self.client,
            "activity_dashboard.js 必须读 ``sse.subscriber_count``",
        )

    def test_client_reads_heartbeat_total(self) -> None:
        self.assertIn(
            "sse.heartbeat_total",
            self.client,
            "activity_dashboard.js 必须读 ``sse.heartbeat_total``",
        )

    def test_client_reads_latency_p50_p95_count(self) -> None:
        # ``_formatLatency`` 读 sse.latency_ms.p50_ms / p95_ms / count
        for field in ("latency.p50_ms", "latency.p95_ms", "latency.count"):
            self.assertIn(
                field,
                self.client,
                f"activity_dashboard.js 必须读 sse.``{field}``",
            )


class TestR154TasksContract(unittest.TestCase):
    """``/api/tasks`` ↔ JS ``_formatTasks`` 字段."""

    def setUp(self) -> None:
        self.client = _read(ACTIVITY_JS)

    def test_client_reads_stats_subfield(self) -> None:
        # ``_formatTasks`` 读 tasks.stats，然后 stats.pending / active / completed / total
        self.assertIn(
            "tasks.stats",
            self.client,
            "activity_dashboard.js 必须读 ``tasks.stats``",
        )
        for f in ("stats.pending", "stats.active", "stats.completed", "stats.total"):
            self.assertIn(
                f,
                self.client,
                f"_formatTasks 必须读 ``{f}``",
            )


class TestR154HealthContract(unittest.TestCase):
    """``/api/system/health`` ↔ JS ``_formatHealth`` / ``_formatNotif`` 字段."""

    def setUp(self) -> None:
        self.server = _read(SYSTEM_PY)
        self.client = _read(ACTIVITY_JS)

    def test_server_emits_status_and_checks(self) -> None:
        # 系统健康 endpoint 必须 jsonify 出 status + checks
        self.assertIn(
            '"status":',
            self.server,
            "system_health handler 必须 jsonify 出 ``status`` 字段",
        )
        self.assertIn(
            '"checks":',
            self.server,
            "system_health handler 必须 jsonify 出 ``checks`` 字段",
        )

    def test_client_reads_health_status(self) -> None:
        self.assertIn(
            "health.status",
            self.client,
            "_formatHealth 必须读 ``health.status``",
        )

    def test_client_reads_checks_notification(self) -> None:
        self.assertIn(
            "health.checks",
            self.client,
            "_formatNotif 必须读 ``health.checks``",
        )
        self.assertIn(
            "checks.notification",
            self.client,
            "_formatNotif 必须读 ``checks.notification``",
        )
        self.assertIn(
            "notif.per_provider",
            self.client,
            "_formatNotif 必须读 ``checks.notification.per_provider``",
        )

    def test_client_reads_per_provider_streak_fields(self) -> None:
        self.assertIn(
            "stats.success_streak",
            self.client,
            "_formatNotif 必须读 ``per_provider[x].success_streak`` (R145)",
        )
        self.assertIn(
            "stats.failure_streak",
            self.client,
            "_formatNotif 必须读 ``per_provider[x].failure_streak`` (R145)",
        )


class TestR154EndpointURLs(unittest.TestCase):
    """4 个 endpoint 路径 + JS 引用一致（防 typo / 异型）."""

    def setUp(self) -> None:
        self.client = _read(ACTIVITY_JS)
        self.system_src = _read(SYSTEM_PY)
        self.task_src = _read(TASK_PY)

    def test_health_endpoint_match(self) -> None:
        self.assertIn(
            '"/api/system/health"',
            self.client,
            "JS 必须用字面 /api/system/health 作 endpoint",
        )
        self.assertIn(
            '"/api/system/health"',
            self.system_src,
            "Flask 必须在 system.py 注册 /api/system/health",
        )

    def test_sse_stats_endpoint_match(self) -> None:
        self.assertIn(
            '"/api/system/sse-stats"',
            self.client,
            "JS 必须用字面 /api/system/sse-stats 作 endpoint",
        )
        self.assertIn(
            '"/api/system/sse-stats"',
            self.system_src,
            "Flask 必须在 system.py 注册 /api/system/sse-stats",
        )

    def test_recent_logs_endpoint_match(self) -> None:
        # JS 端带 ``?limit=5``；server 端只匹配 path
        self.assertIn(
            '"/api/system/recent-logs?limit=5"',
            self.client,
            "JS 必须用字面 /api/system/recent-logs?limit=5 作 endpoint",
        )
        self.assertIn(
            '"/api/system/recent-logs"',
            self.system_src,
            "Flask 必须在 system.py 注册 /api/system/recent-logs",
        )

    def test_tasks_endpoint_match(self) -> None:
        self.assertIn(
            '"/api/tasks"',
            self.client,
            "JS 必须用字面 /api/tasks 作 endpoint",
        )
        # /api/tasks 注册在 task.py
        self.assertIn(
            '"/api/tasks"',
            self.task_src,
            "Flask 必须在 task.py 注册 /api/tasks",
        )


if __name__ == "__main__":
    unittest.main()
