"""Enforce an XSS-safety annotation on every ``.innerHTML = t(…)`` site.

Why this matters
----------------
i18next shipped **two** disclosed XSS CVEs (CVE-2017-16010 and
AIKIDO-2024-10543) that boil down to the same root cause: callers
assume interpolated translation output is HTML-safe, write it to
``.innerHTML`` (or a framework equivalent that forwards to
``innerHTML``), and a malicious author of translations — or of a
parameter value — can inject arbitrary markup / ``<script>`` / ``on*``
handlers.

Our ``t()`` intentionally does **not** HTML-escape, because (a) most
callers write it to ``textContent`` which auto-escapes, and (b) we use
ICU ``#`` / mustache ``{{…}}`` interpolation with developer-authored
templates where escaping would double-encode. That's the same contract
``react-intl``'s ``FormattedMessage`` makes when rendered inside JSX.

So the contract every caller must obey is simple and auditable:

    Any line that writes a ``t(…)`` / ``_t(…)`` / DOM-translation output
    to ``.innerHTML`` (or ``.innerHTML +=``) MUST carry an explicit
    ``AIIA-XSS-SAFE:`` comment explaining why the payload is safe —
    typically "dev-authored locale key + non-user-controlled params"
    or "runs through ``sanitizePromptHtml``".

This test is the auditable enforcement: it scans ``static/js/**`` and
``packages/vscode/**`` for any ``.innerHTML`` write that pulls from a
translation API and fails the suite unless the same line or the
immediate preceding line carries the contract marker. New contributors
get a pointer to ``docs/i18n.md`` Security §.

Scope & non-goals
-----------------
* We deliberately **don't** cover every ``.innerHTML =`` write —
  SVG markup, sanitised markdown, and fixed HTML blocks are outside
  this policy's remit. That's the job of the separate CSP hardening
  track.
* Minified mirrors (``*.min.js``) are excluded; they're generated
  artefacts.
* Third-party vendored files (prism / marked / mathjax / lottie) are
  excluded.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_GLOBS = [
    ROOT / "static" / "js",
    ROOT / "packages" / "vscode",
]
EXCLUDE_DIRS = {
    "node_modules",
    "vendor",
    "mathjax",
    "lottie",
    "prism-components",
    "dist",
    "test",
    "tests",
    # ``npm run vscode:check`` unpacks a pristine Visual Studio Code
    # release into ``packages/vscode/.vscode-test/`` for integration
    # testing. Those are MIT-licensed third-party sources we must not
    # audit (and can't patch, since the next test run re-extracts
    # them).
    ".vscode-test",
}
EXCLUDE_FILE_PATTERNS = (
    re.compile(r"\.min\.js$"),
    re.compile(r"^prism(\.|-)", re.IGNORECASE),
    re.compile(r"^marked", re.IGNORECASE),
    re.compile(r"^lottie", re.IGNORECASE),
    re.compile(r"^tex-mml"),
)

SAFETY_MARKER = "AIIA-XSS-SAFE:"

# ``hEl.innerHTML = hVal`` in i18n.js translateDOM is the canonical
# "allow HTML on a ``data-i18n-html`` attribute" path — the value came
# straight from ``t(key)`` without params. The marker must still be on
# that line; we don't special-case it.
INNERHTML_T_CALL = re.compile(
    r"\.innerHTML\s*[+]?=\s*[^;]*?(?:\bt\(|\b_t\(|\bt\s*\(|\bhVal\b|\b__domSecT\b)"
)

# A line qualifies as "part of the safety comment block" above the
# ``.innerHTML = …`` assignment when it is pure whitespace or a
# ``//``/``/*``/``*`` comment line. We walk upward from the offending
# line collecting such lines — the marker only needs to appear
# *somewhere in that contiguous comment block*. This matches how
# developers actually write multi-line rationale comments (e.g. three
# ``//`` lines citing the locale key, the interpolated params, and the
# ``docs/i18n.md`` section) without forcing everything onto a single
# line.
_COMMENT_LINE = re.compile(r"^\s*(?://|/\*|\*|$)")


def _iter_js_files() -> list[Path]:
    out: list[Path] = []
    for root in TARGET_GLOBS:
        for path in root.rglob("*.js"):
            rel = path.relative_to(ROOT)
            parts = set(rel.parts)
            if parts & EXCLUDE_DIRS:
                continue
            name = path.name
            if any(pat.search(name) for pat in EXCLUDE_FILE_PATTERNS):
                continue
            out.append(path)
        for path in root.rglob("*.ts"):
            rel = path.relative_to(ROOT)
            parts = set(rel.parts)
            if parts & EXCLUDE_DIRS:
                continue
            out.append(path)
    return sorted(out)


def _has_safety_marker(lines: list[str], idx: int) -> bool:
    """Return ``True`` if an ``AIIA-XSS-SAFE:`` marker is attached to
    ``lines[idx]``.

    The marker is accepted when it appears either:

    * on the assignment line itself (trailing ``// AIIA-XSS-SAFE: …``), or
    * anywhere in the contiguous comment block that directly precedes
      the assignment line. The block is the run of consecutive ``//``,
      ``/*``, ``*``, or blank lines immediately above, and stops at the
      first code line — exactly how ``eslint-disable-next-line`` would
      delimit it, generalised to multi-line rationale.
    """
    if SAFETY_MARKER in lines[idx]:
        return True
    cursor = idx - 1
    while cursor >= 0 and _COMMENT_LINE.match(lines[cursor]):
        if SAFETY_MARKER in lines[cursor]:
            return True
        cursor -= 1
    return False


class TestInnerHtmlSafetyComment(unittest.TestCase):
    def test_every_innerhtml_t_call_carries_safety_marker(self) -> None:
        offenders: list[tuple[Path, int, str]] = []
        for path in _iter_js_files():
            lines = path.read_text(encoding="utf-8").splitlines()
            for idx, line in enumerate(lines):
                if not INNERHTML_T_CALL.search(line):
                    continue
                if _has_safety_marker(lines, idx):
                    continue
                offenders.append((path.relative_to(ROOT), idx + 1, line.strip()))
        if offenders:
            formatted = [f"{p}:{ln}: {src}" for (p, ln, src) in offenders]
            self.fail(
                "Each .innerHTML write that consumes a translation must carry "
                "an 'AIIA-XSS-SAFE: <reason>' comment on the same line or in "
                "the contiguous comment block immediately above it (see "
                "docs/i18n.md § Security). Offenders:\n  " + "\n  ".join(formatted)
            )

    def test_marker_regex_does_not_trigger_on_textcontent(self) -> None:
        """Sanity: the regex must not false-positive on ``textContent = t(…)``
        or ``innerText = t(…)``. This is a self-test so future regex tweaks
        don't accidentally widen the net to safe sinks.
        """
        safe_lines = [
            "button.textContent = t('status.copied')",
            "element.innerText = _t('page.label')",
            "span.setAttribute('aria-label', t('aria.close'))",
        ]
        for src in safe_lines:
            with self.subTest(src=src):
                self.assertIsNone(INNERHTML_T_CALL.search(src))

    def test_marker_regex_catches_the_canonical_violations(self) -> None:
        """Sanity: the regex must hit the exact patterns the codebase
        uses today — catching them IS the point of the test.
        """
        unsafe_lines = [
            "button.innerHTML = checkIconSvg + t('status.copied')",
            "submitBtn.innerHTML = t('status.submitting')",
            "hint.innerHTML = `${svg}${_t('page.noContent.newTasks', { count: count })}`",
            "if (hVal !== hKey) hEl.innerHTML = hVal",
            "button.innerHTML = `${copyIconSvg}${__domSecT('page.copyFailed')}`",
        ]
        for src in unsafe_lines:
            with self.subTest(src=src):
                self.assertIsNotNone(INNERHTML_T_CALL.search(src))

    def test_comment_block_walker_scans_past_multi_line_rationale(self) -> None:
        """``_has_safety_marker`` must treat a three-line ``//`` block as
        one "attached" comment, not three independent lines.
        """
        block = [
            "    // AIIA-XSS-SAFE: dev-authored icon + static locale key.",
            "    // t() does not interpolate user-controlled params here.",
            "    // See docs/i18n.md § Security.",
            "    button.innerHTML = iconSvg + t('status.copied')",
        ]
        self.assertTrue(_has_safety_marker(block, 3))

    def test_comment_block_walker_rejects_detached_markers(self) -> None:
        """A marker separated from the assignment by a code line must
        **not** count — otherwise a stale marker upstream could keep
        masking new offenders.
        """
        block = [
            "    // AIIA-XSS-SAFE: belongs to the previous innerHTML call.",
            "    element.classList.add('loaded')",
            "    other.innerHTML = t('status.ready')",
        ]
        self.assertFalse(_has_safety_marker(block, 2))


if __name__ == "__main__":
    unittest.main()
