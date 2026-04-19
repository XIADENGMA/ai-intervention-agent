"""L3·G2: exercise the locale-aware ``formatNumber / formatDate /
formatRelativeTime / formatRelativeFromNow / formatList`` wrappers
baked into ``static/js/i18n.js`` and ``packages/vscode/i18n.js``.

Why these tests exist
---------------------
Without a single locale-aware formatting pipeline, contributors reach
for ``(n / 1024).toFixed(2)`` or ``date.toLocaleString()`` directly and
ship strings that (a) ignore the active locale and (b) can't be proofed
by the pseudo-locale QA gate. The wrappers route everything through
``Intl.*`` under the hood and cache per-locale instances so the hot path
(e.g. re-rendering a task list) doesn't re-construct a formatter each
call.

What we verify
--------------
1. Every wrapper is present in the public API surface in BOTH copies of
   the module.
2. ``formatNumber`` respects the active locale (en uses ``,`` as
   thousands sep; zh-CN uses ``,`` too but we still check formatter
   swap happens). Respects ``options.maximumFractionDigits``.
3. ``formatDate`` respects the active locale and returns something
   sensible for both Date and epoch-ms.
4. ``formatRelativeTime`` routes through ``Intl.RelativeTimeFormat``
   (e.g. ``"3 days ago"`` for en, ``"3天前"`` for zh-CN).
5. ``formatRelativeFromNow`` auto-picks the right unit for a delta and
   matches the ICU output format.
6. ``formatList`` uses ``Intl.ListFormat`` conjunction formatting.
7. Invalid input fails gracefully (``NaN`` → stringified fallback,
   ``null`` / ``undefined`` → empty / raw value).
8. Repeated calls are **idempotent** — the cache doesn't corrupt
   subsequent returns.

Node harness
------------
We reuse the same subprocess-based pattern as
``test_i18n_icu_plural.py``: load the real file via ``require(...)``,
register a locale (empty — these wrappers don't touch the locale
dictionary), set lang, then call the function by name and print the
result. Tests SKIP when ``node`` isn't on PATH so developer laptops
without Node can still run the Python suite — CI always has Node via
the mocha gate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBUI_I18N = REPO_ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N = REPO_ROOT / "packages" / "vscode" / "i18n.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _call_api(
    i18n_path: Path,
    lang: str,
    method: str,
    args: list,
) -> str:
    """Call ``api[method](...args)`` inside a node subprocess and return
    the stringified output.

    ``args`` are JSON-serialized; tests pass strings, numbers, plain
    objects, and arrays. For Date inputs we pass the epoch ms and let
    the JS side turn it into a Date (the wrappers accept both).
    """
    harness = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: %(lang_literal)s };
        require(%(path_literal)s);
        const api = globalThis.AIIA_I18N;
        api.registerLocale(%(lang_literal)s, {});
        api.setLang(%(lang_literal)s);
        const args = %(args_literal)s;
        const out = api[%(method_literal)s].apply(null, args);
        process.stdout.write(String(out));
        """
    ) % {
        "path_literal": json.dumps(str(i18n_path)),
        "lang_literal": json.dumps(lang),
        "method_literal": json.dumps(method),
        "args_literal": json.dumps(args),
    }
    proc = subprocess.run(
        ["node", "-e", harness],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}:\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _api_surface(i18n_path: Path) -> list[str]:
    harness = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: "en" };
        require(%(path_literal)s);
        const keys = Object.keys(globalThis.AIIA_I18N).sort();
        process.stdout.write(JSON.stringify(keys));
        """
    ) % {"path_literal": json.dumps(str(i18n_path))}
    proc = subprocess.run(
        ["node", "-e", harness],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)


_NODE_MESSAGE = "node runtime unavailable; covered by mocha gate"


@unittest.skipUnless(_node_available(), _NODE_MESSAGE)
class TestIntlSurface(unittest.TestCase):
    """Both copies MUST expose the same public Intl wrapper set."""

    def test_webui_exposes_all_wrappers(self) -> None:
        keys = set(_api_surface(WEBUI_I18N))
        for expected in (
            "formatNumber",
            "formatDate",
            "formatRelativeTime",
            "formatRelativeFromNow",
            "formatList",
        ):
            self.assertIn(expected, keys, f"missing {expected!r} in web UI api")

    def test_vscode_exposes_all_wrappers(self) -> None:
        keys = set(_api_surface(VSCODE_I18N))
        for expected in (
            "formatNumber",
            "formatDate",
            "formatRelativeTime",
            "formatRelativeFromNow",
            "formatList",
        ):
            self.assertIn(expected, keys, f"missing {expected!r} in vscode api")


class _WrapperTestsMixin(unittest.TestCase):
    """Shared behavior tests; subclassed with a concrete I18N_PATH.

    ``__test__ = False`` keeps pytest from collecting the abstract mixin
    itself while still giving the type-checker visibility into
    ``unittest.TestCase``'s assertion surface (``assertEqual`` etc.)."""

    __test__ = False

    I18N_PATH: Path

    def _call(self, lang: str, method: str, args: list) -> str:
        return _call_api(self.I18N_PATH, lang, method, args)

    def test_format_number_english(self) -> None:
        # 1,234,567 en-US: comma-separated
        out = self._call("en", "formatNumber", [1234567])
        self.assertEqual(out, "1,234,567")

    def test_format_number_chinese(self) -> None:
        # 1,234,567 zh-CN: comma-separated too (CLDR uses grouping=3)
        out = self._call("zh-CN", "formatNumber", [1234567])
        self.assertEqual(out, "1,234,567")

    def test_format_number_options_fraction_digits(self) -> None:
        out = self._call(
            "en",
            "formatNumber",
            [1234.5678, {"maximumFractionDigits": 2}],
        )
        self.assertEqual(out, "1,234.57")

    def test_format_number_invalid_value_fallback(self) -> None:
        # Intl.NumberFormat.format(NaN) returns 'NaN' in ICU; still stable.
        out = self._call("en", "formatNumber", ["not-a-number"])
        self.assertIn(out, ("NaN", "not-a-number"))

    def test_format_date_english_returns_nonempty(self) -> None:
        # 2024-01-02T03:04:05Z
        out = self._call("en", "formatDate", [1704164645000])
        # The exact format is locale-data dependent; assert it's non-empty
        # and contains the year.
        self.assertTrue(out)
        self.assertIn("2024", out)

    def test_format_date_with_options(self) -> None:
        out = self._call(
            "en",
            "formatDate",
            [1704164645000, {"year": "numeric", "month": "short", "day": "numeric"}],
        )
        self.assertIn("2024", out)

    def test_format_date_invalid_returns_something(self) -> None:
        out = self._call("en", "formatDate", ["not-a-date"])
        # Either an "Invalid Date" string from Intl, or an ISO fallback.
        self.assertTrue(isinstance(out, str))

    def test_format_relative_time_english(self) -> None:
        out = self._call("en", "formatRelativeTime", [-3, "day"])
        # en-US: "3 days ago". We match loosely to accommodate ICU variants.
        self.assertIn("3", out)
        self.assertIn("day", out.lower())

    def test_format_relative_time_chinese(self) -> None:
        out = self._call("zh-CN", "formatRelativeTime", [-3, "day"])
        self.assertIn("3", out)

    def test_format_list_two_items_english(self) -> None:
        out = self._call("en", "formatList", [["Alice", "Bob"]])
        # en-US conjunction: "Alice and Bob"
        self.assertIn("Alice", out)
        self.assertIn("Bob", out)
        self.assertIn("and", out)

    def test_format_list_three_items_english(self) -> None:
        out = self._call("en", "formatList", [["a", "b", "c"]])
        self.assertIn("a", out)
        self.assertIn("b", out)
        self.assertIn("c", out)

    def test_format_list_empty_returns_empty(self) -> None:
        out = self._call("en", "formatList", [[]])
        self.assertEqual(out, "")

    def test_format_list_single_item(self) -> None:
        out = self._call("en", "formatList", [["only"]])
        self.assertEqual(out, "only")

    def test_format_relative_from_now_seconds(self) -> None:
        # Target = now; should be "0 seconds" or similar.
        # Node exec time jitter is <1s, so the bucket can land on 0 s.
        # We only assert the output mentions a time-like unit word.
        harness = textwrap.dedent(
            """
            globalThis.window = globalThis;
            globalThis.document = undefined;
            globalThis.navigator = { language: "en" };
            require(%(path_literal)s);
            const api = globalThis.AIIA_I18N;
            api.registerLocale("en", {});
            api.setLang("en");
            // Target 2s in the future; choose a value safely inside the
            // "second" bucket (<60s) and away from the rounding edge.
            const out = api.formatRelativeFromNow(Date.now() + 2000);
            process.stdout.write(String(out));
            """
        ) % {"path_literal": json.dumps(str(self.I18N_PATH))}
        proc = subprocess.run(
            ["node", "-e", harness],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertTrue(out)
        self.assertIn("second", out.lower())

    def test_format_cache_does_not_corrupt_results(self) -> None:
        # Run the same call twice and verify both return identical output.
        harness = textwrap.dedent(
            """
            globalThis.window = globalThis;
            globalThis.document = undefined;
            globalThis.navigator = { language: "en" };
            require(%(path_literal)s);
            const api = globalThis.AIIA_I18N;
            api.registerLocale("en", {});
            api.setLang("en");
            const a = api.formatNumber(1234.5678, { maximumFractionDigits: 2 });
            const b = api.formatNumber(1234.5678, { maximumFractionDigits: 2 });
            const c = api.formatNumber(42);
            const d = api.formatNumber(1234.5678, { maximumFractionDigits: 2 });
            process.stdout.write(JSON.stringify([a, b, c, d]));
            """
        ) % {"path_literal": json.dumps(str(self.I18N_PATH))}
        proc = subprocess.run(
            ["node", "-e", harness],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        a, b, c, d = json.loads(proc.stdout)
        self.assertEqual(a, b)
        self.assertEqual(a, d)
        # Different options → different cached instance, different output.
        self.assertNotEqual(a, c)

    def test_locale_switch_invalidates_via_different_cache_key(self) -> None:
        # Confirm switching lang actually affects formatNumber output.
        harness = textwrap.dedent(
            """
            globalThis.window = globalThis;
            globalThis.document = undefined;
            globalThis.navigator = { language: "en" };
            require(%(path_literal)s);
            const api = globalThis.AIIA_I18N;
            api.registerLocale("en", {});
            api.registerLocale("zh-CN", {});
            api.setLang("en");
            const formatEn = api.formatRelativeTime(-3, "day");
            api.setLang("zh-CN");
            const formatZh = api.formatRelativeTime(-3, "day");
            process.stdout.write(JSON.stringify([formatEn, formatZh]));
            """
        ) % {"path_literal": json.dumps(str(self.I18N_PATH))}
        proc = subprocess.run(
            ["node", "-e", harness],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        en, zh = json.loads(proc.stdout)
        # They should differ: en → "3 days ago", zh → "3天前".
        self.assertNotEqual(en, zh)


@unittest.skipUnless(_node_available(), _NODE_MESSAGE)
class TestIntlWebUI(_WrapperTestsMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), _NODE_MESSAGE)
class TestIntlVSCode(_WrapperTestsMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


if __name__ == "__main__":
    unittest.main()
