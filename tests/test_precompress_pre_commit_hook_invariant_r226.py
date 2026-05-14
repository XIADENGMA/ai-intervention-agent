"""R226 / Cycle 13 · F-cycle12-2: precompress-freshness pre-commit hook
invariant.

Background
----------
CR#25 §3 flagged R223 → R224 lag as F-cycle12-2: R223 added a new
i18n key to ``en.json`` / ``zh-CN.json`` but did **not** regenerate
the precompressed ``.br`` / ``.gz`` mirrors that ``static/locales/``
ships alongside each JSON. ``scripts/ci_gate.py`` caught the drift
on the next run, but the lag meant a server hot-reloading the JSON
would briefly serve the old precompressed mirror — silent staleness.

R226 promotes the freshness check from ``ci_gate.py`` into a
pre-commit hook by registering ``scripts/precompress_static.py
--check`` in ``.pre-commit-config.yaml`` gated on changes under
``src/ai_intervention_agent/static/(css|js|locales)/``. This test
locks the hook config in place so a future ``.pre-commit-config.yaml``
refactor cannot silently drop the guard.

Cases (8 total):

1. ``.pre-commit-config.yaml`` exists at the repo root.
2. The hook id ``check-static-precompress-fresh`` is present.
3. The hook entry invokes ``scripts/precompress_static.py --check``
   (not a typo'd alternative).
4. The hook ``files:`` pattern matches the three asset subdirectories
   we care about (``css``, ``js``, ``locales``).
5. The hook ``pass_filenames: false`` (otherwise pre-commit would
   pass staged filenames to the script which would then try to
   compress whatever filenames it was passed — wrong).
6. The hook ``language: system`` (uses the project's uv env, not
   a managed pre-commit venv with its own dependency resolution).
7. The R226 / F-cycle12-2 origin is documented in a comment near
   the hook block (prevents the "why is this hook here?" question
   in 6 months).
8. ``scripts/precompress_static.py --check`` exists + is invocable
   from the current shell (smoke test that the hook target is real).
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_CONFIG_PATH = REPO_ROOT / ".pre-commit-config.yaml"
PRECOMPRESS_SCRIPT_PATH = REPO_ROOT / "scripts" / "precompress_static.py"


def _read_config() -> str:
    return HOOK_CONFIG_PATH.read_text(encoding="utf-8")


def _extract_hook_block(config: str, hook_id: str) -> str:
    """Return the rough YAML block (one or two screens) around the
    given ``- id: <hook_id>`` anchor. We don't parse YAML — string
    presence is plenty for the invariants we care about, and pulling
    in a parser would couple this test to a YAML library that's
    otherwise unused in tests/."""
    pattern = re.compile(
        rf"(?:^- id: {re.escape(hook_id)}.*?)(?=^- id: |\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(config)
    if match:
        return match.group(0)
    # Fallback: the hook id may be indented under a ``hooks:`` list,
    # so try matching the indented form too.
    pattern2 = re.compile(
        rf"(?:^ +- id: {re.escape(hook_id)}.*?)(?=^ +- id: |\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match2 = pattern2.search(config)
    return match2.group(0) if match2 else ""


class TestHookConfigPresent(unittest.TestCase):
    def test_config_file_exists(self) -> None:
        self.assertTrue(
            HOOK_CONFIG_PATH.is_file(),
            f".pre-commit-config.yaml missing at {HOOK_CONFIG_PATH}",
        )

    def test_hook_id_present(self) -> None:
        config = _read_config()
        self.assertIn(
            "check-static-precompress-fresh",
            config,
            (
                "R226 / F-cycle12-2 pre-commit hook id "
                "'check-static-precompress-fresh' missing from "
                ".pre-commit-config.yaml — the precompress freshness "
                "guard has been silently removed."
            ),
        )


class TestHookEntryInvokesCorrectScript(unittest.TestCase):
    def test_entry_invokes_precompress_static_check(self) -> None:
        config = _read_config()
        block = _extract_hook_block(config, "check-static-precompress-fresh")
        self.assertTrue(
            block,
            "Could not locate hook block for check-static-precompress-fresh.",
        )
        self.assertIn(
            "scripts/precompress_static.py --check",
            block,
            (
                "R226 hook entry should invoke "
                "`scripts/precompress_static.py --check` — current "
                "entry diverged: " + repr(block[:200])
            ),
        )

    def test_entry_uses_uv_run_python(self) -> None:
        config = _read_config()
        block = _extract_hook_block(config, "check-static-precompress-fresh")
        self.assertIn(
            "uv run python",
            block,
            (
                "R226 hook entry should invoke via `uv run python` "
                "(matches other local hooks in this file)."
            ),
        )


class TestHookFilesPattern(unittest.TestCase):
    def test_files_pattern_matches_three_asset_subdirs(self) -> None:
        config = _read_config()
        block = _extract_hook_block(config, "check-static-precompress-fresh")
        files_match = re.search(r"files:\s*(.+?)\n", block)
        self.assertIsNotNone(
            files_match, "R226 hook missing required `files:` directive."
        )
        assert files_match is not None  # narrow for ty
        files_pattern = files_match.group(1).strip()
        for subdir in ("css", "js", "locales"):
            with self.subTest(subdir=subdir):
                self.assertIn(
                    subdir,
                    files_pattern,
                    (
                        f"R226 hook files-pattern does not match "
                        f"`static/{subdir}/...` — dropping a subdir "
                        "would silently disable freshness checks "
                        "for that asset type."
                    ),
                )


class TestHookExecutionDirectives(unittest.TestCase):
    def test_pass_filenames_false(self) -> None:
        config = _read_config()
        block = _extract_hook_block(config, "check-static-precompress-fresh")
        self.assertIn(
            "pass_filenames: false",
            block,
            (
                "R226 hook MUST set `pass_filenames: false`. If "
                "filenames are passed to precompress_static.py, the "
                "script will try to compress whatever filenames it was "
                "given instead of running its full directory scan."
            ),
        )

    def test_language_system(self) -> None:
        config = _read_config()
        block = _extract_hook_block(config, "check-static-precompress-fresh")
        self.assertIn(
            "language: system",
            block,
            (
                "R226 hook MUST set `language: system` so it inherits "
                "the project's uv env. Letting pre-commit manage a "
                "separate venv would duplicate brotli / gzip deps."
            ),
        )


class TestHookProvenanceDocumented(unittest.TestCase):
    def test_r226_or_fcycle12_2_origin_mentioned(self) -> None:
        config = _read_config()
        # Look in a window just above + including the hook block. We
        # accept either tag because the comment may name only one of
        # them (R-tag is canonical for the implementation, F-cycle12-2
        # is canonical for the backlog reference).
        block = _extract_hook_block(config, "check-static-precompress-fresh")
        idx = config.find(block)
        comment_window = config[max(0, idx - 2000) : idx + len(block)]
        self.assertTrue(
            "R226" in comment_window or "F-cycle12-2" in comment_window,
            (
                "R226 hook block lacks origin comment mentioning "
                "either R226 or F-cycle12-2. Future readers won't "
                "know the rationale for the precompress freshness "
                "guard if both tags get refactored out."
            ),
        )


class TestPrecompressScriptInvocable(unittest.TestCase):
    """Smoke test the hook's actual target — if precompress_static.py
    were renamed without updating the hook, this catches it."""

    def test_script_file_exists(self) -> None:
        self.assertTrue(
            PRECOMPRESS_SCRIPT_PATH.is_file(),
            f"precompress_static.py missing at {PRECOMPRESS_SCRIPT_PATH} — R226 hook target is broken.",
        )

    def test_script_help_runs_without_crash(self) -> None:
        # We don't run --check here (could be expensive in CI's first
        # bring-up); --help is the cheapest smoke that imports cleanly.
        result = subprocess.run(
            [sys.executable, str(PRECOMPRESS_SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(
            result.returncode,
            0,
            (
                "precompress_static.py --help failed with exit "
                f"{result.returncode}; stderr={result.stderr!r}"
            ),
        )
        self.assertIn(
            "--check",
            result.stdout,
            (
                "precompress_static.py --help output does not "
                "advertise the --check flag the R226 hook depends on. "
                "Verify the flag is still implemented before relying "
                "on the hook."
            ),
        )


if __name__ == "__main__":
    unittest.main()
