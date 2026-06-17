# feedback_types

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/feedback_types.md`](../api/feedback_types.md)

Lightweight feedback payload types for Web UI hot paths.

``shared_types`` also exports these shapes for backward compatibility, but it
defines the Pydantic configuration models too. Importing it from ``web_ui`` would
pull Pydantic and the full config model graph into the cold-start path just to
name a ``TypedDict``. Keep these runtime-dict contracts in a tiny module so the
Web UI can start without paying that cost.

## 类

### `class FeedbackImage`

Single image block returned by the Web UI / MCP feedback flow.

### `class FeedbackResult`

Feedback result structure returned by ``/api/feedback``.
