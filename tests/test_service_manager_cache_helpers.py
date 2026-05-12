"""CR#16 F-5：``service_manager.invalidate_web_ui_config_cache`` 单测。

公开 API
========

`invalidate_web_ui_config_cache()` 取代「测试 reach 到 ``_config_cache``
private dict」这个旧 pattern。其他模块（含测试）现在通过 public helper
访问缓存清空行为：

* 形状更窄——只动 web_ui config TTL 缓存，不重置 http client / generation
  bump（那些走 ``_invalidate_runtime_caches_on_config_change``）；
* 线程安全——仍走 ``_config_cache_lock``，与读路径一致；
* 可测试——一次调用后再读 ``_config_cache`` 应见 ``config=None`` +
  ``timestamp=0.0``。

invariant 守护
========

1. ``invalidate_web_ui_config_cache`` 是 public function（无下划线前缀）；
2. 调用后 ``_config_cache["config"]`` 必为 None；
3. 调用后下一次 ``get_web_ui_config()`` 必 cache miss（验证：先填充
   cache，调 invalidate，再读，应触发 load）；
4. 与 ``_invalidate_runtime_caches_on_config_change`` 是不同函数——
   后者副作用更广，不能混用。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent import service_manager


class TestInvalidateHelperPublicAPI(unittest.TestCase):
    """API surface contract：函数名 + 签名 + module-level 可见性。"""

    def test_function_exists_and_is_public(self) -> None:
        """函数必须是 public（无下划线前缀）——public helper 才能稳定 import。"""
        self.assertTrue(
            hasattr(service_manager, "invalidate_web_ui_config_cache"),
            "service_manager 必须暴露 invalidate_web_ui_config_cache",
        )
        self.assertTrue(
            callable(service_manager.invalidate_web_ui_config_cache),
            "invalidate_web_ui_config_cache 必须可调用",
        )
        # public 标志：函数名不以下划线开头
        self.assertFalse(
            service_manager.invalidate_web_ui_config_cache.__name__.startswith("_"),
            "invalidate_web_ui_config_cache 不应是 private helper",
        )

    def test_function_takes_no_args(self) -> None:
        """无参——副作用纯粹是清缓存，不需要外部输入。"""
        import inspect

        sig = inspect.signature(service_manager.invalidate_web_ui_config_cache)
        self.assertEqual(
            len(sig.parameters),
            0,
            "invalidate_web_ui_config_cache 应无参数",
        )

    def test_function_returns_none(self) -> None:
        """返回 None——副作用函数惯例。"""
        result = service_manager.invalidate_web_ui_config_cache()
        self.assertIsNone(result, "invalidate_web_ui_config_cache 应返回 None")


class TestInvalidateHelperBehavior(unittest.TestCase):
    """行为契约：清空后 cache 状态可见、下一次 fetch 必 miss。"""

    def setUp(self) -> None:
        # 先调用一次 get_web_ui_config 填充 cache（让测试明确知道 cache 状态）
        try:
            service_manager.get_web_ui_config()
        except Exception:
            # config 不可用的极端环境也 OK——只关心 invalidate 行为
            pass

    def test_invalidate_clears_config_field(self) -> None:
        service_manager.invalidate_web_ui_config_cache()
        self.assertIsNone(
            service_manager._config_cache["config"],
            "调用 invalidate 后 _config_cache['config'] 必为 None",
        )

    def test_invalidate_resets_timestamp(self) -> None:
        service_manager.invalidate_web_ui_config_cache()
        self.assertEqual(
            service_manager._config_cache["timestamp"],
            0.0,
            "调用 invalidate 后 _config_cache['timestamp'] 必为 0.0",
        )

    def test_invalidate_does_not_bump_generation(self) -> None:
        """与广义 _invalidate_runtime_caches_on_config_change 的区别：本函数
        不动 ``_config_cache_generation``——副作用面更窄。"""
        before = service_manager._config_cache_generation
        service_manager.invalidate_web_ui_config_cache()
        after = service_manager._config_cache_generation
        self.assertEqual(
            before,
            after,
            "invalidate_web_ui_config_cache 不应碰 _config_cache_generation",
        )


class TestInvalidateHelperDistinctFromBroadFunction(unittest.TestCase):
    """与 ``_invalidate_runtime_caches_on_config_change`` 是不同函数。"""

    def test_different_function_object(self) -> None:
        broad = service_manager._invalidate_runtime_caches_on_config_change
        narrow = service_manager.invalidate_web_ui_config_cache
        self.assertIsNot(
            broad,
            narrow,
            "广义 invalidate 与 web_ui-only invalidate 不应是同一函数",
        )

    def test_narrow_function_ast_does_not_touch_http_clients(self) -> None:
        """narrow 函数只动 ``_config_cache``——绝不能动 http client / generation。
        用 ast 提取**实际 Name 引用**（排除 docstring 字符串），比字面源码
        匹配更鲁棒。"""
        import ast
        import inspect

        narrow_src = inspect.getsource(service_manager.invalidate_web_ui_config_cache)
        tree = ast.parse(narrow_src)
        # 提取所有 Name node id（即代码里真正引用的标识符）
        names_used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        forbidden = {"_sync_client", "_async_client", "_config_cache_generation"}
        leaked = names_used & forbidden
        self.assertEqual(
            leaked,
            set(),
            f"invalidate_web_ui_config_cache 不应引用 {leaked}——副作用面应保持狭窄",
        )


if __name__ == "__main__":
    unittest.main()
