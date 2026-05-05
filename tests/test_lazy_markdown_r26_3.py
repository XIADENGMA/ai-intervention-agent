"""R26.3 lazy ``markdown`` import + lazy ``markdown.Markdown(...)`` instantiation 守护

背景
----
``web_ui.py`` 模块顶级原本有 ``import markdown``（~8.9 ms cold cache），且
``WebFeedbackUI.setup_markdown`` 在 ``__init__`` 链路里立刻 ``self.md =
markdown.Markdown(extensions=[...10 个扩展...])`` 一次性预热全部插件
（codehilite Pygments + footnote AST + nl2br + md_in_html + ... 共 ~10-15 ms 的
插件 regex/lexer 编译），合计 ~20-25 ms 的 wall-clock cost 落在每个
``web_ui`` 子进程 cold-start 上。R26.3 把两步都推迟到首次 ``render_markdown``
调用：(1) ``import markdown`` 下沉到 ``render_markdown`` 体内、(2) ``self.md``
sentinel ``None`` 起步，由首次 ``render_markdown`` 在 ``self._md_lock`` 临界区
里完成「双重检查 lazy init」。

本测试套件锁定四组不变量：

1. **静态 source-text 不变量** —— 防止重构悄悄拆掉 lazy-load 契约
2. **运行时 sys.modules 不变量** —— 子进程隔离地真实加载 ``web_ui``，断言
   ``import web_ui`` 完成后 ``markdown`` 不在 ``sys.modules``，``WebFeedbackUI()``
   构造完毕后 ``markdown`` 仍不在 ``sys.modules``
3. **行为契约 / lazy-init 第一次触发** —— 首次 ``render_markdown`` 调用后
   ``markdown`` 才进入 ``sys.modules``，``self.md`` 才不再是 ``None``
4. **线程安全 race 保护** —— 100 条线程同时跑 ``render_markdown(text)``，
   ``markdown.Markdown`` 只构造一次（不会因 race 构造多份）
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import textwrap
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_PATH = REPO_ROOT / "web_ui.py"


def _strip_docstrings_and_comments(src: str) -> str:
    """剔除 module / class / function 顶级 docstring 与 ``# ...`` 注释，
    避免「``import markdown`` 写在注释/docstring 里也算 import」的误判。

    保守起见，只剔除最常见的两类：
    - 三引号 docstring（贪婪匹配，跨行）
    - ``#`` 行注释（行尾起到行首的部分）

    剔除完毕后单行内残余 ``import`` 语句一定是真的 import。
    """
    src = re.sub(r'""".*?"""', "", src, flags=re.DOTALL)
    src = re.sub(r"'''.*?'''", "", src, flags=re.DOTALL)
    src = re.sub(r"(?m)#[^\n]*", "", src)
    return src


class TestStaticSourceInvariants(unittest.TestCase):
    """``web_ui.py`` 源文本必须满足的 R26.3 不变量"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.full_src = WEB_UI_PATH.read_text(encoding="utf-8")
        cls.cleaned_src = _strip_docstrings_and_comments(cls.full_src)

    def test_no_module_top_import_markdown(self) -> None:
        """``web_ui.py`` 模块顶级**不能**有 ``import markdown`` / ``from markdown import ...``。

        Lazy-load 契约的最强证据：模块顶级的 import 只能出现在 ``cleaned_src``
        的第 0 缩进列。函数体内的 import 缩进 ≥ 4 spaces 不会被这个 regex 匹配。
        """
        pattern = re.compile(r"(?m)^(import\s+markdown\b|from\s+markdown\s+import\b)")
        match = pattern.search(self.cleaned_src)
        self.assertIsNone(
            match,
            "R26.3: ``web_ui.py`` 顶级**不能**有 ``import markdown``——"
            "它必须下沉到 ``render_markdown`` 体内的 lazy import",
        )

    def test_render_markdown_body_has_lazy_import(self) -> None:
        """``render_markdown`` 函数体里必须有 ``import markdown``，
        且必须在 ``markdown.Markdown(...)`` 实例化**之前**。"""
        from web_ui import WebFeedbackUI

        src = inspect.getsource(WebFeedbackUI.render_markdown)
        # 剔除 docstring 后才查
        src = _strip_docstrings_and_comments(src)
        self.assertIn(
            "import markdown",
            src,
            "R26.3: ``render_markdown`` 必须在体内 lazy import markdown",
        )
        self.assertIn(
            "markdown.Markdown(",
            src,
            "R26.3: ``render_markdown`` 必须 lazy-init ``markdown.Markdown(...)``",
        )
        # 顺序：import 必须在 Markdown(...) 之前
        import_pos = src.find("import markdown")
        ctor_pos = src.find("markdown.Markdown(")
        self.assertLess(
            import_pos,
            ctor_pos,
            "R26.3: ``import markdown`` 必须在 ``markdown.Markdown(...)`` 构造之前",
        )

    def test_setup_markdown_uses_none_sentinel(self) -> None:
        """``setup_markdown`` 体内必须有 ``self.md`` 起步为 ``None`` 的 sentinel
        赋值，**不能**直接 ``self.md = markdown.Markdown(...)``。"""
        from web_ui import WebFeedbackUI

        src = inspect.getsource(WebFeedbackUI.setup_markdown)
        src = _strip_docstrings_and_comments(src)
        self.assertRegex(
            src,
            r"self\.md\s*:\s*Any\s*=\s*None",
            "R26.3: ``setup_markdown`` 必须用 ``self.md: Any = None`` sentinel",
        )
        self.assertNotIn(
            "markdown.Markdown(",
            src,
            "R26.3: ``setup_markdown`` 体内不能再有 ``markdown.Markdown(...)`` "
            "实例化——已下沉到 ``render_markdown``",
        )

    def test_module_level_md_constants_exist(self) -> None:
        """``_MD_EXTENSIONS`` / ``_MD_EXTENSION_CONFIGS`` 必须在模块级声明，
        让 lazy-init 路径只是一行 ``markdown.Markdown(**kwargs)`` 简洁调用。"""
        import web_ui

        self.assertTrue(hasattr(web_ui, "_MD_EXTENSIONS"))
        self.assertTrue(hasattr(web_ui, "_MD_EXTENSION_CONFIGS"))
        self.assertIsInstance(web_ui._MD_EXTENSIONS, list)
        self.assertIsInstance(web_ui._MD_EXTENSION_CONFIGS, dict)
        # 锁定关键扩展不能在重构时被悄悄删掉
        for required_ext in (
            "fenced_code",
            "codehilite",
            "tables",
            "toc",
            "nl2br",
            "footnotes",
        ):
            self.assertIn(
                required_ext,
                web_ui._MD_EXTENSIONS,
                f"R26.3: 关键扩展 ``{required_ext}`` 不能在重构中丢失",
            )
        # codehilite 配置必须保留 monokai 内联样式
        self.assertIn("codehilite", web_ui._MD_EXTENSION_CONFIGS)
        codehilite_cfg = web_ui._MD_EXTENSION_CONFIGS["codehilite"]
        self.assertEqual(codehilite_cfg.get("pygments_style"), "monokai")
        self.assertTrue(
            codehilite_cfg.get("noclasses"), "必须保留 noclasses=True 以避免 CSP 冲突"
        )

    def test_rationale_tag_present(self) -> None:
        """模块源文必须留下 ``R26.3`` 标记，方便 ``git grep`` 翻案归因。"""
        self.assertIn("R26.3", self.full_src, "R26.3: 模块源里必须有 ``R26.3`` 标记")


class TestRuntimeSysModulesInvariant(unittest.TestCase):
    """子进程隔离运行时 ``sys.modules`` 不变量——真实测，不被同进程其他测试污染"""

    @staticmethod
    def _run_subprocess_assert(script: str) -> tuple[int, str, str]:
        """在子进程跑独立 ``python -c``，返回 (returncode, stdout, stderr)。"""
        proc = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_import_web_ui_does_not_load_markdown(self) -> None:
        """在干净子进程里 ``import web_ui`` 完成后，``markdown`` **不能**
        在 ``sys.modules``——证明 R26.3 lazy-load 在 module-import 链路上有效。"""
        rc, out, err = self._run_subprocess_assert("""
            import sys
            import web_ui  # noqa: F401
            assert "markdown" not in sys.modules, (
                "R26.3 regression: 'markdown' is in sys.modules after `import web_ui`"
            )
            print("OK")
        """)
        self.assertEqual(rc, 0, f"subprocess failed:\nSTDOUT: {out}\nSTDERR: {err}")
        self.assertIn("OK", out)

    def test_construct_webfeedbackui_does_not_load_markdown(self) -> None:
        """干净子进程里 ``WebFeedbackUI(...)`` 构造完成后，``markdown`` 仍**不能**
        在 ``sys.modules``——证明 ``setup_markdown`` 走 sentinel 路径不再 eager
        构造 Markdown 实例。"""
        rc, out, err = self._run_subprocess_assert("""
            import sys
            from web_ui import WebFeedbackUI
            ui = WebFeedbackUI(prompt='r26-3', port=0)
            assert "markdown" not in sys.modules, (
                f"R26.3 regression: 'markdown' is in sys.modules after WebFeedbackUI(); "
                f"keys = {sorted(k for k in sys.modules if 'markdown' in k)}"
            )
            assert ui.md is None, f"R26.3 regression: ui.md should be None, got {ui.md!r}"
            print("OK")
        """)
        self.assertEqual(rc, 0, f"subprocess failed:\nSTDOUT: {out}\nSTDERR: {err}")
        self.assertIn("OK", out)

    def test_first_render_markdown_call_loads_markdown(self) -> None:
        """干净子进程里首次 ``render_markdown(text)`` 调用后，``markdown``
        **必须**在 ``sys.modules`` 且 ``self.md`` 不再是 ``None``——证明
        lazy-init 在使用点正确触发。"""
        rc, out, err = self._run_subprocess_assert("""
            import sys
            from web_ui import WebFeedbackUI
            ui = WebFeedbackUI(prompt='r26-3', port=0)
            assert "markdown" not in sys.modules
            assert ui.md is None
            html = ui.render_markdown("# title\\n\\nbody")
            assert "<h1" in html, f"render output should be HTML, got {html!r}"
            assert "markdown" in sys.modules, (
                "R26.3 contract: 'markdown' MUST be in sys.modules after first render_markdown"
            )
            assert ui.md is not None, (
                "R26.3 contract: ui.md MUST be initialized after first render_markdown"
            )
            print("OK")
        """)
        self.assertEqual(rc, 0, f"subprocess failed:\nSTDOUT: {out}\nSTDERR: {err}")
        self.assertIn("OK", out)


class TestLazyInitThreadSafety(unittest.TestCase):
    """100 个线程并发 ``render_markdown``：``markdown.Markdown(...)`` 只构造一次"""

    def test_concurrent_first_render_initializes_only_once(self) -> None:
        """100 个线程同时跑 ``render_markdown(...)``，``markdown.Markdown``
        构造调用 count 必须等于 1（不是 100，也不是 1+race-leftover）。

        如果 lazy-init 没有用 ``self._md_lock`` 守护，多线程同时看到
        ``self.md is None`` 会各自构造一份实例（最后一个赋值的胜出，前面
        的实例被 GC 回收，浪费 CPU 但功能仍正确）；本测试就是要保证
        「不浪费」这一性能不变量。
        """
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="thread-safe", port=0)
        # 用 monkey-patch 计数 ``markdown.Markdown`` 构造次数
        import markdown as _md  # 测试代码本身可以 eager import，不影响产品代码

        original_markdown_cls = _md.Markdown
        ctor_count = [0]
        ctor_lock = threading.Lock()

        def counting_markdown(*args: object, **kwargs: object) -> object:
            with ctor_lock:
                ctor_count[0] += 1
            return original_markdown_cls(*args, **kwargs)

        _md.Markdown = counting_markdown  # ty: ignore[invalid-assignment]
        try:
            barrier = threading.Barrier(parties=100)
            errors: list[BaseException] = []

            def worker(i: int) -> None:
                try:
                    barrier.wait()
                    ui.render_markdown(f"# heading {i}")
                except BaseException as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertFalse(errors, f"Some threads errored: {errors!r}")
            self.assertEqual(
                ctor_count[0],
                1,
                f"R26.3 race regression: ``markdown.Markdown`` constructed "
                f"{ctor_count[0]} times instead of 1",
            )
            self.assertIsNotNone(
                ui.md, "After 100 concurrent renders, ui.md must be set"
            )
        finally:
            _md.Markdown = original_markdown_cls


class TestBackwardCompatibility(unittest.TestCase):
    """既有 API contract 不能因为 R26.3 lazy-init 改动被破坏"""

    @classmethod
    def setUpClass(cls) -> None:
        from web_ui import WebFeedbackUI

        cls.WebFeedbackUI = WebFeedbackUI

    def test_render_markdown_returns_html_with_codehilite(self) -> None:
        """``render_markdown`` 渲染含代码块的文本必须 (a) 触发 lazy init，
        (b) 输出含 monokai 内联样式（``noclasses=True`` 的契约）。"""
        ui = self.WebFeedbackUI(prompt="x", port=0)
        out = ui.render_markdown("```python\nprint('hi')\n```")
        self.assertIn("<div", out, "Code block must wrap in HTML")
        self.assertIn("style=", out, "noclasses=True 必须输出内联 style 属性")

    def test_render_markdown_empty_text_short_circuits_without_loading_markdown(
        self,
    ) -> None:
        """空文本短路返回 ``""``，**不能**触发 lazy import。"""
        # 这个测试在主进程跑，不能用 sys.modules 全局状态；改为检查 ui.md
        # 是否仍然是 None。
        ui = self.WebFeedbackUI(prompt="x", port=0)
        self.assertIsNone(ui.md)
        out = ui.render_markdown("")
        self.assertEqual(out, "")
        # 空字符串路径在 ``with self._md_lock:`` 之前就 short-circuit return ""，
        # 所以 lazy init 不会被触发——ui.md 仍是 None
        self.assertIsNone(
            ui.md,
            "R26.3: 空字符串路径必须在锁之前 short-circuit，不触发 lazy init",
        )


if __name__ == "__main__":
    unittest.main()
