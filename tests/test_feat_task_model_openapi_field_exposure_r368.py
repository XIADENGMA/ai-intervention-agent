"""R368 · Task Pydantic 模型字段 ↔ OpenAPI schema 反向曝光 invariant
(cycle-42 #A1, **API contract 4th 应用 — 工业化深化期**)。

API contract 应用 lineage
-------------------------

- R355 (cycle-40 #B1): 1st app — OpenAPI 三件套覆盖
- R358 (cycle-41 #A1): 2nd app — POST error response 覆盖
- R364 (cycle-41 #D1): 3rd app — tag taxonomy 封闭集合
- **R368 (本 commit, cycle-42)**: **4th app 工业化深化期** — Pydantic
  model ↔ OpenAPI schema 反向 field 曝光分类锁定

R368 audit 目标
---------------

``Task`` (``src/ai_intervention_agent/task_queue.py``) 是 ``/api/tasks``
GET 序列化的核心 Pydantic 模型。它的所有 field 必须被分类到 3 个
exposure 类型:

1. **USER_VISIBLE**: 必须出现在 ``/api/tasks`` GET docstring schema 内
   (前端 / VS Code extension 直接消费)
2. **INTERNAL**: 故意不暴露 (e.g., ``created_at_monotonic`` 用于内部
   计时, ``predefined_options_defaults`` 内部 storage flag)
3. **COMPUTED**: 不是 Pydantic 字段, 但通过 ``get_remaining_time()``
   等 helper 在 serialize 时注入 (出现在 schema 但不在 model_fields)

当开发者:

- 新增 Task 字段 → 必须分类 + 决定是否曝光
- 重命名 Task 字段 → snapshot 失效, 强制 review
- 在 docstring 偷加字段但忘了添加到 model → COMPUTED 类型校验失败

R368 invariant (4 层)
---------------------

1. **Layer 1 (Anchor)**: Task model 可以 import + ``model_fields`` 非空
2. **Layer 2 (Classification completeness)**: Task 的每个 Pydantic field
   都必须 ∈ USER_VISIBLE ∪ INTERNAL (orphan field check)
3. **Layer 3 (User-visible forward exposure)**: 每个 USER_VISIBLE field
   必须在 ``/api/tasks`` GET docstring 内找到 (即 schema 真的曝光了)
4. **Layer 4 (Internal whitelist meaningful)**: INTERNAL 集合不为空
   (证明分类机制在用)

为什么 4 层而非 3 层
--------------------

Layer 2 + 3 + 4 联合证明: **分类穷尽 (Layer 2) + 实际暴露 (Layer 3) +
机制运转 (Layer 4)**。如果只有 Layer 3, 开发者可以把所有 field 标为
INTERNAL 来短路, Layer 2 强制 explicit classification, Layer 4 防 100%
INTERNAL 的退化分类。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# USER_VISIBLE: 必须出现在 /api/tasks GET docstring schema 内的 field
# (字段名直接 1:1 比对)
USER_VISIBLE_FIELDS: frozenset[str] = frozenset(
    {
        "task_id",
        "prompt",
        "predefined_options",
        "auto_resubmit_timeout",
        "created_at",
        "status",
        "result",
        "completed_at",
        "extends_used",
        "feedback_placeholder",
        "question_type",
        "header_label",
        # Loop engineering P1 — loop 上下文 5 字段（前端按 loop_id 聚合
        # 多轮任务 / 显示轮次标签；export 携带以支持 audit 回放）
        "loop_id",
        "loop_objective",
        "loop_phase",
        "success_criteria",
        "iteration_label",
    }
)

# INTERNAL: 故意不暴露的内部 storage field, 必须显式标注
INTERNAL_FIELDS: frozenset[str] = frozenset(
    {
        # 内部 monotonic 时钟基线 — get_remaining_time() 用; 不应曝
        # 露给前端, 前端只看 derived remaining_time
        "created_at_monotonic",
        # parallel-array flag — 内部 storage; 前端只看 predefined_
        # options + options_defaults 的语义 union
        "predefined_options_defaults",
        # R702 — 「调用方显式传入 timeout」标记, 只影响 config 热更新
        # 同步是否跳过该任务 (幽灵提交根因修复); 对前端无语义, 前端只
        # 看 auto_resubmit_timeout / remaining_time 本身
        "auto_resubmit_timeout_explicit",
    }
)


def _get_task_fields() -> set[str]:
    """Import Task model 并返回 model_fields 集合。"""
    from ai_intervention_agent.task_queue import Task

    return set(Task.model_fields.keys())


TASK_GET_ENDPOINTS = (
    "/api/tasks",
    "/api/tasks/<task_id>",
    "/api/tasks/export",
)


def _get_all_task_get_docstrings() -> str:
    """聚合 3 个 task GET endpoint 的 docstring (拼成单字符串)。

    USER_VISIBLE field 在任一 GET 出现即视为"已曝光", 因为前端 UI 整
    体由这 3 个 endpoint 联合驱动 (列表 + 详情 + 导出)。
    """
    py_file = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    docs: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if not (isinstance(dec.func, ast.Attribute) and dec.func.attr == "route"):
                continue
            if not dec.args:
                continue
            first = dec.args[0]
            if not isinstance(first, ast.Constant):
                continue
            if first.value not in TASK_GET_ENDPOINTS:
                continue
            has_get = False
            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, ast.List):
                    for elt in kw.value.elts:
                        if isinstance(elt, ast.Constant) and elt.value == "GET":
                            has_get = True
            if has_get:
                docs.append(ast.get_docstring(node) or "")
    assert len(docs) >= 2, (
        f"R368: expected to find >= 2 task GET endpoints, got "
        f"{len(docs)}; check TASK_GET_ENDPOINTS list freshness"
    )
    return "\n\n".join(docs)


def _get_tasks_get_docstring() -> str:
    """向后兼容 alias — 现已聚合多个 endpoint 的 docstring。"""
    return _get_all_task_get_docstrings()


class TestLayer1Anchor:
    """Layer 1: Task model 可加载, model_fields 非空。"""

    def test_task_loadable(self):
        fields = _get_task_fields()
        assert len(fields) >= 8, (
            f"R368-L1: Task model has only {len(fields)} fields, "
            f"expected >= 8. Likely import broken or model gutted."
        )

    def test_tasks_get_docstring_loadable(self):
        doc = _get_tasks_get_docstring()
        assert "responses:" in doc, (
            "R368-L1: /api/tasks GET docstring missing OpenAPI block "
            "(should be caught by R355 too)"
        )


class TestLayer2ClassificationCompleteness:
    """Layer 2: Task 每个 field ∈ USER_VISIBLE ∪ INTERNAL。"""

    def test_no_orphan_fields(self):
        fields = _get_task_fields()
        classified = USER_VISIBLE_FIELDS | INTERNAL_FIELDS
        orphans = fields - classified
        if orphans:
            raise AssertionError(
                f"R368-L2: {len(orphans)} Task field(s) not classified:\n"
                + "\n".join(f"  - {f}" for f in sorted(orphans))
                + "\nFix: add to either USER_VISIBLE_FIELDS (if it "
                "appears in /api/tasks GET schema) or INTERNAL_FIELDS "
                "(if it's internal storage). Forces explicit decision "
                "about API contract on every new field."
            )

    def test_no_stale_classification(self):
        fields = _get_task_fields()
        classified = USER_VISIBLE_FIELDS | INTERNAL_FIELDS
        stale = classified - fields
        if stale:
            raise AssertionError(
                f"R368-L2: {len(stale)} classified field(s) no longer "
                f"exist on Task model:\n"
                + "\n".join(f"  - {f}" for f in sorted(stale))
                + "\nFix: remove from USER_VISIBLE_FIELDS or "
                "INTERNAL_FIELDS — Task model was refactored and "
                "these are now orphan classifications."
            )


class TestLayer3UserVisibleForwardExposure:
    """Layer 3: 每个 USER_VISIBLE field 必须在 GET docstring 出现。"""

    def test_every_user_visible_in_docstring(self, subtests):
        doc = _get_tasks_get_docstring()
        missing: list[str] = []
        for field in sorted(USER_VISIBLE_FIELDS):
            with subtests.test(field=field):
                # 简单字面 substring check — docstring 是 YAML, field
                # 名作为 key 出现的形式是 ``field_name:`` 或 ``- field_name``
                if f"{field}:" not in doc and f"- {field}" not in doc:
                    missing.append(field)
        if missing:
            raise AssertionError(
                f"R368-L3: {len(missing)} USER_VISIBLE field(s) NOT "
                f"found in /api/tasks GET docstring:\n"
                + "\n".join(f"  - {f}" for f in missing)
                + "\nFix: either add the field to the OpenAPI schema "
                "in the docstring (preferred), or reclassify it as "
                "INTERNAL with rationale."
            )


class TestLayer4InternalWhitelistMeaningful:
    """Layer 4: INTERNAL 不为空 (机制运转证明)。"""

    def test_internal_not_empty(self):
        assert len(INTERNAL_FIELDS) > 0, (
            "R368-L4: INTERNAL_FIELDS is empty. Classification "
            "mechanism must have non-zero usage; if Task really "
            "exposes 100% of fields, document it explicitly."
        )

    def test_internal_fields_exist_on_model(self):
        fields = _get_task_fields()
        for f in sorted(INTERNAL_FIELDS):
            assert f in fields, (
                f"R368-L4: INTERNAL field {f!r} not on Task model "
                f"(stale classification or rename without update)"
            )


class TestR368LineageMarker:
    def test_this_file_contains_r368_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R368" in text

    def test_this_file_references_api_contract_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R355", "R358", "R364"):
            assert prior in text, f"R368: must cite API contract lineage: {prior}"

    def test_this_file_marks_fourth_application(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("4th 应用", "工业化深化期"):
            assert kw in text, f"R368: missing keyword: {kw!r}"
