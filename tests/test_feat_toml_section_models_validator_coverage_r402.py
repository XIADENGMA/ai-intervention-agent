"""R402 · ``shared_types`` TOML section models 数值字段 validator
覆盖 invariant — Pydantic field validator coverage 5th app (cycle-45
扩展 #1, **Pydantic validator coverage 维度达 5 应用深化期完全工业
化**)。

R380 (cycle-43 1st) — NotificationConfig 命名 pattern + @field_validator
R384 (cycle-43 2nd) — Task 注释显式 clamp
R388 (cycle-44 3rd) — WebUIConfig + FeedbackConfig 工业化
R396 (cycle-45 4th) — NotificationEvent 深化期 + 源同步修复
**R402 (cycle-45 5th) — shared_types section models, 引入第 2 种
validator 风格 (Annotated[X, BeforeValidator(...)])**

新维度: validator 风格识别
--------------------------

Pydantic v2 提供 2 种字段验证风格:

1. **Decorator 风格** (R380/R384/R388/R396 已覆盖):
   ```python
   @field_validator("port", mode="before")
   @classmethod
   def clamp_port(cls, v): ...
   ```

2. **Annotated 风格** (本 R402 新增覆盖):
   ```python
   from pydantic import BeforeValidator
   port: Annotated[int, BeforeValidator(_clamp_int(1, 65535, 8080))] = 8080
   ```

shared_types.py 内的 TOML section models (NotificationSectionConfig /
WebUISectionConfig / FeedbackSectionConfig) **全部使用 Annotated 风
格** —— R380/R388 的 AST-walk 找 ``field_validator`` decorator 完全
看不到这些字段, 形成 invariant 覆盖漏洞。

R402 invariant 同时识别两种风格, 锁 shared_types section models 的
数值字段必须任一种风格存在。

R402 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: shared_types 的 3 个 section models 可加载,
   每个含至少 2 个数值字段 (按 R388 命名 pattern);
2. **Layer 2 (Forward coverage)**: 每个数值字段必须有 ``@field_validator``
   或 ``Annotated[X, BeforeValidator(...)]`` (任一即可);
3. **Layer 3 (Whitelist meaningful)**: 显式豁免 (理想为空) + rationale;

methodology lineage
-------------------

R402 是 **Pydantic field validator coverage 5 应用 lineage**:

| Pass | R#    | 应用对象                              | 验证风格              |
| ---- | ----- | ------------------------------------- | --------------------- |
| 1st  | R380  | NotificationConfig                    | @field_validator      |
| 2nd  | R384  | Task                                   | @field_validator      |
| 3rd  | R388  | WebUIConfig + FeedbackConfig           | @field_validator      |
| 4th  | R396  | NotificationEvent (含源同步修复)      | @field_validator      |
| 5th  | R402  | **shared_types 3 section models**     | **Annotated[BV(...)]**|

5 应用 = **深化期完全工业化** (5+ 应用是项目里程碑常用阈值, 与 v3.7
decision-three-layer 4 应用 / v3.8 全 pattern / v3.9 6 应用 等成熟
pattern 进入同一深化梯队)。

**特殊价值**: R402 让 invariant 覆盖从单一 validator 风格扩展到双风
格, 防 future contributor 用 Annotated 风格写新字段时 R388 covereage
audit 漏检。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_TYPES_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "shared_types.py"

NUMERIC_FIELD_PATTERNS: tuple[str, ...] = (
    r".*_timeout$",
    r".*_count$",
    r".*_delay$",
    r".*_volume$",
    r".*_interval$",
    r".*_retries$",
    r".*_countdown$",
    r".*_max_wait$",
    r"^timeout$",
    r"^delay$",
    r"^interval$",
    r"^port$",
)

TARGET_CLASSES: tuple[str, ...] = (
    "NotificationSectionConfig",
    "WebUISectionConfig",
    "FeedbackSectionConfig",
)

EXEMPT_FIELDS_BY_CLASS: dict[str, dict[str, str]] = {
    "NotificationSectionConfig": {},
    "WebUISectionConfig": {},
    "FeedbackSectionConfig": {},
}


def _is_numeric_field(name: str) -> bool:
    return any(re.match(p, name) for p in NUMERIC_FIELD_PATTERNS)


def _read_module() -> ast.Module:
    return ast.parse(SHARED_TYPES_PY.read_text(encoding="utf-8"))


def _get_class_field_names(module: ast.Module, class_name: str) -> list[str]:
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


def _get_validated_field_names(module: ast.Module, class_name: str) -> set[str]:
    """同时识别 @field_validator decorator 和 Annotated[X, BeforeValidator(...)] 风格。

    返回所有有 validator 覆盖的字段名集合。
    """
    out: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            # decorator 风格
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in stmt.decorator_list:
                        target = dec.func if isinstance(dec, ast.Call) else dec
                        is_validator = (
                            isinstance(target, ast.Name)
                            and target.id == "field_validator"
                        )
                        if is_validator and isinstance(dec, ast.Call):
                            for arg in dec.args:
                                if isinstance(arg, ast.Constant) and isinstance(
                                    arg.value, str
                                ):
                                    out.add(arg.value)
                # Annotated[X, BeforeValidator(...)] 风格
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    annotation = stmt.annotation
                    if _annotation_has_before_validator(annotation):
                        out.add(stmt.target.id)
    return out


def _annotation_has_before_validator(annotation: ast.expr) -> bool:
    """检查类型注解是否含 ``Annotated[X, BeforeValidator(...)]`` / 同族验证器。"""
    if not isinstance(annotation, ast.Subscript):
        return False
    # value 是 Annotated
    val = annotation.value
    if not (isinstance(val, ast.Name) and val.id == "Annotated"):
        return False
    # slice 是 Tuple, 找 BeforeValidator/AfterValidator/PlainValidator/WrapValidator
    slice_node = annotation.slice
    if isinstance(slice_node, ast.Tuple):
        for elem in slice_node.elts:
            if isinstance(elem, ast.Call):
                func = elem.func
                func_name = func.id if isinstance(func, ast.Name) else None
                if func_name in (
                    "BeforeValidator",
                    "AfterValidator",
                    "PlainValidator",
                    "WrapValidator",
                ):
                    return True
    return False


class TestLayer1Anchor:
    """Layer 1: 3 个 section models 可加载, 各含至少 2 数值字段。"""

    def test_classes_loadable(self, subtests):
        module = _read_module()
        class_names = {n.name for n in ast.walk(module) if isinstance(n, ast.ClassDef)}
        for cls in TARGET_CLASSES:
            with subtests.test(cls=cls):
                assert cls in class_names, (
                    f"R402-L1: '{cls}' missing in shared_types.py"
                )

    def test_each_class_has_numeric_fields(self, subtests):
        module = _read_module()
        for cls in TARGET_CLASSES:
            with subtests.test(cls=cls):
                fields = _get_class_field_names(module, cls)
                numeric = [f for f in fields if _is_numeric_field(f)]
                assert len(numeric) >= 2, (
                    f"R402-L1: '{cls}' only has {len(numeric)} numeric "
                    f"fields ({numeric}), expected >= 2."
                )


class TestLayer2ForwardCoverage:
    """Layer 2: 每个数值字段必须有 validator (任一风格)。"""

    def test_every_numeric_field_has_validator_or_whitelisted(self, subtests):
        module = _read_module()
        violations: list[str] = []
        for cls in TARGET_CLASSES:
            fields = _get_class_field_names(module, cls)
            validated = _get_validated_field_names(module, cls)
            exempts = EXEMPT_FIELDS_BY_CLASS.get(cls, {})
            for f in fields:
                if not _is_numeric_field(f):
                    continue
                with subtests.test(cls=cls, field=f):
                    if f in exempts:
                        continue
                    if f not in validated:
                        violations.append(
                            f"  {cls}.{f}: numeric field without "
                            f"@field_validator OR Annotated[X, "
                            f"BeforeValidator(...)]"
                        )
        if violations:
            raise AssertionError(
                f"R402-L2: {len(violations)} numeric field(s) without "
                f"validator (任一风格):\n" + "\n".join(violations)
            )


class TestLayer3WhitelistMeaningful:
    """Layer 3: 豁免条目必须存在 + rationale ≥ 50 字符。"""

    def test_exempt_fields_exist_on_class(self, subtests):
        module = _read_module()
        for cls, exempts in EXEMPT_FIELDS_BY_CLASS.items():
            fields = set(_get_class_field_names(module, cls))
            for entry in exempts:
                with subtests.test(cls=cls, field=entry):
                    assert entry in fields, f"R402-L3: stale exempt '{cls}.{entry}'"

    def test_exempt_rationale_nonempty(self, subtests):
        for cls, exempts in EXEMPT_FIELDS_BY_CLASS.items():
            for entry, rationale in exempts.items():
                with subtests.test(cls=cls, field=entry):
                    assert len(rationale.strip()) >= 50, (
                        f"R402-L3: '{cls}.{entry}' rationale too short"
                    )


class TestR402LineageMarker:
    """Methodology lineage 引用必须保留。"""

    def test_this_file_contains_r402_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R402" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R380", "R388", "R396"):
            assert prior in text, f"R402: must cite related lineage: {prior}"

    def test_this_file_marks_5th_milestone(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "Pydantic field validator coverage 5th app",
            "深化期完全工业化",
        ):
            assert kw in text, f"R402: missing keyword: {kw!r}"
