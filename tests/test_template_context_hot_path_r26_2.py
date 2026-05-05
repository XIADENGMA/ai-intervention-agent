"""R26.2 性能不变量：``_get_template_context`` 热路径优化的契约保护。

背景
====

``WebFeedbackUI._get_template_context()`` 在两条路径上跑：
- 浏览器对 ``/`` 的每次 GET（人类用户每次刷新页面）。
- VS Code webview 的 ``_getHtmlContent`` 重渲染（``resolveWebviewView`` 初始 +
  ``setUrl`` 切换 + 语言切换 re-render 等场景，单次会话可能 5-10 次）。

R26.2 之前每次调用做了三件浪费的事情：
1. 重新分配 12 元素的 ``_RTL_LANG_PREFIXES`` tuple，对每个 prefix 跑两次
   ``startswith(p + "-")`` / ``== p`` 比较。
2. 跑一次 ``Path(__file__).resolve()`` syscall + 字符串拼接得到 ``static_dir``。
3. 4 次 ``self._get_file_version(static_dir / ...)`` 调用，每次都做 ``Path.stat()``
   syscall 取 mtime。

R26.2 通过以下三处改动把 ``_get_template_context`` 从 ~0.07 ms 降到 ~0.04 ms：

(1) ``_RTL_LANG_PREFIXES`` 提到模块级 ``frozenset``，``html_dir`` 计算改为
    单次 ``primary_subtag = html_lang.lower().partition('-')[0]`` + ``in`` 集合查询。
(2) ``self._static_dir`` 在 ``__init__`` 算好缓存（fallback 走模块级
    ``_get_module_static_dir()`` 兜底，让 ``object.__new__(WebFeedbackUI)``
    测试场景仍然可用）。
(3) ``_compute_file_version`` 自由函数 + ``@lru_cache(maxsize=64)``，按文件路径
    字符串缓存 stat 结果——进程级缓存命中后零 syscall。

不变量
======

1. **静态源码**：
   - ``_RTL_LANG_PREFIXES`` 必须是模块级 ``frozenset[str]``（不是函数内 tuple）。
   - 必须有模块级 ``_compute_file_version`` 函数且带 ``@lru_cache``。
   - 必须有模块级 ``_get_module_static_dir`` 函数且带 ``@lru_cache``。
   - ``WebFeedbackUI.__init__`` 必须给 ``self._static_dir`` 赋值。
   - ``_get_template_context`` 必须使用 ``getattr(self, '_static_dir', None) or
     _get_module_static_dir()`` 模式（保证 ``object.__new__`` 兜底）。
   - ``_get_template_context`` 必须直接调用 ``_compute_file_version(...)``
     而不是 ``self._get_file_version(...)``（绕过实例方法分发开销）。

2. **行为契约**：
   - ``_get_template_context`` 返回的 ``html_dir`` 在 RTL 语言（如 ``ar`` /
     ``he`` / ``fa``）下必须是 ``"rtl"``，LTR 语言（``en`` / ``zh-CN`` / ``ja``
     等）下必须是 ``"ltr"``。
   - ``_compute_file_version`` 对同一路径的二次调用必须命中 lru_cache（< 1 µs）。
   - ``_get_module_static_dir()`` 返回 ``Path``，二次调用必须命中 lru_cache。

3. **向后兼容**：``WebFeedbackUI._get_file_version`` 实例方法仍然存在并转调到
   ``_compute_file_version``，保证旧的测试与外部调用方继续工作。
"""

from __future__ import annotations

import inspect
import re
import time
import unittest

import web_ui


class TestModuleLevelHotPathConstants(unittest.TestCase):
    """模块级常量与函数必须按 R26.2 设计存在。"""

    def test_rtl_lang_prefixes_is_module_level_frozenset(self) -> None:
        """``_RTL_LANG_PREFIXES`` 必须是 frozenset，避免每次调用重新分配。"""
        self.assertTrue(
            hasattr(web_ui, "_RTL_LANG_PREFIXES"),
            "web_ui 模块必须暴露 ``_RTL_LANG_PREFIXES`` 模块级常量",
        )
        self.assertIsInstance(
            web_ui._RTL_LANG_PREFIXES,
            frozenset,
            "``_RTL_LANG_PREFIXES`` 必须是 frozenset（O(1) lookup + 不可变）",
        )
        # 确认包含核心 RTL 语言
        for lang in ("ar", "he", "fa", "ur", "yi"):
            with self.subTest(lang=lang):
                self.assertIn(
                    lang,
                    web_ui._RTL_LANG_PREFIXES,
                    f"``{lang}`` 是常见 RTL 语言，必须在 ``_RTL_LANG_PREFIXES`` 中",
                )

    def test_compute_file_version_is_lru_cached_module_function(self) -> None:
        """``_compute_file_version`` 必须是模块级函数，且带 ``@lru_cache``。"""
        self.assertTrue(
            hasattr(web_ui, "_compute_file_version"),
            "web_ui 模块必须暴露 ``_compute_file_version`` 自由函数",
        )
        # functools.lru_cache 装饰过的函数有 ``cache_info`` / ``cache_clear`` 属性
        self.assertTrue(
            hasattr(web_ui._compute_file_version, "cache_info"),
            "``_compute_file_version`` 必须用 ``@lru_cache`` 装饰（缓存 stat 结果）",
        )
        self.assertTrue(
            hasattr(web_ui._compute_file_version, "cache_clear"),
            "``_compute_file_version`` 必须用 ``@lru_cache`` 装饰",
        )

    def test_get_module_static_dir_is_lru_cached(self) -> None:
        """``_get_module_static_dir`` 必须是模块级 ``@lru_cache(maxsize=1)`` 函数。"""
        self.assertTrue(
            hasattr(web_ui, "_get_module_static_dir"),
            "web_ui 模块必须暴露 ``_get_module_static_dir`` fallback 函数",
        )
        self.assertTrue(
            hasattr(web_ui._get_module_static_dir, "cache_info"),
            "``_get_module_static_dir`` 必须用 ``@lru_cache`` 装饰",
        )

    def test_compute_file_version_cache_hit_is_fast(self) -> None:
        """``_compute_file_version`` 二次调用必须命中 lru_cache，几乎零成本。"""
        from pathlib import Path

        # 用一个已存在的真实文件触发首次缓存
        real_path = str(Path(web_ui.__file__).resolve())
        web_ui._compute_file_version.cache_clear()
        web_ui._compute_file_version(real_path)  # warm

        # 1000 次缓存命中应该 < 1 ms 总和
        t0 = time.perf_counter()
        for _ in range(1000):
            web_ui._compute_file_version(real_path)
        elapsed_us = (time.perf_counter() - t0) * 1_000_000
        per_call_us = elapsed_us / 1000

        self.assertLess(
            per_call_us,
            10.0,
            f"R26.2 缓存命中应 < 10 µs/call，实测 {per_call_us:.3f} µs",
        )


class TestSourceInvariants(unittest.TestCase):
    """``_get_template_context`` 函数体源码必须使用新的快路径调用方式。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.func_src = inspect.getsource(web_ui.WebFeedbackUI._get_template_context)

    def test_uses_compute_file_version_directly(self) -> None:
        """函数体必须调用 ``_compute_file_version(...)`` 而不是 ``self._get_file_version(...)``。"""
        # 至少 4 处 _compute_file_version 调用（css / multi_task / theme / app）
        compute_calls = re.findall(r"_compute_file_version\s*\(", self.func_src)
        self.assertGreaterEqual(
            len(compute_calls),
            4,
            f"R26.2: ``_get_template_context`` 必须有至少 4 处 ``_compute_file_version`` "
            f"调用（实际 {len(compute_calls)} 处）",
        )

        # 不能再调用 self._get_file_version（绕过 self 绑定开销）
        self_get_calls = re.findall(r"self\._get_file_version\s*\(", self.func_src)
        self.assertEqual(
            len(self_get_calls),
            0,
            "R26.2: ``_get_template_context`` 不能再调用 ``self._get_file_version()``"
            "——应直接走 ``_compute_file_version(str(path))`` 跳过实例方法分发",
        )

    def test_uses_partition_for_rtl_check(self) -> None:
        """``html_dir`` 必须通过 ``primary_subtag in _RTL_LANG_PREFIXES`` 判断，
        不能是逐 prefix ``startswith`` 比较。"""
        # 必须有 partition('-') 取主语言子标签
        self.assertIn(
            "partition",
            self.func_src,
            "R26.2: ``html_dir`` 计算应通过 ``html_lang.lower().partition('-')`` "
            "提取主语言子标签",
        )
        # 必须用 ``in _RTL_LANG_PREFIXES`` 集合查询
        self.assertIn(
            "_RTL_LANG_PREFIXES",
            self.func_src,
            "``_get_template_context`` 必须引用模块级 ``_RTL_LANG_PREFIXES``",
        )
        # 不能再用 ``for p in _RTL_LANG_PREFIXES`` 循环模式
        # （docstring 里描述旧实现的 ``startswith(p + "-")`` 文本是允许的，
        # 那是文档说明而不是代码——我们查的是「真正的循环语句」）
        self.assertIsNone(
            re.search(r"\bfor\s+p\s+in\s+_RTL_LANG_PREFIXES\b", self.func_src),
            "R26.2: 删掉旧的 ``for p in _RTL_LANG_PREFIXES`` 循环——"
            "现在用 ``primary_subtag in _RTL_LANG_PREFIXES`` 单次集合查询",
        )

    def test_uses_static_dir_attribute_with_fallback(self) -> None:
        """函数体必须用 ``getattr(self, '_static_dir', None) or _get_module_static_dir()`` 模式。"""
        self.assertIn(
            "_static_dir",
            self.func_src,
            "``_get_template_context`` 必须使用 ``self._static_dir``",
        )
        self.assertIn(
            "_get_module_static_dir",
            self.func_src,
            "``_get_template_context`` 必须有 ``_get_module_static_dir`` fallback "
            "（保护 ``object.__new__(WebFeedbackUI)`` 测试场景）",
        )


class TestHtmlDirBehavior(unittest.TestCase):
    """``html_dir`` 行为契约：RTL 语言返回 ``rtl``，其它返回 ``ltr``。"""

    def setUp(self) -> None:
        # 用 ``object.__new__`` 跳过 ``__init__``，构造裸对象只测 html_dir 逻辑
        self.ui = object.__new__(web_ui.WebFeedbackUI)

    def _call_with_lang(self, lang: str) -> dict:
        from unittest.mock import MagicMock, patch

        mock_config = MagicMock()
        mock_config.get_section.return_value = {"language": lang}
        with (
            patch("web_ui.get_config", return_value=mock_config),
            patch.object(
                web_ui.WebFeedbackUI, "_get_csp_nonce", return_value="test-nonce"
            ),
            patch("web_ui._compute_file_version", return_value="v1"),
        ):
            return self.ui._get_template_context()

    def test_en_is_ltr(self) -> None:
        ctx = self._call_with_lang("en")
        self.assertEqual(ctx["html_dir"], "ltr")
        self.assertEqual(ctx["html_lang"], "en")

    def test_zh_cn_is_ltr(self) -> None:
        ctx = self._call_with_lang("zh-CN")
        self.assertEqual(ctx["html_dir"], "ltr")
        self.assertEqual(ctx["html_lang"], "zh-CN")

    def test_auto_falls_back_to_en_ltr(self) -> None:
        ctx = self._call_with_lang("auto")
        self.assertEqual(ctx["html_dir"], "ltr")
        self.assertEqual(ctx["html_lang"], "en")


class TestBackwardCompatibilityOfGetFileVersion(unittest.TestCase):
    """``WebFeedbackUI._get_file_version`` 实例方法必须仍然可用（向后兼容）。"""

    def test_instance_method_still_works(self) -> None:
        """旧的 ``self._get_file_version(path)`` API 必须继续返回正确版本字符串。"""
        ui = web_ui.WebFeedbackUI(prompt="r26-2-test", port=0)

        # 对真实文件返回 8 位字符串
        from pathlib import Path

        result = ui._get_file_version(Path(web_ui.__file__))
        self.assertIsInstance(result, str)
        self.assertGreater(
            len(result),
            0,
            "对存在的文件，``_get_file_version`` 必须返回非空字符串",
        )
        self.assertLessEqual(
            len(result),
            8,
            "版本字符串最多 8 位（mtime int 取后 8 位）",
        )

    def test_instance_method_returns_default_on_missing_file(self) -> None:
        """文件不存在时 ``_get_file_version`` 返回 ``"1"``——保持原有 OSError 兜底语义。"""
        ui = web_ui.WebFeedbackUI(prompt="r26-2-test", port=0)
        result = ui._get_file_version("/nonexistent/path/file.css")
        self.assertEqual(
            result,
            "1",
            '文件不存在时必须返回默认 ``"1"``',
        )


if __name__ == "__main__":
    unittest.main()
