"""R270 / cycle-23 Track-B (R269 spillover):
``test_readme_factual_claims_invariant_r233.py`` 必须用 graceful fallback
而不是 hard-code ``["uv", "run", "pytest"]``，避免在没装 uv 的 dev env
里 raise FileNotFoundError 让 R233 4 个 invariant 全 fail。

Why locked
----------

Pre-R270 的 ``_collect_pytest_test_count`` 直接：

    subprocess.run(
        ["uv", "run", "pytest", "--collect-only", "-q"],
        ...
    )

这个在以下环境会炸：
- macOS Homebrew 默认 PATH（uv 装在 ``~/.cargo/bin`` 但 fish-shell 未自动导出）
- pipx 隔离环境（直接装 pytest 但没 uv）
- CI Linux 不用 ``setup-uv@v3`` 的下游 fork

R269 修了 freshness 测试的 bare ``"python"``；R270 是同源 fix 的延伸——
任何 test 子进程依赖 PATH 二进制都应有 ``shutil.which()`` 守卫 + fallback。

Invariant
---------

1. ``_build_pytest_collect_cmd`` 函数必须存在（不能被简化掉直接 inline 调
   ``["uv", "run", ...]``）
2. 函数体必须 reference ``shutil.which("uv")``——证明做了 PATH probe
3. 函数体必须有 fallback 分支用 ``sys.executable``——证明 uv 不在 PATH
   时仍能跑
4. ``_collect_pytest_test_count`` 必须调 ``_build_pytest_collect_cmd()``，
   而不是 bypass 它直接传 list（双锁防 revert）
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "tests" / "test_readme_factual_claims_invariant_r233.py"


def _parse_module() -> ast.Module:
    return ast.parse(TARGET.read_text(encoding="utf-8"), filename=str(TARGET))


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


class TestBuildPytestCollectCmdExists(unittest.TestCase):
    def test_helper_function_defined(self) -> None:
        tree = _parse_module()
        fn = _find_function(tree, "_build_pytest_collect_cmd")
        self.assertIsNotNone(
            fn,
            "R270: ``_build_pytest_collect_cmd`` helper must exist; "
            "do not inline ``['uv', 'run', ...]`` back into "
            "``_collect_pytest_test_count``.",
        )


class TestBuildPytestCollectCmdUsesPathProbe(unittest.TestCase):
    def test_helper_calls_shutil_which_uv(self) -> None:
        tree = _parse_module()
        fn = _find_function(tree, "_build_pytest_collect_cmd")
        assert fn is not None
        source = ast.unparse(fn)
        self.assertIn(
            "shutil.which",
            source,
            "R270: helper must probe PATH via ``shutil.which`` so the "
            "subprocess.run call doesn't blow up with FileNotFoundError "
            "on systems without uv installed.",
        )
        self.assertIn(
            '"uv"',
            source,
            "R270: helper must probe specifically for the ``uv`` binary; "
            "otherwise the primary fast-path is unreachable.",
        )

    def test_helper_has_sys_executable_fallback(self) -> None:
        tree = _parse_module()
        fn = _find_function(tree, "_build_pytest_collect_cmd")
        assert fn is not None
        source = ast.unparse(fn)
        self.assertIn(
            "sys.executable",
            source,
            "R270: helper must have a fallback branch that uses "
            "``sys.executable`` so the test still works without ``uv`` "
            "(e.g. pipx-installed pytest, system pip-installed pytest).",
        )
        self.assertIn(
            '"-m"',
            source,
            "R270: fallback must use ``python -m pytest`` form (not "
            "``python pytest``), which is the canonical way to invoke "
            "pytest from an arbitrary python interpreter.",
        )
        self.assertIn(
            '"pytest"',
            source,
            "R270: fallback must still target pytest; otherwise we're "
            "counting the wrong thing.",
        )


class TestCollectCallsHelper(unittest.TestCase):
    def test_collect_function_delegates_to_helper(self) -> None:
        tree = _parse_module()
        fn = _find_function(tree, "_collect_pytest_test_count")
        assert fn is not None, (
            "R270: ``_collect_pytest_test_count`` must still exist as the "
            "public entry point of the count probe."
        )
        source = ast.unparse(fn)
        self.assertIn(
            "_build_pytest_collect_cmd()",
            source,
            "R270: ``_collect_pytest_test_count`` must invoke the helper "
            "``_build_pytest_collect_cmd()`` rather than reconstructing "
            "the command in-line (which would re-introduce the bare "
            "``['uv', ...]`` regression).",
        )

    def test_collect_function_does_not_hardcode_uv_list(self) -> None:
        """Double-lock: even if someone adds a duplicate code path, no
        hard-coded ``"uv"`` string literal may appear at the top of any
        ``subprocess.run`` arg list inside ``_collect_pytest_test_count``."""
        tree = _parse_module()
        fn = _find_function(tree, "_collect_pytest_test_count")
        assert fn is not None
        for sub in ast.walk(fn):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            is_subprocess_run = (
                isinstance(func, ast.Attribute)
                and func.attr == "run"
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            )
            if not is_subprocess_run:
                continue
            if not sub.args:
                continue
            first_arg = sub.args[0]
            if isinstance(first_arg, ast.List) and first_arg.elts:
                head = first_arg.elts[0]
                if isinstance(head, ast.Constant) and head.value == "uv":
                    self.fail(
                        "R270: ``_collect_pytest_test_count`` must not "
                        "hard-code ``['uv', ...]`` as the subprocess.run "
                        "argv. Use ``_build_pytest_collect_cmd()`` so "
                        "non-uv environments work too."
                    )


class TestImportsAreRobust(unittest.TestCase):
    def test_module_imports_shutil_and_sys(self) -> None:
        source = TARGET.read_text(encoding="utf-8")
        self.assertIn(
            "import shutil",
            source,
            "R270: module must import ``shutil`` so ``shutil.which`` is "
            "available to the helper.",
        )
        self.assertIn(
            "import sys",
            source,
            "R270: module must import ``sys`` so ``sys.executable`` is "
            "available to the fallback.",
        )


if __name__ == "__main__":
    unittest.main()
