"""L4·G1 – ``scripts/check_i18n_orphan_keys.py`` 的 pytest 镜像。

脚本 warn-only（不挂 CI），给贡献者 soft 信号；strict dead-key gate 已在
``test_runtime_behavior.py``。本文件锁「扫描器合约」而非 codebase 状态：
  1. ``t(...)`` 提取正则必须认齐我们实际用过的 wrapper（``_t`` / ``tl``
     / ``hostT`` / ``__vuT`` / ``__domSecT`` / ``__ncT``）；新增 wrapper 忘
     了改扫描器会让 orphan 报告说谎；
  2. JSON 输出形状稳定（``orphans`` / ``total_keys`` / ``used_keys``
     per surface），给未来 dashboard / PR commenter 用；
  3. ``--strict`` 真的在有 orphan 时 exit 1；
  4. ``--json`` 输出是合法 JSON。

使用合成 fixture，避免与 ``test_runtime_behavior.py`` 的 dead-key 测试
双重覆盖。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_i18n_orphan_keys import (
    JS_T_CALL_RE,
    _flatten_keys,
    _strip_source_comments,
    main,
    scan,
)


class TestRegexCoversAllWrappers(unittest.TestCase):
    """The JS_T_CALL_RE regex MUST recognize every wrapper the project
    uses. Production code paths, not hypothetical ones."""

    def test_every_known_wrapper(self) -> None:
        for call, expected in [
            ("t('a.b.c')", "a.b.c"),
            ("_t('foo.bar')", "foo.bar"),
            ("tl('baz.qux')", "baz.qux"),
            ("hostT('statusBar.tasks')", "statusBar.tasks"),
            ("__vuT('validation.x')", "validation.x"),
            ("__domSecT('page.y')", "page.y"),
            ("__ncT('notify.z')", "notify.z"),
        ]:
            with self.subTest(call=call):
                matches = JS_T_CALL_RE.findall(call)
                self.assertIn(expected, matches, f"regex missed {call!r}")

    def test_property_access_not_matched(self) -> None:
        """``obj.t('foo')`` MUST NOT be picked up (property access)."""
        matches = JS_T_CALL_RE.findall("obj.t('foo.bar')")
        self.assertEqual(matches, [])

    def test_variable_identifier_not_matched(self) -> None:
        """``myT('foo')`` is NOT one of our wrappers — must be skipped."""
        matches = JS_T_CALL_RE.findall("myT('foo.bar')")
        self.assertEqual(matches, [])

    def test_prettier_multiline_call_is_matched(self) -> None:
        """R18.3 reverse-lock：Prettier 把长参数列表切成多行后第一参数前会带
        换行 + 缩进；扫描器必须容忍这种格式，否则真在用的 key 会被误报为 dead。

        这是一个真实历史 bug 的回归 fixture：
        ``static/js/settings-manager.js`` 里 4 个 ``settings.openConfigInIde*``
        key 在 Prettier 把 ``_tl(`` 切成多行后被旧正则 silent miss，
        ``test_runtime_behavior::test_web_locale_no_dead_keys`` 误报失败。
        """
        # 准确还原 Prettier 行为：``_tl(`` 后立刻 ``\n`` + 6 空格缩进
        snippet = (
            '_tl(\n  "settings.openConfigInIdeOpened",\n  "Opened with {editor}.",\n)'
        )
        matches = JS_T_CALL_RE.findall(snippet)
        self.assertIn(
            "settings.openConfigInIdeOpened",
            matches,
            "Prettier 多行 _tl(\\n  'key', ...) 必须能被 JS_T_CALL_RE 识别；"
            "否则 4 个 settings.openConfigInIde* key 会重新被误报为 dead。",
        )

    def test_tab_indented_multiline_call_is_matched(self) -> None:
        """ESLint / Biome / Tabs-only 项目可能用 ``\\t`` 缩进而不是空格；
        ``\\s*`` 也必须覆盖 tab，避免再开一道兼容性洞。"""
        snippet = "tl(\n\t'foo.bar',\n\t'fallback'\n)"
        matches = JS_T_CALL_RE.findall(snippet)
        self.assertIn("foo.bar", matches)

    def test_single_line_compact_call_still_matched(self) -> None:
        """正向反向锁：放宽到 ``\\(\\s*`` 不能让旧的紧凑形式失配。"""
        for call in (
            "_tl('a.b.c')",
            'tl("x.y", fallback)',
            "t( 'spaced.inside' )",
        ):
            with self.subTest(call=call):
                matches = JS_T_CALL_RE.findall(call)
                self.assertTrue(matches, f"compact-form regression: {call!r} unmatched")


class TestStripSourceComments(unittest.TestCase):
    """``_strip_source_comments`` 必须把注释里的 ``t('key')`` 字面量剥掉，
    避免 banner / docstring / inline 注释里的示例被当成实际引用。

    历史 bug：``packages/vscode/extension.ts`` banner 注释里写了
    ``hostT('statusBar.unkown')``（故意拼错让 tsc 挂掉）；
    扫描器把它当真实引用，输出 ``used > total`` 的假信号——直到 R92 才发现。
    并且修复时还要避免把"line comment 里的 ``/*``"误判为 block comment 起点。
    """

    def test_line_comment_t_call_is_stripped(self) -> None:
        src = "// see t('foo.bar') for the real key\nconst x = 1;"
        out = _strip_source_comments(src)
        self.assertNotIn("t('foo.bar')", out)
        self.assertIn("const x = 1;", out)

    def test_block_comment_t_call_is_stripped(self) -> None:
        src = "/* example: hostT('statusBar.unkown') */\nconst x = 1;"
        out = _strip_source_comments(src)
        self.assertNotIn("hostT('statusBar.unkown')", out)
        self.assertIn("const x = 1;", out)

    def test_real_t_call_outside_comment_survives(self) -> None:
        src = "// note: t('comment.key') is just an example\nbtn.html = t('real.key');"
        out = _strip_source_comments(src)
        # 注释内的不计
        matches = JS_T_CALL_RE.findall(out)
        self.assertNotIn("comment.key", matches)
        # 真代码必须保留
        self.assertIn("real.key", matches)

    def test_line_comment_with_slash_star_does_not_swallow_following_code(self) -> None:
        """关键回归：``// ... locales/*.json`` 这类 line comment 含字面 ``/*``，
        不能被当成 block comment 起点而吞掉之后几百行真代码。

        v1.5 实测：``static/js/app.js`` line 538 ``// 走 locales/*.json …`` 在
        修复前让扫描器把后续 688 行（含 ``status.copied`` / ``status.copyFailed``
        / ``status.submitting`` / ``status.submitFailed`` 等多个真实 ``t(...)``
        调用）一并视作 block comment，触发 17 个假 orphan。
        """
        src = (
            "// 走 locales/*.json 静态 key 且无参数。详见 docs/i18n.md\n"
            "btn.html = t('status.copied');\n"
            "btn.html = t('status.copyFailed');\n"
        )
        out = _strip_source_comments(src)
        matches = set(JS_T_CALL_RE.findall(out))
        self.assertIn("status.copied", matches, "block-comment-from-line-comment 回归")
        self.assertIn(
            "status.copyFailed", matches, "block-comment-from-line-comment 回归"
        )

    def test_line_offsets_preserved(self) -> None:
        """剥注释必须保留行号，方便上层 ``find()`` 计算 lineno。"""
        src = "line1\n// comment\nline3\n"
        out = _strip_source_comments(src)
        self.assertEqual(out.count("\n"), src.count("\n"))


class TestFlatten(unittest.TestCase):
    def test_flatten_simple(self) -> None:
        self.assertEqual(
            _flatten_keys({"a": {"b": "x", "c": "y"}, "d": "z"}),
            {"a.b", "a.c", "d"},
        )

    def test_flatten_ignores_non_dict_descendants(self) -> None:
        # Arrays / numbers aren't i18n "keys"; flatten should stop at
        # the nearest leaf.
        self.assertEqual(
            _flatten_keys({"a": [1, 2, 3], "b": 7}),
            {"a", "b"},
        )


class TestScanReturnsStableShape(unittest.TestCase):
    """Run the real scanner against the committed codebase.

    We don't assert exact orphan counts (those drift intentionally as
    the codebase evolves). We only assert the SHAPE."""

    def test_shape(self) -> None:
        report = scan()
        self.assertIn("web", report)
        self.assertIn("vscode", report)
        for surface in ("web", "vscode"):
            entry = report[surface]
            self.assertIn("orphans", entry)
            self.assertIn("total_keys", entry)
            self.assertIn("used_keys", entry)
            self.assertIsInstance(entry["orphans"], list)
            self.assertIsInstance(entry["total_keys"], int)
            self.assertIsInstance(entry["used_keys"], int)


class TestMainModes(unittest.TestCase):
    """Exit-code contract of ``main(...)``."""

    def test_default_is_warn(self, capsys=None) -> None:
        rc = main([])
        self.assertEqual(rc, 0, "warn mode must never exit non-zero")

    def test_json_is_valid_json(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertIn("web", parsed)
        self.assertIn("vscode", parsed)

    def test_strict_exits_zero_when_no_orphans(self) -> None:
        # The current codebase is orphan-free, so --strict must pass.
        rc = main(["--strict"])
        self.assertEqual(
            rc,
            0,
            "codebase currently has 0 orphans; --strict should exit 0",
        )


if __name__ == "__main__":
    unittest.main()
