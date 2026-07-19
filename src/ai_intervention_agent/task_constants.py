"""Task-related constants that are safe for Web UI cold-start imports."""

from __future__ import annotations

PLACEHOLDER_MAX_LENGTH: int = 200
"""Maximum textarea placeholder length accepted for a feedback task."""

# ---------------------------------------------------------------------------
# Loop engineering (P1) — 长度上限常量
# ---------------------------------------------------------------------------
# 5 个 loop_* 字段全部是可选自由文本；上限只做防滥用 clamp（超长静默截断，
# 与 feedback_placeholder / header_label 同一处理模式），不做格式校验——
# loop_id 是 agent 自定义的稳定标识，phase / label 是自由词汇表。

LOOP_ID_MAX_LENGTH: int = 64
"""Maximum accepted length for ``loop_id`` (agent-chosen stable loop key)."""

LOOP_TEXT_MAX_LENGTH: int = 500
"""Maximum accepted length for ``loop_objective`` / ``success_criteria``."""

LOOP_LABEL_MAX_LENGTH: int = 32
"""Maximum accepted length for ``loop_phase`` / ``iteration_label``."""

# ---------------------------------------------------------------------------
# Loop engineering (P3) — 完成轮次台账（loop history ledger）边界
# ---------------------------------------------------------------------------
# 「已完成任务 10s 清理」策略对 loop 场景不友好：历史轮次被整体删除后
# 无法回看「这个目标经历了哪几轮、每轮人说了什么」。P3 的策略是：任务
# 完成时若携带 loop_id，把**压缩后的 metadata**（去掉 prompt 大字段、
# 图片只记数量）记入 per-loop 台账，任务本体仍按 10s 清理。台账有界，
# 防止长会话内存无限增长。

LOOP_HISTORY_MAX_LOOPS: int = 20
"""Maximum distinct loops kept in the ledger (stalest-updated evicted)."""

LOOP_HISTORY_MAX_ROUNDS: int = 50
"""Maximum completed rounds kept per loop (oldest rounds dropped)."""

LOOP_VERDICT_MAX_LENGTH: int = 200
"""Maximum length of the user-verdict text stored per ledger round."""
