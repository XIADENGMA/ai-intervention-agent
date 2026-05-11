"""R183：``scripts/bump_version.py --warn-empty-unreleased`` 行为契约。

闭合 CR#13 §F-3：在 ``bump_version`` 执行 bump 之前轻量检查
``CHANGELOG.md [Unreleased]`` 是否为空。如果空了大概率是
"忘记 backfill 入口"——打 WARNING 提示用户，但不阻断 bump
（偶尔有正当理由发空 changelog 版本，如纯 chore release）。

本套件覆盖三层：

1. **纯函数层**：``_unreleased_section_is_empty`` 的边界
   情况（无标题 / 空区段 / 有 bullet / 有子标题但无 bullet
   等）。
2. **CLI flag 默认值**：``--warn-empty-unreleased`` 默认开启，
   ``--no-warn-empty-unreleased`` 可显式抑制。
3. **end-to-end bump**：构造临时 repo 跑真实 ``main()``，
   验证 stderr 是否打了 R183 WARNING token。
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_bump_version() -> ModuleType:
    """Load ``scripts/bump_version.py`` by absolute path.

    Using ``importlib.util.spec_from_file_location`` (instead of
    mutating ``sys.path`` + ``import bump_version``) keeps the static
    type-checker happy ``ty`` can't see ``sys.path`` injections so
    the bare import name is unresolvable—and keeps test isolation
    tight (no global ``sys.path`` pollution).
    """
    path = REPO_ROOT / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump_version = _load_bump_version()


class TestR183UnreleasedSectionIsEmpty(unittest.TestCase):
    """``_unreleased_section_is_empty`` 的边界契约。"""

    def test_no_unreleased_header_treated_as_empty(self) -> None:
        text = "# Changelog\n\n## [1.6.3] — 2026-05-12\n\n- foo\n"
        self.assertTrue(bump_version._unreleased_section_is_empty(text))

    def test_unreleased_with_only_subheadings_is_empty(self) -> None:
        text = (
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "### Added\n\n"
            "### Changed\n\n"
            "### Fixed\n\n"
            "## [1.6.3] — 2026-05-12\n\n"
            "- foo\n"
        )
        self.assertTrue(bump_version._unreleased_section_is_empty(text))

    def test_unreleased_with_bullet_is_not_empty(self) -> None:
        text = (
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "### Added\n\n"
            "- **R183** — bump_version --warn-empty-unreleased.\n\n"
            "## [1.6.3] — 2026-05-12\n\n"
            "- earlier release\n"
        )
        self.assertFalse(bump_version._unreleased_section_is_empty(text))

    def test_unreleased_with_star_bullet_is_not_empty(self) -> None:
        text = (
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "### Added\n\n"
            "* alt-style bullet still counts\n\n"
            "## [1.6.3] — 2026-05-12\n\n"
        )
        self.assertFalse(bump_version._unreleased_section_is_empty(text))

    def test_unreleased_at_eof_no_next_release(self) -> None:
        text = "# Changelog\n\n## [Unreleased]\n\n- single entry, no future release header\n"
        self.assertFalse(bump_version._unreleased_section_is_empty(text))

    def test_unreleased_at_eof_empty(self) -> None:
        text = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n"
        self.assertTrue(bump_version._unreleased_section_is_empty(text))

    def test_bullet_in_earlier_release_does_not_count(self) -> None:
        """关键边界：上一个发布里有 bullet，[Unreleased] 自己仍空。

        避免"扫整个文件"的实现错配——必须严格限定在
        [Unreleased] 与下一个 ## [ 之间。
        """
        text = (
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "### Added\n\n"
            "## [1.6.3] — 2026-05-12\n\n"
            "- prior release entry\n"
            "- another prior entry\n"
        )
        self.assertTrue(bump_version._unreleased_section_is_empty(text))


class TestR183ChangelogUnreleasedSection(unittest.TestCase):
    """``_changelog_unreleased_section`` 端点切分契约。"""

    def test_returns_none_without_header(self) -> None:
        self.assertIsNone(
            bump_version._changelog_unreleased_section(
                "# Changelog\n\n## [1.6.3] — 2026-05-12\n"
            )
        )

    def test_span_ends_before_next_release(self) -> None:
        text = "# Changelog\n\n## [Unreleased]\n\nA\nB\n\n## [1.6.3] — 2026-05-12\nC\n"
        span = bump_version._changelog_unreleased_section(text)
        self.assertIsNotNone(span)
        assert span is not None
        start, end = span
        # span 必须正好覆盖 [Unreleased] 主体（A, B），不能溢出到 1.6.3
        body = text[start:end]
        self.assertIn("A\nB", body)
        self.assertNotIn("1.6.3", body)
        self.assertNotIn("\nC\n", body)

    def test_span_at_eof_when_no_next_release(self) -> None:
        text = "# Changelog\n\n## [Unreleased]\n\nfoo\n"
        span = bump_version._changelog_unreleased_section(text)
        self.assertIsNotNone(span)
        assert span is not None
        start, end = span
        self.assertEqual(text[start:end].strip(), "foo")


class TestR183CliFlagDefaults(unittest.TestCase):
    """``--warn-empty-unreleased`` 的 argparse 行为。"""

    def test_help_lists_both_polarity_flags(self) -> None:
        """``BooleanOptionalAction`` 默认会暴露 ``--no-`` 反义，
        必须保持，否则用户没法在自动化里抑制 WARNING。"""
        from io import StringIO

        buf = StringIO()
        with mock.patch("sys.stdout", buf), self.assertRaises(SystemExit):
            bump_version.main(["--help"])
        out = buf.getvalue()
        self.assertIn("--warn-empty-unreleased", out)
        self.assertIn("--no-warn-empty-unreleased", out)
        self.assertIn("R183", out)


def _bare_repo_layout(root: Path) -> None:
    """造一个最小的 fake repo，让 bump_version 不会因缺文件 abort。

    只放 ``bump_version`` 必须读 / 改的文件；CHANGELOG 由各
    用例自己用 ``write_text`` 注入。
    """
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test-pkg"\nversion = "1.6.3"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        '[[package]]\nname = "ai-intervention-agent"\nversion = "1.6.3"\n',
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        '{\n  "name": "test",\n  "version": "1.6.3"\n}\n',
        encoding="utf-8",
    )
    (root / "package-lock.json").write_text(
        '{\n  "name": "test",\n  "version": "1.6.3",\n'
        '  "packages": {\n'
        '    "": {\n      "version": "1.6.3"\n    },\n'
        '    "packages/vscode": {\n      "version": "1.6.3"\n    }\n'
        "  }\n}\n",
        encoding="utf-8",
    )
    (root / "packages" / "vscode").mkdir(parents=True)
    (root / "packages" / "vscode" / "package.json").write_text(
        '{\n  "name": "vsc",\n  "version": "1.6.3"\n}\n',
        encoding="utf-8",
    )
    (root / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True)
    (root / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").write_text(
        "form: yes\n      placeholder: e.g. 1.6.3\n",
        encoding="utf-8",
    )
    (root / "CITATION.cff").write_text(
        'cff-version: 1.2.0\nversion: "1.6.3"\n',
        encoding="utf-8",
    )


class TestR183EndToEndBumpEmitsWarning(unittest.TestCase):
    """跑真实 ``main()``，断言 WARNING 行为。"""

    def setUp(self) -> None:
        # 用 ExitStack 注册资源——pytest 8 的 unraisable hook 会把
        # `TemporaryDirectory` 双重清理触发的 ``ResourceWarning`` 升成
        # 测试错误，所以这里走 ``__enter__`` + ``addCleanup(__exit__)``
        # 的对称模式，确保只清理一次。
        tmp = TemporaryDirectory()
        self._root = Path(tmp.__enter__())
        self.addCleanup(tmp.__exit__, None, None, None)
        _bare_repo_layout(self._root)
        # bump_version 通过 `_repo_root()` 拿仓库根（基于 __file__）。
        # 我们把整个仓库 mock 到 _root 即可——用 patch 覆盖。
        repo_root_patcher = mock.patch.object(
            bump_version, "_repo_root", return_value=self._root
        )
        repo_root_patcher.start()
        self.addCleanup(repo_root_patcher.stop)

    def _bump_to(
        self,
        version: str,
        *,
        changelog: str | None,
        extra_args: list[str] | None = None,
    ) -> tuple[int, str]:
        """运行 bump_version.main 并返回 (rc, stderr)。"""
        if changelog is not None:
            (self._root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        from io import StringIO

        stderr_buf = StringIO()
        stdout_buf = StringIO()
        with (
            mock.patch("sys.stderr", stderr_buf),
            mock.patch("sys.stdout", stdout_buf),
        ):
            rc = bump_version.main([version, *(extra_args or [])])
        return rc, stderr_buf.getvalue()

    def test_empty_unreleased_emits_warning_by_default(self) -> None:
        cl = (
            "# Changelog\n\n## [Unreleased]\n\n"
            "### Added\n\n### Changed\n\n### Fixed\n\n"
            "## [1.6.3] — 2026-05-12\n\n- prior entry\n"
        )
        rc, stderr = self._bump_to("1.6.4", changelog=cl)
        self.assertEqual(rc, 0, msg=stderr)
        self.assertIn("R183", stderr)
        self.assertIn("[Unreleased]", stderr)
        self.assertIn("WARNING", stderr)

    def test_non_empty_unreleased_emits_no_warning(self) -> None:
        cl = (
            "# Changelog\n\n## [Unreleased]\n\n"
            "### Added\n\n- a new R-cycle entry\n\n"
            "## [1.6.3] — 2026-05-12\n\n- prior entry\n"
        )
        rc, stderr = self._bump_to("1.6.4", changelog=cl)
        self.assertEqual(rc, 0, msg=stderr)
        self.assertNotIn("R183", stderr)

    def test_no_warn_flag_suppresses_even_when_empty(self) -> None:
        cl = (
            "# Changelog\n\n## [Unreleased]\n\n"
            "### Added\n\n"
            "## [1.6.3] — 2026-05-12\n\n- prior entry\n"
        )
        rc, stderr = self._bump_to(
            "1.6.4", changelog=cl, extra_args=["--no-warn-empty-unreleased"]
        )
        self.assertEqual(rc, 0, msg=stderr)
        self.assertNotIn("R183", stderr)

    def test_missing_changelog_does_not_break_bump(self) -> None:
        """``CHANGELOG.md`` 不存在不应让 bump 失败。
        这条边界很重要——新项目第一次 bump 时还没 CHANGELOG。"""
        rc, stderr = self._bump_to("1.6.4", changelog=None)
        self.assertEqual(rc, 0, msg=stderr)
        # 既不报错也不打 WARNING（文件不存在，不是"忘记 backfill"）
        self.assertNotIn("R183", stderr)


if __name__ == "__main__":
    unittest.main()
