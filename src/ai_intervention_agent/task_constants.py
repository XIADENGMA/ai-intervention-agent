"""Task-related constants that are safe for Web UI cold-start imports."""

from __future__ import annotations

PLACEHOLDER_MAX_LENGTH: int = 200
"""Maximum textarea placeholder length accepted for a feedback task."""


LOOP_ID_MAX_LENGTH: int = 64
"""Maximum accepted length for ``loop_id`` (agent-chosen stable loop key)."""

LOOP_TEXT_MAX_LENGTH: int = 500
"""Maximum accepted length for ``loop_objective`` / ``success_criteria``."""

LOOP_LABEL_MAX_LENGTH: int = 32
"""Maximum accepted length for ``loop_phase`` / ``iteration_label``."""


LOOP_HISTORY_MAX_LOOPS: int = 20
"""Maximum distinct loops kept in the ledger (stalest-updated evicted)."""

LOOP_HISTORY_MAX_ROUNDS: int = 50
"""Maximum completed rounds kept per loop (oldest rounds dropped)."""

LOOP_VERDICT_MAX_LENGTH: int = 200
"""Maximum length of the user-verdict text stored per ledger round."""
