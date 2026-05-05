"""R20.9 ``server_config._lazy_mcp_types`` 行为锁定测试

背景
----
``mcp.types`` 单独 import 约 ~184 ms。Web UI 子进程通过
``task_queue → server_config`` 间接拖入 mcp.types 是 R20.8 优化后剩余
的最大启动开销。R20.9 把 ``server_config.py`` 中 ``from mcp.types
import ...`` 改成 ``TYPE_CHECKING`` gate + 单例 lazy loader，让
``mcp.types`` 仅在**首次**响应构建（``parse_structured_response`` /
``_process_image`` / ``_make_resubmit_response``）时才加载，
后续调用完全零开销。

实测：``import server_config`` 从 ~213 ms 降至 ~72 ms（-141 ms / -66%）。

本测试套件锁定 5 条不变量：

1. **解耦不变量**（fresh interpreter 子进程独立验证）
   - 加载 ``server_config`` 时**不**触发 ``mcp.types`` 加载
   - 加载 ``task_queue`` 时**不**触发 ``mcp.types`` 加载
   - 第一次调用 ``parse_structured_response`` 后 ``mcp.types`` 必须已加载

2. **lazy loader 缓存正确性**
   - 多次调用 ``_lazy_mcp_types()`` 返回同一对象（单例）
   - 缓存对象拥有 ``TextContent`` / ``ImageContent`` / ``ContentBlock`` 属性

3. **运行时行为零回归**
   - ``parse_structured_response`` 输出与 R20.9 前完全一致
   - ``_make_resubmit_response(as_mcp=True)`` 返回 list of TextContent
   - ``_process_image`` 返回 (ImageContent, str)

4. **源文本不变量**
   - ``server_config.py`` 必须**不**含模块顶层 ``from mcp.types import``
   - ``server_config.py`` 必须包含 ``from __future__ import annotations``
   - ``server_config.py`` 必须保留 ``_lazy_mcp_types`` 函数定义

5. **类型注解兼容**
   - ``parse_structured_response`` 的 ``__annotations__`` 仍能解析（字符串
     形式但可访问）——确保 IDE / mypy 不被打破
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════════════
# 1. 解耦不变量：使用全新子进程独立验证
# ═══════════════════════════════════════════════════════════════════════════
class TestImportDecoupling(unittest.TestCase):
    """fresh interpreter 中 server_config / task_queue 不应触发 mcp.types 加载"""

    def _run_in_subprocess(self, code: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return result.stdout.strip()

    def test_loading_server_config_does_not_load_mcp_types(self) -> None:
        out = self._run_in_subprocess(
            "import sys\n"
            "import server_config  # noqa: F401\n"
            "print('LOADED' if 'mcp.types' in sys.modules else 'NOT_LOADED')\n"
        )
        last = out.splitlines()[-1] if out else ""
        self.assertEqual(
            last,
            "NOT_LOADED",
            "import server_config 不应触发 mcp.types 加载（R20.9 lazy 化的全部价值）",
        )

    def test_loading_task_queue_does_not_load_mcp_types(self) -> None:
        out = self._run_in_subprocess(
            "import sys\n"
            "import task_queue  # noqa: F401\n"
            "print('LOADED' if 'mcp.types' in sys.modules else 'NOT_LOADED')\n"
        )
        last = out.splitlines()[-1] if out else ""
        self.assertEqual(
            last,
            "NOT_LOADED",
            "import task_queue 不应触发 mcp.types 加载——这是 web_ui 子进程"
            "启动延迟节省的核心",
        )

    def test_first_call_to_parse_response_does_load_mcp_types(self) -> None:
        """lazy load 必须真的发生：调用 parse_structured_response 后 mcp.types 进入 sys.modules"""
        out = self._run_in_subprocess(
            "import sys\n"
            "import server_config\n"
            "before = 'mcp.types' in sys.modules\n"
            "result = server_config.parse_structured_response("
            "{'user_input': 'hi', 'selected_options': ['x']})\n"
            "after = 'mcp.types' in sys.modules\n"
            "print(f'BEFORE={before} AFTER={after} ITEMS={len(result)}')\n"
        )
        last = out.splitlines()[-1] if out else ""
        self.assertEqual(
            last,
            "BEFORE=False AFTER=True ITEMS=1",
            f"调用 parse_structured_response 后 mcp.types 必须被加载，且返回 1 个 item，实际：{out!r}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 2. Lazy loader 缓存正确性
# ═══════════════════════════════════════════════════════════════════════════
class TestLazyLoaderCache(unittest.TestCase):
    def test_repeated_calls_return_same_object(self) -> None:
        from server_config import _lazy_mcp_types

        a = _lazy_mcp_types()
        b = _lazy_mcp_types()
        c = _lazy_mcp_types()
        self.assertIs(a, b, "lazy loader 必须缓存为单例")
        self.assertIs(b, c)

    def test_returned_module_has_required_attributes(self) -> None:
        from server_config import _lazy_mcp_types

        types_mod = _lazy_mcp_types()
        for attr_name in ("TextContent", "ImageContent", "ContentBlock"):
            self.assertTrue(
                hasattr(types_mod, attr_name),
                f"_lazy_mcp_types() 返回的模块缺少 {attr_name}—— "
                f"上游 mcp 库可能改了 API",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 3. 运行时行为零回归
# ═══════════════════════════════════════════════════════════════════════════
class TestRuntimeBehaviorParity(unittest.TestCase):
    def test_parse_structured_response_returns_list_with_text_content(self) -> None:
        from server_config import _lazy_mcp_types, parse_structured_response

        result = parse_structured_response(
            {"user_input": "hello", "selected_options": ["A", "B"]}
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1, "纯文本输入应只产 1 个 TextContent")
        text_cls = _lazy_mcp_types().TextContent
        self.assertIsInstance(result[0], text_cls)
        self.assertEqual(result[0].type, "text")
        self.assertIn("hello", result[0].text)
        self.assertIn("A", result[0].text)

    def test_make_resubmit_response_as_mcp_returns_list_of_textcontent(self) -> None:
        from server_config import _lazy_mcp_types, _make_resubmit_response

        result = _make_resubmit_response(as_mcp=True)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        text_cls = _lazy_mcp_types().TextContent
        self.assertIsInstance(result[0], text_cls)

    def test_make_resubmit_response_as_dict_returns_plain_dict(self) -> None:
        from server_config import _make_resubmit_response

        result = _make_resubmit_response(as_mcp=False)
        self.assertIsInstance(result, dict)
        self.assertIn("text", result)


# ═══════════════════════════════════════════════════════════════════════════
# 4. 源文本不变量
# ═══════════════════════════════════════════════════════════════════════════
class TestSourceTextInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = (PROJECT_ROOT / "server_config.py").read_text(encoding="utf-8")

    def test_no_module_level_mcp_types_import(self) -> None:
        """source-text 层禁止把 mcp.types 拖回模块顶部 eager import"""
        for forbidden in (
            "\nfrom mcp.types import",
            "\nimport mcp.types",
        ):
            self.assertNotIn(
                forbidden,
                self.src,
                f"server_config.py 不允许 {forbidden!r}—— 这会破坏 R20.9 lazy 化",
            )

    def test_has_future_annotations(self) -> None:
        """PEP 563 是 lazy 化的前提（让类型注解延迟求值）"""
        self.assertIn(
            "from __future__ import annotations",
            self.src,
            "server_config.py 必须开启 PEP 563（注解延迟求值），"
            "否则 list[ContentBlock] 等注解会在 import 时尝试解析名字而失败",
        )

    def test_has_type_checking_gated_import(self) -> None:
        """TYPE_CHECKING 块下的 mcp.types import 是给类型检查器看的"""
        self.assertIn("if TYPE_CHECKING:", self.src)
        # 确认有 mcp.types 的 TYPE_CHECKING import（多空格容忍）
        self.assertTrue(
            "from mcp.types import" in self.src,
            "server_config.py 必须保留 TYPE_CHECKING 块下的 mcp.types import"
            "（供 mypy / IDE 解析签名）",
        )

    def test_lazy_loader_function_exists(self) -> None:
        self.assertIn("def _lazy_mcp_types(", self.src)
        self.assertIn("_mcp_types_module", self.src)


# ═══════════════════════════════════════════════════════════════════════════
# 5. 类型注解兼容（PEP 563 字符串形式仍可访问）
# ═══════════════════════════════════════════════════════════════════════════
class TestAnnotationCompatibility(unittest.TestCase):
    def test_annotations_are_strings_after_pep563(self) -> None:
        """PEP 563 后所有注解都应该是字符串形式"""
        from server_config import parse_structured_response

        annotations = parse_structured_response.__annotations__
        self.assertIn("return", annotations)
        return_ann = annotations["return"]
        self.assertIsInstance(
            return_ann,
            str,
            "PEP 563 启用后函数注解必须是字符串形式（延迟求值）",
        )
        self.assertIn("ContentBlock", return_ann)


if __name__ == "__main__":
    unittest.main()
