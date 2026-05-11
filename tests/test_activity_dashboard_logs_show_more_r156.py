"""R156 — Activity Dashboard logs row "show 50" toggle (CR#9 F-4 follow-up).

Background
----------
R153 shipped the logs row inline expand showing the last 5 entries.
Code Review #9 flagged F-4: operators investigating a known incident
want the full 50-entry ring buffer the endpoint can serve, but the
default 5-entry cap forces them into ``curl`` or a separate ops tool.
R156 closes that gap with a sibling toggle next to ``[expand]``:
clicking ``[show 50]`` flips the in-flight ``?limit=N`` from 5 to 50;
clicking ``[show 5]`` flips it back.

The toggle's choice is persisted to localStorage under a schema-
versioned key (``aiia.activity_dashboard.logs_limit.v1``) so the
preference survives reloads, mirroring R155's expanded-state pattern.

Constraints / invariants locked by this suite
---------------------------------------------
1.  **Constants** — ``LOGS_LIMIT_DEFAULT = 5`` /
    ``LOGS_LIMIT_EXPANDED = 50`` / ``LOGS_LIMIT_LS_KEY = aiia.activity_dashboard.logs_limit.v1``
    / ``LOGS_LIMIT_SCHEMA_VERSION = 1`` /
    ``ENDPOINT_RECENT_LOGS_BASE = "/api/system/recent-logs"`` all
    exported on ``window.AIIA_ACTIVITY_DASHBOARD``.
2.  **API surface** — ``_readLogsLimit`` / ``_writeLogsLimit``
    defined and exported.
3.  **Allowlist** — ``_readLogsLimit`` returns ``null`` for any
    payload whose ``limit`` is not exactly LOGS_LIMIT_DEFAULT or
    LOGS_LIMIT_EXPANDED (defensive against future schema bumps
    introducing a third value without a version bump).
4.  **Write coercion** — ``_writeLogsLimit`` coerces invalid input
    back to LOGS_LIMIT_DEFAULT so callers can't poison the
    storage payload.
5.  **F-5 lesson scaling** — the only comparison shape on
    LOGS_LIMIT_SCHEMA_VERSION inside ``_readLogsLimit`` is strict
    equality.
6.  **Dynamic URL builder** — ``_pollOnce`` constructs the
    recent-logs URL as ``ENDPOINT_RECENT_LOGS_BASE + "?limit=" +
    _state.logsLimit`` rather than the static literal R152 used.
7.  **State machine** — ``_state`` carries a ``logsLimit`` field
    defaulting to ``LOGS_LIMIT_DEFAULT``.
8.  **Init hydrate** — ``init()`` reads the persisted limit and
    sets ``_state.logsLimit = LOGS_LIMIT_EXPANDED`` iff the
    payload is exactly that.
9.  **Toggle button rendering** — ``_renderLogsRow`` creates a
    sibling ``button.activity-dashboard-logs-show-more`` once,
    seeds it with the correct label for the current state, and
    binds a click handler that swaps the state + writes storage
    + kicks a microtask poll.
10. **i18n keys** — two new keys
    (``activityDashboardLogsShowMore`` /
    ``activityDashboardLogsShowDefault``) present in en + zh-CN
    + pseudo locales.
11. **CSS** — ``.activity-dashboard-logs-show-more`` defined in
    main.css with hover / focus-visible state.

A failing case here means the JS code or CSS drifted out of lockstep
with the persistence + URL builder contract; fix the source rather
than relaxing the test.
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


R156_I18N_KEYS = (
    "activityDashboardLogsShowMore",
    "activityDashboardLogsShowDefault",
)


class TestR156Constants(unittest.TestCase):
    """常量锁."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_logs_limit_default_is_five(self) -> None:
        m = re.search(r"LOGS_LIMIT_DEFAULT\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "LOGS_LIMIT_DEFAULT 必须存在")
        assert m is not None
        self.assertEqual(int(m.group(1)), 5)

    def test_logs_limit_expanded_is_fifty(self) -> None:
        m = re.search(r"LOGS_LIMIT_EXPANDED\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "LOGS_LIMIT_EXPANDED 必须存在")
        assert m is not None
        self.assertEqual(int(m.group(1)), 50)

    def test_logs_limit_ls_key_versioned(self) -> None:
        m = re.search(r'LOGS_LIMIT_LS_KEY\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m, "LOGS_LIMIT_LS_KEY 必须存在")
        assert m is not None
        key = m.group(1)
        self.assertIn("v1", key, f"LOGS_LIMIT_LS_KEY 必须含 v1 namespace：{key!r}")
        self.assertIn("aiia", key, "LOGS_LIMIT_LS_KEY 必须以 aiia.* 命名空间")
        self.assertIn("logs_limit", key, "LOGS_LIMIT_LS_KEY 必须含 logs_limit 表明用途")

    def test_logs_limit_schema_version_is_one(self) -> None:
        m = re.search(r"LOGS_LIMIT_SCHEMA_VERSION\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "LOGS_LIMIT_SCHEMA_VERSION 必须存在")
        assert m is not None
        self.assertEqual(int(m.group(1)), 1)

    def test_endpoint_recent_logs_base_present(self) -> None:
        m = re.search(r'ENDPOINT_RECENT_LOGS_BASE\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m, "ENDPOINT_RECENT_LOGS_BASE 必须存在")
        assert m is not None
        self.assertEqual(
            m.group(1),
            "/api/system/recent-logs",
            "ENDPOINT_RECENT_LOGS_BASE 必须 = /api/system/recent-logs（无 query）",
        )


class TestR156APISurface(unittest.TestCase):
    """函数 / module export 表面契约."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_read_logs_limit_defined(self) -> None:
        self.assertRegex(self.js, r"function\s+_readLogsLimit\b")

    def test_write_logs_limit_defined(self) -> None:
        self.assertRegex(self.js, r"function\s+_writeLogsLimit\b")

    def test_window_exports(self) -> None:
        for key in (
            "LOGS_LIMIT_DEFAULT:",
            "LOGS_LIMIT_EXPANDED:",
            "LOGS_LIMIT_LS_KEY:",
            "LOGS_LIMIT_SCHEMA_VERSION:",
            "ENDPOINT_RECENT_LOGS_BASE:",
            "_readLogsLimit:",
            "_writeLogsLimit:",
        ):
            self.assertIn(
                key,
                self.js,
                f"window.AIIA_ACTIVITY_DASHBOARD 必须 export {key}",
            )


class TestR156ReadDefenses(unittest.TestCase):
    """_readLogsLimit 必须 defensively 处理坏 payload + allowlist 值."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+_readLogsLimit\s*\(\s*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_readLogsLimit 函数体必须可被抓取")
        assert m is not None
        self.body = m.group(1)

    def test_outer_try_catch(self) -> None:
        self.assertIn("try {", self.body)
        self.assertIn("catch (_err)", self.body)

    def test_typeof_localstorage_guard(self) -> None:
        self.assertRegex(
            self.body,
            r'typeof\s+localStorage\s*===\s*"undefined"',
            "_readLogsLimit 必须 typeof 检查 localStorage 存在",
        )

    def test_handles_json_parse_failure(self) -> None:
        self.assertIn("JSON.parse", self.body)
        self.assertRegex(
            self.body,
            r"try\s*\{\s*parsed\s*=\s*JSON\.parse",
            "JSON.parse 必须包内层 try/catch",
        )

    def test_validates_schema_version_strict(self) -> None:
        self.assertIn(
            "parsed.v === LOGS_LIMIT_SCHEMA_VERSION",
            self.body,
            "_readLogsLimit 必须用 === 严格比较 LOGS_LIMIT_SCHEMA_VERSION",
        )

    def test_validates_limit_is_number(self) -> None:
        self.assertRegex(
            self.body,
            r'typeof\s+parsed\.limit\s*===\s*"number"',
            "_readLogsLimit 必须验证 parsed.limit 是 number",
        )

    def test_limit_allowlist(self) -> None:
        # 必须只接受 LOGS_LIMIT_DEFAULT 或 LOGS_LIMIT_EXPANDED 两个值
        self.assertRegex(
            self.body,
            r"parsed\.limit\s*===\s*LOGS_LIMIT_DEFAULT",
            "_readLogsLimit 必须 allowlist parsed.limit === LOGS_LIMIT_DEFAULT",
        )
        self.assertRegex(
            self.body,
            r"parsed\.limit\s*===\s*LOGS_LIMIT_EXPANDED",
            "_readLogsLimit 必须 allowlist parsed.limit === LOGS_LIMIT_EXPANDED",
        )


class TestR156WriteDefenses(unittest.TestCase):
    """_writeLogsLimit 必须 coerce + try/catch."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+_writeLogsLimit\s*\([^)]*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_writeLogsLimit 函数体必须可被抓取")
        assert m is not None
        self.body = m.group(1)

    def test_coerce_unknown_input_to_default(self) -> None:
        # ``safe = limit === LOGS_LIMIT_EXPANDED ? EXPANDED : DEFAULT`` 形式
        self.assertRegex(
            self.body,
            r"limit\s*===\s*LOGS_LIMIT_EXPANDED",
            "_writeLogsLimit 必须 coerce 输入到 allowlist 值之一",
        )

    def test_wrapped_in_try_catch(self) -> None:
        self.assertIn("try {", self.body)

    def test_typeof_localstorage_guard(self) -> None:
        self.assertRegex(self.body, r'typeof\s+localStorage\s*===\s*"undefined"')

    def test_uses_setitem(self) -> None:
        self.assertIn("localStorage.setItem(LOGS_LIMIT_LS_KEY", self.body)

    def test_payload_has_schema_version(self) -> None:
        self.assertIn("v: LOGS_LIMIT_SCHEMA_VERSION", self.body)


class TestR156SchemaVersionShape(unittest.TestCase):
    """CR#9 F-5 lesson scaling — LOGS_LIMIT_SCHEMA_VERSION 只能 === 比较."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+_readLogsLimit\s*\(\s*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_readLogsLimit 函数体必须可被抓取")
        assert m is not None
        self.body = m.group(1)

    def test_only_strict_equality(self) -> None:
        ops_after = re.findall(
            r"LOGS_LIMIT_SCHEMA_VERSION\s*(===|!==|==|!=|<=|>=|<|>)",
            self.body,
        )
        ops_before = re.findall(
            r"(===|!==|==|!=|<=|>=|<|>)\s*LOGS_LIMIT_SCHEMA_VERSION",
            self.body,
        )
        unique = set(ops_after) | set(ops_before)
        self.assertTrue(
            unique, "_readLogsLimit 内必须有 LOGS_LIMIT_SCHEMA_VERSION 比较"
        )
        self.assertEqual(
            unique,
            {"==="},
            f"LOGS_LIMIT_SCHEMA_VERSION 必须只用 === 严格比较，发现 {unique!r}",
        )


class TestR156DynamicURLBuilder(unittest.TestCase):
    """_pollOnce 必须用 ENDPOINT_RECENT_LOGS_BASE + ?limit= 构造 URL."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_uses_base_plus_query(self) -> None:
        self.assertIn(
            'ENDPOINT_RECENT_LOGS_BASE + "?limit=" + _state.logsLimit',
            self.js,
            "_pollOnce 必须用 BASE + ?limit= + _state.logsLimit 构造 URL",
        )


class TestR156StateMachine(unittest.TestCase):
    """_state 必须有 logsLimit 字段且默认 = LOGS_LIMIT_DEFAULT."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_state_has_logs_limit_default(self) -> None:
        self.assertRegex(
            self.js,
            r"logsLimit:\s*LOGS_LIMIT_DEFAULT",
            "_state 必须默认 logsLimit: LOGS_LIMIT_DEFAULT",
        )


class TestR156InitHydrate(unittest.TestCase):
    """init() 必须读 persisted limit 并 hydrate 到 _state."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+init\s*\(\s*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "init 函数体必须可被抓取")
        assert m is not None
        self.body = m.group(1)

    def test_reads_logs_limit_on_init(self) -> None:
        self.assertIn(
            "_readLogsLimit()",
            self.body,
            "init 必须调用 _readLogsLimit() 做 hydrate",
        )

    def test_only_hydrates_to_expanded(self) -> None:
        # init() 只在 saved === LOGS_LIMIT_EXPANDED 时改 _state；
        # 否则用 default。
        self.assertRegex(
            self.body,
            r"savedLimit\s*===\s*LOGS_LIMIT_EXPANDED",
            "init 必须用 === LOGS_LIMIT_EXPANDED 检查",
        )


class TestR156RenderShowMoreButton(unittest.TestCase):
    """_renderLogsRow 必须 create + bind show-more button."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_show_more_button_class(self) -> None:
        self.assertIn(
            "activity-dashboard-logs-show-more",
            self.js,
            "_renderLogsRow 必须创建 .activity-dashboard-logs-show-more button",
        )

    def test_button_is_real_button_element(self) -> None:
        self.assertIn(
            'moreBtn = document.createElement("button")',
            self.js,
            "show-more 控件必须是 <button>（不能是 <a> / <span>）",
        )
        self.assertIn(
            'moreBtn.type = "button"',
            self.js,
            "<button type=button> 防止 form 提交副作用",
        )

    def test_click_handler_writes_storage(self) -> None:
        # 点击 handler 必须 call _writeLogsLimit
        self.assertIn(
            "_writeLogsLimit(_state.logsLimit)",
            self.js,
            "show-more click handler 必须 _writeLogsLimit",
        )

    def test_click_handler_kicks_immediate_poll(self) -> None:
        # 立即 poll 让新 limit 生效，不必等 5s
        self.assertRegex(
            self.js,
            r"Promise\.resolve\(\)\.then\(_pollOnce\)",
            "show-more handler 必须 microtask poll 让新 limit 立即生效",
        )

    def test_swaps_label_keys(self) -> None:
        # 至少要引用 ShowMore + ShowDefault 两个 i18n keys
        self.assertIn(
            "settings.activityDashboardLogsShowMore",
            self.js,
        )
        self.assertIn(
            "settings.activityDashboardLogsShowDefault",
            self.js,
        )


class TestR156I18nCoverage(unittest.TestCase):
    """2 个新 keys 必须在 en / zh-CN / pseudo 三份 locale 内."""

    def test_all_keys_in_en(self) -> None:
        data = _read_locale(LOCALE_EN).get("settings", {})
        for key in R156_I18N_KEYS:
            self.assertIn(key, data, f"en.json 缺 settings.{key}")

    def test_all_keys_in_zh(self) -> None:
        data = _read_locale(LOCALE_ZH).get("settings", {})
        for key in R156_I18N_KEYS:
            self.assertIn(key, data, f"zh-CN.json 缺 settings.{key}")

    def test_all_keys_in_pseudo(self) -> None:
        data = _read_locale(LOCALE_PSEUDO).get("settings", {})
        for key in R156_I18N_KEYS:
            self.assertIn(key, data, f"_pseudo/pseudo.json 缺 settings.{key}")


class TestR156CssDefinitions(unittest.TestCase):
    """.activity-dashboard-logs-show-more CSS 类必须定义."""

    def setUp(self) -> None:
        self.css = _read(CSS_PATH)

    def test_show_more_class_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.activity-dashboard-logs-show-more\s*\{",
            "main.css 必须定义 .activity-dashboard-logs-show-more",
        )

    def test_show_more_hover_focus_defined(self) -> None:
        self.assertRegex(
            self.css,
            r"\.activity-dashboard-logs-show-more:hover",
            "main.css 必须定义 .activity-dashboard-logs-show-more:hover",
        )


if __name__ == "__main__":
    unittest.main()
