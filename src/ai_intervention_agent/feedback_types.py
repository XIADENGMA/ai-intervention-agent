"""Lightweight feedback payload types for Web UI hot paths.

``shared_types`` also exports these shapes for backward compatibility, but it
defines the Pydantic configuration models too. Importing it from ``web_ui`` would
pull Pydantic and the full config model graph into the cold-start path just to
name a ``TypedDict``. Keep these runtime-dict contracts in a tiny module so the
Web UI can start without paying that cost.
"""

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
