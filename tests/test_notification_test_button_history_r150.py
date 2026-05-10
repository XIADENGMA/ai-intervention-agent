"""R150 — Self-test history trail (localStorage) for the notification button.

Background
----------
R141-R145 shipped the server-side observability stack (per-provider
stats, last_error_class, success/failure streaks); R146 added the UI
button that triggers the dispatch; R147 added the post-dispatch health
probe; R148 fixed R147's age-only false-success race with a
baseline-delta classifier.  The remaining user-facing gap, called out
in Code Review #8 as F-6, is that **every click overwrites the previous
verdict** — there's no audit trail saying "the last 5 self-tests were
delivered / delivered / failed / delivered / delivered".

R150 closes that gap with a localStorage-backed "last 5 results" trail,
mirroring the same pattern uptime-kuma and healthchecks.io use under
their probe-trigger buttons.  The trail is collapsed by default
(an ``aria-expanded`` toggle button), capped at HISTORY_MAX_ENTRIES (=5),
versioned (``v: 1``) so a future schema bump can drop incompatible
entries safely, and synced across tabs via the ``storage`` event.

Constraints / invariants locked by this suite
---------------------------------------------
1.  **常量锁定** — HISTORY_LS_KEY is a ``v1``-namespaced string,
    HISTORY_MAX_ENTRIES = 5, HISTORY_TOGGLE_ID + HISTORY_LIST_ID match
    the HTML element IDs, HISTORY_SCHEMA_VERSION = 1.
2.  **API 表面** — ``_readStorage``, ``_loadHistory``, ``_pushHistory``,
    ``_clearHistory``, ``_renderHistory``, ``_formatRelativeTime``,
    ``_historyVerdictLabel`` all defined and exported on
    ``window.AIIA_NOTIFICATION_TEST_BUTTON``.
3.  **schema discipline** — ``_loadHistory`` filters non-array,
    non-object, missing-version, and stale-version entries; entries
    written by ``_pushHistory`` carry exactly the fields documented in
    the JS comment block (``v``, ``ts``, ``verdict_kind``, ``providers``,
    ``source``, ``event_id``, optional ``error_class``).
4.  **cap 锁** — ``_pushHistory`` truncates the combined list to 5;
    no entry exceeds 16 providers; provider strings are sliced at 32 chars.
5.  **DOM 渲染契约** — ``_renderHistory`` clears the node first, uses
    ``createElement`` + ``textContent`` (no innerHTML), shows the
    "no tests yet" empty-state when localStorage is empty, applies the
    ``self-test-history-{kind}`` CSS class per entry.
6.  **trigger wiring** — ``triggerSelfTest`` calls ``_pushHistory`` once
    after both the success path (with ``source: "dispatch"``) and the
    network-error path (with ``source: "network"``); both call sites
    re-render the list so the user sees the new entry immediately.
7.  **init wiring** — ``init()`` queries the toggle + list elements,
    initial-renders the list, attaches a click handler that flips
    ``aria-expanded`` + the ``[hidden]`` attribute, and registers a
    ``storage`` event listener for multi-tab sync.
8.  **HTML elements** — ``web_ui.html`` ships the toggle button (with
    ``aria-controls``, ``aria-expanded="false"``) and the list (with
    ``role="log"``, ``aria-live="polite"``, ``hidden``).
9.  **i18n 完整性** — All twelve new keys are present in en + zh-CN +
    _pseudo locale files, with the right Mustache / ICU placeholder
    signatures.
10. **R146/R147/R148 envelope** — JS file line cap raised to 1100;
    ``_classifyProviderVerdict`` / ``_runProbe`` / ``triggerSelfTest``
    signatures still match the older suites (regression guard).

A failing case here usually means either the JS code or the HTML
markup drifted out of lockstep with the test contract; in that case
fix the source rather than relaxing the test, because the contract
is exactly what the user-facing trail depends on.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/notification_test_button.js"
HTML_PATH = ROOT / "src/ai_intervention_agent/templates/web_ui.html"
LOCALE_EN = ROOT / "src/ai_intervention_agent/static/locales/en.json"
LOCALE_ZH = ROOT / "src/ai_intervention_agent/static/locales/zh-CN.json"
LOCALE_PSEUDO = ROOT / "src/ai_intervention_agent/static/locales/_pseudo/pseudo.json"
CSS_PATH = ROOT / "src/ai_intervention_agent/static/css/main.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _read_locale(p: Path) -> dict:
    return json.loads(_read(p))


HISTORY_KEYS = (
    "systemTestHistoryToggle",
    "systemTestHistoryEmpty",
    "systemTestHistoryAgeJustNow",
    "systemTestHistoryAgeSeconds",
    "systemTestHistoryAgeMinutes",
    "systemTestHistoryAgeHours",
    "systemTestHistoryAgeDays",
    "systemTestHistoryVerdictSuccess",
    "systemTestHistoryVerdictWarning",
    "systemTestHistoryVerdictError",
    "systemTestHistoryVerdictUnknown",
)


class TestR150Constants(unittest.TestCase):
    """常量锁定 — 允许微调描述但锁死值 / id 名."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_history_ls_key_is_versioned(self) -> None:
        m = re.search(r'HISTORY_LS_KEY\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m, "HISTORY_LS_KEY 必须存在")
        assert m is not None
        key = m.group(1)
        # ``v1`` namespace lets future schema bumps coexist with old data
        # rather than crashing on it.
        self.assertIn(
            "v1", key, f"HISTORY_LS_KEY 必须含版本号（``v1`` 命名空间）：{key!r}"
        )
        self.assertIn("self_test", key, "HISTORY_LS_KEY 必须含特征字段表明用途")

    def test_history_max_entries_is_five(self) -> None:
        m = re.search(r"HISTORY_MAX_ENTRIES\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "HISTORY_MAX_ENTRIES 必须存在")
        assert m is not None
        self.assertEqual(
            int(m.group(1)),
            5,
            "HISTORY_MAX_ENTRIES 必须 = 5（uptime-kuma / healthchecks.io 同款）",
        )

    def test_history_schema_version_is_one(self) -> None:
        m = re.search(r"HISTORY_SCHEMA_VERSION\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "HISTORY_SCHEMA_VERSION 必须存在")
        assert m is not None
        self.assertEqual(int(m.group(1)), 1)

    def test_history_toggle_id_matches_html(self) -> None:
        m = re.search(r'HISTORY_TOGGLE_ID\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m)
        assert m is not None
        toggle_id = m.group(1)
        html = _read(HTML_PATH)
        # HTML must use the exact same id literal.
        self.assertIn(
            f'id="{toggle_id}"',
            html,
            f"web_ui.html 必须有 id={toggle_id!r} 的 toggle button",
        )

    def test_history_list_id_matches_html(self) -> None:
        m = re.search(r'HISTORY_LIST_ID\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m)
        assert m is not None
        list_id = m.group(1)
        html = _read(HTML_PATH)
        self.assertIn(
            f'id="{list_id}"',
            html,
            f"web_ui.html 必须有 id={list_id!r} 的 history list",
        )


class TestR150APISurface(unittest.TestCase):
    """函数 / module export 表面契约."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_helpers_defined(self) -> None:
        for name in (
            "_readStorage",
            "_loadHistory",
            "_pushHistory",
            "_clearHistory",
            "_renderHistory",
            "_formatRelativeTime",
            "_historyVerdictLabel",
        ):
            self.assertRegex(
                self.js,
                rf"function\s+{re.escape(name)}\s*\(",
                f"helper {name} 必须在 JS 模块内定义",
            )

    def test_helpers_exported_on_window(self) -> None:
        for name in (
            "_readStorage",
            "_loadHistory",
            "_pushHistory",
            "_clearHistory",
            "_renderHistory",
            "_formatRelativeTime",
            "_historyVerdictLabel",
        ):
            self.assertIn(
                f"{name}: {name}",
                self.js,
                f"window.AIIA_NOTIFICATION_TEST_BUTTON 必须 export {name}",
            )

    def test_constants_exported_on_window(self) -> None:
        for name in (
            "HISTORY_LS_KEY",
            "HISTORY_MAX_ENTRIES",
            "HISTORY_TOGGLE_ID",
            "HISTORY_LIST_ID",
            "HISTORY_SCHEMA_VERSION",
        ):
            self.assertIn(
                f"{name}: {name}",
                self.js,
                f"R150 常量 {name} 必须 export 到 window 表面方便测试 / 调试",
            )


class TestR150LoadFiltersBadEntries(unittest.TestCase):
    """``_loadHistory`` 的 schema 防御契约 — 编码进 JS 源码 grep."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+_loadHistory\s*\(\s*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_loadHistory 函数体必须可被抓取")
        assert m is not None
        self.body = m.group(1)

    def test_returns_empty_array_when_storage_unavailable(self) -> None:
        # First branch must early-return [] when _readStorage() === null.
        self.assertRegex(
            self.body,
            r"if\s*\(\s*!storage\s*\)\s*return\s*\[\s*\]",
            "_loadHistory 必须在 storage 不可用时返回 []（隐私模式 / iframe）",
        )

    def test_filters_non_array_payload(self) -> None:
        self.assertRegex(
            self.body,
            r"!Array\.isArray\s*\(\s*parsed\s*\).*return\s*\[\s*\]",
            "_loadHistory 必须在 JSON.parse 结果非 Array 时返回 []",
        )

    def test_filters_by_schema_version(self) -> None:
        # The filter loop must check ``e.v === HISTORY_SCHEMA_VERSION``.
        self.assertRegex(
            self.body,
            r"e\.v\s*===\s*HISTORY_SCHEMA_VERSION",
            "_loadHistory 必须用 HISTORY_SCHEMA_VERSION 过滤 entry",
        )

    def test_schema_version_comparison_is_strict_equality_only(self) -> None:
        """R155 / CR#9 F-5 — property pin: the only comparison shape on
        ``HISTORY_SCHEMA_VERSION`` inside ``_loadHistory`` is strict
        equality (``===``).  Weakening to ``>=`` / ``!==`` / ``<`` /
        ``==`` would silently let an incompatible older / newer schema's
        payload through and crash the renderer when the entry shape
        doesn't match.

        Implementation note: we grep every binary comparison literal
        adjacent to ``HISTORY_SCHEMA_VERSION`` inside the function body
        and assert the operator set is exactly ``{"==="}``.  Catches
        e.g. a future refactor that decides ``e.v >= HISTORY_SCHEMA_VERSION``
        for "forward compat" — wrong direction; the safe response to
        an unknown version is to drop the entry."""
        # Capture (operator) for every ``HISTORY_SCHEMA_VERSION`` adjacency.
        # Match either ``HISTORY_SCHEMA_VERSION <op> X`` or ``X <op>
        # HISTORY_SCHEMA_VERSION`` — both orders.
        ops_after = re.findall(
            r"HISTORY_SCHEMA_VERSION\s*(===|!==|==|!=|<=|>=|<|>)",
            self.body,
        )
        ops_before = re.findall(
            r"(===|!==|==|!=|<=|>=|<|>)\s*HISTORY_SCHEMA_VERSION",
            self.body,
        )
        unique_ops = set(ops_after) | set(ops_before)
        # ``===`` is the only acceptable shape.  Empty set (no comparison
        # anywhere) would also indicate the filter degraded — assert
        # at least one comparison exists.
        self.assertTrue(
            unique_ops,
            "未在 _loadHistory body 内找到任何 HISTORY_SCHEMA_VERSION 比较，"
            "schema 过滤可能已被移除",
        )
        self.assertEqual(
            unique_ops,
            {"==="},
            f"HISTORY_SCHEMA_VERSION 必须只用 === 严格比较，发现 {unique_ops!r}",
        )

    def test_caps_at_max_entries(self) -> None:
        self.assertRegex(
            self.body,
            r"clean\.length\s*>=\s*HISTORY_MAX_ENTRIES",
            "_loadHistory 必须在累计到 HISTORY_MAX_ENTRIES 时跳出循环",
        )


class TestR150PushSchema(unittest.TestCase):
    """``_pushHistory`` 写入 schema 契约 — 必须只含已声明的字段."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+_pushHistory\s*\(\s*entry\s*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_pushHistory 必须可被 regex 抓取")
        assert m is not None
        self.body = m.group(1)

    def test_record_has_all_required_fields(self) -> None:
        for field in (
            "v:",
            "ts:",
            "verdict_kind:",
            "providers:",
            "source:",
            "event_id:",
        ):
            self.assertIn(
                field,
                self.body,
                f"_pushHistory 写入的 record 必须含字段 {field!r}",
            )

    def test_uses_now_for_timestamp(self) -> None:
        self.assertRegex(
            self.body,
            r"ts:\s*Date\.now\s*\(\s*\)",
            "ts 字段必须 = Date.now()（毫秒 epoch）",
        )

    def test_caps_combined_list(self) -> None:
        self.assertRegex(
            self.body,
            r"\.slice\s*\(\s*0\s*,\s*HISTORY_MAX_ENTRIES\s*\)",
            "_pushHistory 必须 ``slice(0, HISTORY_MAX_ENTRIES)`` 截顶",
        )

    def test_caps_provider_count_and_string_length(self) -> None:
        self.assertRegex(
            self.body,
            r"i\s*<\s*16",
            "providers loop 必须 cap 16 (defensive vs malformed entry)",
        )
        self.assertIn(
            ".slice(0, 32)",
            self.body,
            "provider string 必须 .slice(0, 32) 防止巨型字段",
        )

    def test_setitem_swallows_quota_exception(self) -> None:
        # try/catch around setItem so QuotaExceededError doesn't escape.
        self.assertRegex(
            self.body,
            r"try\s*\{[^}]*setItem[^}]*\}\s*catch\s*\(\s*_e\s*\)",
            "setItem 必须包 try/catch 吞 quota 异常",
        )


class TestR150RenderDOMSafety(unittest.TestCase):
    """渲染必须用 textContent / createElement，不得 innerHTML."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+_renderHistory\s*\(\s*node\s*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        self.body = m.group(1)

    def test_clears_node_first(self) -> None:
        self.assertRegex(
            self.body,
            r"while\s*\(\s*node\.firstChild\s*\)\s*node\.removeChild",
            "_renderHistory 必须清空旧节点（FIFO removeChild）再重画",
        )

    def test_uses_text_content_only(self) -> None:
        # 显式禁止 innerHTML / outerHTML / insertAdjacentHTML；contentful
        # children 必须经 textContent 写入。
        self.assertNotIn(".innerHTML", self.body, "_renderHistory 禁止 .innerHTML")
        self.assertNotIn(".outerHTML", self.body, "_renderHistory 禁止 .outerHTML")
        self.assertNotIn(
            ".insertAdjacentHTML",
            self.body,
            "_renderHistory 禁止 .insertAdjacentHTML",
        )

    def test_uses_createelement_for_each_child(self) -> None:
        for tag in ('"li"', '"span"', '"code"'):
            self.assertIn(
                f"createElement({tag})",
                self.body,
                f"_renderHistory 必须用 createElement({tag})",
            )

    def test_empty_state_uses_i18n(self) -> None:
        self.assertRegex(
            self.body,
            r"_t\s*\(\s*[\"']settings\.systemTestHistoryEmpty[\"']\s*\)",
            "空 history 必须显示 i18n 'systemTestHistoryEmpty'",
        )

    def test_entry_class_includes_verdict_kind(self) -> None:
        self.assertRegex(
            self.body,
            r'"self-test-history-entry self-test-history-"\s*\+\s*e\.verdict_kind',
            "每个 entry 的 class 必须含 ``self-test-history-{kind}`` 后缀",
        )

    def test_renders_event_id_truncated(self) -> None:
        self.assertRegex(
            self.body,
            r"e\.event_id\.slice\s*\(\s*0\s*,\s*8\s*\)",
            "event_id 渲染必须 slice(0, 8)（与 commit hash 同长度）",
        )


class TestR150TriggerSelfTestWiring(unittest.TestCase):
    """``triggerSelfTest`` 必须在两条出口都 push history."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"async function triggerSelfTest\([^)]*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "triggerSelfTest 必须可被 regex 抓取")
        assert m is not None
        self.body = m.group(1)

    def test_pushes_history_on_dispatch_success(self) -> None:
        # _pushHistory({ ..., source: "dispatch", ... }) 必须出现在
        # _setStatus(verdict) 之后、_runProbe 之前。
        self.assertRegex(
            self.body,
            r'_pushHistory\(\s*\{[^}]*verdict_kind:\s*verdict\.kind[^}]*source:\s*"dispatch"',
            "成功路径必须 _pushHistory 一条 source=dispatch 的 entry",
        )

    def test_pushes_history_on_network_error(self) -> None:
        # catch 块也必须 push 一条 source: "network" 的 entry。
        self.assertRegex(
            self.body,
            r'_pushHistory\(\s*\{[^}]*verdict_kind:\s*"error"[^}]*source:\s*"network"',
            "网络错误路径必须 _pushHistory 一条 source=network、kind=error 的 entry",
        )

    def test_rerenders_history_after_push(self) -> None:
        # 每次 push 之后必须立即调 _renderHistory(historyListNode) 让用户看到。
        # 注意是两次（dispatch + network 两条路径）— 每条都得有。
        self.assertGreaterEqual(
            len(re.findall(r"_renderHistory\s*\(", self.body)),
            2,
            "两条路径都必须立即 _renderHistory 让用户看到新 entry",
        )


class TestR150InitWiring(unittest.TestCase):
    """init() 必须挂 toggle / storage event."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function init\(\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        self.body = m.group(1)

    def test_queries_history_elements(self) -> None:
        self.assertIn("getElementById(HISTORY_TOGGLE_ID)", self.body)
        self.assertIn("getElementById(HISTORY_LIST_ID)", self.body)

    def test_initial_render(self) -> None:
        # 进入页面就得渲染一次，不然 hidden 状态下用户首次展开看不到旧数据。
        self.assertRegex(
            self.body,
            r"_renderHistory\s*\(\s*historyList\s*\)",
            "init() 必须初次渲染 history list",
        )

    def test_toggle_click_flips_aria_expanded(self) -> None:
        self.assertRegex(
            self.body,
            r'historyToggle\.setAttribute\s*\(\s*"aria-expanded"',
            "toggle click 必须翻转 aria-expanded",
        )

    def test_toggle_click_toggles_hidden_attribute(self) -> None:
        self.assertIn(
            'historyList.setAttribute("hidden", "")',
            self.body,
            "toggle 折叠时必须重新加 hidden 属性",
        )
        self.assertIn(
            'historyList.removeAttribute("hidden")',
            self.body,
            "toggle 展开时必须移除 hidden 属性",
        )

    def test_storage_event_listener_attached(self) -> None:
        # 跨 tab 同步：另一个 tab 写入触发本 tab 的 storage 事件。
        self.assertRegex(
            self.body,
            r'addEventListener\s*\(\s*"storage"',
            "init() 必须注册 storage 事件监听器（多 tab 同步）",
        )


class TestR150HTMLContract(unittest.TestCase):
    """HTML 必须有 toggle + list 元素，含 a11y 属性."""

    def setUp(self) -> None:
        self.html = _read(HTML_PATH)

    def test_toggle_button_present(self) -> None:
        self.assertIn(
            'id="system-notification-test-history-toggle"',
            self.html,
            "history toggle button 必须在 HTML 中",
        )
        self.assertIn(
            'aria-controls="system-notification-test-history-list"',
            self.html,
            "toggle 必须 aria-controls 指向 list id",
        )
        self.assertIn(
            'aria-expanded="false"',
            self.html,
            "toggle 默认必须 aria-expanded=false",
        )

    def test_history_list_present(self) -> None:
        self.assertIn(
            'id="system-notification-test-history-list"',
            self.html,
            "history list <ul> 必须在 HTML 中",
        )
        # role=log + aria-live=polite 让 SR 在新 entry 出现时自然朗读。
        idx = self.html.find('id="system-notification-test-history-list"')
        # 节点定义只取 ~400 字符上下文做 a11y 属性检查。
        ctx = self.html[idx : idx + 400]
        self.assertIn('role="log"', ctx, "list 必须 role='log'")
        self.assertIn(
            'aria-live="polite"',
            ctx,
            "list 必须 aria-live='polite'（新 entry 朗读但不打断）",
        )
        self.assertRegex(
            ctx,
            r"\bhidden\b",
            "list 默认必须含 hidden 属性（折叠态）",
        )


class TestR150I18nKeysAcrossLocales(unittest.TestCase):
    """en + zh-CN + _pseudo 必须三套 history keys 全覆盖."""

    def test_en_locale_has_all_keys(self) -> None:
        en = _read_locale(LOCALE_EN)
        settings = en.get("settings", {})
        for key in HISTORY_KEYS:
            self.assertIn(key, settings, f"en locale 缺 settings.{key}")

    def test_zh_cn_locale_has_all_keys(self) -> None:
        zh = _read_locale(LOCALE_ZH)
        settings = zh.get("settings", {})
        for key in HISTORY_KEYS:
            self.assertIn(key, settings, f"zh-CN locale 缺 settings.{key}")

    def test_pseudo_locale_has_all_keys(self) -> None:
        ps = _read_locale(LOCALE_PSEUDO)
        settings = ps.get("settings", {})
        for key in HISTORY_KEYS:
            self.assertIn(key, settings, f"_pseudo locale 缺 settings.{key}")

    def test_en_age_keys_use_icu_plural_signature(self) -> None:
        en = _read_locale(LOCALE_EN)
        settings = en["settings"]
        for key, var in (
            ("systemTestHistoryAgeSeconds", "seconds"),
            ("systemTestHistoryAgeMinutes", "minutes"),
            ("systemTestHistoryAgeHours", "hours"),
            ("systemTestHistoryAgeDays", "days"),
        ):
            v = settings[key]
            self.assertIn(
                f"{{{var}, plural,",
                v,
                f"en {key} 必须用 ICU plural 签名 (var={var})",
            )

    def test_zh_age_keys_use_mustache_param(self) -> None:
        zh = _read_locale(LOCALE_ZH)
        settings = zh["settings"]
        # zh-CN 不需要 plural（中文无单复数变体），只要 {{name}} 占位符。
        for key, var in (
            ("systemTestHistoryAgeSeconds", "seconds"),
            ("systemTestHistoryAgeMinutes", "minutes"),
            ("systemTestHistoryAgeHours", "hours"),
            ("systemTestHistoryAgeDays", "days"),
        ):
            v = settings[key]
            self.assertIn(
                f"{{{var}}}",
                v,
                f"zh-CN {key} 必须含 {{{var}}} 占位符（与 _t 签名对齐）",
            )


class TestR150CSSStyles(unittest.TestCase):
    """CSS 必须有 R150 trail 样式."""

    def test_self_test_history_classes_defined(self) -> None:
        css = _read(CSS_PATH)
        for sel in (
            ".self-test-history",
            ".self-test-history-empty",
            ".self-test-history-entry",
            ".self-test-history-when",
            ".self-test-history-verdict",
            ".self-test-history-providers",
            ".self-test-history-eventid",
        ):
            self.assertIn(sel, css, f"CSS 必须有 {sel} 选择器")

    def test_verdict_kinds_have_color_tokens(self) -> None:
        css = _read(CSS_PATH)
        for kind in ("success", "warning", "error"):
            sel = f".self-test-history-{kind} .self-test-history-verdict"
            self.assertIn(sel, css, f"verdict-kind {kind} 必须有 color rule")
            # 颜色必须用 token 而非硬编码（R66 / R99 / R109 baseline 检查）。
        self.assertIn("var(--success-500)", css)
        self.assertIn("var(--warning-500)", css)
        self.assertIn("var(--error-500)", css)


class TestR150LineCountEnvelope(unittest.TestCase):
    """JS 文件长度 envelope — R150 添加 ~150 LoC，cap 应升到 1100."""

    def test_js_file_within_envelope(self) -> None:
        line_count = sum(1 for _ in _read(JS_PATH).splitlines())
        # 下限保持 400（与 R146 envelope 测试同步）。
        self.assertGreaterEqual(
            line_count,
            700,
            f"JS 文件行数 {line_count} 偏少；R146-R148 至少 700 行打底",
        )
        self.assertLessEqual(
            line_count,
            1100,
            f"JS 文件行数 {line_count} 超过 R150 cap (1100)；考虑拆模块",
        )


if __name__ == "__main__":
    unittest.main()
