"""L4·G2 – 守护 ``aiia-i18n/no-missing-i18n-key`` ESLint rule。

规则定义在 ``packages/vscode/eslint-plugin-aiia-i18n.mjs``，由
``packages/vscode/eslint.config.mjs`` 接入所有 JS/MJS。两文件编辑场景
割裂（写规则 vs 改项目配置），容易意外 disable。本测试：
  1. 喂 bad fixture（``t('not.a.real.key')``）→ 至少 1 条 ruleId
     ``aiia-i18n/no-missing-i18n-key`` 的报错；
  2. 喂 control fixture（``t('validation.invalidFile')``，真实 key）→
     该规则 0 报错。

Hermetic：``--stdin`` + ``--stdin-filename`` 指向 ``packages/vscode/`` 下
临时文件（flat-config 要求 input path 在 config root 里）；``--format json``
解析。``npx eslint`` 不在 PATH（纯 Python 环境）时 SKIP。
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
    """通过 interactive zsh 执行命令，以加载 fnm 管理的 ``npx`` / ``node``
    shell function（直接 subprocess 看不到，与 ``scripts/ci_gate.py`` 同款）。"""
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
    """通过 interactive shell 探测 npx-eslint（fnm-aware）。"""
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
