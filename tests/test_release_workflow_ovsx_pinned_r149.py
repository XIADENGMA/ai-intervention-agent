"""R149 — ``ovsx`` version pin guard for release workflow.

Background
----------
Between v1.6.0 (released 2026-05-08, succeeded) and v1.6.1 (released
2026-05-10, **failed**) the project's ``ovsx`` invocation in
``.github/workflows/release.yml`` was the floating
``npx --yes ovsx publish ...``.  In those two days, ``ovsx``'s
publish-side validator tightened its handling of NLS placeholders for
``displayName``: the same VSIX that v1.6.0 had successfully published
got rejected with "Display name in extension.vsixmanifest and
package.json does not match" for v1.6.1.

The fix in :file:`tests/test_vscode_displayname_literal_for_ovsx.py`
addresses the underlying displayName inconsistency.  This file (R149)
addresses the **second** root cause: the floating ``ovsx`` tag means
any future upstream tightening can again silently break a release.
With a pin we get deterministic, reproducible publishes; an upgrade is
a tracked PR (caller bumps the pin → re-runs release on a tag → either
ships or fails predictably) instead of an undated toolchain drift.

What this test pins
-------------------
1.  The ``ovsx publish`` step in :file:`.github/workflows/release.yml`
    invokes ``npx --yes ovsx@<X.Y.Z> publish``.  Floating tag
    (``npx --yes ovsx publish``) is forbidden.
2.  The same pin appears for the ``ovsx verify-pat`` invocation
    (lest the two go out of sync and we publish with a different
    binary than we verified the PAT against).
3.  The pinned version follows semver (``\\d+\\.\\d+\\.\\d+``) — no
    ``latest`` / ``next`` / floating version selectors.
4.  At least one comment near the invocation explains *why* the pin
    exists, so a future contributor can find R149's history rather
    than silently restoring the floating tag.

Why this lives in tests/ instead of pre-commit
----------------------------------------------
``ci_gate.py`` runs the full pytest suite, so a guard placed here
gates the same merges that pre-commit does.  Open VSX failures
historically only surfaced *after* a release tag was pushed — far too
late.  This test catches a "let's just unpin ovsx, latest is always
fine" patch at PR review time.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _read_workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


class TestOvsxVersionPinned(unittest.TestCase):
    def test_workflow_file_exists(self) -> None:
        self.assertTrue(WORKFLOW.exists(), f"missing {WORKFLOW}")

    def test_no_floating_ovsx_invocation(self) -> None:
        # Forbid bare ``npx --yes ovsx publish`` / ``ovsx verify-pat``.
        # Allow ``ovsx@x.y.z``.  Use a regex that intentionally does NOT
        # match the pinned form so a single grep tells us about drift.
        text = _read_workflow()
        for verb in ("publish", "verify-pat"):
            unpinned_pattern = rf"npx\s+--yes\s+ovsx\s+{re.escape(verb)}"
            self.assertNotRegex(
                text,
                unpinned_pattern,
                f"release.yml has unpinned ``npx --yes ovsx {verb}`` — "
                f"R149 pinned this to ``ovsx@<x.y.z>`` because the "
                f"floating tag silently broke v1.6.1.  Restore the pin "
                f"or update the pinned version, but do not unpin.",
            )

    def test_pinned_version_format(self) -> None:
        text = _read_workflow()
        # Match every ``ovsx@<...>`` and ensure it's strict semver.
        # ``\b`` anchors so ``ovsx@@`` won't false-match.
        all_pins = re.findall(r"\bovsx@(\S+)\b", text)
        self.assertTrue(
            all_pins,
            "release.yml is missing any ``ovsx@<version>`` pin; R149 "
            "requires at least one for the Open VSX publish step.",
        )
        for pin in all_pins:
            self.assertRegex(
                pin,
                r"^\d+\.\d+\.\d+$",
                f"ovsx pin {pin!r} is not strict semver. R149 forbids "
                f"floating selectors (``latest`` / ``next`` / etc.) "
                f"because they re-create the same drift that broke "
                f"the v1.6.1 release.",
            )

    def test_publish_and_verify_use_same_pin(self) -> None:
        # Defence-in-depth: if there are two ``ovsx@`` occurrences (one
        # for ``verify-pat`` and one for ``publish``), they must agree.
        # Otherwise we risk validating with one binary and shipping
        # with another — exactly the kind of asymmetry that hides
        # toolchain bugs.
        text = _read_workflow()
        pins = set(re.findall(r"\bovsx@(\S+)\b", text))
        self.assertLessEqual(
            len(pins),
            1,
            f"release.yml has multiple ovsx pins {sorted(pins)!r}. "
            f"All ovsx@ invocations must use the same version so the "
            f"verify-pat and publish steps run the same binary.",
        )

    def test_pin_explained_by_nearby_comment(self) -> None:
        # We want a R149 / R148 / "pin" / "drift" mention within a few
        # lines of the ``ovsx@`` line so a future maintainer can find
        # the rationale by ``git blame`` / inline reading.  Match
        # whichever wording the commit author chose.
        text = _read_workflow()
        idx = text.find("ovsx@")
        self.assertGreater(idx, 0, "no ``ovsx@`` line found")
        window_start = max(0, idx - 1500)
        window = text[window_start:idx]
        self.assertRegex(
            window,
            r"R149|pin|floating|drift|toolchain|deterministic",
            "release.yml ovsx@ pin should have a nearby comment "
            "explaining why it's pinned (R149 rationale). Searched "
            "window above the line; expected one of: R149 / pin / "
            "floating / drift / toolchain / deterministic.",
        )


if __name__ == "__main__":
    unittest.main()
