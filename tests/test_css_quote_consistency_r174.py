"""R174 / CR#10 F-1：CSS 字符串引号一致性漂移检测器测试。

锁定 ``scripts/check_css_quote_consistency.py`` 的核心行为：

1. ``_strip_comments_and_url_blocks`` 正确剔除 ``/* ... */`` 注释 + ``url(...)``
   嵌套（防止 SVG xmlns 里 single-quote、注释里 single-quote 被误计为样式硬
   编码）；
2. ``count_naked_single_quotes`` 与 ``find_naked_single_quotes_with_lines``
   匹配真实违规、给出可定位的行号；
3. ``scan_files`` 正确处理多目标 / 缺失文件 / I/O 错误；
4. CLI 在 ``count == baseline`` / ``count > baseline`` / ``count < baseline``
   三个分支退出码与提示一致；
5. ``static/css/main.css`` 实际"裸露"single-quote 数 == 脚本默认 baseline，
   保证 R174 commit 时刻的 baseline 数字与代码同步；
6. ``.pre-commit-config.yaml`` 里 R174 hook 配置正确（entry 指向脚本、
   files glob 只匹配 main.css）。

这是「护栏脚本本身的测试」，对应 R66 ``test_brand_color_consistency_r66.py``
的同模式实现。
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
import check_css_quote_consistency as guard  # ty: ignore[unresolved-import]


class TestStripCommentsAndUrlBlocks(unittest.TestCase):
    """``_strip_comments_and_url_blocks`` 必须剥掉 url(...) + /* ... */。"""

    def test_strips_single_line_comment(self) -> None:
        src = ".x { color: red; } /* 'inside comment' */ .y { color: blue; }"
        out = guard._strip_comments_and_url_blocks(src)
        self.assertNotIn("inside comment", out)
        self.assertIn(".x", out)
        self.assertIn(".y", out)

    def test_strips_multiline_comment(self) -> None:
        src = "/*\n * 多行\n * 'single quote inside'\n */\n.x { color: red; }"
        out = guard._strip_comments_and_url_blocks(src)
        self.assertNotIn("single quote inside", out)
        self.assertIn(".x", out)

    def test_strips_url_block_with_svg_xmlns(self) -> None:
        """关键场景：url("data:image/svg+xml;...xmlns='http://...'") 是合法嵌套。"""
        src = (
            '.x { background: url("data:image/svg+xml;,%3csvg '
            "xmlns='http://www.w3.org/2000/svg'/%3e\"); }"
        )
        out = guard._strip_comments_and_url_blocks(src)
        self.assertNotIn("xmlns=", out)
        self.assertIn(".x", out)

    def test_strips_url_block_no_quotes(self) -> None:
        """url() 不带引号的旧式写法也被剥（保守起见整段 url(...) 都跳过）。"""
        src = ".x { background: url(/img/icon.svg); }"
        out = guard._strip_comments_and_url_blocks(src)
        self.assertNotIn("url(/img/icon.svg)", out)

    def test_preserves_quotes_in_actual_selector(self) -> None:
        """非注释 / 非 url 的 single-quote 必须保留。"""
        src = "/* note */ [data-theme='dark'] { color: red; }"
        out = guard._strip_comments_and_url_blocks(src)
        self.assertIn("'dark'", out)

    def test_empty_input(self) -> None:
        self.assertEqual(guard._strip_comments_and_url_blocks(""), "")


class TestCountNakedSingleQuotes(unittest.TestCase):
    """``count_naked_single_quotes`` 必须只算"裸露"single-quote 字符串。"""

    def test_zero_when_no_quotes(self) -> None:
        src = ".x { color: red; }"
        self.assertEqual(guard.count_naked_single_quotes(src), 0)

    def test_zero_when_only_double_quotes(self) -> None:
        src = '@import url("./other.css"); [data-theme="dark"] { color: red; }'
        self.assertEqual(guard.count_naked_single_quotes(src), 0)

    def test_zero_when_quotes_inside_url(self) -> None:
        """url() 内嵌 single-quote（SVG xmlns 场景）不算违规。"""
        src = (
            '.x { background: url("data:image/svg+xml;,'
            "%3csvg xmlns='http://example.com/'/%3e\"); }"
        )
        self.assertEqual(guard.count_naked_single_quotes(src), 0)

    def test_zero_when_quotes_inside_comment(self) -> None:
        """注释里的 single-quote（文档引用）不算违规。"""
        src = "/* 写 [data-theme='dark'] 表示深色模式 */\n.x { color: red; }"
        self.assertEqual(guard.count_naked_single_quotes(src), 0)

    def test_counts_attribute_selector_quotes(self) -> None:
        """``[data-theme='dark']`` 属于"裸露"违规。"""
        src = "[data-theme='dark'] { color: red; }"
        self.assertEqual(guard.count_naked_single_quotes(src), 1)

    def test_counts_content_property_quotes(self) -> None:
        """``content: 'hello'`` 属于"裸露"违规。"""
        src = ".x::before { content: 'hello'; }"
        self.assertEqual(guard.count_naked_single_quotes(src), 1)

    def test_counts_font_family_quotes(self) -> None:
        """``font-family: 'Andale Mono'`` 属于"裸露"违规。"""
        src = ".x { font-family: 'Andale Mono', monospace; }"
        self.assertEqual(guard.count_naked_single_quotes(src), 1)

    def test_counts_multiple_violations(self) -> None:
        src = """
        [data-theme='dark'] {
          font-family: 'Ubuntu Mono', 'Andale Mono';
          content: 'hello';
        }
        """
        self.assertEqual(guard.count_naked_single_quotes(src), 4)


class TestFindNakedSingleQuotesWithLines(unittest.TestCase):
    """行号定位行为。"""

    def test_returns_empty_when_clean(self) -> None:
        src = ".x { color: red; }"
        self.assertEqual(guard.find_naked_single_quotes_with_lines(src), [])

    def test_returns_violations_with_line_numbers(self) -> None:
        src = "line 1\n[data-theme='dark']\n[data-theme='light']\n"
        out = guard.find_naked_single_quotes_with_lines(src)
        self.assertEqual(len(out), 2)
        # 行号都应该 ≥ 1
        for line_no, _ in out:
            self.assertGreaterEqual(line_no, 1)
        self.assertEqual([lit for _, lit in out], ["'dark'", "'light'"])

    def test_skips_url_block_violations(self) -> None:
        """url() 内的 single-quote 不应出现在结果里。"""
        src = "url(\"%3csvg xmlns='http://example.com/'/%3e\")\n"
        self.assertEqual(guard.find_naked_single_quotes_with_lines(src), [])


class TestScanFiles(unittest.TestCase):
    """``scan_files`` 处理多文件 / 缺失文件 / 真实文件。"""

    def test_clean_file(self) -> None:
        css_file = REPO_ROOT / "src/ai_intervention_agent/static/css/main.css"
        total, per_file = guard.scan_files([css_file])
        # main.css 在 R169 commit 73d9980 后应保持 0 处违规
        self.assertEqual(total, 0)
        self.assertEqual(per_file, [])

    def test_dirty_file_reports_details(self, tmp_path: Path | None = None) -> None:
        """临时构造一个 dirty CSS 文件，确认 scan_files 准确报告。"""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".css", delete=False, encoding="utf-8"
        ) as f:
            f.write("[data-theme='dark'] { content: 'x'; }\n")
            tmp_name = f.name

        try:
            total, per_file = guard.scan_files([Path(tmp_name)])
            self.assertEqual(total, 2)
            self.assertEqual(len(per_file), 1)
            path, details = per_file[0]
            self.assertEqual(str(path), tmp_name)
            self.assertEqual(len(details), 2)
        finally:
            Path(tmp_name).unlink(missing_ok=True)

    def test_missing_file_is_skipped(self) -> None:
        """目标文件不存在 → silently skip + warn，不抛异常。"""
        bogus = REPO_ROOT / "src/this/file/does/not/exist.css"
        buf = io.StringIO()
        with redirect_stderr(buf):
            total, per_file = guard.scan_files([bogus])
        self.assertEqual(total, 0)
        self.assertEqual(per_file, [])
        self.assertIn("目标文件不存在", buf.getvalue())


class TestMainEquivalence(unittest.TestCase):
    """CLI ``main()`` 三个分支退出码 + main.css baseline 同步。"""

    def test_main_clean_returns_zero(self) -> None:
        """默认配置（main.css == baseline 0）→ exit 0。"""
        out_buf = io.StringIO()
        with patch.object(sys, "argv", ["check_css_quote_consistency.py"]):
            with redirect_stdout(out_buf):
                code = guard.main()
        self.assertEqual(code, 0)
        self.assertIn("CSS 引号一致性检查通过", out_buf.getvalue())

    def test_main_quiet_no_output_on_pass(self) -> None:
        """``--quiet`` 在 pass 时不输出 —— pre-commit 友好。"""
        out_buf = io.StringIO()
        with patch.object(sys, "argv", ["check_css_quote_consistency.py", "--quiet"]):
            with redirect_stdout(out_buf):
                code = guard.main()
        self.assertEqual(code, 0)
        self.assertEqual(out_buf.getvalue(), "")

    def test_main_violation_returns_one(self) -> None:
        """传入 prism.css（含 2 处 single-quote font-family）→ exit 1。"""
        err_buf = io.StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "check_css_quote_consistency.py",
                "src/ai_intervention_agent/static/css/prism.css",
            ],
        ):
            with redirect_stderr(err_buf):
                code = guard.main()
        self.assertEqual(code, 1)
        self.assertIn("CSS 引号一致性漂移", err_buf.getvalue())
        self.assertIn("prism.css", err_buf.getvalue())

    def test_main_below_baseline_warns(self) -> None:
        """count < baseline → exit 0 但 stderr 提示降 baseline。"""
        err_buf = io.StringIO()
        with patch.object(
            sys,
            "argv",
            ["check_css_quote_consistency.py", "--baseline", "10"],
        ):
            with redirect_stderr(err_buf):
                code = guard.main()
        self.assertEqual(code, 0)
        self.assertIn("已收敛", err_buf.getvalue())


class TestMainCssBaselineSync(unittest.TestCase):
    """锁定 ``main.css`` 实际"裸露"single-quote 数 == ``DEFAULT_BASELINE``。"""

    def test_main_css_matches_baseline(self) -> None:
        css_file = REPO_ROOT / "src/ai_intervention_agent/static/css/main.css"
        total, _ = guard.scan_files([css_file])
        self.assertEqual(
            total,
            guard.DEFAULT_BASELINE,
            f'main.css 当前 {total} 处"裸露"single-quote，'
            f"但 DEFAULT_BASELINE = {guard.DEFAULT_BASELINE}。"
            "如果 PR 有意改变 baseline，请同步更新脚本里的 DEFAULT_BASELINE。",
        )


class TestPreCommitConfig(unittest.TestCase):
    """``.pre-commit-config.yaml`` 里 R174 hook 配置正确。"""

    def test_hook_registered(self) -> None:
        config_path = REPO_ROOT / ".pre-commit-config.yaml"
        config_text = config_path.read_text(encoding="utf-8")
        self.assertIn("check-css-quote-consistency", config_text)

    def test_hook_entry_correct(self) -> None:
        config_path = REPO_ROOT / ".pre-commit-config.yaml"
        config_text = config_path.read_text(encoding="utf-8")
        self.assertIn(
            "uv run python scripts/check_css_quote_consistency.py --quiet",
            config_text,
        )

    def test_hook_files_glob_targets_project_owned_css(self) -> None:
        """files glob 必须明确指到项目自有 CSS（main + tri-state-panel）。

        这是 R174 / CR#10 F-1 + R178 follow-up 的关键决策：
        ``prism.css`` 是 vendor 代码，**始终**排除在外；``main.css`` 和
        ``tri-state-panel.css`` 都已经收敛到 double-quote 基线，纳入守门。
        如果未来再加项目自有 CSS（例如 ``components/foo.css``），需要同步
        改 ``DEFAULT_TARGETS`` 与 files glob。
        """
        config_path = REPO_ROOT / ".pre-commit-config.yaml"
        config_text = config_path.read_text(encoding="utf-8")
        self.assertIn(
            "files: ^src/ai_intervention_agent/static/css/(main|tri-state-panel)\\.css$",
            config_text,
        )

    def test_default_targets_cover_project_owned_css(self) -> None:
        """``DEFAULT_TARGETS`` 必须涵盖项目自有 CSS（main + tri-state-panel）。

        R178 follow-up 把 tri-state-panel.css 收敛到 double-quote 后，
        DEFAULT_TARGETS 同步扩展。这条测试防止后续重构悄悄把它从默认目标
        里删掉，让守门覆盖范围缩水。
        """
        from scripts.check_css_quote_consistency import DEFAULT_TARGETS

        self.assertIn(
            "src/ai_intervention_agent/static/css/main.css",
            DEFAULT_TARGETS,
        )
        self.assertIn(
            "src/ai_intervention_agent/static/css/tri-state-panel.css",
            DEFAULT_TARGETS,
        )
        # vendor 代码必须保持排除
        self.assertNotIn(
            "src/ai_intervention_agent/static/css/prism.css",
            DEFAULT_TARGETS,
        )


if __name__ == "__main__":
    unittest.main()
