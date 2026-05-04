"""interactive_feedback MCP 工具 annotations 契约测试。

目标
----
锁定 `mcp.list_tools()` 协议输出中包含 `ToolAnnotations`，
让 client (ChatGPT / Claude Desktop / Cursor) 能正确识别工具语义：
- 不是破坏性操作（不弹"危险操作"二次确认）
- 不是只读操作（client 知道会有副作用）
- 涉及外部交互（与人和通知服务交互）

防止后续重构误删 annotations，导致 client 退回到「默认按破坏性处理」的体验。
"""

from __future__ import annotations

import asyncio
import unittest

from mcp.types import Tool, ToolAnnotations

import server


def _resolved_tool() -> Tool:
    """获取 interactive_feedback tool 并 narrow 类型，让 ty 通过。"""
    tools = asyncio.run(server.mcp.list_tools())
    tool = next((t for t in tools if t.name == "interactive_feedback"), None)
    assert tool is not None, "interactive_feedback 未在 MCP 工具列表中暴露"
    return tool


def _resolved_annotations() -> ToolAnnotations:
    """获取并 narrow ToolAnnotations，让后续断言能稳定访问 hint 字段。"""
    tool = _resolved_tool()
    ann = tool.annotations
    assert ann is not None, "annotations 缺失，client 会退回默认 destructive 处理"
    return ann


class TestInteractiveFeedbackAnnotations(unittest.TestCase):
    """验证 ToolAnnotations 已通过 MCP 协议层正确暴露。"""

    def test_tool_is_registered(self) -> None:
        """interactive_feedback 必须在 MCP 工具列表中可见。"""
        # _resolved_tool 内部已 assert，会抛 AssertionError 引导失败定位
        self.assertIsNotNone(_resolved_tool())

    def test_annotations_attached(self) -> None:
        """annotations 字段不能为 None —— 否则 client 退回默认严格模式。"""
        self.assertIsNotNone(_resolved_annotations())

    def test_title_is_human_friendly(self) -> None:
        """title 用于 client UI 显示，应该是人类可读的中文标题。"""
        ann = _resolved_annotations()
        title = ann.title
        assert isinstance(title, str), "annotations.title 缺失或非字符串"
        self.assertIn("反馈", title, f"title 应当体现「反馈」语义，实际: {title!r}")

    def test_not_destructive(self) -> None:
        """interactive_feedback 不删除/覆盖任何资源，必须 destructiveHint=False。

        如果误标 True，ChatGPT 等会每次弹"危险操作"对话框，体验很差。
        """
        ann = _resolved_annotations()
        self.assertIs(
            ann.destructiveHint,
            False,
            "interactive_feedback 不会破坏数据，destructiveHint 必须显式 False",
        )

    def test_not_idempotent(self) -> None:
        """每次调用产生新任务事件，明确非幂等。"""
        ann = _resolved_annotations()
        self.assertIs(
            ann.idempotentHint,
            False,
            "每次调用都会创建新任务事件，必须显式 idempotentHint=False",
        )

    def test_not_read_only(self) -> None:
        """会持久化任务到磁盘并触发通知，不是只读。

        显式 False 比让 client 猜更安全：避免 client 误以为「无副作用」
        而在某些场景下跳过审计。
        """
        ann = _resolved_annotations()
        self.assertIs(
            ann.readOnlyHint,
            False,
            "会写 task queue + 发通知，readOnlyHint 必须显式 False",
        )

    def test_open_world(self) -> None:
        """与外部用户和通知服务交互，是开放世界工具。"""
        ann = _resolved_annotations()
        self.assertIs(
            ann.openWorldHint,
            True,
            "工具与外部用户/通知服务交互，必须 openWorldHint=True",
        )


class TestAnnotationsRoundTripViaProtocol(unittest.TestCase):
    """端到端：通过 MCP 协议公共 API 获取 annotations，模拟 client 视角。"""

    def test_mcp_protocol_exposes_annotations(self) -> None:
        """模拟 client 调用 list_tools 协议，能拿到完整 annotations 对象。

        防止「内部数据有，但协议层丢失」的回归。
        """
        ann = _resolved_annotations()
        self.assertEqual(ann.title, "Interactive Feedback (人机协作反馈)")
        self.assertFalse(ann.readOnlyHint)
        self.assertFalse(ann.destructiveHint)
        self.assertFalse(ann.idempotentHint)
        self.assertTrue(ann.openWorldHint)

    def test_get_tool_also_exposes_annotations(self) -> None:
        """`mcp.get_tool('name')` 路径同样要暴露 annotations，覆盖另一个公共 API。"""
        tool = asyncio.run(server.mcp.get_tool("interactive_feedback"))
        assert tool is not None, "get_tool 必须能拿到 interactive_feedback"
        ann = tool.annotations
        assert ann is not None, "get_tool 路径下 annotations 不能丢"
        self.assertFalse(ann.destructiveHint)


if __name__ == "__main__":
    unittest.main()
