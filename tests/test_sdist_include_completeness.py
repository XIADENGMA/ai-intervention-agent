"""防回归：pyproject.toml 的 sdist include 列表应覆盖所有运行时 Python 模块。

背景：
- `[tool.hatch.build.targets.sdist].include` 控制 `pip install` 源码包的文件集合
- 若新增 .py 模块但忘记加入 include，用户 `pip install` 后会缺少文件导致 ImportError

检查逻辑：
- 扫描项目根目录的所有 .py 文件（排除 scripts/ 和 tests/）
- 扫描包含 __init__.py 的子目录（排除 tests/、scripts/、packages/）
- 与 sdist include 列表对比，报告遗漏项
"""

import tomllib
import unittest
from pathlib import Path


class TestSdistIncludeCompleteness(unittest.TestCase):
    """确保 sdist include 列表覆盖所有运行时 Python 模块和包目录。"""

    def test_all_root_py_modules_in_sdist(self):
        repo_root = Path(__file__).resolve().parents[1]
        pyproject_path = repo_root / "pyproject.toml"
        self.assertTrue(pyproject_path.exists())

        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        include_list: list[str] = (
            data.get("tool", {})
            .get("hatch", {})
            .get("build", {})
            .get("targets", {})
            .get("sdist", {})
            .get("include", [])
        )
        include_set = {entry.lstrip("/") for entry in include_list}

        skip_dirs = {"tests", "scripts", "packages", "docs", ".github"}

        root_py_files = sorted(
            f.name
            for f in repo_root.glob("*.py")
            if f.is_file() and not f.name.startswith("_")
        )
        missing_modules = [f for f in root_py_files if f not in include_set]
        self.assertEqual(
            missing_modules,
            [],
            f"以下 .py 模块未包含在 sdist include 列表中: {missing_modules}",
        )

        pkg_dirs = sorted(
            d.name
            for d in repo_root.iterdir()
            if d.is_dir() and (d / "__init__.py").exists() and d.name not in skip_dirs
        )
        missing_dirs = [d for d in pkg_dirs if d not in include_set]
        self.assertEqual(
            missing_dirs,
            [],
            f"以下 Python 包目录未包含在 sdist include 列表中: {missing_dirs}",
        )
