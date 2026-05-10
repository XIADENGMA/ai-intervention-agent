"""VS Code extension ``displayName`` literal-vs-NLS-placeholder guard.

Background
----------
``packages/vscode/package.json`` historically used the NLS pattern for
its ``displayName`` field:

.. code-block:: json

    { "displayName": "%displayName%" }

…with the resolved string living in ``package.nls.json`` /
``package.nls.zh-CN.json``. The VS Code Marketplace and ``vsce`` happily
resolve ``%displayName%`` against the NLS bundles when generating the
``.vsix``: the manifest inside the archive carries the **literal**
"AI Intervention Agent", while the on-disk ``package.json`` keeps
``%displayName%``.

Open VSX (``ovsx publish``) — at least starting some time between
2026-05-08 (v1.6.0 release succeeded) and 2026-05-10 (v1.6.1 release
failed) — added a strict pre-publish check:

    ❌  Display name in extension.vsixmanifest and package.json does
        not match.

That check reads ``package.json`` literally and compares to the
resolved ``<DisplayName>`` in ``extension.vsixmanifest``.  With the NLS
placeholder the two will *never* match — the publish always fails.

This test locks the canonical fix: ``displayName`` must be a **literal
string** in ``package.json``, equal to whatever ``package.nls.json`` and
``package.nls.zh-CN.json`` carry. That keeps Open VSX happy without
sacrificing localised display in the actual VS Code UI (the NLS files
still drive the locale-aware menu / activity-bar labels because VS Code
resolves NLS keys for *runtime* strings; ``displayName`` happens to be
one of the few fields that *both* the marketplace metadata and runtime
care about).

What this test pins
-------------------
1.  ``package.json`` ``displayName`` is a non-empty literal string,
    **not** the ``%displayName%`` NLS placeholder.
2.  Both NLS bundles (``package.nls.json`` and ``package.nls.zh-CN.json``)
    carry the same literal value, so localised installs see the exact
    same display name that the marketplace does — drift between them
    has historically been a sneaky bug source.
3.  A negative assertion that *no* file under ``packages/vscode/`` writes
    ``"%displayName%"`` to ``package.json`` (catches re-introduction by
    a future "let's NLS-ify everything" refactor).

Why this lives in tests/ instead of pre-commit
----------------------------------------------
``ci_gate.py`` runs the full pytest suite, so any guard placed here gets
the same coverage as the runtime tests **without** adding a new
pre-commit check that would only fire locally. The Open VSX failure is
a release-pipeline blocker, and pytest is what gates merging to ``main``
in this repo.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_JSON = ROOT / "packages" / "vscode" / "package.json"
NLS_EN = ROOT / "packages" / "vscode" / "package.nls.json"
NLS_ZH = ROOT / "packages" / "vscode" / "package.nls.zh-CN.json"

# Fixed value the entire toolchain must agree on. If the project ever
# wants to rename the extension, update this constant + all three files
# in lock-step. Don't read it back from the JSON files — that would
# defeat the drift guard.
EXPECTED_DISPLAY_NAME = "AI Intervention Agent"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestDisplayNameLiteralForOvsx(unittest.TestCase):
    def test_package_json_displayname_is_literal(self) -> None:
        data = _load(PKG_JSON)
        self.assertIn("displayName", data, "package.json missing displayName")
        value = data["displayName"]
        self.assertIsInstance(value, str)
        self.assertNotEqual(
            value,
            "%displayName%",
            "package.json displayName must be a literal string, not the NLS "
            "placeholder %displayName%. Open VSX strict-checks this against "
            "the resolved value inside extension.vsixmanifest and rejects "
            "publish when they differ — which broke the v1.6.1 release. "
            "Hard-code the localised name (en is canonical) here.",
        )
        self.assertNotIn(
            "%",
            value,
            "package.json displayName looks like an NLS placeholder still",
        )
        self.assertTrue(value.strip(), "displayName cannot be whitespace")

    def test_displayname_matches_canonical(self) -> None:
        data = _load(PKG_JSON)
        self.assertEqual(
            data["displayName"],
            EXPECTED_DISPLAY_NAME,
            f"package.json displayName drifted from canonical "
            f"{EXPECTED_DISPLAY_NAME!r}. Update both this constant and the "
            f"NLS bundles together if the rename is intentional.",
        )

    def test_nls_en_matches_displayname(self) -> None:
        # Even though package.json no longer references %displayName%, the
        # NLS bundle still carries it — VS Code reads bundle entries for
        # runtime localised strings (activity bar / menu / view container
        # / commands). Keep it consistent so a zh-CN user sees the same
        # name on the marketplace listing as in their VS Code UI.
        data = _load(NLS_EN)
        self.assertEqual(
            data.get("displayName"),
            EXPECTED_DISPLAY_NAME,
            "package.nls.json displayName must match canonical literal",
        )

    def test_nls_zh_cn_matches_displayname(self) -> None:
        data = _load(NLS_ZH)
        self.assertEqual(
            data.get("displayName"),
            EXPECTED_DISPLAY_NAME,
            "package.nls.zh-CN.json displayName must match canonical literal",
        )

    def test_no_other_source_file_uses_nls_displayname_placeholder(self) -> None:
        # Defence-in-depth: scan **source** files in the vscode package
        # for any leftover ``"displayName": "%displayName%"`` (catches a
        # naive re-introduction by a "let's NLS-ify everything" refactor).
        #
        # Scope (only what's tracked in git):
        #   - skip ``dist/`` — generated by ``tsc`` from source; whatever
        #     pre-publish minifier ran last left an NLS-shaped copy there
        #     and *that* doesn't drive ovsx (the .vsix's manifest does)
        #   - skip ``node_modules/`` — third-party packages
        #   - skip the NLS bundles themselves — they're *meant* to define
        #     the placeholder's value, not consume it
        skip_names = {NLS_EN.name, NLS_ZH.name}
        skip_dirs = {"dist", "node_modules", ".vscode-test", "out"}
        offending: list[Path] = []
        for path in (ROOT / "packages" / "vscode").rglob("*.json"):
            if path.name in skip_names:
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if '"displayName": "%displayName%"' in text:
                offending.append(path.relative_to(ROOT))
        self.assertFalse(
            offending,
            f"%displayName% NLS placeholder leaked into: {offending}. Replace "
            f"with the literal {EXPECTED_DISPLAY_NAME!r} (Open VSX rejects "
            f"any mismatch between vsixmanifest and package.json).",
        )


if __name__ == "__main__":
    unittest.main()
