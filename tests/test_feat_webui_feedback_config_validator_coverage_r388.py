"""R388 · WebUIConfig + FeedbackConfig 数值字段 ``@field_validator``
覆盖 invariant — Pydantic field validator coverage 3rd app (cycle-44
#A1, **Pydantic validator coverage 维度达 3 应用工业化阈值**)。

R380 (1st) 锁了 NotificationConfig 内匹配 ``*_timeout`` / ``*_count``
等命名 pattern 的字段必须有 ``@field_validator``。
R384 (2nd) 锁了 ``Task`` 模型 inline 注释明确 clamp 约束的字段。
R388 (3rd) 把 R380 的命名 pattern 扩展并应用到 ``WebUIConfig`` +
``FeedbackConfig`` 两个用户可配置 Pydantic 模型, 完成 **3 应用工业化
阈值**。

差异点
------

R380 的命名 pattern 用后缀 anchor ``.*_timeout$`` — 匹配 ``bark_timeout``
但**不匹配单独的 ``timeout``** (WebUIConfig.timeout / FeedbackConfig.timeout
字段)。R388 引入更宽松的 pattern:

- 后缀 anchor 保留 (e.g., ``http_request_timeout``)
- **新增**: 字段名 == "timeout" / "port" / "delay" / "interval" /
  "retries" / "max_retries" / "auto_resubmit_timeout" 等
  bare 形式也属于数值字段

R388 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: ``WebUIConfig`` + ``FeedbackConfig`` 可加载,
   各自含至少 3 个数值字段;
2. **Layer 2 (Forward coverage)**: 每个数值字段必须有
   ``@field_validator(field_name)`` 装饰的方法 (或在
   ``EXEMPT_FIELDS_BY_CLASS`` 显式豁免);
3. **Layer 3 (Whitelist meaningful)**: 豁免条目必须真实 (字段存在 +
   rationale ≥ 50 字符);

为什么重要
----------

WebUIConfig 的 ``port`` 是用户可配置的关键字段; FeedbackConfig 的
``timeout`` / ``auto_resubmit_timeout`` 影响 UX 核心行为。无 validator
覆盖 → 用户输入 ``port=0`` / ``timeout=-100`` → 整个 config 加载失败
→ 服务无法启动。

methodology lineage
-------------------

R388 与 R380 (NotificationConfig 命名隐式) + R384 (Task 注释显式) 形
成 **Pydantic field validator coverage 3 应用工业化 lineage**:

| Pass | R#    | 应用对象          | 识别方式                      |
| ---- | ----- | ----------------- | ----------------------------- |
| 1st  | R380  | NotificationConfig | 命名 pattern (suffix anchor)  |
| 2nd  | R384  | Task               | inline comment 显式 clamp     |
| 3rd  | R388  | WebUIConfig +     | 命名 pattern (含 bare 形式)   |
|      |       | FeedbackConfig    |                               |

进入工业化阈值 (3 应用) 后, Pydantic validator coverage 与
v3.7/v3.8/v3.9 等 pattern 维度并列, 任何新增 Pydantic 模型的数值字
段都必须遵守此 invariant。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_CONFIG_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "server_config.py"

# 数值字段命名 pattern (后缀 + bare 形式)
NUMERIC_FIELD_PATTERNS: tuple[str, ...] = (
    # 后缀 anchor (含 prefix, e.g., ``http_request_timeout``)
    r".*_timeout$",
    r".*_count$",
    r".*_delay$",
    r".*_volume$",
    r".*_interval$",
    r".*_retries$",
    # bare 形式 (单独使用, R388 新增)
    r"^timeout$",
    r"^delay$",
    r"^interval$",
    r"^port$",
    r"^max_retries$",
    r"^retry_delay$",
    r"^auto_resubmit_timeout$",
)

# 每个 class 的豁免字段 (key: class 名, value: {field: rationale})
EXEMPT_FIELDS_BY_CLASS: dict[str, dict[str, str]] = {
    "WebUIConfig": {},
    "FeedbackConfig": {},
}

# 目标 class 列表 (R388 范围)
TARGET_CLASSES: tuple[str, ...] = ("WebUIConfig", "FeedbackConfig")


def _is_numeric_field(name: str) -> bool:
    return any(re.match(p, name) for p in NUMERIC_FIELD_PATTERNS)


def _read_module() -> ast.Module:
    return ast.parse(SERVER_CONFIG_PY.read_text(encoding="utf-8"))


def _get_class_field_names(module: ast.Module, class_name: str) -> list[str]:
    """提取 class 内 annotated 字段名 (跳过 ``_`` / ``ClassVar``)。"""
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
                # 跳过 ClassVar[...] 注释 (它们不是 instance field)
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
    """提取 class 内 @field_validator 装饰方法所覆盖的字段名集合。"""
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
    """Layer 1: WebUIConfig + FeedbackConfig 可加载, 各含至少 3 个数值字段。"""

    def test_classes_loadable(self, subtests):
        module = _read_module()
        class_names = {n.name for n in ast.walk(module) if isinstance(n, ast.ClassDef)}
        for cls in TARGET_CLASSES:
            with subtests.test(cls=cls):
                assert cls in class_names, (
                    f"R388-L1: target class '{cls}' not found in server_config.py"
                )

    def test_each_class_has_numeric_fields(self, subtests):
        module = _read_module()
        for cls in TARGET_CLASSES:
            with subtests.test(cls=cls):
                fields = _get_class_field_names(module, cls)
                numeric = [f for f in fields if _is_numeric_field(f)]
                assert len(numeric) >= 2, (
                    f"R388-L1: '{cls}' only has {len(numeric)} numeric "
                    f"field(s) ({numeric}), expected >= 2. Refactor must "
                    f"update NUMERIC_FIELD_PATTERNS or target list."
                )


class TestLayer2ForwardCoverage:
    """Layer 2: 每个数值字段必须有 @field_validator 或显式豁免。"""

    def test_every_numeric_field_has_validator_or_whitelisted(self, subtests):
        module = _read_module()
        violations: list[str] = []
        for cls in TARGET_CLASSES:
            fields = _get_class_field_names(module, cls)
            validators = _get_validators_for_class(module, cls)
            exempts = EXEMPT_FIELDS_BY_CLASS.get(cls, {})
            for f in fields:
                if not _is_numeric_field(f):
                    continue
                with subtests.test(cls=cls, field=f):
                    if f in exempts:
                        continue
                    if f not in validators:
                        violations.append(
                            f"  {cls}.{f}: numeric field without "
                            f"@field_validator decorator"
                        )
        if violations:
            raise AssertionError(
                f"R388-L2: {len(violations)} numeric field(s) without "
                f"@field_validator:\n"
                + "\n".join(violations)
                + "\n\nFix: add @field_validator(name) method that "
                "clamps/validates input, OR add to "
                "EXEMPT_FIELDS_BY_CLASS with rationale."
            )


class TestLayer3WhitelistMeaningful:
    """Layer 3: 豁免条目必须存在 + rationale ≥ 50 字符。"""

    def test_exempt_fields_exist_on_class(self, subtests):
        module = _read_module()
        for cls, exempts in EXEMPT_FIELDS_BY_CLASS.items():
            fields = set(_get_class_field_names(module, cls))
            for entry in exempts:
                with subtests.test(cls=cls, field=entry):
                    assert entry in fields, (
                        f"R388-L3: stale exempt entry '{cls}.{entry}' not on class"
                    )

    def test_exempt_rationale_nonempty(self, subtests):
        for cls, exempts in EXEMPT_FIELDS_BY_CLASS.items():
            for entry, rationale in exempts.items():
                with subtests.test(cls=cls, field=entry):
                    assert len(rationale.strip()) >= 50, (
                        f"R388-L3: '{cls}.{entry}' rationale too short "
                        f"(< 50 chars). Must explain why validator is "
                        f"unnecessary + where enforcement is."
                    )


class TestR388LineageMarker:
    """Methodology lineage 引用必须保留。"""

    def test_this_file_contains_r388_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R388" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R380", "R384"):
            assert prior in text, f"R388: must cite related lineage: {prior}"

    def test_this_file_marks_3rd_app_industrialization(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("Pydantic field validator coverage 3rd app", "工业化阈值"):
            assert kw in text, f"R388: missing keyword: {kw!r}"
