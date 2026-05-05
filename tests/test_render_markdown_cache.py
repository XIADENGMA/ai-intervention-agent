"""R20.7 ``WebFeedbackUI.render_markdown`` LRU 缓存测试

背景
----
``/api/config`` 是被 VSCode webview + 浏览器 web UI 反复轮询的 hot path
（默认 ~2-30s 一次），handler 中 ``render_markdown(active_task.prompt)``
是 ~5-20 ms 的 CPU 密集型操作（codehilite Pygments + 10+ 扩展）。
但同一个 prompt 在任务生命周期内不会变，引入 LRU 缓存后命中率 ~100%。

本测试套件通过两条互补路径锁定行为：

1. **功能正确性**
   - 命中返回与 miss 结果完全一致（不是 stale）
   - LRU 逐出最旧条目，保留热条目
   - 容量上限严格守住
   - 空字符串不进 cache（避免污染）
   - markdown 实例只对 unique prompt 调用一次 ``convert``

2. **源文本不变量**（防止 cache 在重构中被悄悄拆掉）
   - ``self._md_cache`` 字段在 ``__init__`` 里声明
   - ``render_markdown`` 持锁、查表、写表、LRU 逐出四条关键代码路径仍在原位
"""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import patch

WEB_UI_PATH = Path(__file__).resolve().parent.parent / "web_ui.py"


class TestRenderMarkdownCacheCorrectness(unittest.TestCase):
    """LRU 缓存功能层面的正确性测试"""

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls.WebFeedbackUI = WebFeedbackUI

    def setUp(self) -> None:
        self.ui = self.WebFeedbackUI(prompt="cache test", port=18910)

    def test_empty_text_returns_empty_and_does_not_cache(self) -> None:
        """空字符串短路返回，不写入 cache"""
        out = self.ui.render_markdown("")
        self.assertEqual(out, "")
        self.assertEqual(len(self.ui._md_cache), 0)

    def test_first_call_populates_cache(self) -> None:
        """首次渲染后 cache 中应有该条目"""
        self.assertEqual(len(self.ui._md_cache), 0)
        out = self.ui.render_markdown("# Hello")
        self.assertIn("<h1", out)
        self.assertEqual(len(self.ui._md_cache), 1)
        self.assertIn("# Hello", self.ui._md_cache)

    def test_cache_hit_returns_identical_html(self) -> None:
        """命中返回的 HTML 与 miss 路径完全一致（不是 stale 副本）"""
        first = self.ui.render_markdown("# Title\n\nbody")
        second = self.ui.render_markdown("# Title\n\nbody")
        self.assertEqual(first, second)

    def test_cache_hit_skips_markdown_convert(self) -> None:
        """命中时 ``self.md.convert`` 不再被调用（核心性能不变量）"""
        text = "# Hot path"
        self.ui.render_markdown(text)
        with patch.object(
            self.ui.md, "convert", wraps=self.ui.md.convert
        ) as wrapped_convert:
            for _ in range(50):
                self.ui.render_markdown(text)
            wrapped_convert.assert_not_called()

    def test_cache_miss_calls_convert_once_per_unique_text(self) -> None:
        """N 个不同 prompt 调 ``convert`` 恰好 N 次"""
        prompts = [f"# Heading {i}" for i in range(5)]
        with patch.object(
            self.ui.md, "convert", wraps=self.ui.md.convert
        ) as wrapped_convert:
            for p in prompts:
                self.ui.render_markdown(p)
                self.ui.render_markdown(p)
                self.ui.render_markdown(p)
            self.assertEqual(wrapped_convert.call_count, 5)

    def test_cache_evicts_oldest_when_full(self) -> None:
        """容量满时逐出最旧条目（LRU 语义）"""
        cap = self.ui._md_cache_capacity
        for i in range(cap):
            self.ui.render_markdown(f"# entry {i}")
        self.assertEqual(len(self.ui._md_cache), cap)
        self.assertIn("# entry 0", self.ui._md_cache)

        self.ui.render_markdown("# overflow")
        self.assertEqual(len(self.ui._md_cache), cap)
        self.assertNotIn("# entry 0", self.ui._md_cache)
        self.assertIn("# overflow", self.ui._md_cache)
        self.assertIn("# entry 1", self.ui._md_cache)

    def test_lru_touch_protects_recent_hits(self) -> None:
        """命中条目移到末尾，逐出时跳过它"""
        cap = self.ui._md_cache_capacity
        for i in range(cap):
            self.ui.render_markdown(f"# entry {i}")
        self.ui.render_markdown("# entry 0")
        self.ui.render_markdown("# overflow")

        self.assertIn("# entry 0", self.ui._md_cache)
        self.assertNotIn("# entry 1", self.ui._md_cache)
        self.assertIn("# overflow", self.ui._md_cache)

    def test_capacity_bounded(self) -> None:
        """无论塞多少条，cache 大小永不超过 capacity"""
        cap = self.ui._md_cache_capacity
        for i in range(cap * 5):
            self.ui.render_markdown(f"# entry {i}")
        self.assertLessEqual(len(self.ui._md_cache), cap)

    def test_concurrent_renders_do_not_corrupt_cache(self) -> None:
        """并发 render 不破坏 cache 大小不变量

        ``markdown.Markdown`` 实例非线程安全；``self._md_lock`` 必须保护
        cache 读写 + ``reset/convert`` 整段。这里通过多线程并发 render
        相同+不同 prompt，验证最终 cache 大小受容量约束。
        """
        cap = self.ui._md_cache_capacity
        errors: list[BaseException] = []
        unique_prompts = [f"# concurrent {i}" for i in range(cap // 2)]

        def worker() -> None:
            try:
                for _ in range(10):
                    for p in unique_prompts:
                        self.ui.render_markdown(p)
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertLessEqual(len(self.ui._md_cache), cap)
        for p in unique_prompts:
            self.assertIn(p, self.ui._md_cache)


class TestRenderMarkdownCacheSourceInvariants(unittest.TestCase):
    """源文本不变量：阻止 cache 在重构中被悄悄移除/弱化"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_UI_PATH.read_text(encoding="utf-8")

    def test_md_cache_field_declared_in_init(self) -> None:
        """``self._md_cache`` 必须作为 dict 在 ``__init__`` 中声明"""
        self.assertIn(
            "self._md_cache: dict[str, str] = {}",
            self.source,
            "render_markdown 的 LRU cache 字段被移除/重命名；如果是有意改造，"
            "请同时更新此测试。",
        )

    def test_md_cache_capacity_declared_in_init(self) -> None:
        """``_md_cache_capacity`` 必须有显式上限（防御无界增长）"""
        self.assertIn(
            "self._md_cache_capacity: int = 16",
            self.source,
            "cache 容量上限被移除——会导致内存无界增长。",
        )

    def test_render_markdown_uses_lock(self) -> None:
        """缓存读写必须在 ``self._md_lock`` 保护下进行"""
        self.assertIn(
            "with self._md_lock:",
            self.source,
            "_md_lock 保护被移除——markdown 实例非线程安全，会导致并发渲染崩溃。",
        )

    def test_render_markdown_has_cache_lookup(self) -> None:
        """命中分支必须存在（cache.get + return cached）"""
        self.assertIn(
            "cached = self._md_cache.get(text)",
            self.source,
            "cache 查询路径被移除——/api/config hot path 退化为每次都解析 markdown。",
        )

    def test_render_markdown_has_lru_touch(self) -> None:
        """命中后必须做 LRU touch（pop + 重新插入）"""
        self.assertIn(
            "self._md_cache.pop(text)",
            self.source,
            "LRU touch 被移除——cache 退化为 FIFO，热条目可能被逐出。",
        )

    def test_render_markdown_evicts_oldest_when_full(self) -> None:
        """超容量时必须逐出最旧条目"""
        self.assertIn(
            "next(iter(self._md_cache))",
            self.source,
            "LRU 逐出策略被移除——会导致内存无界或写入失败。",
        )


if __name__ == "__main__":
    unittest.main()
