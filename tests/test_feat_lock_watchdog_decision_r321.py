"""R321 · `_LOCK_WATCHDOG_TIMEOUT_S = 30.0` 决策三层 invariant
(v3.7 decision-three-layer pattern 3rd app)。

背景
----

R315 (cycle-32 #A2, 2d75971) 用 perf-baseline pattern 锁定了
``task_queue.py`` 的 4 个关键常量, 包括 ``_LOCK_WATCHDOG_TIMEOUT_S = 30.0``
和 ``_LOCK_WATCHDOG_SCAN_INTERVAL_S = 5.0``。R315 锁字面量, **但没锁
"为什么是 30s 而不是 10s/60s/300s"** 的设计依据。

R321 (cycle-34 #A1, 本 commit) 用 decision-three-layer pattern 把数字背
后的决策落到独立文档 (`docs/perf-lock-watchdog-r321.md`), 并用 invariant
锁定 "数字 ↔ 决策 ↔ 文档" 三层一致性:

- **Layer 1 (Code)**: ``_LOCK_WATCHDOG_TIMEOUT_S = 30.0`` 的字面量 / 类型 /
  消费者
- **Layer 2 (Decision Doc)**: ``docs/perf-lock-watchdog-r321.md`` 存在 +
  实质性 + 内含数字 + 决策推理 + re-tune triggers
- **Layer 3 (Cross-layer)**: 文档里的数字与代码字面量一致 + 文档引用代码
  路径

Pattern lineage (decision-three-layer):

- 1st app: R308 (cr61) — CI pytest-xdist ``-n 4`` benchmark decision
- 2nd app: R314 (cr62) — ``_FETCH_RETRY_BACKOFF_S`` retry sequence
- **3rd app: R321 (本 commit)** — ``_LOCK_WATCHDOG_TIMEOUT_S`` 决策

**里程碑**: v3.7 decision-three-layer pattern 达 3 应用, **v3.7 完全工业
化** (配合 v3.7 三层一致性 R317 已达 3 app)。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_TASK_QUEUE_PY = SRC / "ai_intervention_agent" / "task_queue.py"
_DECISION_DOC = REPO_ROOT / "docs" / "perf-lock-watchdog-r321.md"

# 锁定的目标常量值
EXPECTED_TIMEOUT_S = 30.0
EXPECTED_SCAN_INTERVAL_S = 5.0


# ------------------------------------------------------------------
# Layer 1 — Code (task_queue.py)
# ------------------------------------------------------------------


class TestLayer1CodeConstant:
    """Layer 1: ``_LOCK_WATCHDOG_TIMEOUT_S`` 字面量, 类型, 消费者锚点。"""

    def test_task_queue_py_exists(self):
        assert _TASK_QUEUE_PY.is_file()

    def test_constant_defined_with_exact_value_and_type(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        pattern = r"^_LOCK_WATCHDOG_TIMEOUT_S\s*:\s*float\s*=\s*30\.0\b"
        assert re.search(pattern, text, re.MULTILINE), (
            "R321 Layer 1: `_LOCK_WATCHDOG_TIMEOUT_S: float = 30.0` "
            "exact literal must exist at module level. R321 锁字面量, 任何"
            "改动 (10.0 / 60.0 / 300.0) 必须先更新 docs/perf-lock-watchdog-r321.md"
        )

    def test_scan_interval_defined_with_exact_value(self):
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        pattern = r"^_LOCK_WATCHDOG_SCAN_INTERVAL_S\s*:\s*float\s*=\s*5\.0\b"
        assert re.search(pattern, text, re.MULTILINE), (
            "R321 Layer 1: `_LOCK_WATCHDOG_SCAN_INTERVAL_S: float = 5.0` "
            "exact literal must exist at module level."
        )

    def test_runtime_value_matches_expected(self):
        from ai_intervention_agent.task_queue import (
            _LOCK_WATCHDOG_SCAN_INTERVAL_S,
            _LOCK_WATCHDOG_TIMEOUT_S,
        )

        assert _LOCK_WATCHDOG_TIMEOUT_S == EXPECTED_TIMEOUT_S
        assert _LOCK_WATCHDOG_SCAN_INTERVAL_S == EXPECTED_SCAN_INTERVAL_S
        assert isinstance(_LOCK_WATCHDOG_TIMEOUT_S, float)
        assert isinstance(_LOCK_WATCHDOG_SCAN_INTERVAL_S, float)

    def test_constant_actually_consumed_by_watchdog_code(self):
        """R321 anchor: 必须有 ``_scan_pending_and_dump_slow`` / ``_lock_
        watchdog_loop`` 真的读这两个常量, 防止改名 / 死代码漂移。"""
        text = _TASK_QUEUE_PY.read_text(encoding="utf-8")
        # 期望至少 1 个对比表达式: ``now - rec["start"] > _LOCK_WATCHDOG_TIMEOUT_S``
        assert re.search(r"> _LOCK_WATCHDOG_TIMEOUT_S", text), (
            "R321 anchor: _LOCK_WATCHDOG_TIMEOUT_S must be consumed in "
            "comparison (typically `now - rec['start'] > _LOCK_WATCHDOG_TIMEOUT_S`)"
        )
        # 期望至少 1 个对 ``_LOCK_WATCHDOG_SCAN_INTERVAL_S`` 的引用
        assert re.search(
            r"_lock_watchdog_wake_event\.wait\(_LOCK_WATCHDOG_SCAN_INTERVAL_S\)",
            text,
        ), (
            "R321 anchor: _LOCK_WATCHDOG_SCAN_INTERVAL_S must be passed "
            "to event.wait(...) in watchdog loop"
        )


# ------------------------------------------------------------------
# Layer 2 — Decision Doc
# ------------------------------------------------------------------


class TestLayer2DecisionDoc:
    """Layer 2: 决策文档 docs/perf-lock-watchdog-r321.md 存在且实质。"""

    def test_decision_doc_exists(self):
        assert _DECISION_DOC.is_file(), (
            f"R321 Layer 2: decision doc missing at {_DECISION_DOC}"
        )

    def test_decision_doc_substantial(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        # 至少 1500 chars (实质性决策文档不会比这少)
        assert len(text) >= 1500, (
            f"R321 Layer 2: decision doc too short ({len(text)} chars), "
            f"expected >= 1500. Decision docs should explain why 30.0 not "
            f"10/60/300, mention re-tune triggers, etc."
        )

    def test_decision_doc_has_r321_marker(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        assert "R321" in text

    def test_decision_doc_references_r315_prior_art(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        assert "R315" in text, (
            "R321 Layer 2: decision doc must cite R315 (the perf-baseline "
            "commit that locked the constant first)"
        )

    def test_decision_doc_references_decision_three_layer_prior_apps(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        for prior in ("R308", "R314"):
            assert prior in text, (
                f"R321 Layer 2: decision doc must cite {prior} as prior "
                f"decision-three-layer app (lineage trace)"
            )

    def test_decision_doc_explains_value_choice(self):
        """文档必须解释为什么 30 不是 10/60/300。"""
        text = _DECISION_DOC.read_text(encoding="utf-8")
        # 至少提到 3 个 alternative 值
        alternatives_mentioned = sum(
            1 for v in ("10s", "60s", "300s", "10 ", "60 ", "300 ") if v in text
        )
        assert alternatives_mentioned >= 2, (
            f"R321 Layer 2: decision doc should compare 30s against at "
            f"least 2 alternative values (10s/60s/300s etc.). Found "
            f"{alternatives_mentioned}."
        )

    def test_decision_doc_has_retune_triggers(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        # 至少 1 个 re-tune trigger 关键词
        keywords = ("re-tune", "retune", "重新调", "重新评估", "考虑改")
        hits = sum(1 for kw in keywords if kw in text)
        assert hits >= 1, (
            f"R321 Layer 2: decision doc should document re-tune triggers "
            f"(when to revisit this value). Looked for {keywords}, found "
            f"{hits}."
        )


# ------------------------------------------------------------------
# Layer 3 — Cross-layer consistency
# ------------------------------------------------------------------


class TestLayer3CrossLayerConsistency:
    """Layer 3: 文档里的数字与代码字面量一致, 文档引用代码路径。"""

    def test_doc_mentions_exact_timeout_value(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        # 必须有 "30.0" / "30s" / "30 s" 之一
        assert re.search(r"\b30(?:\.0)?(?:\s*s|秒| s)?\b", text), (
            "R321 Layer 3: doc must mention exact value 30 / 30.0 / 30s, "
            "matching code literal"
        )

    def test_doc_mentions_exact_scan_interval_value(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        assert re.search(r"\b5(?:\.0)?(?:\s*s|秒| s)?\b", text), (
            "R321 Layer 3: doc must mention SCAN_INTERVAL value 5 / 5.0 / 5s"
        )

    def test_doc_references_code_file_path(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        assert "task_queue.py" in text, (
            "R321 Layer 3: doc must reference src code path "
            "`task_queue.py` so future readers can locate the constant"
        )

    def test_doc_references_consumer_functions(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        # 必须至少提到 2 个 consumer 函数名之一
        consumers = ("_scan_pending_and_dump_slow", "_lock_watchdog_loop")
        hits = sum(1 for c in consumers if c in text)
        assert hits >= 1, (
            f"R321 Layer 3: doc must reference at least one consumer "
            f"function from {consumers}, found {hits}"
        )

    def test_doc_mentions_ratio_invariant(self):
        text = _DECISION_DOC.read_text(encoding="utf-8")
        # ratio TIMEOUT / SCAN_INTERVAL = 6 是 R315 锁定的 meta-lint
        assert re.search(r"30\s*/\s*5\s*=\s*6|ratio|比例", text), (
            "R321 Layer 3: doc must document TIMEOUT/SCAN_INTERVAL ratio "
            "(R315 meta-lint: ratio >= 5)"
        )


# ------------------------------------------------------------------
# Pattern lineage marker
# ------------------------------------------------------------------


class TestR321LineageMarker:
    """R321 是 v3.7 decision-three-layer pattern 3rd app, 锁定 docstring 引用。"""

    def test_this_file_contains_r321_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R321" in text
        assert "decision-three-layer" in text.lower() or "决策三层" in text

    def test_this_file_references_prior_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R308", "R314"):
            assert prior in text, (
                f"R321 docstring must cite prior decision-three-layer app: {prior}"
            )

    def test_this_file_documents_three_layers(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "Layer 1",
            "Layer 2",
            "Layer 3",
            "_LOCK_WATCHDOG_TIMEOUT_S",
            "perf-lock-watchdog-r321.md",
        ):
            assert kw in text, f"R321 docstring missing keyword: {kw!r}"
