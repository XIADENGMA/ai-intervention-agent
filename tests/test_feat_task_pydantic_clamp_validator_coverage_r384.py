"""R384 · Pydantic validator coverage 2nd app — Task 模型 soft-limit
字段必须有 ``@field_validator`` 或 whitelist + rationale (cycle-43
扩展 #1, **Pydantic field validator coverage 2nd 应用进入巩固期**)。

背景
----

``Task`` (``task_queue.py:240``) Pydantic 模型有 3 个字段在 inline
docstring / 注释里被明确标注"clamp" / "max length"约束:

- ``auto_resubmit_timeout: int`` — TOML/HTTP 输入 clamp 到
  ``[AUTO_RESUBMIT_TIMEOUT_MIN, AUTO_RESUBMIT_TIMEOUT_MAX]``;
- ``feedback_placeholder: str | None`` — 软上限 ``PLACEHOLDER_MAX_LENGTH``
  (200 chars), 注释明确"长度软上限 200 chars";
- ``header_label: str | None`` — clamp ``HEADER_LABEL_MAX_LENGTH``
  (16 chars), 注释明确"clamp 16 chars"。

但 ``Task`` 模型本身**没有任何 ``@field_validator``** —— clamp 全靠
route layer (``web_ui_validators.validate_auto_resubmit_timeout``) +
``add_task`` 内嵌 ``s[:N]`` 截断完成。

风险:
- ``Task(prompt="x", header_label="x" * 999)`` 直接构造 = 16-char
  约束完全失效 (绕过 add_task);
- 持久化文件被手改 → ``_restore_*`` 路径有部分截断逻辑但若新增字段
  忘了在 restore 路径加 clamp 就 silent overflow;
- ``predefined_options_defaults`` 和 ``predefined_options`` 长度不匹配
  也由 route 层校验而非 model 层。

R384 invariant 强制: ``Task`` 模型的 clamp-mentioned 字段必须有
``@field_validator`` 装饰的 coerce/clamp 方法, 或在
``CLAMP_ENFORCEMENT_WHITELIST`` 显式列出 + 链接到 route/persistence
层的 clamp 实现位置 + rationale。

R384 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: ``Task`` 模型 AST-loadable, 至少含 3 个有
   clamp 约束的字段 (``auto_resubmit_timeout`` /
   ``feedback_placeholder`` / ``header_label``);
2. **Layer 2 (Forward coverage)**: 每个 clamp-mentioned 字段必须有
   ``@field_validator(field_name)`` 装饰的方法, 或在
   ``CLAMP_ENFORCEMENT_WHITELIST`` 显式豁免 (并附 rationale comment 行);
3. **Layer 3 (Whitelist meaningful)**: whitelist 条目必须真存在于
   ``Task`` 类, 并且对应的 clamp 常量 (``PLACEHOLDER_MAX_LENGTH`` /
   ``HEADER_LABEL_MAX_LENGTH`` / ``AUTO_RESUBMIT_TIMEOUT_MAX``) 必须存
   在于 source 中 (防 silent rename/删除)。

methodology lineage
-------------------

R384 与 **R380** (Pydantic validator coverage 1st, NotificationConfig
数值字段命名 pattern + ``@field_validator``) 并列, 是 Pydantic
validator coverage 维度 2nd 应用, 标志该维度进入**巩固期**。

差异:
- R380 = naming-pattern driven (``*_timeout`` / ``*_count`` 等命名规
  律 → 自动识别 numeric 字段);
- R384 = comment/constraint-driven (字段 docstring/注释里明确写
  "clamp N chars" / "soft limit" → 显式列出 whitelist);

互补覆盖了 "约束来自命名 (隐式)" 和 "约束来自文档 (显式)" 两种
typical pattern。

与:
- R368 (API contract 4th, Task 字段曝光分类) — 锁 Task 的字段对外
  api 文档完整性;
- R380 (Pydantic validator 1st) — 锁 NotificationConfig 数值字段;

形成 "Task 模型 schema 行为契约完整三层" (字段曝光 + 字段类型 + 字
段约束)。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_QUEUE_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "task_queue.py"
VALIDATORS_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_validators.py"

# Task 模型内有 clamp 约束的字段 (按 source 静态扫描得出)
EXPECTED_CLAMP_FIELDS: set[str] = {
    "auto_resubmit_timeout",
    "feedback_placeholder",
    "header_label",
}

# clamp 约束所引用的常量 (必须存在于 task_queue.py 或导入)
EXPECTED_CLAMP_CONSTANTS: dict[str, str] = {
    "auto_resubmit_timeout": "AUTO_RESUBMIT_TIMEOUT_MAX",
    "feedback_placeholder": "PLACEHOLDER_MAX_LENGTH",
    "header_label": "HEADER_LABEL_MAX_LENGTH",
}

# whitelist: clamp 约束已在 route / add_task / restore 层实施而非 model 层
# (理想状态为空 = 全部由 @field_validator 实施; 当前为 3 个 = R384 启动状态)
CLAMP_ENFORCEMENT_WHITELIST: dict[str, str] = {
    "auto_resubmit_timeout": (
        "clamp 在 ``web_ui_validators.validate_auto_resubmit_timeout`` "
        "(route layer); persistence restore 路径用 min/max clamp; "
        "future: 移到 model layer @field_validator"
    ),
    "feedback_placeholder": (
        "clamp 在 ``Task.add_task`` (route layer) 用 s[:200] 截断; "
        "persistence ``_restore_*`` 路径用 [:PLACEHOLDER_MAX_LENGTH]; "
        "future: 移到 model layer @field_validator(mode='before')"
    ),
    "header_label": (
        "clamp 在 ``Task.add_task`` (route layer) 用 s[:16] 截断; "
        "persistence ``_restore_*`` 路径用 [:HEADER_LABEL_MAX_LENGTH]; "
        "future: 移到 model layer @field_validator(mode='before')"
    ),
}


def _read_task_queue_ast() -> ast.Module:
    return ast.parse(TASK_QUEUE_PY.read_text(encoding="utf-8"))


def _get_class_field_names(module: ast.Module, class_name: str) -> list[str]:
    """提取 class 内所有 annotated 字段名 (按声明顺序)。"""
    out: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    name = stmt.target.id
                    if not name.startswith("_") and not name.isupper():
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
    """Layer 1: Task 模型可加载, 含至少 3 个 clamp-mentioned 字段。"""

    def test_task_class_loadable(self):
        module = _read_task_queue_ast()
        class_names = {n.name for n in ast.walk(module) if isinstance(n, ast.ClassDef)}
        assert "Task" in class_names, "R384-L1: Task class must exist in task_queue.py"

    def test_at_least_3_clamp_fields_present(self):
        module = _read_task_queue_ast()
        fields = set(_get_class_field_names(module, "Task"))
        missing = EXPECTED_CLAMP_FIELDS - fields
        assert not missing, (
            f"R384-L1: missing clamp-mentioned fields on Task: "
            f"{missing}. Refactor must update EXPECTED_CLAMP_FIELDS."
        )


class TestLayer2ForwardCoverage:
    """Layer 2: 每个 clamp-mentioned 字段必须有 ``@field_validator`` 或在 whitelist 内。"""

    def test_every_clamp_field_has_validator_or_whitelisted(self, subtests):
        module = _read_task_queue_ast()
        validators = _get_validators_for_class(module, "Task")
        violations: list[str] = []
        for field in sorted(EXPECTED_CLAMP_FIELDS):
            with subtests.test(field=field):
                in_validators = field in validators
                in_whitelist = field in CLAMP_ENFORCEMENT_WHITELIST
                if not in_validators and not in_whitelist:
                    violations.append(
                        f"  {field}: clamp-mentioned field without "
                        "@field_validator AND not in "
                        "CLAMP_ENFORCEMENT_WHITELIST"
                    )
        if violations:
            raise AssertionError(
                f"R384-L2: {len(violations)} clamp-mentioned field(s) "
                f"without enforcement:\n"
                + "\n".join(violations)
                + "\n\nFix: add @field_validator(name, mode='before') "
                "method that clamps invalid input, OR add to "
                "CLAMP_ENFORCEMENT_WHITELIST with rationale (where "
                "clamp is actually enforced + future plan)."
            )


class TestLayer3WhitelistMeaningful:
    """Layer 3: whitelist 必须真实 (字段存在 + 常量存在 + rationale 非空)。"""

    def test_whitelist_fields_exist_on_task(self, subtests):
        module = _read_task_queue_ast()
        fields = set(_get_class_field_names(module, "Task"))
        for entry in CLAMP_ENFORCEMENT_WHITELIST:
            with subtests.test(field=entry):
                assert entry in fields, (
                    f"R384-L3: stale whitelist entry '{entry}' not on Task"
                )

    def test_whitelist_rationale_nonempty(self, subtests):
        for entry, rationale in CLAMP_ENFORCEMENT_WHITELIST.items():
            with subtests.test(field=entry):
                assert len(rationale.strip()) >= 50, (
                    f"R384-L3: whitelist '{entry}' rationale too short "
                    f"(< 50 chars). Must explain where clamp is enforced "
                    f"+ future plan."
                )

    def test_expected_clamp_constants_exist_in_source(self, subtests):
        source = TASK_QUEUE_PY.read_text(encoding="utf-8")
        for field, const in EXPECTED_CLAMP_CONSTANTS.items():
            with subtests.test(field=field, constant=const):
                assert const in source, (
                    f"R384-L3: clamp constant '{const}' for '{field}' "
                    f"not found in task_queue.py — silent rename/删除?"
                )


class TestR384LineageMarker:
    """Methodology lineage 引用必须保留, 防被误删。"""

    def test_this_file_contains_r384_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R384" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R380", "R368"):
            assert prior in text, f"R384: must cite related lineage: {prior}"

    def test_this_file_marks_2nd_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("Pydantic validator coverage 2nd", "巩固期"):
            assert kw in text, f"R384: missing keyword: {kw!r}"
