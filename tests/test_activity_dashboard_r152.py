"""R152 — Activity Dashboard subsection inside the settings panel.

Background
----------
R141-R150 shipped a comprehensive server-side observability stack:
``/api/system/health`` (server status + per-provider notification stats
with success_streak / failure_streak / last_error_class),
``/api/system/sse-stats`` (emit_total, subscriber_count, heartbeat_total,
P50 / P95 emit→deliver latency), ``/api/tasks`` (pending / active /
completed / total task queue counters) and ``/api/system/recent-logs``
(redacted recent WARNING / ERROR ring buffer entries).  Up to R150 the
only way to read all four was ``curl`` — fine for ops dashboards, not
great for end-users.

R152 closes that loop with a collapsed-by-default Activity Dashboard
subsection in the settings panel.  Clicking the toggle expands a
``<dl>`` of six rows (tasks · sse · latency · notif · health · logs),
fetches the four endpoints in parallel every 5 s, and pauses polling
when the tab is in the background.

Constraints / invariants locked by this suite
---------------------------------------------
1.  **常量锁定** — dashboard / toggle / body / row-id prefix, four
    endpoint paths, three poll constants (default / min / max),
    fetch-timeout cap, six row definitions.
2.  **API 表面** — ``_fetchJson``, ``_formatTasks``, ``_formatSse``,
    ``_formatLatency``, ``_formatNotif``, ``_formatHealth``,
    ``_formatLogs``, ``_ensureRow``, ``_writeRow``, ``_renderAll``,
    ``_pollOnce``, ``_open``, ``_close``, ``init``, ``setPollMs``,
    ``getLastRender`` all exported on ``window.AIIA_ACTIVITY_DASHBOARD``.
3.  **safety 锁** — every formatter handles the null / non-object input
    gracefully (returns ``null`` or an "empty" i18n key), every
    formatter slices long string fields to bound layout, and
    ``_writeRow`` caps written text at 256 chars.
4.  **lifecycle** — ``_open`` flips ``aria-expanded`` true and starts
    polling; ``_close`` flips it false and aborts the in-flight fetch.
    ``init`` is idempotent via the ``data-r152-bound="1"`` sentinel.
5.  **visibility 适配** — handler registered on ``open``, removed on
    ``close``; reacts to ``document.hidden``.
6.  **HTML elements** — ``web_ui.html`` ships the dashboard section,
    toggle button + ``aria-controls`` / ``aria-expanded`` / hint
    paragraph + ``<dl>`` body with ``aria-live="polite"`` and the
    ``hidden`` attribute.
7.  **i18n 完整性** — All eleven new keys are present in en + zh-CN +
    _pseudo locale files with the right Mustache placeholders.
8.  **CSS 锁** — ``.activity-dashboard-body``,
    ``.activity-dashboard-row``, ``.activity-dashboard-label``,
    ``.activity-dashboard-value``, ``.activity-dashboard-stale``
    selectors are all defined in main.css.
9.  **script wiring** — ``activity_dashboard.js`` is loaded via
    cache-busted version string injected from
    ``activity_dashboard_version`` in ``web_ui.py``.
10. **JS file size envelope** — file stays under 700 lines (the IIFE is
    intentionally small; future growth should split modules).

A failing case here usually means either the JS code or the HTML markup
drifted out of lockstep with the test contract; in that case fix the
source rather than relaxing the test, because the contract is exactly
what the user-facing dashboard depends on.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/activity_dashboard.js"
HTML_PATH = ROOT / "src/ai_intervention_agent/templates/web_ui.html"
WEB_UI_PY_PATH = ROOT / "src/ai_intervention_agent/web_ui.py"
LOCALE_EN = ROOT / "src/ai_intervention_agent/static/locales/en.json"
LOCALE_ZH = ROOT / "src/ai_intervention_agent/static/locales/zh-CN.json"
LOCALE_PSEUDO = ROOT / "src/ai_intervention_agent/static/locales/_pseudo/pseudo.json"
CSS_PATH = ROOT / "src/ai_intervention_agent/static/css/main.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _read_locale(p: Path) -> dict:
    return json.loads(_read(p))


DASHBOARD_KEYS = (
    "activityDashboardToggle",
    "activityDashboardHint",
    "activityDashboardRowTasks",
    "activityDashboardRowSse",
    "activityDashboardRowLatency",
    "activityDashboardRowNotif",
    "activityDashboardRowHealth",
    "activityDashboardRowLogs",
    "activityDashboardTasksValue",
    "activityDashboardSseValue",
    "activityDashboardLatencyEmpty",
    "activityDashboardLatencyValue",
    "activityDashboardNotifEmpty",
    "activityDashboardNotifLine",
    "activityDashboardHealthValue",
    "activityDashboardLogsValue",
)


class TestR152Constants(unittest.TestCase):
    """常量锁定 — id / 端点 / 轮询窗口 / 超时."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_dashboard_id_matches_html(self) -> None:
        m = re.search(r'DASHBOARD_ID\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m, "DASHBOARD_ID 必须存在")
        assert m is not None
        dashboard_id = m.group(1)
        html = _read(HTML_PATH)
        self.assertIn(
            f'id="{dashboard_id}"',
            html,
            f"web_ui.html 必须有 id={dashboard_id!r} 的 dashboard section",
        )

    def test_toggle_id_matches_html(self) -> None:
        m = re.search(r'TOGGLE_ID\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m)
        assert m is not None
        toggle_id = m.group(1)
        html = _read(HTML_PATH)
        self.assertIn(f'id="{toggle_id}"', html)

    def test_body_id_matches_html(self) -> None:
        m = re.search(r'BODY_ID\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m)
        assert m is not None
        body_id = m.group(1)
        html = _read(HTML_PATH)
        self.assertIn(f'id="{body_id}"', html)

    def test_endpoint_paths_documented(self) -> None:
        for var, expected in (
            ("ENDPOINT_HEALTH", "/api/system/health"),
            ("ENDPOINT_SSE_STATS", "/api/system/sse-stats"),
            ("ENDPOINT_TASKS", "/api/tasks"),
        ):
            m = re.search(rf'{var}\s*=\s*"([^"]+)"', self.js)
            self.assertIsNotNone(m, f"{var} 必须存在")
            assert m is not None
            self.assertEqual(
                m.group(1),
                expected,
                f"{var} 必须 = {expected!r}",
            )

    def test_recent_logs_endpoint_has_limit(self) -> None:
        m = re.search(r'ENDPOINT_RECENT_LOGS\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m, "ENDPOINT_RECENT_LOGS 必须存在")
        assert m is not None
        endpoint = m.group(1)
        self.assertTrue(
            endpoint.startswith("/api/system/recent-logs"),
            f"ENDPOINT_RECENT_LOGS 必须落在 /api/system/recent-logs：{endpoint!r}",
        )
        self.assertIn(
            "limit=",
            endpoint,
            "ENDPOINT_RECENT_LOGS 必须明确指定 limit 参数避免无界拉取",
        )

    def test_poll_constants_in_range(self) -> None:
        for var, expected in (
            ("POLL_MS_DEFAULT", 5000),
            ("POLL_MS_MIN", 1000),
            ("POLL_MS_MAX", 60000),
            ("FETCH_TIMEOUT_MS", 4000),
        ):
            m = re.search(rf"{var}\s*=\s*(\d+)", self.js)
            self.assertIsNotNone(m, f"{var} 必须存在")
            assert m is not None
            self.assertEqual(
                int(m.group(1)),
                expected,
                f"{var} 锁定为 {expected}",
            )

    def test_fetch_timeout_below_poll_default(self) -> None:
        """超时必须 < 轮询周期，不然两次 poll 会重叠."""
        timeout = int(
            re.search(r"FETCH_TIMEOUT_MS\s*=\s*(\d+)", self.js).group(1)  # type: ignore
        )
        default_ms = int(
            re.search(r"POLL_MS_DEFAULT\s*=\s*(\d+)", self.js).group(1)  # type: ignore
        )
        self.assertLess(
            timeout, default_ms, "FETCH_TIMEOUT_MS 必须小于 POLL_MS_DEFAULT"
        )


class TestR152RowDefs(unittest.TestCase):
    """ROW_DEFS — 6 行表面契约."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_row_defs_block_present(self) -> None:
        self.assertIn(
            "var ROW_DEFS = [",
            self.js,
            "ROW_DEFS 数组必须存在（顺序锁）",
        )

    def test_all_six_rows_referenced(self) -> None:
        for row_id in ("tasks", "sse", "latency", "notif", "health", "logs"):
            self.assertIn(
                f'id: "{row_id}"',
                self.js,
                f"ROW_DEFS 必须包含 id={row_id!r} 的行",
            )

    def test_all_six_rows_use_settings_namespace_labels(self) -> None:
        labels = re.findall(r'label:\s*"settings\.activityDashboard(\w+)"', self.js)
        self.assertEqual(
            len(labels),
            6,
            f"必须有 6 个 settings.activityDashboard.* 的 label，实际 {labels!r}",
        )


class TestR152APISurface(unittest.TestCase):
    """函数 / module export 表面契约."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_helpers_defined(self) -> None:
        for name in (
            "_fetchJson",
            "_formatTasks",
            "_formatSse",
            "_formatLatency",
            "_formatNotif",
            "_formatHealth",
            "_formatLogs",
            "_ensureRow",
            "_writeRow",
            "_renderAll",
            "_pollOnce",
            "_startPolling",
            "_stopPolling",
            "_open",
            "_close",
        ):
            self.assertRegex(
                self.js,
                rf"function\s+{name}\b",
                f"{name} 必须以 function 形式定义",
            )

    def test_public_init_exists(self) -> None:
        self.assertRegex(self.js, r"function\s+init\b")

    def test_set_poll_ms_exists(self) -> None:
        self.assertRegex(self.js, r"function\s+setPollMs\b")

    def test_get_last_render_exists(self) -> None:
        self.assertRegex(self.js, r"function\s+getLastRender\b")

    def test_window_export_namespace(self) -> None:
        self.assertIn(
            "window.AIIA_ACTIVITY_DASHBOARD",
            self.js,
            "必须挂载到 window.AIIA_ACTIVITY_DASHBOARD",
        )

    def test_public_exports_included(self) -> None:
        for key in (
            "init:",
            "setPollMs:",
            "getLastRender:",
            "_fetchJson:",
            "_pollOnce:",
            "_open:",
            "_close:",
        ):
            self.assertIn(
                key,
                self.js,
                f"window.AIIA_ACTIVITY_DASHBOARD 必须 export {key}",
            )


class TestR152SafetyDefenses(unittest.TestCase):
    """格式化器对脏输入 / 缺失字段的防御 + 长度截断 + 中止信号."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_fetch_uses_same_origin(self) -> None:
        self.assertIn(
            'credentials: "same-origin"',
            self.js,
            "_fetchJson 必须明确 credentials=same-origin（保留 cookie）",
        )

    def test_fetch_handles_non_ok(self) -> None:
        self.assertIn(
            "if (!resp.ok) return null;",
            self.js,
            "_fetchJson 必须在 non-OK 时返回 null 而不抛异常",
        )

    def test_fetch_passes_abort_signal(self) -> None:
        self.assertRegex(
            self.js,
            r"signal:\s*controller\s*\?\s*controller\.signal\s*:\s*undefined",
            "_fetchJson 必须把 AbortController.signal 传给 fetch",
        )

    def test_writerow_caps_text_length(self) -> None:
        # textContent 截断保护：长度 256 + ellipsis
        self.assertRegex(
            self.js,
            r"text\.length\s*>\s*256",
            "_writeRow 必须把超长 text 截断到 256 字符",
        )

    def test_health_status_sliced(self) -> None:
        self.assertRegex(
            self.js,
            r"health\.status\s*\|\|\s*\"unknown\"\)\.slice\(0,\s*16\)",
            "health.status 必须 slice(0, 16) 防止 layout 击穿",
        )

    def test_notif_provider_sliced(self) -> None:
        self.assertRegex(
            self.js,
            r"k\.slice\(0,\s*16\)",
            "notification provider 名必须 slice(0, 16)",
        )


class TestR152DOMRender(unittest.TestCase):
    """渲染契约 — 只用 createElement + textContent + setAttribute."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_uses_create_element(self) -> None:
        self.assertIn(
            'document.createElement("div")',
            self.js,
            "_ensureRow 必须使用 createElement('div') 创建行容器",
        )
        self.assertIn('document.createElement("dt")', self.js)
        self.assertIn('document.createElement("dd")', self.js)

    def test_no_innerhtml_anywhere(self) -> None:
        self.assertNotIn(
            ".innerHTML",
            self.js,
            "禁止使用 innerHTML（DOM-XSS 风险）",
        )

    def test_stale_class_applied(self) -> None:
        self.assertIn(
            'row.classList.add("activity-dashboard-stale")',
            self.js,
            "_writeRow 必须在 stale 分支添加 .activity-dashboard-stale 类",
        )

    def test_stale_class_removed(self) -> None:
        self.assertIn(
            'row.classList.remove("activity-dashboard-stale")',
            self.js,
            "_writeRow 必须在 fresh 分支移除 stale 类",
        )

    def test_aria_expanded_toggle(self) -> None:
        self.assertIn(
            'toggleBtn.setAttribute("aria-expanded", "true")',
            self.js,
            "_open 必须把 aria-expanded 翻成 true",
        )
        self.assertIn(
            'toggleBtn.setAttribute("aria-expanded", "false")',
            self.js,
            "_close 必须把 aria-expanded 翻成 false",
        )

    def test_hidden_attribute_toggled(self) -> None:
        self.assertIn(
            'body.removeAttribute("hidden")',
            self.js,
            "_open 必须解除 [hidden]",
        )
        self.assertIn(
            'body.setAttribute("hidden", "")',
            self.js,
            "_close 必须重新设置 [hidden]",
        )


class TestR152LifecycleAndPolling(unittest.TestCase):
    """轮询启动 / 取消 / visibility / idempotent init."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_polling_clears_interval(self) -> None:
        self.assertIn(
            "clearInterval(_state.timerId)",
            self.js,
            "_stopPolling 必须 clearInterval",
        )

    def test_polling_aborts_inflight(self) -> None:
        self.assertIn(
            "_state.inflight.abort()",
            self.js,
            "_stopPolling 必须 abort 在飞的 fetch",
        )

    def test_visibility_listener_registered(self) -> None:
        self.assertIn(
            'document.addEventListener("visibilitychange"',
            self.js,
            "_open 必须挂 visibilitychange 监听器",
        )

    def test_visibility_listener_unregistered(self) -> None:
        self.assertIn(
            'document.removeEventListener(\n          "visibilitychange"',
            self.js,
            "_close 必须移除 visibilitychange 监听器",
        )

    def test_init_idempotent(self) -> None:
        # ``data-r152-bound="1"`` 哨兵；第二次 init 会快速返回
        self.assertIn(
            "data-r152-bound",
            self.js,
            "init 必须以 data-r152-bound 哨兵防止双绑定",
        )

    def test_kicks_immediate_poll_on_open(self) -> None:
        self.assertIn(
            "Promise.resolve().then(_pollOnce)",
            self.js,
            "_startPolling 必须先打一发 microtask poll，再 setInterval",
        )


class TestR152HtmlElements(unittest.TestCase):
    """web_ui.html 必须 ship 对应骨架."""

    def setUp(self) -> None:
        self.html = _read(HTML_PATH)

    def test_dashboard_section_present(self) -> None:
        self.assertIn(
            'id="activity-dashboard"',
            self.html,
            "web_ui.html 必须有 activity-dashboard section",
        )

    def test_toggle_button_attributes(self) -> None:
        # 必须是 <button type="button">  + aria-controls + aria-expanded
        # 不强求行序 — 用 multiline 正则匹配跨行的属性
        self.assertRegex(
            self.html,
            r'id="activity-dashboard-toggle"[^>]*\n[^<]*type="button"',
            "toggle 必须是 button type=button",
        )
        self.assertIn(
            'aria-controls="activity-dashboard-body"',
            self.html,
            "toggle 必须 aria-controls 指向 body",
        )
        self.assertIn(
            'aria-expanded="false"',
            self.html,
            "toggle 初始 aria-expanded=false",
        )

    def test_body_dl_attributes(self) -> None:
        # <dl id="activity-dashboard-body" ... role="region" aria-live="polite" hidden>
        self.assertIn('id="activity-dashboard-body"', self.html)
        self.assertIn('role="region"', self.html)
        self.assertIn('aria-labelledby="activity-dashboard-toggle"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        # 必须 hidden — collapse 状态
        body_block_match = re.search(
            r'<dl\s+[^>]*id="activity-dashboard-body"[^>]*>',
            self.html,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(
            body_block_match, "必须找到 <dl id=activity-dashboard-body>"
        )
        assert body_block_match is not None
        self.assertIn(
            "hidden",
            body_block_match.group(0),
            "<dl id=activity-dashboard-body> 必须默认 hidden",
        )

    def test_hint_text_present(self) -> None:
        self.assertIn(
            'data-i18n="settings.activityDashboardHint"',
            self.html,
            "hint paragraph 必须挂 data-i18n=activityDashboardHint",
        )


class TestR152ScriptWiring(unittest.TestCase):
    """activity_dashboard.js 必须由 web_ui.html 加载 + 版本号注入."""

    def test_script_tag_present(self) -> None:
        html = _read(HTML_PATH)
        self.assertRegex(
            html,
            r'src="/static/js/activity_dashboard\.js\?v=\{\{ activity_dashboard_version \}\}"',
            "web_ui.html 必须以 cache-busted 版本号引用 activity_dashboard.js",
        )

    def test_version_injection_in_web_ui_py(self) -> None:
        py = _read(WEB_UI_PY_PATH)
        self.assertIn(
            '"activity_dashboard_version"',
            py,
            "web_ui.py 必须在模板 context 中注入 activity_dashboard_version",
        )
        self.assertRegex(
            py,
            r'_compute_file_version\(\s*str\(static_dir\s*/\s*"js"\s*/\s*"activity_dashboard\.js"\)\s*\)',
            "activity_dashboard_version 必须由 _compute_file_version 算出",
        )


class TestR152I18nCoverage(unittest.TestCase):
    """所有 R152 i18n keys 必须出现在 en / zh-CN / pseudo 三份 locale 里."""

    def test_all_keys_in_en(self) -> None:
        data = _read_locale(LOCALE_EN)
        settings = data.get("settings", {})
        for key in DASHBOARD_KEYS:
            self.assertIn(key, settings, f"en.json 缺 settings.{key}")

    def test_all_keys_in_zh(self) -> None:
        data = _read_locale(LOCALE_ZH)
        settings = data.get("settings", {})
        for key in DASHBOARD_KEYS:
            self.assertIn(key, settings, f"zh-CN.json 缺 settings.{key}")

    def test_all_keys_in_pseudo(self) -> None:
        data = _read_locale(LOCALE_PSEUDO)
        settings = data.get("settings", {})
        for key in DASHBOARD_KEYS:
            self.assertIn(key, settings, f"_pseudo/pseudo.json 缺 settings.{key}")

    def test_mustache_signatures_match(self) -> None:
        """en 与 zh 的 placeholder 必须一致（dead-key analyzer 静态保证）."""
        en = _read_locale(LOCALE_EN).get("settings", {})
        zh = _read_locale(LOCALE_ZH).get("settings", {})
        for key in DASHBOARD_KEYS:
            en_params = sorted(re.findall(r"\{\{(\w+)\}\}", en.get(key, "")))
            zh_params = sorted(re.findall(r"\{\{(\w+)\}\}", zh.get(key, "")))
            self.assertEqual(
                en_params,
                zh_params,
                f"en / zh 在 {key} 的 mustache 签名不一致: "
                f"en={en_params!r} zh={zh_params!r}",
            )

    def test_tasks_value_signature(self) -> None:
        en = _read_locale(LOCALE_EN).get("settings", {})
        params = sorted(
            re.findall(r"\{\{(\w+)\}\}", en.get("activityDashboardTasksValue", ""))
        )
        self.assertEqual(
            params,
            ["active", "completed", "pending", "total"],
            "activityDashboardTasksValue 必须含 pending / active / completed / total",
        )

    def test_sse_value_signature(self) -> None:
        en = _read_locale(LOCALE_EN).get("settings", {})
        params = sorted(
            re.findall(r"\{\{(\w+)\}\}", en.get("activityDashboardSseValue", ""))
        )
        self.assertEqual(
            params,
            ["emit", "heartbeat", "subs"],
            "activityDashboardSseValue 必须含 emit / subs / heartbeat",
        )


class TestR152CssDefinitions(unittest.TestCase):
    """主样式表必须定义对应的视觉契约."""

    def setUp(self) -> None:
        self.css = _read(CSS_PATH)

    def test_body_class_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.activity-dashboard-body\s*\{",
            "main.css 必须定义 .activity-dashboard-body",
        )

    def test_row_class_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.activity-dashboard-row\s*\{",
            "main.css 必须定义 .activity-dashboard-row",
        )

    def test_label_value_classes_defined(self) -> None:
        self.assertRegex(self.css, r"\.activity-dashboard-label\s*\{")
        self.assertRegex(self.css, r"\.activity-dashboard-value\s*\{")

    def test_stale_class_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.activity-dashboard-stale\b",
            "main.css 必须定义 .activity-dashboard-stale（fetch 失败视觉）",
        )

    def test_uses_existing_vars_only(self) -> None:
        # 锁死 — 不能引入未定义变量。同 R150 修复教训
        forbidden = ("--surface-100", "--border-color")
        # 抓 R152 段落（.activity-dashboard-body 起点到下一个非 .activity-dashboard- 选择器）
        m = re.search(
            r"\.activity-dashboard-body\s*\{[\s\S]+?\n\.activity-dashboard-stale[\s\S]+?\}\n",
            self.css,
        )
        self.assertIsNotNone(m, "无法定位 R152 CSS 段")
        assert m is not None
        section = m.group(0)
        for var in forbidden:
            self.assertNotIn(
                var,
                section,
                f"R152 CSS 段禁止引用 {var}（未定义变量）",
            )


class TestR152FileSize(unittest.TestCase):
    """JS 文件不能膨胀；R152 IIFE 应保持精炼."""

    def test_js_under_700_lines(self) -> None:
        js = _read(JS_PATH)
        lines = js.count("\n") + 1
        self.assertLess(
            lines,
            700,
            f"activity_dashboard.js 必须 < 700 行（当前 {lines}）",
        )


if __name__ == "__main__":
    unittest.main()
