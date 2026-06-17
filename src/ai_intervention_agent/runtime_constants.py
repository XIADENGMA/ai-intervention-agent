"""Runtime constants that must be cheap to import.

Keep these values outside ``server_config`` because ``server_config`` defines
Pydantic models and MCP response helpers. Web UI startup paths need the numeric
contracts only, and importing Pydantic for constants alone costs measurable cold
start time.
"""

from __future__ import annotations

FEEDBACK_TIMEOUT_DEFAULT = 600
"""Default backend maximum wait time in seconds."""

FEEDBACK_TIMEOUT_MIN = 10
"""Minimum backend wait time in seconds."""

FEEDBACK_TIMEOUT_MAX = 7200
"""Maximum backend wait time in seconds."""

AUTO_RESUBMIT_TIMEOUT_DEFAULT = 240
"""Default frontend auto-resubmit countdown in seconds."""

AUTO_RESUBMIT_TIMEOUT_MIN = 10
"""Minimum non-zero frontend auto-resubmit countdown in seconds."""

AUTO_RESUBMIT_TIMEOUT_MAX = 3600
"""Maximum frontend auto-resubmit countdown in seconds."""

BACKEND_BUFFER = 40
"""Backend buffer seconds added beyond the frontend countdown."""

BACKEND_MIN = 260
"""Backend minimum wait time in seconds."""
