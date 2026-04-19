"""L3·G2 follow-up: pin ``formatRelativeFromNow`` bucket boundaries to
the industry-canonical moment.js thresholds (44s / 45m / 22h / 26d /
11month). Without this test we shipped output like ``"in 60 seconds"``
/ ``"in 60 minutes"`` / ``"in 24 hours"`` / ``"in 30 days"`` /
``"in 12 months"`` at the exact threshold where the user expects
``"in 1 minute"`` / ``"in 1 hour"`` / ``"in 1 day"`` / ``"in 1 month"``
/ ``"in 1 year"``.

Why moment's table and not our first-principles alternatives
------------------------------------------------------------
- moment.js ships ``s=45 / m=45 / h=22 / d=26 / M=11`` as defaults,
  documented and referenced by day.js, luxon, date-fns-tz and every
  major humanize library since ~2014.
- ``Intl.RelativeTimeFormat`` only handles *value + unit → string*;
  it explicitly leaves bucket-selection to the caller. Copying moment
  avoids reinventing UX research.
- Using the moment cutoffs makes our rounding behaviour match every
  existing user-facing RTL bar chart / timeline on the web, reducing
  the ``60-seconds-ago`` footgun to zero.

Deterministic harness
---------------------
We inject a fake ``Date`` into the node VM so each assertion maps to
a known ``absSec``. ``Intl.RelativeTimeFormat.format(...)`` still uses
the real ICU data (node's embedded CLDR), so the expected English
strings lock us to the ICU contract, not to our own string table.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBUI_I18N = ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N = ROOT / "packages" / "vscode" / "i18n.js"

FAKE_NOW_MS = 1_704_164_645_000  # fixed epoch; deterministic reruns


def _node_available() -> bool:
    return shutil.which("node") is not None


def _call_from_now(i18n_path: Path, delta_ms: int, lang: str = "en") -> str:
    """Call ``api.formatRelativeFromNow(FAKE_NOW + delta_ms)`` in a VM
    where ``Date.now()`` is pinned to ``FAKE_NOW_MS``. Return stdout."""
    script = textwrap.dedent(
        """
        const FAKE_NOW = %(fake_now)d;
        class FakeDate extends Date {
          constructor(...a) {
            if (a.length === 0) super(FAKE_NOW);
            else super(...a);
          }
          static now() { return FAKE_NOW; }
        }
        globalThis.Date = FakeDate;
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: %(lang_literal)s };
        require(%(path_literal)s);
        const api = globalThis.AIIA_I18N;
        api.registerLocale(%(lang_literal)s, {});
        api.setLang(%(lang_literal)s);
        const out = api.formatRelativeFromNow(FAKE_NOW + %(delta_ms)d);
        process.stdout.write(String(out));
        """
    ) % {
        "fake_now": FAKE_NOW_MS,
        "lang_literal": json.dumps(lang),
        "path_literal": json.dumps(str(i18n_path)),
        "delta_ms": delta_ms,
    }
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


# moment's default thresholds, translated into absSec ceilings:
#   absSec <  45        → seconds
#   absSec <  45 * 60   → minutes   (2700)
#   absSec <  22 * 3600 → hours     (79200)
#   absSec <  26 * 86400 → days     (2246400)
#   absSec <  11 * 2592000 → months (28512000, using 30-day month)
#   else               → years
#
# Expected Intl.RelativeTimeFormat.format output (numeric='always', en):
#   ``in <n> <unit>`` with unit pluralised for n != 1.
#
# Note: the 30-day month is what moment.js uses internally; keeping it
# consistent avoids subtle off-by-hours regressions when switching libs.
CASES = [
    # label,                  delta_ms,                expect_substring,      forbidden_substring
    ("0s", 0, "0 seconds", None),
    ("44s_stay", 44_000, "44 seconds", None),
    ("45s_promote_minute", 45_000, "1 minute", "seconds"),
    ("59s_minute", 59_000, "1 minute", None),
    ("89s_minute", 89_000, "1 minute", None),
    ("90s_minute2", 90_000, "2 minutes", None),
    ("2699s_45_minute", 2_699_000, "45 minutes", None),
    ("2700s_promote_hour", 2_700_000, "1 hour", "minute"),
    ("79199s_22h", 79_199_000, "22 hours", None),
    ("79200s_promote_day", 79_200_000, "1 day", "hour"),
    ("2246399s_26d", 2_246_399_000, "26 days", None),
    ("2246400s_promote_month", 2_246_400_000, "1 month", "day"),
    ("28511999s_11mo", 28_511_999_000, "11 months", None),
    ("28512000s_promote_year", 28_512_000_000, "1 year", "month"),
    # Past-facing (negative deltas) parity:
    ("neg_45s_promote", -45_000, "1 minute ago", None),
    ("neg_2700s_promote", -2_700_000, "1 hour ago", None),
    ("neg_79200s_promote", -79_200_000, "1 day ago", None),
]


class _ThresholdMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def _run_case(
        self, label: str, delta_ms: int, expect: str, forbid: str | None
    ) -> None:
        out = _call_from_now(self.I18N_PATH, delta_ms)
        self.assertIn(
            expect,
            out,
            f"case={label!r} delta_ms={delta_ms} got={out!r} expect substring={expect!r}",
        )
        if forbid:
            self.assertNotIn(
                forbid,
                out,
                f"case={label!r} delta_ms={delta_ms} got={out!r} "
                f"must NOT contain {forbid!r} (bucket bleed / no promotion)",
            )


def _make_case(label: str, delta_ms: int, expect: str, forbid: str | None):
    def _t(self: _ThresholdMixin) -> None:
        self._run_case(label, delta_ms, expect, forbid)

    _t.__name__ = f"test_{label}"
    return _t


for _label, _delta, _expect, _forbid in CASES:
    setattr(
        _ThresholdMixin,
        f"test_{_label}",
        _make_case(_label, _delta, _expect, _forbid),
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestRelativeTimeThresholdsWebUI(_ThresholdMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestRelativeTimeThresholdsVSCode(_ThresholdMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


class TestByteParityForRelativeTimeBuckets(unittest.TestCase):
    """The two copies MUST produce identical output on every bucket
    boundary so UI/VSCode feel the same on a 45-second-old timestamp."""

    @unittest.skipUnless(_node_available(), "node runtime unavailable")
    def test_two_halves_match_on_every_case(self) -> None:
        mismatches: list[str] = []
        for label, delta_ms, _, _ in CASES:
            web = _call_from_now(WEBUI_I18N, delta_ms)
            vsc = _call_from_now(VSCODE_I18N, delta_ms)
            if web != vsc:
                mismatches.append(f"{label}: web={web!r} vsc={vsc!r}")
        self.assertFalse(
            mismatches,
            "two-halves divergence:\n  " + "\n  ".join(mismatches),
        )


# ---- Edge-case inputs (Infinity / NaN / MAX_SAFE_INTEGER) -----------------
#
# Users occasionally hand ``formatRelativeFromNow`` garbage — a missing
# timestamp coerced through ``new Date("")``, an ``Infinity`` from a
# broken API, a ``Number.MAX_SAFE_INTEGER`` accidentally left over from
# a loop bound. The contract is:
#   - Never throw. The formatter is on the rendering hot path; a throw
#     there breaks the whole translated string.
#   - Return the relative-time string for 0 seconds (``"in 0 seconds"``
#     under ``numeric: 'always'``, ``en``). This matches moment.js's
#     humanize(0) behaviour when fed a junk duration and is the least-
#     surprising fallback we can offer.
#   - Web UI and VSCode copies MUST behave identically (byte parity).


def _call_with_target_expr(i18n_path: Path, target_expr: str, lang: str = "en") -> str:
    """Evaluate ``target_expr`` at Node level and pass the resulting
    value directly into ``formatRelativeFromNow``. Lets us exercise
    non-JSON-encodable inputs like ``Infinity`` and ``NaN``.
    """
    script = textwrap.dedent(
        """
        const FAKE_NOW = %(fake_now)d;
        class FakeDate extends Date {
          constructor(...a) {
            if (a.length === 0) super(FAKE_NOW);
            else super(...a);
          }
          static now() { return FAKE_NOW; }
        }
        globalThis.Date = FakeDate;
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: %(lang_literal)s };
        require(%(path_literal)s);
        const api = globalThis.AIIA_I18N;
        api.registerLocale(%(lang_literal)s, {});
        api.setLang(%(lang_literal)s);
        const target = (%(target_expr)s);
        const out = api.formatRelativeFromNow(target);
        process.stdout.write(String(out));
        """
    ) % {
        "fake_now": FAKE_NOW_MS,
        "lang_literal": json.dumps(lang),
        "path_literal": json.dumps(str(i18n_path)),
        "target_expr": target_expr,
    }
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


EDGE_CASES = [
    # label, target_expr, expected_substring
    ("positive_infinity", "Infinity", "0 seconds"),
    ("negative_infinity", "-Infinity", "0 seconds"),
    ("nan", "NaN", "0 seconds"),
    ("max_safe_integer", "Number.MAX_SAFE_INTEGER", "0 seconds"),
    ("min_safe_integer", "Number.MIN_SAFE_INTEGER", "0 seconds"),
    ("invalid_date_string", 'new Date("not-a-date")', "0 seconds"),
    ("invalid_date_literal", 'new Date("")', "0 seconds"),
    ("undefined_target", "undefined", "0 seconds"),
    ("null_target", "null", "0 seconds"),
]


class _EdgeCaseMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def _run_edge(self, label: str, target_expr: str, expect: str) -> None:
        out = _call_with_target_expr(self.I18N_PATH, target_expr)
        self.assertIn(
            expect,
            out,
            f"edge case={label!r} target_expr={target_expr!r} "
            f"got={out!r} expect substring={expect!r}",
        )


def _make_edge(label: str, target_expr: str, expect: str):
    def _t(self: _EdgeCaseMixin) -> None:
        self._run_edge(label, target_expr, expect)

    _t.__name__ = f"test_edge_{label}"
    return _t


for _label, _expr, _expect in EDGE_CASES:
    setattr(
        _EdgeCaseMixin,
        f"test_edge_{_label}",
        _make_edge(_label, _expr, _expect),
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestRelativeTimeEdgeWebUI(_EdgeCaseMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestRelativeTimeEdgeVSCode(_EdgeCaseMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestRelativeTimeEdgeByteParity(unittest.TestCase):
    def test_edge_outputs_match_between_halves(self) -> None:
        mismatches: list[str] = []
        for label, expr, _ in EDGE_CASES:
            web = _call_with_target_expr(WEBUI_I18N, expr)
            vsc = _call_with_target_expr(VSCODE_I18N, expr)
            if web != vsc:
                mismatches.append(f"{label}: web={web!r} vsc={vsc!r}")
        self.assertFalse(
            mismatches,
            "edge-case output diverged across halves:\n  " + "\n  ".join(mismatches),
        )


if __name__ == "__main__":
    unittest.main()
