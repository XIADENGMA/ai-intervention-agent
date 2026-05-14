r"""R219 / Cycle 11 · F-cycle10-3 · CHANGELOG inline-code lint 护栏 invariant。

设计目标
========

R211 (Cycle 10) 一次性 normalize 363 个 ``X`` (双反引号 reST 风格)
→ `X` (单反引号 Markdown 标准), 但**没有 lint 守护**。任何
contributor (或 Prettier 这类 formatter / IDE auto-fix) 未来把双反
引号又加回来, 会逐 commit 累积, R211 cleanup 努力归零。

R219 加 ``scripts/check_changelog_inline_code_style.py`` 作为 lint
工具 + ``.pre-commit-config.yaml`` 把它注册为 pre-commit hook
``check-changelog-inline-code-style``。本 invariant test 守 R219
的 3 类契约:

1. **lint script 存在 + 可执行**: ``scripts/check_changelog_
   inline_code_style.py`` 必须存在 + shebang + exit code 语义。
2. **pre-commit hook 注册存在**: ``.pre-commit-config.yaml`` 必须
   含 ``id: check-changelog-inline-code-style`` 的 hook 定义 + 关
   联到 ``CHANGELOG.md`` 文件 pattern。
3. **当前 CHANGELOG.md 通过 lint** (双重保险, 防止 R211 后混入):
   直接调 ``find_violations()`` 函数, 必须返回空列表。
4. **lint 自身行为正确性**: 三类 self-test 验证
   ``find_violations()`` 的 fence-aware + 反引号 escape 边界正确。

设计契约
========

A. **lint script 路径稳定**: ``scripts/check_changelog_inline_
   code_style.py`` 路径写死, 防 future refactor 把 script 移到别
   处但忘了更新 pre-commit-config.yaml 的 entry 路径。
B. **hook id 稳定**: ``check-changelog-inline-code-style`` id 写
   死, 防 hook 改名后 invariant 失守。
C. **零容忍当前违规**: 任何当前 CHANGELOG.md 内的 ``X`` 违规会
   被立即抓出, R211 cleanup 不能退化。

实施于 2026-05-14, 共 7 个测试用例 (4 类 invariant) + 3 subtests。
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINT_SCRIPT = REPO_ROOT / "scripts" / "check_changelog_inline_code_style.py"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

EXPECTED_HOOK_ID = "check-changelog-inline-code-style"


def _load_lint_module():
    """Load the lint script as a module for direct function-level testing。"""
    spec = importlib.util.spec_from_file_location(
        "check_changelog_inline_code_style", LINT_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load lint script as module: {LINT_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_changelog_inline_code_style"] = module
    spec.loader.exec_module(module)
    return module


class TestLintScriptExistsAndExecutable(unittest.TestCase):
    """R219 lint script 文件级 invariants。"""

    def test_lint_script_exists(self) -> None:
        self.assertTrue(
            LINT_SCRIPT.exists(),
            f"R219 lint script 缺失: {LINT_SCRIPT}. 删除前请同步移除 .pre-commit-config "
            "中的 check-changelog-inline-code-style hook + 本 invariant test。",
        )

    def test_lint_script_has_shebang(self) -> None:
        first_line = LINT_SCRIPT.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(
            first_line.startswith("#!"),
            f"R219 lint script 首行应为 shebang, 实际 {first_line!r}; "
            "pre-commit 不依赖 shebang 但保持可独立 ``./scripts/...`` 执行的便利。",
        )

    def test_lint_script_is_executable(self) -> None:
        mode = os.stat(LINT_SCRIPT).st_mode
        self.assertTrue(
            mode & 0o111,
            f"R219 lint script 应有执行权限 (chmod +x), 实际 mode={oct(mode)}",
        )


class TestPreCommitHookRegistration(unittest.TestCase):
    """``.pre-commit-config.yaml`` 必须注册 R219 hook。"""

    def setUp(self) -> None:
        self.assertTrue(PRECOMMIT_CONFIG.exists(), f"missing: {PRECOMMIT_CONFIG}")
        self.config_text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")

    def test_hook_id_present(self) -> None:
        self.assertIn(
            f"id: {EXPECTED_HOOK_ID}",
            self.config_text,
            f"pre-commit-config.yaml 必须含 'id: {EXPECTED_HOOK_ID}' hook 定义 "
            "(R219 / F-cycle10-3 护栏)。",
        )

    def test_hook_entry_points_to_lint_script(self) -> None:
        """hook entry 必须指向 ``scripts/check_changelog_inline_code_style.py``。"""
        pattern = re.compile(
            r"id:\s*check-changelog-inline-code-style.*?entry:\s*([^\n]+)",
            re.DOTALL,
        )
        match = pattern.search(self.config_text)
        self.assertIsNotNone(
            match, "找不到 check-changelog-inline-code-style hook 的 entry 行"
        )
        assert match is not None
        entry = match.group(1).strip()
        self.assertIn(
            "scripts/check_changelog_inline_code_style.py",
            entry,
            f"R219 hook entry 应指向 scripts/check_changelog_inline_code_style.py, 实际 = {entry!r}",
        )

    def test_hook_scoped_to_changelog_md(self) -> None:
        """hook 必须限定 ``files: ^CHANGELOG\\.md$`` 避免误检其它文件。"""
        pattern = re.compile(
            r"id:\s*check-changelog-inline-code-style.*?files:\s*([^\n]+)",
            re.DOTALL,
        )
        match = pattern.search(self.config_text)
        self.assertIsNotNone(match, "找不到 R219 hook 的 files: pattern")
        assert match is not None
        files_pattern = match.group(1).strip()
        self.assertIn(
            "CHANGELOG",
            files_pattern,
            f"R219 hook 必须 scoped 到 CHANGELOG.md (实际 files = {files_pattern!r})",
        )


class TestCurrentChangelogPassesLint(unittest.TestCase):
    """当前 CHANGELOG.md 必须通过 R219 lint (零容忍 ``X`` 违规)。"""

    def test_current_changelog_zero_violations(self) -> None:
        lint = _load_lint_module()
        text = CHANGELOG.read_text(encoding="utf-8")
        violations = lint.find_violations(text)
        if violations:
            self.fail(
                f"当前 CHANGELOG.md 有 {len(violations)} 个 ``X`` 违规 "
                "(R211 cleanup 退化 / R219 lint 未生效):\n  "
                + "\n  ".join(
                    f"line {ln}: {full!r} → suggest {sug!r}"
                    for ln, full, sug in violations[:10]
                )
                + (
                    f"\n  ... 还有 {len(violations) - 10} 个"
                    if len(violations) > 10
                    else ""
                )
            )


class TestLintFunctionBehavior(unittest.TestCase):
    """R219 lint script 的 ``find_violations()`` 函数行为正确性。"""

    def setUp(self) -> None:
        self.lint = _load_lint_module()

    def test_detects_simple_violation(self) -> None:
        """``hello`` 在 prose 行应被检测出。"""
        text = "This is ``hello`` and that is fine."
        violations = self.lint.find_violations(text)
        self.assertEqual(len(violations), 1)
        _ln, full, sug = violations[0]
        self.assertEqual(full, "``hello``")
        self.assertEqual(sug, "`hello`")

    def test_ignores_violations_inside_fenced_block(self) -> None:
        """围栏 ```bash 内的双反引号不应被检测 (代码内是数据, 不是 inline-code)。"""
        text = "Some prose.\n```bash\necho ``hello``\n```\nAfter fence.\n"
        violations = self.lint.find_violations(text)
        self.assertEqual(
            len(violations),
            0,
            f"fenced block 内不应误报, 实际 violations={violations!r}",
        )

    def test_does_not_match_triple_backtick_fence(self) -> None:
        """三反引号围栏行自身不应被误检为 inline-code 双反引号。"""
        text = "```python\nprint('hello')\n```\n"
        violations = self.lint.find_violations(text)
        self.assertEqual(len(violations), 0, "三反引号围栏不应被误检为 ``X`` 违规")

    def test_fix_text_is_idempotent(self) -> None:
        """对已经修复的文本再 fix 一次, 应不改变内容。"""
        original = "prose with `single backtick` here."
        once = self.lint.fix_text(original)
        twice = self.lint.fix_text(once)
        self.assertEqual(once, twice, "fix_text 应是 idempotent")
        self.assertEqual(once, original, "已合规的文本应被 fix_text 原样返回")


if __name__ == "__main__":
    unittest.main()
