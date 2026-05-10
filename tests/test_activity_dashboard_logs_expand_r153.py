"""R153 — Activity Dashboard logs row inline expand + R152 logs bug fix.

Background
----------
R152 shipped the Activity Dashboard with six rows; the ``logs`` row
showed a one-line summary like ``5 warnings · 2 errors · 12 recent``.
Two follow-ups closed important loops:

1.  **Server-payload field-name bug (R152 → R153 fix)** — R152's
    ``_formatLogs`` read ``logs.logs``, but the actual server response
    from ``web_ui_routes/system.py::recent_logs`` ships the array under
    ``entries``.  Net effect: ``_formatLogs`` always returned ``null``
    → the logs row showed permanently ``stale`` whenever the endpoint
    responded.  R153 fixes the field-name and locks it with a
    regression test.

2.  **Inline expand** — competitive parity with uptime-kuma /
    healthchecks.io / grafana dashboards: an ``[expand]`` button under
    the logs summary reveals the last 5 entries (LOGS_TAIL_COUNT) with
    level + UTC HH:MM:SS + 256-char-sliced message.  Closes the
    "see indicator → know the detail" loop without a separate page.

Constraints / invariants locked by this suite
---------------------------------------------
1.  **Bug-fix regression** — ``_formatLogs`` reads ``logs.entries``,
    not ``logs.logs``; payload-handling never refers back to the
    broken ``.logs`` field name.
2.  **Return-shape contract** — ``_formatLogs`` now returns an object
    ``{ summary, entries }`` rather than a string.  ``entries`` is
    always an array; on bad input it's an empty array and ``summary``
    is null (lets the renderer fall back to "—").
3.  **API surface** — ``_renderLogsRow``, ``_logLevelClassSuffix``,
    ``_logTimeShort`` defined and exported on
    ``window.AIIA_ACTIVITY_DASHBOARD``; constants ``LOGS_TAIL_COUNT``
    and ``LOG_MESSAGE_SLICE`` also exported.
4.  **Tail cap** — ``_formatLogs`` returns at most LOGS_TAIL_COUNT
    entries even if the server shipped 50.
5.  **DOM-XSS immunity** — renderer keeps using ``createElement`` +
    ``textContent``; the renderer never invokes ``innerHTML``.
6.  **a11y** — expand control is a real ``<button>`` with
    ``aria-controls`` + ``aria-expanded``; list ``<ul>`` carries
    ``role="list"`` + ``aria-live="polite"`` + the ``hidden`` attribute
    on first render.
7.  **i18n keys** — three new keys (``activityDashboardLogsExpand``,
    ``activityDashboardLogsCollapse``, ``activityDashboardLogsEmpty``)
    in en + zh-CN + pseudo locale files.
8.  **CSS contract** — six new class selectors
    (``.activity-dashboard-logs-summary`` /
    ``.activity-dashboard-logs-expand`` /
    ``.activity-dashboard-logs-list`` /
    ``.activity-dashboard-log-entry`` /
    ``.activity-dashboard-log-warning`` /
    ``.activity-dashboard-log-error``) all defined in main.css.
9.  **Level-colour mapping** — ``_logLevelClassSuffix`` collapses
    ``CRITICAL`` onto ``error`` and ``WARN`` onto ``warning``; any
    unrecognised level falls back to ``info``.
10. **Server-payload renderer message slice** — both the summary and
    the per-entry message text are sliced to ``LOG_MESSAGE_SLICE``
    (= 256) before being written via ``textContent``.

A failing case here usually means either the JS code or the CSS / i18n
drifted; fix the source rather than relaxing the test, because the
contract is exactly what the user-visible expand-on-demand feature
depends on.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/activity_dashboard.js"
LOCALE_EN = ROOT / "src/ai_intervention_agent/static/locales/en.json"
LOCALE_ZH = ROOT / "src/ai_intervention_agent/static/locales/zh-CN.json"
LOCALE_PSEUDO = ROOT / "src/ai_intervention_agent/static/locales/_pseudo/pseudo.json"
CSS_PATH = ROOT / "src/ai_intervention_agent/static/css/main.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _read_locale(p: Path) -> dict:
    return json.loads(_read(p))


R153_I18N_KEYS = (
    "activityDashboardLogsExpand",
    "activityDashboardLogsCollapse",
    "activityDashboardLogsEmpty",
)


class TestR153LogsFieldBugFix(unittest.TestCase):
    """关键 bug fix — _formatLogs 必须读 entries，不能再读 logs.logs."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_format_logs_reads_entries_field(self) -> None:
        self.assertIn(
            "var entries = logs.entries;",
            self.js,
            "_formatLogs 必须读 logs.entries（R152 旧版读的是 logs.logs，永远 null）",
        )

    def test_format_logs_no_longer_reads_logs_dot_logs(self) -> None:
        """旧的 logs.logs 字段名彻底消失（除了 docstring 引用解释 bug）."""
        # 允许在注释里出现（解释历史），但代码体里不能用作 array 取值
        m = re.search(r"^\s*var\s+entries\s*=\s*logs\.logs\b", self.js, re.MULTILINE)
        self.assertIsNone(
            m,
            "_formatLogs 不再有 ``var entries = logs.logs`` 这种 buggy 取值",
        )

    def test_format_logs_returns_object(self) -> None:
        """返回结构改成 { summary, entries }."""
        # 至少出现一次 ``{ summary: summary, entries: tail }`` shape
        self.assertRegex(
            self.js,
            r"return\s+\{\s*summary:\s*summary,\s*entries:\s*tail\s*\}",
            "_formatLogs 必须返回 { summary, entries } 对象",
        )

    def test_format_logs_returns_empty_shape_on_bad_input(self) -> None:
        """坏输入必须返回 { summary: null, entries: [] } 而不是字符串 / null."""
        # 两个分支：!logs 与 entries 非数组
        empty_shape = re.findall(
            r"return\s+\{\s*summary:\s*null,\s*entries:\s*\[\]\s*\}", self.js
        )
        self.assertGreaterEqual(
            len(empty_shape),
            2,
            "_formatLogs 必须在两条防御分支（非 object / entries 非数组）返回 empty shape",
        )


class TestR153Constants(unittest.TestCase):
    """新增常量 LOGS_TAIL_COUNT / LOG_MESSAGE_SLICE 必须存在并落在合理范围."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_logs_tail_count_is_five(self) -> None:
        m = re.search(r"LOGS_TAIL_COUNT\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "LOGS_TAIL_COUNT 必须存在")
        assert m is not None
        self.assertEqual(int(m.group(1)), 5)

    def test_log_message_slice_is_256(self) -> None:
        m = re.search(r"LOG_MESSAGE_SLICE\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "LOG_MESSAGE_SLICE 必须存在")
        assert m is not None
        self.assertEqual(int(m.group(1)), 256)


class TestR153APISurface(unittest.TestCase):
    """函数 / module export 表面契约."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_render_logs_row_defined(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+_renderLogsRow\b",
            "_renderLogsRow 必须以 function 形式定义",
        )

    def test_log_level_class_suffix_defined(self) -> None:
        self.assertRegex(self.js, r"function\s+_logLevelClassSuffix\b")

    def test_log_time_short_defined(self) -> None:
        self.assertRegex(self.js, r"function\s+_logTimeShort\b")

    def test_window_exports_include_new_helpers(self) -> None:
        for key in (
            "_renderLogsRow:",
            "_logLevelClassSuffix:",
            "_logTimeShort:",
            "LOGS_TAIL_COUNT:",
            "LOG_MESSAGE_SLICE:",
        ):
            self.assertIn(
                key,
                self.js,
                f"window.AIIA_ACTIVITY_DASHBOARD 必须 export {key}",
            )


class TestR153LevelMapping(unittest.TestCase):
    """level -> CSS suffix 映射锁."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_warning_maps_to_warning(self) -> None:
        # ``WARNING`` -> "warning"
        self.assertRegex(
            self.js,
            r'upper\s*===\s*"WARNING"',
            "WARNING level 必须映射到 ``warning`` suffix",
        )

    def test_warn_maps_to_warning(self) -> None:
        # 短形 WARN 也映射
        self.assertRegex(
            self.js,
            r'upper\s*===\s*"WARN"',
            "WARN level 必须也映射到 ``warning`` suffix",
        )

    def test_critical_maps_to_error(self) -> None:
        self.assertRegex(
            self.js,
            r'upper\s*===\s*"CRITICAL"',
            "CRITICAL level 必须合并到 ``error`` bucket（视觉一致）",
        )

    def test_error_maps_to_error(self) -> None:
        self.assertRegex(
            self.js,
            r'upper\s*===\s*"ERROR"',
            "ERROR level 必须映射到 ``error`` suffix",
        )

    def test_default_returns_info(self) -> None:
        self.assertRegex(
            self.js,
            r'return\s+"info"',
            "未识别的 level 必须 fall back 到 ``info``",
        )


class TestR153SafetyDefenses(unittest.TestCase):
    """字段截断 + DOM-XSS 免疫 + idempotent re-render."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_level_sliced(self) -> None:
        self.assertRegex(
            self.js,
            r"e\.level\.slice\(0,\s*16\)",
            "log entry 的 level 字符串必须 slice(0, 16)",
        )

    def test_message_sliced_to_constant(self) -> None:
        self.assertRegex(
            self.js,
            r"msg\.length\s*>\s*LOG_MESSAGE_SLICE",
            "log entry 的 message 必须使用 LOG_MESSAGE_SLICE 常量做长度截断",
        )

    def test_no_innerhtml_in_logs_row(self) -> None:
        self.assertNotIn(
            ".innerHTML",
            self.js,
            "整个 module 禁止 innerHTML（DOM-XSS 风险）",
        )

    def test_rebuild_list_clears_first(self) -> None:
        # 每 tick 重建之前必须先清空 list 子节点
        self.assertIn(
            "while (list.firstChild) list.removeChild(list.firstChild)",
            self.js,
            "_renderLogsRow 必须在重建前清空 list（idempotent re-render）",
        )

    def test_log_entries_use_text_content(self) -> None:
        # level/ts/message 三个 span 都使用 .textContent
        self.assertIn("levelSpan.textContent = level;", self.js)
        self.assertIn("tsSpan.textContent = ts;", self.js)
        # msg 可能落到 "—"
        self.assertRegex(self.js, r'msgSpan\.textContent\s*=\s*msg\s*\|\|\s*"—"')


class TestR153A11y(unittest.TestCase):
    """expand 按钮 + list 的 a11y 属性契约."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_expand_button_is_real_button(self) -> None:
        self.assertIn(
            'btn = document.createElement("button")',
            self.js,
            "expand 控件必须用 <button>（不能是 <a> / <span>）",
        )
        self.assertIn(
            'btn.type = "button"',
            self.js,
            "<button type=button> 防止 form 提交副作用",
        )

    def test_expand_aria_controls_set(self) -> None:
        self.assertIn(
            'btn.setAttribute("aria-controls", "activity-dashboard-logs-list")',
            self.js,
            "expand button 必须 aria-controls 指向 list id",
        )

    def test_expand_aria_expanded_starts_false(self) -> None:
        self.assertIn(
            'btn.setAttribute("aria-expanded", "false")',
            self.js,
            "expand button 初始 aria-expanded=false",
        )

    def test_list_has_aria_attributes(self) -> None:
        self.assertIn('list.setAttribute("role", "list")', self.js)
        self.assertIn('list.setAttribute("aria-live", "polite")', self.js)
        self.assertIn('list.setAttribute("hidden", "")', self.js)


class TestR153I18nCoverage(unittest.TestCase):
    """3 个新 keys 在 en / zh-CN / pseudo 三份 locale 必须齐全."""

    def test_all_keys_in_en(self) -> None:
        data = _read_locale(LOCALE_EN).get("settings", {})
        for key in R153_I18N_KEYS:
            self.assertIn(key, data, f"en.json 缺 settings.{key}")

    def test_all_keys_in_zh(self) -> None:
        data = _read_locale(LOCALE_ZH).get("settings", {})
        for key in R153_I18N_KEYS:
            self.assertIn(key, data, f"zh-CN.json 缺 settings.{key}")

    def test_all_keys_in_pseudo(self) -> None:
        data = _read_locale(LOCALE_PSEUDO).get("settings", {})
        for key in R153_I18N_KEYS:
            self.assertIn(key, data, f"_pseudo/pseudo.json 缺 settings.{key}")


class TestR153CssDefinitions(unittest.TestCase):
    """新增 .activity-dashboard-log-* / -logs-* 类必须定义."""

    def setUp(self) -> None:
        self.css = _read(CSS_PATH)

    def test_summary_class_defined(self) -> None:
        self.assertRegex(self.css, r"\.activity-dashboard-logs-summary\s*\{")

    def test_expand_class_defined(self) -> None:
        self.assertRegex(self.css, r"\.activity-dashboard-logs-expand\s*\{")

    def test_list_class_defined(self) -> None:
        self.assertRegex(self.css, r"\.activity-dashboard-logs-list\s*\{")

    def test_entry_class_defined(self) -> None:
        self.assertRegex(self.css, r"\.activity-dashboard-log-entry\s*\{")

    def test_warning_class_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.activity-dashboard-log-warning\s+\.activity-dashboard-log-level\s*\{",
            "warning level 必须有 color override 选择器",
        )

    def test_error_class_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.activity-dashboard-log-error\s+\.activity-dashboard-log-level\s*\{",
            "error level 必须有 color override 选择器",
        )

    def test_list_hidden_attribute_styled(self) -> None:
        self.assertRegex(
            self.css,
            r"\.activity-dashboard-logs-list\[hidden\]\s*\{",
            "logs-list[hidden] 必须有 display:none 规则",
        )


class TestR153RenderLogsRowWired(unittest.TestCase):
    """_renderAll 必须在 logs 行调用 _renderLogsRow."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_render_all_dispatches_logs(self) -> None:
        self.assertRegex(
            self.js,
            r'if\s*\(def\.id\s*===\s*"logs"\)\s*\{',
            "_renderAll 必须 if (def.id === 'logs') 分支",
        )
        self.assertIn(
            "_renderLogsRow(row, entry)",
            self.js,
            "_renderAll 必须在 logs 分支调用 _renderLogsRow",
        )


class TestR153FormatLogsTailCap(unittest.TestCase):
    """_formatLogs 必须只取最近 LOGS_TAIL_COUNT 条."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_tail_slice_present(self) -> None:
        # tail = entries.slice(Math.max(0, entries.length - LOGS_TAIL_COUNT))
        self.assertRegex(
            self.js,
            r"entries\.slice\(\s*Math\.max\(\s*0,\s*entries\.length\s*-\s*LOGS_TAIL_COUNT\s*\)\s*\)",
            "_formatLogs 必须 tail-slice 最近 LOGS_TAIL_COUNT 条",
        )


class TestR153IsoTimeSlice(unittest.TestCase):
    """_logTimeShort 必须正确提取 HH:MM:SS."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_indexof_t_used(self) -> None:
        # ISO 用 'T' 分隔日期和时间
        self.assertRegex(
            self.js,
            r'tsIso\.indexOf\("T"\)',
            "_logTimeShort 必须用 'T' 索引切出 time 段",
        )

    def test_slice_8_chars(self) -> None:
        # slice(t + 1, t + 9) 取 HH:MM:SS（8 char）
        self.assertIn(
            "tsIso.slice(t + 1, t + 9)",
            self.js,
            "_logTimeShort 必须切 8 chars（HH:MM:SS）",
        )


if __name__ == "__main__":
    unittest.main()
