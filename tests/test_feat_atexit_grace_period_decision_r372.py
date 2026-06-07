"""R372 · `_ATEXIT_GRACE_PERIOD_SECONDS = 1.5` 决策三层 invariant
(cycle-42 #C2, **v3.7 decision-three-layer pattern 4th 应用 — 完全工业
化深化期**)。

v3.7 decision-three-layer 应用 lineage
--------------------------------------

- 1st app: R308 (cr61) — CI pytest-xdist ``-n 4`` benchmark decision
- 2nd app: R314 (cr62) — ``_FETCH_RETRY_BACKOFF_S`` retry sequence
- 3rd app: R321 (cr64) — ``_LOCK_WATCHDOG_TIMEOUT_S`` 决策
- **4th app: R372 (本 commit)** — ``_ATEXIT_GRACE_PERIOD_SECONDS = 1.5``
  决策

背景
----

``notification_manager.py:1923`` 把 atexit shutdown grace period 固定
为 1.5s。这个数字背后的设计依据 (人对 <2s 退出延迟无感 + 单次
Bark/钉钉 HTTP request 典型 200-800ms) 在 inline rationale 中给出, 但
之前没有 invariant 强制锁定:

- 字面量 (1.5)
- inline rationale (说明为何不是 1.0 / 3.0 / 5.0)
- 唯一消费者 (``_shutdown_global_notification_manager`` 直接传给
  ``shutdown(grace_period=...)``)

R372 invariant (3 层)
---------------------

1. **Layer 1 (Code constant)**: ``_ATEXIT_GRACE_PERIOD_SECONDS = 1.5``
   字面量精确, 类型 float
2. **Layer 2 (Inline rationale)**: 常量声明前方有 docstring 或注释,
   包含 "1.5" 字面量 + 长度 ≥ 100 字符 (证明是实质决策记录, 而非
   placeholder)
3. **Layer 3 (Single consumer + cross-source)**: ``_atexit`` 注册的
   ``_shutdown_global_notification_manager`` 函数体内必须引用此常量
   (无 magic 1.5 硬编码)

为什么 4th 应用进入完全工业化深化期
-----------------------------------

v3.7 decision-three-layer pattern 在 R321 (3rd app) 达到 "工业化" 阈
值。R372 是 **4th app — 完全工业化深化期**, 标志着该 pattern 已经稳
定到可以**任意复用到新 magic number** 而无需重新设计模板:

- R321 用 separate decision doc (``docs/perf-lock-watchdog-r321.md``)
- R372 用 inline rationale (常量声明前的 commentary)

两者证明 pattern 兼容多种实现风格 (独立文档 vs 内嵌注释), 增加可复
用性。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NM_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "notification_manager.py"

EXPECTED_GRACE_PERIOD = 1.5


def _get_const_value() -> float:
    """从 notification_manager.py 提取 ``_ATEXIT_GRACE_PERIOD_SECONDS`` 值。"""
    text = NM_PY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (
                    isinstance(t, ast.Name)
                    and t.id == "_ATEXIT_GRACE_PERIOD_SECONDS"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, (int, float))
                ):
                    return float(node.value.value)
    raise AssertionError(
        "R372-L1: cannot find _ATEXIT_GRACE_PERIOD_SECONDS assignment "
        "in notification_manager.py"
    )


def _get_rationale_text() -> str:
    """提取常量声明前的注释段 (作为 Layer 2 rationale source)。"""
    text = NM_PY.read_text(encoding="utf-8")
    lines = text.splitlines()
    # 找到 _ATEXIT_GRACE_PERIOD_SECONDS 这一行的索引
    target_idx = -1
    for i, line in enumerate(lines):
        if "_ATEXIT_GRACE_PERIOD_SECONDS" in line and "=" in line:
            target_idx = i
            break
    assert target_idx >= 0, "R372-L2: _ATEXIT_GRACE_PERIOD_SECONDS assignment not found"
    # 向上回溯, 收集连续的 # 开头注释
    rationale_lines: list[str] = []
    j = target_idx - 1
    while j >= 0:
        s = lines[j].strip()
        if s.startswith("#"):
            rationale_lines.insert(0, s.lstrip("# ").rstrip())
            j -= 1
        elif s == "":
            j -= 1
            # 空行允许穿透 (有时注释中间有空行段落)
            if j >= 0 and not lines[j].strip().startswith("#"):
                break
        else:
            break
    return "\n".join(rationale_lines)


class TestLayer1CodeConstant:
    """Layer 1: ``_ATEXIT_GRACE_PERIOD_SECONDS`` 字面量 + 类型。"""

    def test_constant_value_is_1_5(self):
        v = _get_const_value()
        assert v == EXPECTED_GRACE_PERIOD, (
            f"R372-L1: _ATEXIT_GRACE_PERIOD_SECONDS should equal "
            f"{EXPECTED_GRACE_PERIOD}, got {v}"
        )

    def test_constant_type_is_float(self):
        v = _get_const_value()
        assert isinstance(v, float), (
            f"R372-L1: _ATEXIT_GRACE_PERIOD_SECONDS must be float, "
            f"got {type(v).__name__}"
        )


class TestLayer2InlineRationale:
    """Layer 2: inline rationale 注释存在且实质性。"""

    def test_rationale_contains_value_literal(self):
        rationale = _get_rationale_text()
        assert "1.5" in rationale, (
            "R372-L2: rationale comment must mention the literal "
            "value '1.5' (so the value choice is anchored in prose, "
            "not just code)"
        )

    def test_rationale_length_substantive(self):
        rationale = _get_rationale_text()
        assert len(rationale) >= 100, (
            f"R372-L2: rationale comment must be >= 100 chars to "
            f"qualify as substantive decision record (got "
            f"{len(rationale)} chars). Either expand or split into "
            f"separate decision doc."
        )

    def test_rationale_mentions_decision_factors(self):
        rationale = _get_rationale_text().lower()
        # 至少 1 个量化决策因素 + 1 个时间窗口论据
        has_factor = any(
            kw in rationale for kw in ("ms", "request", "bark", "钉钉", "http")
        )
        has_perception = any(kw in rationale for kw in ("无感", "用户", "退出", "卡住"))
        assert has_factor and has_perception, (
            "R372-L2: rationale should mention both a quantitative "
            "factor (request latency, HTTP timing) AND a user-perception "
            "argument (why 1.5s feels right for the user)"
        )


class TestLayer3SingleConsumerCrossSource:
    """Layer 3: ``_shutdown_global_notification_manager`` 必须引用此常量。"""

    def test_shutdown_function_uses_constant(self):
        text = NM_PY.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_shutdown_global_notification_manager"
            ):
                body_src = ast.unparse(node)
                assert "_ATEXIT_GRACE_PERIOD_SECONDS" in body_src, (
                    "R372-L3: _shutdown_global_notification_manager "
                    "must reference _ATEXIT_GRACE_PERIOD_SECONDS by "
                    "name, not hardcoded 1.5"
                )
                # 不能有 magic 1.5 hardcoded
                magic_hits = re.findall(r"\b1\.5\b", body_src)
                assert not magic_hits, (
                    "R372-L3: _shutdown_global_notification_manager "
                    "must not contain hardcoded magic '1.5' — use "
                    "_ATEXIT_GRACE_PERIOD_SECONDS constant"
                )
                return
        raise AssertionError("R372-L3: _shutdown_global_notification_manager not found")


class TestR372LineageMarker:
    def test_this_file_contains_r372_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R372" in text

    def test_this_file_references_decision_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R308", "R314", "R321"):
            assert prior in text, (
                f"R372: must cite decision-three-layer lineage: {prior}"
            )

    def test_this_file_marks_fourth_application(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("4th 应用", "完全工业化深化期"):
            assert kw in text, f"R372: missing keyword: {kw!r}"
