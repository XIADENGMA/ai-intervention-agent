"""L4·G2 – guard the ``aiia-i18n/no-missing-i18n-key`` ESLint rule.

Why: we ship the rule in ``packages/vscode/eslint-plugin-aiia-i18n.mjs``
and wire it into ``packages/vscode/eslint.config.mjs`` for every JS /
MJS source. Those two files are edited in very different situations
(rule authoring vs project config), so it's easy to disable the rule
accidentally. This test pokes the linter with a known-bad fixture
file and asserts:

1. The fixture file (``t('not.a.real.key')``) produces **at least one**
   ESLint problem with ``ruleId == aiia-i18n/no-missing-i18n-key``.
2. A control fixture with a real key (``t('validation.invalidFile')``)
   produces **zero** problems from that rule.

Hermetic design
---------------
We feed the fixtures to ESLint via ``--stdin`` with
``--stdin-filename`` pointing at a temp file inside
``packages/vscode/`` (ESLint flat-config requires the input path to
be under the config root). We parse ``--format json`` so the test
doesn't depend on text format. If ``npx eslint`` isn't available on
PATH (e.g. Python-only developer env), the test SKIPs cleanly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"


def _run_via_shell(cmd: str, timeout: int = 60):
    """Invoke a command through an interactive ``zsh`` so that
    ``fnm``-managed ``npx`` / ``node`` shell functions get loaded.

    Direct ``subprocess.run(['npx', ...])`` can't see those shell-level
    functions and fails with ``command not found``. This mirrors the
    approach in ``scripts/ci_gate.py`` when invoking ``npm run`` in
    non-interactive CI."""
    shell = shutil.which("zsh") or shutil.which("bash")
    if shell is None:
        return None
    return subprocess.run(
        [shell, "-i", "-c", cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _eslint_available() -> bool:
    """Probe npx-eslint through an interactive shell (fnm-aware)."""
    if (VSCODE_DIR / "node_modules" / "eslint").is_dir():
        return True
    proc = _run_via_shell(
        f"cd {VSCODE_DIR!s} && npx --no-install eslint --version",
        timeout=30,
    )
    return proc is not None and proc.returncode == 0 and bool(proc.stdout.strip())


def _run_eslint(js_source: str) -> list[dict]:
    """Run ESLint against ``js_source`` using the real project config."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".js",
        dir=VSCODE_DIR,
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(js_source)
        tmp_path = Path(tmp.name)
    try:
        proc = _run_via_shell(
            f"cd {VSCODE_DIR!s} && npx --no-install eslint --format json {tmp_path.name}",
            timeout=90,
        )
        if proc is None:
            raise RuntimeError("no shell available to invoke ESLint")
        if not proc.stdout.strip():
            raise RuntimeError(
                f"no ESLint output (rc={proc.returncode})\nstderr={proc.stderr!r}"
            )
        # Some interactive-shell wrappers prepend banner noise on stderr
        # but stdout holds the pure JSON array. Still, a defensive parse
        # below makes failures obvious.
        return json.loads(proc.stdout)
    finally:
        tmp_path.unlink(missing_ok=True)


@unittest.skipUnless(
    _eslint_available(),
    "npx / eslint not available (run `npm ci` in packages/vscode first)",
)
class TestAiiaI18nEslintRule(unittest.TestCase):
    RULE = "aiia-i18n/no-missing-i18n-key"

    def test_unknown_key_triggers_rule(self) -> None:
        source = (
            "// fixture: deliberately unknown key\n"
            "function test() { t('this.key.does.not.exist.abcxyz') }\n"
        )
        results = _run_eslint(source)
        self.assertEqual(len(results), 1)
        messages = results[0].get("messages", [])
        matching = [m for m in messages if m.get("ruleId") == self.RULE]
        self.assertEqual(
            len(matching),
            1,
            f"Expected 1 {self.RULE!r} error, got {len(matching)}: {messages!r}",
        )
        self.assertIn("this.key.does.not.exist.abcxyz", matching[0].get("message", ""))

    def test_known_key_does_not_trigger_rule(self) -> None:
        # 'status.submitEmpty' exists in both packages/vscode/locales/en.json
        # and static/locales/en.json, so it must pass.
        source = (
            "// fixture: real key (present in both locales)\n"
            "function test() { t('status.submitEmpty') }\n"
        )
        results = _run_eslint(source)
        self.assertEqual(len(results), 1)
        messages = results[0].get("messages", [])
        bad = [m for m in messages if m.get("ruleId") == self.RULE]
        self.assertEqual(
            bad,
            [],
            f"Rule incorrectly fired on a known-good key: {bad!r}",
        )

    def test_rule_ignores_member_access(self) -> None:
        """obj.t('...') MUST NOT trip the rule (see plugin doc)."""
        source = "function test() { const api = {}; api.t('this.looks.fake') }\n"
        results = _run_eslint(source)
        messages = results[0].get("messages", [])
        bad = [m for m in messages if m.get("ruleId") == self.RULE]
        self.assertEqual(
            bad,
            [],
            f"Rule incorrectly fired on member-access t(): {bad!r}",
        )


if __name__ == "__main__":
    unittest.main()
