import tomllib
import unittest
from pathlib import Path


class TestPyprojectDependencyGroupsConsistency(unittest.TestCase):
    """防回归：pyproject.toml 中 dev 依赖定义应保持一致。

    背景：
    - `[dependency-groups].dev`：给 uv/CI 使用（uv sync --all-groups）
    - `[project.optional-dependencies].dev`：给 pip/本地 `.[dev]` 使用

    两者若漂移，会导致“本地/CI 依赖不一致”，进而引发门禁与开发体验分叉。
    """

    def test_dev_group_matches_optional_dev(self):
        repo_root = Path(__file__).resolve().parents[1]
        pyproject_path = repo_root / "pyproject.toml"
        self.assertTrue(pyproject_path.exists(), f"missing file: {pyproject_path}")

        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        opt_dev = (
            data.get("project", {}).get("optional-dependencies", {}).get("dev")  # type: ignore[call-arg]
        )
        group_dev = data.get("dependency-groups", {}).get("dev")

        self.assertIsInstance(
            opt_dev, list, "[project.optional-dependencies].dev missing"
        )
        self.assertIsInstance(group_dev, list, "[dependency-groups].dev missing")

        opt_set = set(opt_dev)
        group_set = set(group_dev)

        if opt_set != group_set:
            missing_in_optional = sorted(group_set - opt_set)
            missing_in_groups = sorted(opt_set - group_set)
            self.fail(
                "dev 依赖定义不一致（optional-dependencies vs dependency-groups）\n"
                f"- missing in [project.optional-dependencies].dev: {missing_in_optional}\n"
                f"- missing in [dependency-groups].dev: {missing_in_groups}"
            )

        # 额外约束：避免重复定义导致锁文件/安装行为不确定
        self.assertEqual(
            len(opt_dev),
            len(opt_set),
            "[project.optional-dependencies].dev contains duplicates",
        )
        self.assertEqual(
            len(group_dev),
            len(group_set),
            "[dependency-groups].dev contains duplicates",
        )
