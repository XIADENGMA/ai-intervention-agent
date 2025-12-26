"""
共享类型定义（TypedDict）

目的：
- 让 `ty` 在跨模块（server/web_ui/task_queue/tests）分析时拥有一致的结构化类型
- 避免在多个文件中重复声明相同的字典结构

说明：
- 这些类型仅用于类型检查/IDE 提示，不影响运行时行为
"""

from typing import TypedDict


class FeedbackImage(TypedDict, total=False):
    """单张图片的结构（Web UI / MCP 交互中使用）"""

    # 纯 base64 数据（可能是 data URI，也可能是纯 base64）
    data: str

    # 可选元信息（字段名在不同链路里可能不同，这里都兼容）
    filename: str
    size: int
    content_type: str
    mimeType: str
    mime_type: str


class FeedbackResult(TypedDict):
    """Web UI 反馈结果结构（与 /api/feedback 返回一致）"""

    user_input: str
    selected_options: list[str]
    images: list[FeedbackImage]
