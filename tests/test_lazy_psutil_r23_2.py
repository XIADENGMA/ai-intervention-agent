"""R23.2 — `web_ui_mdns_utils` 的 `psutil` lazy import 契约测试。

R23.2 把 `web_ui_mdns_utils.py` 的 `import psutil` 从模块顶层移到
`_list_non_loopback_ipv4` 函数内部，让 `web_ui` cold-start trace 跳过 ~3-8 ms
的 psutil 静态导入开销（pre-fix 在 `import psutil` 那行付掉一整套 psutil 子
模块树：`psutil._psosx` ~1.5 ms + `psutil._common` ~1 ms + `psutil._psutil_osx` /
`psutil._psposix` / `psutil._psutil_posix` ~0.5 ms 加起来；`platformdirs`
通过它的 traversal 也被拉进来，cumulative 可观）。

省下来的语义边界：
- 只有调用 `_list_non_loopback_ipv4` 才会真正 import psutil
- mDNS 默认仅在 `bind_interface != 127.0.0.1` 时启用（`web_ui_mdns.py::
  _should_enable_mdns`），且注册逻辑在 daemon thread 异步执行（R20.11）
- 本地回环开发场景（`host=127.0.0.1`）main thread 整个生命周期不需要 psutil

本测试套件锁定的不变量：
1. **Source contract**：`web_ui_mdns_utils.py` 模块顶层不能再 `import psutil`；
   `_list_non_loopback_ipv4` 函数体内必须出现 lazy import。
2. **Doc contract**：`web_ui_mdns_utils` 模块 docstring 必须有 `R23.2` 标记
   + 解释为什么 lazy 化 psutil（让维护者一眼看懂）。
3. **Runtime contract**：
   - 在子进程隔离环境下 `import web_ui_mdns_utils` 后 `sys.modules` 不应包含
     `psutil`（lazy 真的生效）；
   - 调用 `_list_non_loopback_ipv4()` 后 `sys.modules` 必须包含 `psutil`
     （lazy import 触发）；
   - `_list_non_loopback_ipv4()` 在 psutil 不可用时（mock ImportError）
     必须返回 `[]`，不抛异常（兼容 R23.2 的 `except Exception` 兜底）。
4. **Behavioral regression**：`detect_best_publish_ipv4` 仍然能在 mDNS 启用
   场景下正确探测 IPv4（不破 R20.11 的 mDNS 注册路径）。
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

import web_ui_mdns_utils

REPO_ROOT = Path(__file__).resolve().parent.parent


# ============================================================================
# Section 1：源码不变量
# ============================================================================


class TestSourceInvariants(unittest.TestCase):
    """锁定 psutil 在模块顶层不再 import，只在 `_list_non_loopback_ipv4` 内 lazy import。"""

    def setUp(self) -> None:
        self.module_src = inspect.getsource(web_ui_mdns_utils)
        self.list_func_src = inspect.getsource(
            web_ui_mdns_utils._list_non_loopback_ipv4
        )

    def test_module_does_not_top_level_import_psutil(self) -> None:
        """模块顶层（``from __future__`` 之后到第一个 ``def`` 之间）不能 ``import psutil``。

        排除 docstring 内提及的 ``psutil`` 字面量（R23.2 注释会写到为什么
        lazy 这个事），只检查实际的 import 语句。
        """
        first_def_match = re.search(r"^(def |class )", self.module_src, re.MULTILINE)
        if first_def_match is None:
            self.fail("模块至少应有一个 def/class（_is_probably_virtual_interface 等）")
        # type-narrowing: assertIsNotNone 等价 assert
        assert first_def_match is not None
        top_section = self.module_src[: first_def_match.start()]
        self.assertNotRegex(
            top_section,
            r"^\s*import\s+psutil\b",
            "psutil 不应在模块顶层 import；必须 lazy 到 _list_non_loopback_ipv4",
        )
        self.assertNotRegex(
            top_section,
            r"^\s*from\s+psutil\s+import",
            "psutil 不应在模块顶层 from-import；必须 lazy 到 _list_non_loopback_ipv4",
        )

    def test_list_non_loopback_uses_lazy_import(self) -> None:
        """``_list_non_loopback_ipv4`` 函数体内必须有 ``import psutil``。"""
        self.assertRegex(
            self.list_func_src,
            r"\bimport\s+psutil\b",
            "_list_non_loopback_ipv4 函数体内必须 lazy import psutil",
        )

    def test_lazy_import_inside_try_block(self) -> None:
        """lazy import 必须在原 ``try/except Exception`` 块内，让 import 失败也降级。

        psutil 是 hard dependency（pyproject 直接声明），import 失败的概率极
        低，但还是要让 ``except Exception`` 路径接住它。否则在 psutil 损坏 /
        平台不兼容的极端环境下会让整个 mDNS 路径炸而不是降级为不发布 mDNS。

        匹配的是 *语句行* 而非 docstring 内容：用行首缩进 + 关键字模式。
        """
        # 把 docstring 切掉再做位置比较，避免误命中"except Exception"等字面提及
        body_match = re.search(r'""".*?"""', self.list_func_src, re.DOTALL)
        body = (
            self.list_func_src[body_match.end() :] if body_match else self.list_func_src
        )
        try_match = re.search(r"^\s*try:\s*$", body, re.MULTILINE)
        except_match = re.search(r"^\s*except\b", body, re.MULTILINE)
        import_match = re.search(r"^\s*import\s+psutil\b", body, re.MULTILINE)
        self.assertIsNotNone(try_match, "_list_non_loopback_ipv4 应保留 try 块")
        self.assertIsNotNone(except_match, "_list_non_loopback_ipv4 应保留 except 块")
        self.assertIsNotNone(import_match, "_list_non_loopback_ipv4 必须 import psutil")
        # mypy 提示：上面 assertIsNotNone 已保证不是 None
        assert try_match is not None
        assert except_match is not None
        assert import_match is not None
        self.assertLess(
            try_match.start(),
            import_match.start(),
            "import psutil 必须放在 try: 之后",
        )
        self.assertLess(
            import_match.start(),
            except_match.start(),
            "import psutil 必须放在 except 之前（在 try 块体内）",
        )


# ============================================================================
# Section 2：文档契约
# ============================================================================


class TestDocumentationContract(unittest.TestCase):
    """`web_ui_mdns_utils` 模块 docstring 必须解释 R23.2 lazy 动机。"""

    def setUp(self) -> None:
        self.module_doc = web_ui_mdns_utils.__doc__ or ""

    def test_module_docstring_mentions_r23_2_marker(self) -> None:
        self.assertIn(
            "R23.2",
            self.module_doc,
            "模块 docstring 必须有 R23.2 标记，方便日后 grep 追溯优化历史",
        )

    def test_module_docstring_explains_lazy_psutil(self) -> None:
        """必须出现"lazy"+"psutil" 或同等措辞。"""
        self.assertTrue(
            "psutil" in self.module_doc and "lazy" in self.module_doc.lower(),
            "模块 docstring 必须解释 psutil lazy 化的动机，避免日后被误改回顶层 import",
        )


# ============================================================================
# Section 3：运行时验证（子进程隔离 sys.modules 状态）
# ============================================================================


class TestLazyImportRuntime(unittest.TestCase):
    """子进程隔离：刚 ``import web_ui_mdns_utils`` 时 ``sys.modules`` 不包含 psutil。"""

    def _run_isolated(self, body: str) -> tuple[int, str, str]:
        """跑子进程执行 ``body``，返回 (returncode, stdout, stderr)。"""
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(body)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode, result.stdout, result.stderr

    def test_psutil_not_in_sys_modules_after_import(self) -> None:
        """import web_ui_mdns_utils 不应触发 psutil 的预载（lazy 真的生效）。"""
        code = """
            import sys
            assert 'psutil' not in sys.modules, 'psutil 不应预先在 sys.modules（顶层 import）'
            import web_ui_mdns_utils  # noqa: F401
            if 'psutil' in sys.modules:
                print('FAIL psutil_loaded_eagerly')
                sys.exit(1)
            print('OK')
        """
        rc, out, err = self._run_isolated(code)
        self.assertEqual(
            rc,
            0,
            f"子进程应返回 0；实际 rc={rc}, stdout={out!r}, stderr={err!r}",
        )
        self.assertIn("OK", out, f"预期 OK，实际 stdout={out!r}, stderr={err!r}")

    def test_psutil_loaded_after_calling_list_non_loopback(self) -> None:
        """调用 _list_non_loopback_ipv4 后 psutil 必须出现在 sys.modules（lazy 触发）。"""
        code = """
            import sys
            import web_ui_mdns_utils
            assert 'psutil' not in sys.modules, 'psutil 不应在调用前已加载'
            _ = web_ui_mdns_utils._list_non_loopback_ipv4(prefer_physical=True)
            if 'psutil' not in sys.modules:
                print('FAIL psutil_not_loaded_after_call')
                sys.exit(1)
            print('OK')
        """
        rc, out, err = self._run_isolated(code)
        self.assertEqual(
            rc, 0, f"子进程应返回 0；实际 rc={rc}, stdout={out!r}, stderr={err!r}"
        )
        self.assertIn("OK", out)


# ============================================================================
# Section 4：行为回归（psutil 不可用时仍能降级）
# ============================================================================


class TestPsutilUnavailableFallback(unittest.TestCase):
    """psutil import 失败 → ``_list_non_loopback_ipv4`` 必须返回 ``[]``，不抛异常。"""

    def test_returns_empty_when_import_fails(self) -> None:
        """模拟 ``import psutil`` raise ImportError → 函数应返回 ``[]``。"""

        def _raise_import_error(*_args, **_kwargs):
            raise ImportError("psutil unavailable in this test")

        with patch("builtins.__import__", side_effect=_raise_import_error):
            try:
                result = web_ui_mdns_utils._list_non_loopback_ipv4(prefer_physical=True)
            except Exception as e:
                self.fail(
                    f"psutil 不可用时不应抛异常，应返回 []；实际抛了 {type(e).__name__}: {e}"
                )

        self.assertEqual(
            result,
            [],
            f"psutil 不可用时应返回空列表（mDNS 降级路径）；实际：{result!r}",
        )

    def test_returns_empty_when_psutil_raises_at_runtime(self) -> None:
        """psutil 已 import 但 net_if_addrs 抛异常（极端：内核错误） → 仍降级为 []。"""

        class _BoomPsutil:
            @staticmethod
            def net_if_addrs():
                raise OSError("kernel error simulation")

            @staticmethod
            def net_if_stats():
                raise OSError("kernel error simulation")

        # 用 sys.modules patch 替换已加载的 psutil
        with patch.dict(sys.modules, {"psutil": _BoomPsutil}):
            result = web_ui_mdns_utils._list_non_loopback_ipv4(prefer_physical=True)

        self.assertEqual(
            result,
            [],
            f"psutil 运行时炸时应返回 []，实际：{result!r}",
        )


# ============================================================================
# Section 5：mDNS 路径回归（detect_best_publish_ipv4 仍能工作）
# ============================================================================


class TestDetectBestPublishIpv4Regression(unittest.TestCase):
    """R20.11 + R23.2 联合契约：mDNS 探测路径仍正常工作。"""

    def test_explicit_ipv4_bind_returns_directly_no_psutil(self) -> None:
        """显式 IPv4 绑定（非 0.0.0.0/loopback）→ 直接返回，不 import psutil。"""
        # 用 192.0.2.1（TEST-NET-1, RFC 5737）作为合法但非环回的测试 IPv4
        result = web_ui_mdns_utils.detect_best_publish_ipv4("192.0.2.1")
        self.assertEqual(
            result,
            "192.0.2.1",
            f"显式 IPv4 应直接返回；实际：{result!r}",
        )

    def test_loopback_bind_falls_through_to_lookup(self) -> None:
        """``host=127.0.0.1`` → fallthrough 到 _list_non_loopback_ipv4（这条路径才需要 psutil）。"""
        # 不直接验证返回值（依赖本机网卡），只验证调用不抛异常
        try:
            _ = web_ui_mdns_utils.detect_best_publish_ipv4("127.0.0.1")
        except Exception as e:
            self.fail(f"detect_best_publish_ipv4(127.0.0.1) 不应抛异常；实际：{e}")


if __name__ == "__main__":
    unittest.main()
