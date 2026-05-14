"""R243 / Cycle 16 · runtime freshness check for ``_get_minified_file()``.

Why this test
-------------

R242 promoted ``minify_assets.py --check`` to a pre-commit hook so
developers can no longer accidentally commit a state where ``.min.js``
is stale relative to its source ``.js``. But two paths still exist
that let a stale ``.min`` reach the runtime:

1. ``git commit --no-verify`` (standard escape hatch on every hook).
2. Pre-existing stale ``.min`` files that the hook never gets a chance
   to inspect because the commit doesn't touch the source ``.js``
   (the hook's ``files`` filter scopes only to changed files).

R243 hardens ``_get_minified_file()`` itself: if a ``.min`` candidate
exists but is older than the source, return the source filename and
log a WARN. This is belt-and-suspenders defense-in-depth.

This test exercises the **runtime behavior** end-to-end with real
files in a tempdir (Pattern A — runtime contract, not Pattern B
static grep), so any future regression that drops the freshness
check will fail loudly.

What this test guards
---------------------

* Fresh ``.min`` (mtime >= source) → ``.min`` chosen.
* Stale ``.min`` (mtime < source) → source chosen.
* Stale ``.min`` → WARNING logged exactly once per file pair (de-dup).
* Pre-existing behaviors preserved (``.min.*`` requested explicitly
  passed through; missing ``.min`` falls back to source).
* OSError on stat() handled defensively (no crash).
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent.web_ui import WebFeedbackUI


class _BaseMinifiedRuntimeTest(unittest.TestCase):
    """Spin up one WebFeedbackUI per class — cheap, no port collisions thanks to high port."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ui = WebFeedbackUI(prompt="r243 test", port=18926)

    def setUp(self) -> None:
        self.ui._stale_minified_warned.clear()
        self._tmpdir_ctx = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmpdir_ctx.name

    def tearDown(self) -> None:
        self._tmpdir_ctx.cleanup()


class TestFreshMinifiedChosen(_BaseMinifiedRuntimeTest):
    def test_fresh_min_returned_when_min_mtime_ge_source(self) -> None:
        src = Path(self.tmpdir) / "app.js"
        minp = Path(self.tmpdir) / "app.min.js"
        src.write_text("// source", encoding="utf-8")
        minp.write_text("// minified", encoding="utf-8")
        future = time.time() + 60
        os.utime(minp, (future, future))

        result = self.ui._get_minified_file(self.tmpdir, "app.js", ".js")

        self.assertEqual(
            result,
            "app.min.js",
            "R243: 当 .min mtime >= source mtime, 应该 serve .min 版本以保留 "
            "parse-time 优势。当前却 serve 了 source —— 这会让所有现有 "
            ".min 优化失效。",
        )


class TestStaleMinifiedRejected(_BaseMinifiedRuntimeTest):
    def test_stale_min_falls_back_to_source(self) -> None:
        src = Path(self.tmpdir) / "app.js"
        minp = Path(self.tmpdir) / "app.min.js"
        src.write_text("// new source", encoding="utf-8")
        minp.write_text("// old minified", encoding="utf-8")
        past = time.time() - 60
        os.utime(minp, (past, past))

        result = self.ui._get_minified_file(self.tmpdir, "app.js", ".js")

        self.assertEqual(
            result,
            "app.js",
            "R243: 当 .min mtime < source mtime, 必须 serve source 而非 "
            "stale .min。这是 R243 整个的存在意义 —— 没有这条, R234/R238/R240/R241 "
            "类的 silent-stale bug 会重新出现。",
        )


class TestStaleWarningLoggedOnce(_BaseMinifiedRuntimeTest):
    """
    EnhancedLogger 在 stdlib logging 之上再包了一层 (level filter +
    deduplicator + ring buffer), ``self.assertLogs()`` 看不到被
    early-return 掉的 WARNING。改用 ``unittest.mock.patch`` 直接
    spy logger.warning 调用, 这才是 R243 dedup 真正想保护的接口。
    """

    def test_warning_logged_first_call_only(self) -> None:
        src = Path(self.tmpdir) / "app.js"
        minp = Path(self.tmpdir) / "app.min.js"
        src.write_text("// new", encoding="utf-8")
        minp.write_text("// old", encoding="utf-8")
        past = time.time() - 60
        os.utime(minp, (past, past))

        with patch("ai_intervention_agent.web_ui.logger.warning") as warn_spy:
            self.ui._get_minified_file(self.tmpdir, "app.js", ".js")
            self.ui._get_minified_file(self.tmpdir, "app.js", ".js")
            self.ui._get_minified_file(self.tmpdir, "app.js", ".js")

        r243_calls = [
            c
            for c in warn_spy.call_args_list
            if "R243" in (c.args[0] if c.args else "")
        ]
        self.assertEqual(
            len(r243_calls),
            1,
            f"R243: 同一 stale .min 文件应该只 WARN 一次 (per-process dedupe), "
            f"否则每个请求都刷一行日志, 会把生产 / 开发日志淹没。"
            f"实际 R243 WARN 次数: {len(r243_calls)}",
        )

    def test_different_files_warn_independently(self) -> None:
        src_a = Path(self.tmpdir) / "a.js"
        min_a = Path(self.tmpdir) / "a.min.js"
        src_b = Path(self.tmpdir) / "b.js"
        min_b = Path(self.tmpdir) / "b.min.js"
        for f in (src_a, src_b):
            f.write_text("// new", encoding="utf-8")
        for f in (min_a, min_b):
            f.write_text("// old", encoding="utf-8")
        past = time.time() - 60
        os.utime(min_a, (past, past))
        os.utime(min_b, (past, past))

        with patch("ai_intervention_agent.web_ui.logger.warning") as warn_spy:
            self.ui._get_minified_file(self.tmpdir, "a.js", ".js")
            self.ui._get_minified_file(self.tmpdir, "b.js", ".js")

        r243_calls = [
            c
            for c in warn_spy.call_args_list
            if "R243" in (c.args[0] if c.args else "")
        ]
        self.assertEqual(
            len(r243_calls),
            2,
            f"R243 dedup 应按文件名独立, 不能跨文件 dedup —— 否则第一个 stale "
            f".min 警告会沉默后续所有文件的警告, 大大降低诊断价值。"
            f"实际 WARN 次数: {len(r243_calls)}",
        )


class TestExplicitMinRequestPassesThrough(_BaseMinifiedRuntimeTest):
    """显式请求 .min.js (caller 自己指名), 不做任何检查 — 保持原合约。"""

    def test_already_min_returned_as_is(self) -> None:
        src = Path(self.tmpdir) / "app.js"
        minp = Path(self.tmpdir) / "app.min.js"
        src.write_text("// new", encoding="utf-8")
        minp.write_text("// old", encoding="utf-8")
        past = time.time() - 60
        os.utime(minp, (past, past))

        result = self.ui._get_minified_file(self.tmpdir, "app.min.js", ".js")

        self.assertEqual(
            result,
            "app.min.js",
            "R243 不应改变显式 .min 请求的行为 —— caller 已自行选择, "
            "我们不二次猜测。这与 R242 hook 的语义一致, 是开发者已知 "
            "在用 .min 的场景。",
        )


class TestMissingMinifiedFallsBack(_BaseMinifiedRuntimeTest):
    """R243 之前的行为: .min 不存在 → fallback。R243 保持此行为。"""

    def test_no_minified_returns_source(self) -> None:
        src = Path(self.tmpdir) / "app.js"
        src.write_text("// source", encoding="utf-8")

        result = self.ui._get_minified_file(self.tmpdir, "app.js", ".js")

        self.assertEqual(
            result,
            "app.js",
            "R243 必须保留 pre-existing 行为: .min 不存在 → fallback。"
            "否则 production fresh checkout (无 .min) 会 404。",
        )


class TestOSErrorOnStatHandledGracefully(_BaseMinifiedRuntimeTest):
    """stat() race / FS error 不能 crash request — 保守地 fallback。"""

    def test_unreadable_min_falls_back_to_source(self) -> None:
        src = Path(self.tmpdir) / "app.js"
        src.write_text("// source", encoding="utf-8")
        minp = Path(self.tmpdir) / "app.min.js"
        minp.write_text("// min", encoding="utf-8")

        from typing import Any, cast

        original_stat = cast(Any, Path).stat

        def _broken_stat(self: Path, *args: Any, **kwargs: Any) -> Any:
            if self.name == "app.min.js":
                raise OSError("simulated FS error")
            return original_stat(self, *args, **kwargs)

        cast(Any, Path).stat = _broken_stat
        try:
            result = self.ui._get_minified_file(self.tmpdir, "app.js", ".js")
        finally:
            cast(Any, Path).stat = original_stat

        self.assertEqual(
            result,
            "app.js",
            "R243: stat 抛 OSError 时应保守 fallback 到 source, 不能 propagate "
            "异常 —— static asset endpoint 不该因为 transient FS 错误就 500。",
        )


if __name__ == "__main__":
    unittest.main()
