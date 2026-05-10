"""R155 — Activity Dashboard expanded-state persistence (CR#9 F-3 follow-up).

Background
----------
R152 shipped the Activity Dashboard with a collapse-by-default
toggle.  Operators who routinely watch the dashboard during
debugging sessions hit the same UX pinch: every page reload
re-collapses the panel, forcing a re-click.  Code Review #9
flagged this as F-3 (low severity, R155 candidate).

R155 closes the gap by persisting the expanded state to
localStorage under a schema-versioned key
(``aiia.activity_dashboard.expanded.v1``), mirroring the same
pattern R150 uses for the self-test history trail.  On page
load, the `init` hook reads the flag and re-opens the panel if
the user had it open.  Multi-tab sync via the standard
``storage`` event so two windows stay in lockstep.

Constraints / invariants locked by this suite
---------------------------------------------
1.  **Constants** — ``EXPANDED_LS_KEY = "aiia.activity_dashboard.expanded.v1"``
    + ``EXPANDED_SCHEMA_VERSION = 1`` exported and accessible from
    the module's public namespace.
2.  **API surface** — ``_readExpandedFlag`` and ``_writeExpandedFlag``
    exported on ``window.AIIA_ACTIVITY_DASHBOARD``.
3.  **Read defenses** — ``_readExpandedFlag`` early-returns ``null``
    on (a) localStorage unreachable, (b) JSON parse failure,
    (c) schema-version mismatch, (d) payload's ``expanded`` field
    not boolean.  Matches R150's ``_readStorage`` defensive contract.
4.  **Write defenses** — ``_writeExpandedFlag`` wraps ``setItem``
    in try/catch so quota-exceeded / disabled-storage scenarios
    cannot surface as a user-visible TypeError.
5.  **Init wiring** — ``init()`` reads the flag and calls ``_open``
    iff the flag is exactly ``true``; toggling the button calls
    ``_writeExpandedFlag(true)`` on open and ``_writeExpandedFlag(false)``
    on close.
6.  **Multi-tab sync** — ``init()`` registers a ``storage`` event
    listener that filters by ``event.key === EXPANDED_LS_KEY`` and
    drives ``_open`` / ``_close`` to follow the other tab.
7.  **Schema-version comparison shape** — the only comparison shape
    on ``EXPANDED_SCHEMA_VERSION`` inside ``_readExpandedFlag`` is
    strict equality (``===``).  Weakening to ``>=`` / ``!==`` / ``<``
    would silently let an incompatible schema's payload through
    and crash on render.  This is the CR#9 F-5 lesson applied to
    R155's new schema.

A failing case here means the JS code drifted out of lockstep with
the persistence contract; fix the source rather than weakening the
test.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/ai_intervention_agent/static/js/activity_dashboard.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestR155Constants(unittest.TestCase):
    """常量锁."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_expanded_ls_key_is_versioned_namespace(self) -> None:
        m = re.search(r'EXPANDED_LS_KEY\s*=\s*"([^"]+)"', self.js)
        self.assertIsNotNone(m, "EXPANDED_LS_KEY 必须存在")
        assert m is not None
        key = m.group(1)
        self.assertIn(
            "v1", key, f"EXPANDED_LS_KEY 必须含 v1 schema 版本 namespace：{key!r}"
        )
        self.assertIn(
            "activity_dashboard",
            key,
            "EXPANDED_LS_KEY 必须含 activity_dashboard 表明用途",
        )
        self.assertIn(
            "aiia", key, "EXPANDED_LS_KEY 必须以 aiia.* 命名空间避免与他人冲突"
        )

    def test_expanded_schema_version_is_one(self) -> None:
        m = re.search(r"EXPANDED_SCHEMA_VERSION\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "EXPANDED_SCHEMA_VERSION 必须存在")
        assert m is not None
        self.assertEqual(int(m.group(1)), 1)


class TestR155APISurface(unittest.TestCase):
    """函数 / module export 表面契约."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)

    def test_read_helper_defined(self) -> None:
        self.assertRegex(self.js, r"function\s+_readExpandedFlag\b")

    def test_write_helper_defined(self) -> None:
        self.assertRegex(self.js, r"function\s+_writeExpandedFlag\b")

    def test_window_exports(self) -> None:
        for key in (
            "EXPANDED_LS_KEY:",
            "EXPANDED_SCHEMA_VERSION:",
            "_readExpandedFlag:",
            "_writeExpandedFlag:",
        ):
            self.assertIn(
                key,
                self.js,
                f"window.AIIA_ACTIVITY_DASHBOARD 必须 export {key}",
            )


class TestR155ReadDefenses(unittest.TestCase):
    """_readExpandedFlag 必须 defensively 处理各种异常路径."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+_readExpandedFlag\s*\(\s*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_readExpandedFlag 函数体必须可被抓取")
        assert m is not None
        self.body = m.group(1)

    def test_outer_try_catch_present(self) -> None:
        self.assertIn(
            "try {",
            self.body,
            "_readExpandedFlag 必须以 try/catch 包裹整个 body 防 localStorage 抛错",
        )
        self.assertIn(
            "catch (_err)",
            self.body,
            "_readExpandedFlag 必须有 outer catch fallback 到 return null",
        )

    def test_returns_null_when_localstorage_unavailable(self) -> None:
        self.assertRegex(
            self.body,
            r'typeof\s+localStorage\s*===\s*"undefined"',
            "_readExpandedFlag 必须先用 typeof 检查 localStorage 存在",
        )

    def test_handles_json_parse_failure(self) -> None:
        # JSON.parse 必须包裹在 try/catch 内，失败时返回 null
        self.assertIn(
            "JSON.parse",
            self.body,
            "_readExpandedFlag 必须使用 JSON.parse",
        )
        # 内层 try 应该 catch JSON.parse 抛出的 SyntaxError
        self.assertRegex(
            self.body,
            r"try\s*\{\s*parsed\s*=\s*JSON\.parse",
            "JSON.parse 必须在自己的 try 块里以便 fallback 到 return null",
        )

    def test_validates_schema_version(self) -> None:
        self.assertIn(
            "parsed.v === EXPANDED_SCHEMA_VERSION",
            self.body,
            "_readExpandedFlag 必须用 === 严格比较 EXPANDED_SCHEMA_VERSION",
        )

    def test_validates_expanded_field_type(self) -> None:
        self.assertRegex(
            self.body,
            r'typeof\s+parsed\.expanded\s*===\s*"boolean"',
            "_readExpandedFlag 必须验证 parsed.expanded 是 boolean",
        )


class TestR155WriteDefenses(unittest.TestCase):
    """_writeExpandedFlag 必须 defensively 处理 quota / disabled-storage."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+_writeExpandedFlag\s*\([^)]*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_writeExpandedFlag 函数体必须可被抓取")
        assert m is not None
        self.body = m.group(1)

    def test_wrapped_in_try_catch(self) -> None:
        self.assertIn(
            "try {",
            self.body,
            "_writeExpandedFlag 必须包 try/catch 防 setItem 抛 QuotaExceededError",
        )

    def test_typeof_localstorage_guard(self) -> None:
        self.assertRegex(
            self.body,
            r'typeof\s+localStorage\s*===\s*"undefined"',
            "_writeExpandedFlag 必须先检查 localStorage 存在",
        )

    def test_uses_setitem_with_schema_versioned_payload(self) -> None:
        # 必须 JSON.stringify({ v: EXPANDED_SCHEMA_VERSION, expanded: ... })
        self.assertIn(
            "JSON.stringify",
            self.body,
            "_writeExpandedFlag 必须 JSON.stringify payload",
        )
        self.assertIn(
            "v: EXPANDED_SCHEMA_VERSION",
            self.body,
            "_writeExpandedFlag 必须把 v: EXPANDED_SCHEMA_VERSION 写进 payload",
        )

    def test_coerces_to_strict_boolean(self) -> None:
        # ``expanded === true`` 防 truthy 值（如 1, "yes"）变成 true
        self.assertIn(
            "expanded === true",
            self.body,
            "_writeExpandedFlag 必须用 === true 强转 boolean 防 truthy 输入",
        )


class TestR155InitWiring(unittest.TestCase):
    """init() 必须在加载时 hydrate flag 并在 toggle 时 write flag."""

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

    def test_toggle_writes_true_on_open(self) -> None:
        self.assertIn(
            "_writeExpandedFlag(true)",
            self.body,
            "init 的 toggle handler 必须在 open 后 _writeExpandedFlag(true)",
        )

    def test_toggle_writes_false_on_close(self) -> None:
        self.assertIn(
            "_writeExpandedFlag(false)",
            self.body,
            "init 的 toggle handler 必须在 close 后 _writeExpandedFlag(false)",
        )

    def test_hydrates_state_on_init(self) -> None:
        # init 必须读 _readExpandedFlag() 并在 === true 时 _open
        self.assertIn(
            "_readExpandedFlag()",
            self.body,
            "init 必须调用 _readExpandedFlag() 做 hydrate",
        )
        # 必须用 === true 严格比较，避免 undefined / null 触发误开
        self.assertRegex(
            self.body,
            r"_readExpandedFlag\(\)\s*===\s*true",
            "init 必须 === true 严格比较 hydrate 结果",
        )

    def test_storage_event_listener_registered(self) -> None:
        self.assertIn(
            '"storage"',
            self.body,
            "init 必须注册 window 'storage' 事件监听器以同步多标签",
        )

    def test_storage_listener_filters_by_key(self) -> None:
        self.assertIn(
            "event.key !== EXPANDED_LS_KEY",
            self.body,
            "storage 监听器必须 filter 出我们自己的 key",
        )


class TestR155SchemaVersionComparisonShape(unittest.TestCase):
    """CR#9 F-5 — property test: _readExpandedFlag 内 EXPANDED_SCHEMA_VERSION
    比较只能是 strict equality（===）；不能 >= / !== / 等等."""

    def setUp(self) -> None:
        self.js = _read(JS_PATH)
        m = re.search(
            r"function\s+_readExpandedFlag\s*\(\s*\)\s*\{(.*?)\n  \}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_readExpandedFlag 函数体必须可被抓取")
        assert m is not None
        self.body = m.group(1)

    def test_only_strict_equality(self) -> None:
        ops_after = re.findall(
            r"EXPANDED_SCHEMA_VERSION\s*(===|!==|==|!=|<=|>=|<|>)",
            self.body,
        )
        ops_before = re.findall(
            r"(===|!==|==|!=|<=|>=|<|>)\s*EXPANDED_SCHEMA_VERSION",
            self.body,
        )
        unique = set(ops_after) | set(ops_before)
        self.assertTrue(
            unique,
            "未在 _readExpandedFlag 内找到任何 EXPANDED_SCHEMA_VERSION 比较",
        )
        self.assertEqual(
            unique,
            {"==="},
            f"EXPANDED_SCHEMA_VERSION 必须只用 === 严格比较，发现 {unique!r}",
        )


if __name__ == "__main__":
    unittest.main()
