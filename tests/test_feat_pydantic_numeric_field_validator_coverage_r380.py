"""R380 · Pydantic 数值字段 field_validator 覆盖 invariant (cycle-43
#B3, **新维度: Pydantic field validator coverage 1st 应用**)。

背景
----

NotificationConfig 等用户可配置的 Pydantic 模型包含多个数值字段
(``*_timeout`` / ``*_count`` / ``*_delay`` / ``*_volume`` / ``*_interval``)。
这些字段读自 TOML 配置文件, 用户可能误输入:

- 负数 (``retry_count: -1``);
- 超量 (``bark_timeout: 99999``);
- 非数值 (``retry_delay: "two"``);
- None / 空字符串 (``sound_volume: null``)。

无 ``@field_validator(..., mode="before")`` 的字段会让 Pydantic 直接
抛 ``ValidationError``, 导致 **整个 NotificationConfig section 被
拒绝** — 用户一个字段填错, 整个通知子系统挂掉, UX 灾难。

R380 invariant 强制: 所有数值字段 (按命名 pattern 识别) 必须有显式
``coerce_*`` / ``clamp_*`` validator, 保证 invalid input 走 safe
default 而非 raise。

R380 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: NotificationConfig 可加载, 至少含 5 个数值
   字段 (整体规模检查)
2. **Layer 2 (Forward coverage)**: 每个匹配数值命名 pattern 的字段必
   须有对应 ``@field_validator(field_name)`` 装饰的方法
3. **Layer 3 (Whitelist)**: 显式列出豁免字段 (e.g.,
   ``trigger_repeat_interval`` 当前未实施 validator, 等待 follow-up),
   whitelist 可以是空 (理想状态)

为什么这个 invariant 重要
-------------------------

- 防 silent regression: 开发者新增 ``*_timeout`` 字段忘了写 validator
  → invariant 立即 fail
- 强制 explicit safe handling: 字段的 invalid input 行为不再依赖
  Pydantic 默认抛异常, 而是显式 fallback
- 与 ``coerce_int_default(v)`` / ``coerce_int_in_range(v, lo, hi)``
  helper 模式协同

methodology lineage
-------------------

R380 是 **Pydantic validator coverage** 维度首次锁定, 与:
- R370 (配置默认值漂移防护): 锁默认值
- R322 (v3.8 idempotent contract): 锁幂等性
- R368 (API contract 4th): 锁字段曝光

并列, 都属于 "schema 行为契约" 大类。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NM_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "notification_manager.py"

# 数值字段命名 pattern (后缀 keyword)
NUMERIC_FIELD_PATTERNS = (
    r".*_timeout$",
    r".*_count$",
    r".*_delay$",
    r".*_volume$",
    r".*_interval$",
)

# 豁免字段 (理想为空, 当前已知未实施 validator 的字段)
VALIDATOR_WHITELIST: set[str] = {
    # ``trigger_delay`` / ``trigger_repeat_interval`` / ``web_timeout``
    # 当前直接由 Pydantic Annotated 类型校验 (而非 @field_validator),
    # 在 TOML 端有 BeforeValidator clamp; runtime 端用户改不到, future
    # 实施 explicit validator 时移除豁免
    "trigger_delay",
    "trigger_repeat_interval",
    "web_timeout",
}


def _is_numeric_field(name: str) -> bool:
    return any(re.match(p, name) for p in NUMERIC_FIELD_PATTERNS)


def _get_validators_for_class(class_name: str) -> set[str]:
    """提取 class 内 @field_validator 装饰方法所覆盖的字段名集合。"""
    text = NM_PY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    fields: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in stmt.decorator_list:
                    target = dec
                    if isinstance(dec, ast.Call):
                        target = dec
                        if (
                            isinstance(dec.func, ast.Name)
                            and dec.func.id == "field_validator"
                        ):
                            for arg in dec.args:
                                if isinstance(arg, ast.Constant) and isinstance(
                                    arg.value, str
                                ):
                                    fields.add(arg.value)
    return fields


def _get_class_field_names(class_name: str) -> list[str]:
    """提取 class 内所有 annotated 字段名 (按声明顺序)。"""
    text = NM_PY.read_text(encoding="utf-8")
    tree = ast.parse(text)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    name = stmt.target.id
                    if not name.startswith("_") and not name.isupper():
                        out.append(name)
    return out


class TestLayer1Anchor:
    """Layer 1: NotificationConfig 含至少 5 个数值字段。"""

    def test_at_least_5_numeric_fields(self):
        fields = _get_class_field_names("NotificationConfig")
        numeric = [f for f in fields if _is_numeric_field(f)]
        assert len(numeric) >= 5, (
            f"R380-L1: only {len(numeric)} numeric fields in "
            f"NotificationConfig, expected >= 5. Models may have "
            f"been refactored; review NUMERIC_FIELD_PATTERNS."
        )


class TestLayer2ForwardCoverage:
    """Layer 2: 每个数值字段必须有 @field_validator 装饰的方法 (或被豁免)。"""

    def test_every_numeric_field_has_validator_or_whitelisted(self, subtests):
        fields = _get_class_field_names("NotificationConfig")
        validators = _get_validators_for_class("NotificationConfig")
        violations: list[str] = []
        for f in fields:
            if not _is_numeric_field(f):
                continue
            with subtests.test(field=f):
                if f in VALIDATOR_WHITELIST:
                    continue
                if f not in validators:
                    violations.append(
                        f"  {f}: numeric field without @field_validator decorator"
                    )
        if violations:
            raise AssertionError(
                f"R380-L2: {len(violations)} numeric field(s) without "
                f"@field_validator (safe coerce/clamp):\n"
                + "\n".join(violations)
                + "\nFix: add ``@field_validator(name, mode='before')`` "
                "method that coerces invalid input to safe default, "
                "or whitelist the field in VALIDATOR_WHITELIST with "
                "rationale (e.g., 'covered by TOML Annotated clamp')."
            )


class TestLayer3WhitelistMeaningful:
    """Layer 3: whitelist 可以是空 (理想), 但每项必须真存在于 class。"""

    def test_whitelist_entries_exist_on_class(self):
        fields = set(_get_class_field_names("NotificationConfig"))
        stale = [w for w in VALIDATOR_WHITELIST if w not in fields]
        assert not stale, (
            f"R380-L3: stale whitelist entries (not on "
            f"NotificationConfig): {stale}. Remove or update."
        )


class TestR380LineageMarker:
    def test_this_file_contains_r380_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R380" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R370", "R368"):
            assert prior in text, f"R380: must cite related lineage: {prior}"

    def test_this_file_marks_new_dimension(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("Pydantic field validator coverage", "新维度"):
            assert kw in text, f"R380: missing keyword: {kw!r}"
