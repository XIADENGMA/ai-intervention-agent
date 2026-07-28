"""Lightweight feedback payload types for Web UI hot paths."""

from __future__ import annotations

from typing import TypedDict


class FeedbackImage(TypedDict, total=False):
    """Single image block returned by the Web UI / MCP feedback flow."""

    data: str
    filename: str
    size: int
    content_type: str
    mimeType: str
    mime_type: str


class FeedbackResult(TypedDict):
    """Feedback result structure returned by ``/api/feedback``."""

    user_input: str
    selected_options: list[str]
    images: list[FeedbackImage]
