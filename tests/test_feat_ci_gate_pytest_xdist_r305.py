"""R305: ci_gate pytest-xdist parallelization invariant (cycle-30 t30-5)。

cr59 §5 #D — CI gate optimization。R305 在 ``scripts/ci_gate.py`` 的
``pytest_cmd`` 中固化 ``-n 4 --dist=loadfile`` 配置, 把测试时长从
~191s 压到 ~50s (实测 3.8x 加速, 6464 tests + 1 skip + 878 subtests 全过)。

本测试守护 4 条 R305 invariant:
1. ``pytest-xdist>=3.6.0`` 同时声明在 ``[project.optional-dependencies].dev``
   和 ``[dependency-groups].dev`` (R184 一致性 pattern 继承)
2. ``scripts/ci_gate.py`` 的 ``pytest_cmd`` 必须包含 ``-n 4``
3. ``scripts/ci_gate.py`` 的 ``pytest_cmd`` 必须包含 ``--dist=loadfile``
4. ``--dist=worksteal`` 必须 **不** 出现 (worksteal 触发 R72-A test pollution)

================================================================
| Invariant                                | Lock target                |
|------------------------------------------|----------------------------|
| pytest-xdist 双 group 声明                | pyproject.toml             |
| -n 4 worker (sweet spot, 非 -n auto)       | scripts/ci_gate.py         |
| --dist=loadfile (file-local 隔离)         | scripts/ci_gate.py         |
| 禁 --dist=worksteal                       | scripts/ci_gate.py         |
| pytest-xdist >= 3.6.0 (R305 适配版本)     | pyproject.toml ×2          |
| R305 marker 出现在 ci_gate.py 说明文档     | scripts/ci_gate.py         |
================================================================

**lineage**: R296 perf-baseline (时间维度) → R304 perf-baseline (容量/系数
维度) → **R305 perf-baseline (CI 流水线维度, 4th application)** — perf
pattern 从 "运行时常量" 扩展到 "工具链配置常量"。

**性能基线 (R305 commit 时点)**:
- 串行: 191.62s total (74% CPU)
- 4 worker loadfile: 49.79s (285% CPU, **3.8x 加速**)
- 6464 测试 + 1 skip + 878 subtests 全过

未来如果想升 ``-n 8``, 必须先验证 SSE bus 集成测试 GIL 竞争 (实测 ``-n 8``
在 14 寸 M-series 反而退化到 ~52s)。
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
CI_GATE = PROJECT_ROOT / "scripts" / "ci_gate.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _load_pyproject() -> dict:
    return tomllib.loads(_read(PYPROJECT))


# ============================================================
# pyproject.toml — pytest-xdist 双 group 声明 (R184 pattern 继承)
# ============================================================
class TestPytestXdistDeclaredInBothGroups(unittest.TestCase):
    """pytest-xdist 必须同时在 optional-deps 和 dependency-groups 中声明"""

    def setUp(self) -> None:
        self.cfg = _load_pyproject()

    def test_pytest_xdist_in_optional_dependencies_dev(self) -> None:
        """``[project.optional-dependencies].dev`` 必须含 pytest-xdist。"""
        dev = self.cfg["project"]["optional-dependencies"]["dev"]
        match = [d for d in dev if d.startswith("pytest-xdist")]
        self.assertEqual(
            len(match),
            1,
            f"R305: [project.optional-dependencies].dev 必须恰好声明 1 个 "
            f"pytest-xdist (找到 {len(match)}: {match})",
        )

    def test_pytest_xdist_in_dependency_groups_dev(self) -> None:
        """``[dependency-groups].dev`` 必须含 pytest-xdist (R184 一致性)。"""
        dev = self.cfg["dependency-groups"]["dev"]
        match = [d for d in dev if d.startswith("pytest-xdist")]
        self.assertEqual(
            len(match),
            1,
            f"R305: [dependency-groups].dev 必须恰好声明 1 个 pytest-xdist "
            f"(找到 {len(match)}: {match}) — 否则 uv sync --all-groups "
            f"两边漂移 (参考 R184 pattern)",
        )

    def test_pytest_xdist_version_floor_3_6(self) -> None:
        """pytest-xdist 必须 >= 3.6.0 (R305 适配的最小版本)。

        3.6.0 是 ``--dist=worksteal`` 与 ``loadfile`` 共存稳定版本,
        之前的版本对 subTest 节点收集有 bug。
        """
        dev_opt = self.cfg["project"]["optional-dependencies"]["dev"]
        dev_grp = self.cfg["dependency-groups"]["dev"]

        for spec in [dev_opt, dev_grp]:
            xdist = next((d for d in spec if d.startswith("pytest-xdist")), None)
            self.assertIsNotNone(xdist)
            assert xdist is not None
            m = re.search(r"pytest-xdist\s*>=\s*(\d+)\.(\d+)", xdist)
            self.assertIsNotNone(
                m,
                f"R305: pytest-xdist 必须用 >=X.Y 语法声明 floor 版本 (找到 {xdist!r})",
            )
            assert m is not None
            major, minor = int(m.group(1)), int(m.group(2))
            self.assertTrue(
                (major, minor) >= (3, 6),
                f"R305: pytest-xdist >= 3.6.0 (找到 {major}.{minor}), "
                f"低版本 worksteal/loadfile subTest 收集有 bug",
            )


# ============================================================
# scripts/ci_gate.py — pytest_cmd 必须含 -n 4 --dist=loadfile
# ============================================================
class TestCiGatePytestXdistConfig(unittest.TestCase):
    """ci_gate.py 的 pytest_cmd 必须激活 R305 xdist 配置"""

    def setUp(self) -> None:
        self.src = _read(CI_GATE)

    def test_pytest_cmd_contains_n_4(self) -> None:
        """``pytest_cmd`` 必须含 ``-n 4`` (4 worker, sweet spot)。

        不允许 ``-n auto`` (CI runner 通常 2 核, auto 反而比固定 4 慢)。
        """
        m = re.search(
            r"pytest_cmd\s*=\s*\[[^\]]*?\"-n\"[^\]]*?\"4\"[^\]]*?\]",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            'R305: ci_gate.py pytest_cmd 必须含 [..., "-n", "4", ...] '
            "(4 worker 是 sweet spot, 不允许 -n auto)",
        )

    def test_pytest_cmd_contains_dist_loadfile(self) -> None:
        """``pytest_cmd`` 必须含 ``--dist=loadfile``。

        loadfile (同文件同 worker) 是必须的, 因为 worksteal 会触发 R72-A
        共享 root logger 状态的测试副作用污染。
        """
        m = re.search(
            r"pytest_cmd\s*=\s*\[[^\]]*?\"--dist=loadfile\"[^\]]*?\]",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            'R305: ci_gate.py pytest_cmd 必须含 "--dist=loadfile" '
            "(不允许 worksteal —— 后者触发 R72-A 测试副作用污染)",
        )

    def test_pytest_cmd_does_not_contain_worksteal(self) -> None:
        """``pytest_cmd`` 必须 **不** 含 ``--dist=worksteal``。

        worksteal 把同文件测试拆到不同 worker, 触发 R72-A `root logger
        handler 状态` 共享导致的副作用 (multi-file selection 下 4 个测试
        失败, 单文件下通过)。
        """
        self.assertNotIn(
            "--dist=worksteal",
            self.src,
            "R305: ci_gate.py 禁止用 --dist=worksteal (触发 R72-A test pollution); "
            "改用 --dist=loadfile",
        )

    def test_r305_marker_present_in_ci_gate(self) -> None:
        """ci_gate.py 必须有 R305 marker 解释 xdist 设计决策。"""
        self.assertIn(
            "R305",
            self.src,
            "R305: ci_gate.py 必须保留 R305 marker (说明为什么选 -n 4 + loadfile)",
        )

    def test_r305_loadfile_rationale_documented(self) -> None:
        """ci_gate.py 必须解释为什么用 loadfile 而非 worksteal。

        防止未来开发者凭直觉切回 worksteal 而忘了 R72-A 教训。
        """
        # 检查 docstring 中有 "loadfile" + "worksteal" + "pollution/污染" 同时出现
        m = re.search(
            r"loadfile[\s\S]{0,500}?worksteal[\s\S]{0,200}?(?:pollution|污染)",
            self.src,
        )
        self.assertIsNotNone(
            m,
            "R305: ci_gate.py 必须在 R305 注释中解释 loadfile vs worksteal 选择, "
            "说明 worksteal 触发 R72-A test pollution",
        )


# ============================================================
# meta-lint: 防 pytest_cmd 多次定义漂移
# ============================================================
class TestCiGatePytestCmdSingleSourceOfTruth(unittest.TestCase):
    """ci_gate.py 中 pytest_cmd 必须只在一处定义 (R305 后避免漂移)"""

    def setUp(self) -> None:
        self.src = _read(CI_GATE)

    def test_pytest_cmd_assigned_exactly_once(self) -> None:
        """``pytest_cmd = [`` 必须只出现 1 次, 防多个定义点漂移。"""
        # 排除注释 (注释里允许提及 pytest_cmd)
        code_lines = [
            line for line in self.src.split("\n") if not line.strip().startswith("#")
        ]
        code = "\n".join(code_lines)
        assigns = re.findall(r"pytest_cmd\s*=\s*\[", code)
        self.assertEqual(
            len(assigns),
            1,
            f"R305: pytest_cmd 必须只在 ci_gate.py 中赋值 1 次 (找到 {len(assigns)} 处), "
            f"否则多个 pytest 调用配置漂移",
        )


if __name__ == "__main__":
    unittest.main()
