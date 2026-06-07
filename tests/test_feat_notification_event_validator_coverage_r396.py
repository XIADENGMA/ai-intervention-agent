"""R396 · ``NotificationEvent`` 数值字段 ``@field_validator`` 覆盖
invariant — Pydantic field validator coverage 4th app (cycle-45 #A1,
**Pydantic validator coverage 维度进入深化期 4 应用**)。

R380 (cycle-43 1st) — NotificationConfig 命名 pattern
R384 (cycle-43 2nd 巩固) — Task 注释显式 clamp
R388 (cycle-44 3rd 工业化) — WebUIConfig + FeedbackConfig 命名+bare
**R396 (cycle-45 4th 深化) — NotificationEvent**

NotificationEvent (notification_models.py:38) 是事件总线核心数据结
构, 被持久化到 SSE bus 和 retry queue。当前定义:

- ``retry_count: int = 0`` — 匹配 ``*_count`` pattern, **无
  @field_validator**
- ``max_retries: int = 3`` — 匹配 ``^max_retries$`` pattern, **无
  @field_validator**
- ``timestamp: float`` — 匹配未必算 numeric pattern
- ``metadata: dict`` — 已有 ``coerce_none_metadata`` validator

**实际风险**: 攻击者 / buggy provider 注入 ``retry_count = -1`` 或
``max_retries = 99999`` 时, Pydantic 当前直接接受, 后果:

- ``retry_count: -1`` → ``while retry_count < max_retries`` 死循环;
- ``max_retries: 99999`` → 一个通知失败重试 99999 次, 消耗 9 minutes 真实通
  知 spam, 还把 retry queue 占满阻塞其他 event。

R396 invariant 强制 NotificationEvent 的 ``retry_count`` /
``max_retries`` 必须有 ``@field_validator`` clamp (或在 whitelist 内
有 rationale 说明 enforcement 在 NotificationManager 一层完成)。

R396 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: ``NotificationEvent`` 可加载, 含至少 2 个匹
   配 R380/R388 命名 pattern 的数值字段;
2. **Layer 2 (Forward coverage)**: 每个数值字段必须有
   ``@field_validator(field_name)`` 装饰的方法 (或在
   ``EXEMPT_FIELDS`` 显式豁免);
3. **Layer 3 (Whitelist meaningful)**: 豁免条目必须真实 (字段存在 +
   rationale ≥ 50 字符);

methodology lineage
-------------------

R396 是 **Pydantic field validator coverage 4 应用 lineage**:

| Pass | R#    | 应用对象                            | 识别 pattern              |
| ---- | ----- | ----------------------------------- | ------------------------- |
| 1st  | R380  | NotificationConfig                  | 命名 (suffix)             |
| 2nd  | R384  | Task                                 | 注释显式 clamp            |
| 3rd  | R388  | WebUIConfig + FeedbackConfig         | 命名 (suffix + bare)      |
| 4th  | R396  | **NotificationEvent**                | 命名 (suffix + bare)      |

进入**深化期** (4 应用), 与:
- i18n consistency (R350/R353/R366/R374, 4 应用深化)
- doc-parity (R335/R340/R346/R394, 4 应用深化)
- cross-language schema (R285/R297/R302/R360, 4 应用深化)

并列, 都是 4+ 应用深化期成熟 pattern 维度。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "notification_models.py"

# 数值字段命名 pattern (与 R388 一致, 复用 R380 + bare 形式)
NUMERIC_FIELD_PATTERNS: tuple[str, ...] = (
    r".*_timeout$",
    r".*_count$",
    r".*_delay$",
    r".*_volume$",
    r".*_interval$",
    r".*_retries$",
    r"^timeout$",
    r"^delay$",
    r"^interval$",
    r"^port$",
    r"^max_retries$",
    r"^retry_delay$",
    r"^auto_resubmit_timeout$",
)

# 豁免字段 (理想为空; rationale ≥ 50 字符)
EXEMPT_FIELDS: dict[str, str] = {}


def _is_numeric_field(name: str) -> bool:
    return any(re.match(p, name) for p in NUMERIC_FIELD_PATTERNS)


def _read_module() -> ast.Module:
    return ast.parse(MODELS_PY.read_text(encoding="utf-8"))


def _get_class_field_names(module: ast.Module, class_name: str) -> list[str]:
    """提取 class 内 annotated 字段名 (跳过 _ / 全大写 / ClassVar)。"""
    out: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if not isinstance(stmt, ast.AnnAssign):
                    continue
                if not isinstance(stmt.target, ast.Name):
                    continue
                name = stmt.target.id
                if name.startswith("_") or name.isupper():
                    continue
                annotation = stmt.annotation
                is_classvar = False
                if isinstance(annotation, ast.Subscript):
                    val = annotation.value
                    if isinstance(val, ast.Name) and val.id == "ClassVar":
                        is_classvar = True
                if not is_classvar:
                    out.append(name)
    return out


def _get_validators_for_class(module: ast.Module, class_name: str) -> set[str]:
    fields: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in stmt.decorator_list:
                    target = dec.func if isinstance(dec, ast.Call) else dec
                    is_validator = (
                        isinstance(target, ast.Name) and target.id == "field_validator"
                    )
                    if is_validator and isinstance(dec, ast.Call):
                        for arg in dec.args:
                            if isinstance(arg, ast.Constant) and isinstance(
                                arg.value, str
                            ):
                                fields.add(arg.value)
    return fields


class TestLayer1Anchor:
    """Layer 1: NotificationEvent 可加载, 含至少 2 数值字段。"""

    def test_class_loadable(self):
        module = _read_module()
        class_names = {n.name for n in ast.walk(module) if isinstance(n, ast.ClassDef)}
        assert "NotificationEvent" in class_names, (
            "R396-L1: NotificationEvent class missing in notification_models.py"
        )

    def test_has_numeric_fields(self):
        module = _read_module()
        fields = _get_class_field_names(module, "NotificationEvent")
        numeric = [f for f in fields if _is_numeric_field(f)]
        assert len(numeric) >= 2, (
            f"R396-L1: NotificationEvent only has {len(numeric)} numeric "
            f"field(s) ({numeric}), expected >= 2. Refactor must update "
            f"NUMERIC_FIELD_PATTERNS."
        )


class TestLayer2ForwardCoverage:
    """Layer 2: 每个数值字段必须有 @field_validator 或显式豁免。"""

    def test_every_numeric_field_has_validator_or_whitelisted(self, subtests):
        module = _read_module()
        fields = _get_class_field_names(module, "NotificationEvent")
        validators = _get_validators_for_class(module, "NotificationEvent")
        violations: list[str] = []
        for f in fields:
            if not _is_numeric_field(f):
                continue
            with subtests.test(field=f):
                if f in EXEMPT_FIELDS:
                    continue
                if f not in validators:
                    violations.append(
                        f"  NotificationEvent.{f}: numeric field "
                        f"without @field_validator decorator"
                    )
        if violations:
            raise AssertionError(
                f"R396-L2: {len(violations)} numeric field(s) without "
                f"@field_validator on NotificationEvent:\n"
                + "\n".join(violations)
                + "\n\nFix: add @field_validator(name) method that "
                "clamps invalid input (e.g., retry_count must be >=0, "
                "max_retries must be in [0, MAX_REASONABLE_RETRIES]) "
                "OR add to EXEMPT_FIELDS with rationale."
            )


class TestLayer3WhitelistMeaningful:
    """Layer 3: 豁免条目必须真实 (字段存在 + rationale ≥ 50 字符)。"""

    def test_exempt_fields_exist_on_class(self, subtests):
        module = _read_module()
        fields = set(_get_class_field_names(module, "NotificationEvent"))
        for entry in EXEMPT_FIELDS:
            with subtests.test(field=entry):
                assert entry in fields, (
                    f"R396-L3: stale exempt entry '{entry}' not on NotificationEvent"
                )

    def test_exempt_rationale_nonempty(self, subtests):
        for entry, rationale in EXEMPT_FIELDS.items():
            with subtests.test(field=entry):
                assert len(rationale.strip()) >= 50, (
                    f"R396-L3: '{entry}' rationale too short (< 50 "
                    f"chars). Must explain where enforcement is."
                )


class TestR396LineageMarker:
    """Methodology lineage 引用必须保留。"""

    def test_this_file_contains_r396_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R396" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R380", "R384", "R388"):
            assert prior in text, f"R396: must cite related lineage: {prior}"

    def test_this_file_marks_4th_deepening(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("Pydantic field validator coverage 4th app", "深化期"):
            assert kw in text, f"R396: missing keyword: {kw!r}"
