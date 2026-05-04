"""``/api/events`` SSE 端点的限流契约锁试。

历史背景：
- ``/api/events`` 长期没有 explicit limiter，走全局默认 ``60/min``。
- SSE 是长连接，但浏览器在网络抖动 / 用户频繁 reload 场景下会反复
  reconnect。``60/min`` 在调试时极易触顶 → SSE 退化为轮询 → 用户
  误判为"实时推送故障"。
- v1.5.x round-14 给 ``/api/events`` 显式标记 ``@limiter.limit
  ("300 per minute")``，与 ``/api/tasks`` 对齐。本测试用 AST 锁住这
  条 contract，避免未来某次重构把它改回 ``60/min`` 或被错误地标
  ``@limiter.exempt``（exempt 让滥用者无限建立连接消耗 server-side
  队列）。

实现：
- AST 解析 ``web_ui_routes/task.py``，找 ``def sse_events``
- 检查它的 decorator 列表里恰有一条 ``@self.limiter.limit("...")``，
  并断言文本是 ``300 per minute``
- 同时确保**没有** ``@self.limiter.exempt``（与 ``static.py`` 中的
  字体/CSS 等真静态资源路径区分开）
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _find_function_def(source_text: str, target_name: str) -> ast.FunctionDef | None:
    """在 source 里找指定名字的 ``def``（不区分嵌套层级，找第一个就返回）。"""
    tree = ast.parse(source_text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == target_name:
            return node
    return None


def _decorator_to_str(decorator: ast.expr) -> str:
    """把 decorator AST 还原成 source 字符串方便文本断言。"""
    return ast.unparse(decorator)


class TestSseEventsRateLimit(unittest.TestCase):
    """``/api/events`` 的限流不变量。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.task_routes_src = (REPO_ROOT / "web_ui_routes" / "task.py").read_text(
            encoding="utf-8"
        )

    def test_sse_events_function_exists(self) -> None:
        """``def sse_events`` 必须存在于 ``web_ui_routes/task.py``。"""
        node = _find_function_def(self.task_routes_src, "sse_events")
        self.assertIsNotNone(
            node,
            "`sse_events` 函数不存在了；如果 SSE 端点改名，请同步本测试",
        )

    def test_sse_events_has_explicit_limit(self) -> None:
        """``sse_events`` 必须显式标记 ``@self.limiter.limit("300 per minute")``。"""
        node = _find_function_def(self.task_routes_src, "sse_events")
        assert node is not None  # narrowing for ty
        decorator_strs = [_decorator_to_str(d) for d in node.decorator_list]

        limit_decorators = [s for s in decorator_strs if "limiter.limit" in s]
        self.assertEqual(
            len(limit_decorators),
            1,
            f"`sse_events` 必须有恰好 1 条 @self.limiter.limit(...) 装饰器；"
            f"实际装饰器列表: {decorator_strs}",
        )

        actual = limit_decorators[0]
        # 接受多种写法但必须包含 ``300 per minute``
        self.assertIn(
            "300 per minute",
            actual,
            f"SSE 限流必须是 300/min（与 /api/tasks 对齐，避免页面 reload "
            f"频繁导致 60/min 触顶 → SSE 误判为故障）；实际: {actual!r}",
        )

    def test_sse_events_is_not_exempt(self) -> None:
        """``sse_events`` 必须**不**带 ``@limiter.exempt``。

        ``exempt`` 让滥用者无限建立 SSE 连接消耗 server-side 队列；
        SSE 是长连接但仍应有数量级合理的速率上限。
        """
        node = _find_function_def(self.task_routes_src, "sse_events")
        assert node is not None  # narrowing for ty
        decorator_strs = [_decorator_to_str(d) for d in node.decorator_list]

        exempt_decorators = [s for s in decorator_strs if "limiter.exempt" in s]
        self.assertEqual(
            len(exempt_decorators),
            0,
            "`sse_events` 不应使用 @limiter.exempt（无限连接 = 潜在 DoS）；"
            f"实际装饰器列表: {decorator_strs}",
        )


if __name__ == "__main__":
    unittest.main()
