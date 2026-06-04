"""BUG3 回归契约：``get_project_version()`` 必须返回真实版本号而非 ``"unknown"``。

历史问题：``web_ui.py::get_project_version`` 把 ``pyproject.toml`` 拼成
``src/ai_intervention_agent/pyproject.toml``（与 ``__file__`` 同目录），
但仓库实际只有 ``<repo-root>/pyproject.toml``。开发模式 / pip 安装下都
找不到文件，函数永远返回 ``"unknown"``，前端拼 ``v`` 前缀后渲染为
``vunknown``。

新实现的多层兜底策略（按优先级）：
    1. ``importlib.metadata.version("ai-intervention-agent")`` — pip/uv/
       editable install 都能命中的 PEP 566 dist-info 元数据；
    2. 从 ``Path(__file__).parents[2]`` 找 ``pyproject.toml``（开发模式
       裸跑源码兜底）；
    3. 返回 ``"unknown"``（极端兜底，仅 (1)(2) 都失败时）。

本测试通过 happy-path + 注入失败 fixture 锁住所有三层契约。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent


def _project_version_from_pyproject() -> str:
    """直接从 <repo-root>/pyproject.toml 读取声明的版本号（测试参考真源）。"""
    pyproject = REPO_ROOT / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', content)
    assert match is not None, "pyproject.toml 必须有 version 字段（测试真源）"
    return match.group(1)


class TestHappyPathReturnsSemverString(unittest.TestCase):
    """正常导入场景：必须返回非 'unknown' 的语义版本号字符串。"""

    def setUp(self) -> None:
        from ai_intervention_agent.web_ui import get_project_version

        get_project_version.cache_clear()

    def test_returns_non_unknown(self) -> None:
        from ai_intervention_agent.web_ui import get_project_version

        v = get_project_version()
        self.assertIsInstance(v, str)
        self.assertNotEqual(
            v,
            "unknown",
            "get_project_version 不应返回 'unknown'。当前实现说明问题没修复："
            "前端拼 'v' 前缀后会显示 'vunknown'（BUG3 现场）。",
        )

    def test_returns_semver_like_string(self) -> None:
        from ai_intervention_agent.web_ui import get_project_version

        v = get_project_version()
        # 接受 1.7.9 / 2.0.0a1 / 1.7.9.post1 等 PEP 440 风格
        self.assertRegex(
            v,
            r"^\d+\.\d+",
            f"版本号应至少包含两段数字（X.Y...），实际：{v!r}",
        )

    def test_matches_pyproject_version(self) -> None:
        """importlib.metadata 与 pyproject.toml 应同步（在 editable 安装下）。"""
        from ai_intervention_agent.web_ui import get_project_version

        actual = get_project_version()
        declared = _project_version_from_pyproject()
        self.assertEqual(
            actual,
            declared,
            f"get_project_version()={actual!r} 应等于 pyproject.toml 中声明的 "
            f"version={declared!r}（CI 中 editable install 应保证同步）",
        )


class TestFallbackToPyprojectWhenMetadataMissing(unittest.TestCase):
    """``importlib.metadata.version`` 抛 ``PackageNotFoundError`` 时，
    必须降级到从 ``<repo-root>/pyproject.toml`` 读取。
    """

    def setUp(self) -> None:
        from ai_intervention_agent.web_ui import get_project_version

        get_project_version.cache_clear()

    def tearDown(self) -> None:
        from ai_intervention_agent.web_ui import get_project_version

        get_project_version.cache_clear()

    def test_pyproject_fallback_returns_version(self) -> None:
        """模拟"包未安装"，pyproject.toml 兜底必须命中。"""
        from importlib.metadata import PackageNotFoundError

        from ai_intervention_agent import web_ui

        with patch.object(
            web_ui,
            "get_project_version",
            wraps=web_ui.get_project_version.__wrapped__,
        ):
            pass

        with patch(
            "importlib.metadata.version",
            side_effect=PackageNotFoundError("ai-intervention-agent"),
        ):
            web_ui.get_project_version.cache_clear()
            v = web_ui.get_project_version()

        self.assertNotEqual(
            v,
            "unknown",
            "importlib.metadata 失败时 pyproject.toml 兜底应该命中（开发模式裸跑场景）",
        )
        self.assertEqual(v, _project_version_from_pyproject())


class TestUltimateFallback(unittest.TestCase):
    """两层兜底都失败 → 最终返回 ``"unknown"``，不能抛异常。"""

    def setUp(self) -> None:
        from ai_intervention_agent.web_ui import get_project_version

        get_project_version.cache_clear()

    def tearDown(self) -> None:
        from ai_intervention_agent.web_ui import get_project_version

        get_project_version.cache_clear()

    def test_returns_unknown_when_both_fallbacks_fail(self) -> None:
        from importlib.metadata import PackageNotFoundError

        from ai_intervention_agent import web_ui

        with (
            patch(
                "importlib.metadata.version",
                side_effect=PackageNotFoundError("ai-intervention-agent"),
            ),
            patch(
                "pathlib.Path.exists",
                return_value=False,
            ),
        ):
            web_ui.get_project_version.cache_clear()
            v = web_ui.get_project_version()

        self.assertEqual(
            v,
            "unknown",
            "两层兜底都失败时必须优雅返回 'unknown'，不能抛异常给调用方",
        )


class TestPathArithmetic(unittest.TestCase):
    """锁住路径推导：``Path(__file__).parents[2]`` 必须指向仓库根。

    这是修复 BUG3 的核心 — 历史代码用了 ``parent``（指向模块目录），
    结果永远找不到 pyproject.toml。
    """

    def test_parents_2_is_repo_root(self) -> None:
        from ai_intervention_agent import web_ui

        module_file = Path(web_ui.__file__).resolve()
        # parents[0]=src/ai_intervention_agent, parents[1]=src, parents[2]=<repo-root>
        repo_root = module_file.parents[2]
        self.assertTrue(
            (repo_root / "pyproject.toml").exists(),
            f"Path(web_ui.__file__).parents[2] 应指向 <repo-root>，"
            f"实际：{repo_root}；pyproject.toml 应存在",
        )

    def test_parent_is_not_repo_root_regression_guard(self) -> None:
        """回归守卫：``Path(__file__).parent`` 绝不是仓库根（BUG3 历史 bug 位置）。"""
        from ai_intervention_agent import web_ui

        module_dir = Path(web_ui.__file__).resolve().parent
        self.assertFalse(
            (module_dir / "pyproject.toml").exists(),
            "src/ai_intervention_agent/pyproject.toml 不应存在；如果存在说明仓库布局变了，"
            "需要重新评估 BUG3 修复的路径推导是否还正确",
        )


if __name__ == "__main__":
    unittest.main()
