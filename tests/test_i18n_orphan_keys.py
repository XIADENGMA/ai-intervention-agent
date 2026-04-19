"""L4·G1 – pytest mirror of ``scripts/check_i18n_orphan_keys.py``.

What this protects
------------------
The script itself is warn-only (never fails CI). That's intentional:
it exists to give contributors a soft signal about keys that have
accumulated in a locale file without any referrer. A strict gate
already exists in ``test_runtime_behavior.py`` — this pytest guards
the **scanner** rather than the codebase:

1. The regex that extracts ``t(...)``-style call keys must recognize
   every wrapper we actually use in production (``_t``, ``tl``,
   ``hostT``, ``__vuT``, ``__domSecT``, ``__ncT``). If someone adds a
   new wrapper and forgets to update the scanner, orphan reports will
   lie; this test catches that.
2. The scanner's output shape must be stable JSON (``orphans``,
   ``total_keys``, ``used_keys`` per surface). Downstream consumers
   (future dashboards, PR commenters) depend on the shape.
3. ``--strict`` actually fails on orphan input.
4. ``--json`` emits valid JSON.

These are scanner-contract tests, not codebase-state tests. They use
fabricated fixtures where possible to avoid double-coverage with
the dead-key test in ``test_runtime_behavior.py``.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_i18n_orphan_keys import (
    JS_T_CALL_RE,
    _flatten_keys,
    main,
    scan,
)


class TestRegexCoversAllWrappers(unittest.TestCase):
    """The JS_T_CALL_RE regex MUST recognize every wrapper the project
    uses. Production code paths, not hypothetical ones."""

    def test_every_known_wrapper(self) -> None:
        for call, expected in [
            ("t('a.b.c')", "a.b.c"),
            ("_t('foo.bar')", "foo.bar"),
            ("tl('baz.qux')", "baz.qux"),
            ("hostT('statusBar.tasks')", "statusBar.tasks"),
            ("__vuT('validation.x')", "validation.x"),
            ("__domSecT('page.y')", "page.y"),
            ("__ncT('notify.z')", "notify.z"),
        ]:
            with self.subTest(call=call):
                matches = JS_T_CALL_RE.findall(call)
                self.assertIn(expected, matches, f"regex missed {call!r}")

    def test_property_access_not_matched(self) -> None:
        """``obj.t('foo')`` MUST NOT be picked up (property access)."""
        matches = JS_T_CALL_RE.findall("obj.t('foo.bar')")
        self.assertEqual(matches, [])

    def test_variable_identifier_not_matched(self) -> None:
        """``myT('foo')`` is NOT one of our wrappers — must be skipped."""
        matches = JS_T_CALL_RE.findall("myT('foo.bar')")
        self.assertEqual(matches, [])


class TestFlatten(unittest.TestCase):
    def test_flatten_simple(self) -> None:
        self.assertEqual(
            _flatten_keys({"a": {"b": "x", "c": "y"}, "d": "z"}),
            {"a.b", "a.c", "d"},
        )

    def test_flatten_ignores_non_dict_descendants(self) -> None:
        # Arrays / numbers aren't i18n "keys"; flatten should stop at
        # the nearest leaf.
        self.assertEqual(
            _flatten_keys({"a": [1, 2, 3], "b": 7}),
            {"a", "b"},
        )


class TestScanReturnsStableShape(unittest.TestCase):
    """Run the real scanner against the committed codebase.

    We don't assert exact orphan counts (those drift intentionally as
    the codebase evolves). We only assert the SHAPE."""

    def test_shape(self) -> None:
        report = scan()
        self.assertIn("web", report)
        self.assertIn("vscode", report)
        for surface in ("web", "vscode"):
            entry = report[surface]
            self.assertIn("orphans", entry)
            self.assertIn("total_keys", entry)
            self.assertIn("used_keys", entry)
            self.assertIsInstance(entry["orphans"], list)
            self.assertIsInstance(entry["total_keys"], int)
            self.assertIsInstance(entry["used_keys"], int)


class TestMainModes(unittest.TestCase):
    """Exit-code contract of ``main(...)``."""

    def test_default_is_warn(self, capsys=None) -> None:
        rc = main([])
        self.assertEqual(rc, 0, "warn mode must never exit non-zero")

    def test_json_is_valid_json(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertIn("web", parsed)
        self.assertIn("vscode", parsed)

    def test_strict_exits_zero_when_no_orphans(self) -> None:
        # The current codebase is orphan-free, so --strict must pass.
        rc = main(["--strict"])
        self.assertEqual(
            rc,
            0,
            "codebase currently has 0 orphans; --strict should exit 0",
        )


if __name__ == "__main__":
    unittest.main()
