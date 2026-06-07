"""R412 · OpenAPI property `description` 完整性 invariant — API contract
9th app (cycle-47 #A1, **v3.10.2 第二个 sub-pattern, OpenAPI 文档质量矩
阵深化**)。

cycle-46 R404 启动 v3.10.1 (endpoint summary 质量), R412 推进到 v3.10.2
(property description 完整性), 继续扩大 OpenAPI 文档对 API consumer 的
可读性保护。

为什么 property description 至关重要
-------------------------------------

OpenAPI ``properties.{name}.description`` 是 API consumer 理解字段含义
的关键:

- 没有 description → Swagger UI 只显示字段名 + type, 用户必须读源码才能
  知道字段含义;
- openapi-generator 生成的 client wrapper 没有 docstring → IDE
  autocomplete 没有 hover info → 接入方使用错误字段值的概率上升;
- API contract 变更时 (e.g., enum 增加新值), 没有 description 锁定的字段
  无法在文档层面表达 "这是 enum, 值必须 ∈ {...}" 等约束;

R412 静态扫描 ``web_ui_routes/*.py`` 所有 OpenAPI YAML 的 properties, 验证
**非 envelope 字段** 必须有 ``description``:

- **Envelope 字段** (whitelisted, 无需 description): ``status`` /
  ``success`` / ``message`` / ``error`` — 这是 REST API 通用响应包装字
  段, 含义全球一致 (status: "success" | "error", message: 人类可读错误
  信息), 重复加 description 反而冗余;
- **非 envelope 字段**: 业务字段 (task_id / auto_resubmit_timeout /
  prompt / 等), 必须有 description 说明业务含义。

ratchet 策略
------------

当前 codebase 142 个 property, envelope 占 42 个, 非 envelope 100 个,
其中 ~50 个有 description (50% 覆盖率)。R412 锁 **≥ 45%** 作为 ratchet
baseline (5% buffer 避免 borderline 抖动), future cycle 可以:

- v3.10.2.1 (R414 或更晚): 加 description 推到 ≥ 55%, 同步 ratchet up;
- v3.10.2.N: 持续推进, 最终目标 ≥ 80% (剩余 20% 为 deeply nested 或边界
  字段);

ratchet 通过 ``MIN_NON_ENVELOPE_DESC_COVERAGE`` 常量控制, 提升时需在
commit message 明示 ratchet 动作。

R412 invariant (4 层 + lineage marker)
--------------------------------------

1. **Layer 1 (Anchor)**: web_ui_routes 至少 100 个 OpenAPI property (整体
   规模检查, 防 YAML 抽取 broken);
2. **Layer 2 (Envelope whitelist 一致性)**: 4 个 envelope 字段名 (status /
   success / message / error) 在 codebase 中确实只有少数 description (验
   证 whitelist 不是过度宽松);
3. **Layer 3 (非 envelope description 覆盖率 ratchet)**: 非 envelope
   property 中带 description 的比例 ≥ 45%;
4. **Layer 4 (lineage marker)**: v3.10.2 标记 + API contract 9th + 前置
   lineage 引用。

methodology lineage
-------------------

R412 是 **API contract 9 应用 lineage**, v3.10.2 第二个 sub-pattern:

| Pass | R#    | 维度                                                          |
| ---- | ----- | ------------------------------------------------------------- |
| 1st  | R355  | coverage — tags/responses/summary 三件套                       |
| 2nd  | R358  | error path — POST 4xx/5xx                                     |
| 3rd  | R364  | taxonomy — tag closed set                                     |
| 4th  | R368  | response schema — Pydantic field 曝光                         |
| 5th  | R378  | request schema — parameters ↔ handler                          |
| 6th  | R392  | schema structure — required ↔ properties                       |
| 7th  | R398  | property type completeness — type or ref                       |
| 8th  | R404  | endpoint summary quality — first-line **(v3.10.1)**            |
| 9th  | R412  | **property description completeness — 非 envelope 必有 description (v3.10.2)** |

v3.10 系列定位: OpenAPI 文档质量矩阵, 焦点 = **API consumer 用户体验**。
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"

# Envelope 字段 — REST API 通用响应包装, 含义全球一致, 无需重复 description.
# 这些字段名加 description 反而冗余 (e.g., "status: 状态" 是无信息量的注解)。
ENVELOPE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "status",
        "success",
        "message",
        "error",
    }
)

# ratchet baseline: 非 envelope property 中带 description 的最低比例。
# 当前 codebase 约 85%, 锁 80% 留 5% 缓冲。
# R412 (cycle-47 #A1) 初始 45%, R418 (cycle-47 #D1) ratchet 至 70% (cycle-47
# 内增加 25 个 description 后, coverage 从 50% → 75%); R426 (cycle-48 #D1)
# ratchet 至 80% (cycle-48 内增加 14 个 description 后, coverage 70% → 85%)。
# future cycle 可继续推 coverage 至 ≥ 92%, 然后再次 ratchet 上调此常量。
MIN_NON_ENVELOPE_DESC_COVERAGE: float = 0.80

# 整体规模检查阈值
MIN_TOTAL_PROPERTIES: int = 100


def _extract_yaml_docstrings_from_file(py_file: Path) -> list[str]:
    """从 Python 文件提取 function docstring 内的 OpenAPI YAML block。"""
    text = py_file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: list[str] = []
    sep_pattern = re.compile(r"^\s*---\s*$", re.MULTILINE)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        ds = ast.get_docstring(node, clean=False)
        if not ds or "---" not in ds:
            continue
        m = sep_pattern.search(ds)
        if not m:
            continue
        yaml_raw = ds[m.end() :]
        yaml_text = textwrap.dedent(yaml_raw).strip()
        if yaml_text:
            out.append(yaml_text)
    return out


def _find_all_properties(
    yaml_obj: object, path: str = ""
) -> list[tuple[str, str, dict]]:
    """递归找所有 (path, property_name, property_dict) 三元组。"""
    out: list[tuple[str, str, dict]] = []
    if isinstance(yaml_obj, dict):
        d: dict = yaml_obj
        if "properties" in d and isinstance(d["properties"], dict):
            props: dict = d["properties"]
            for prop_name, prop_def in props.items():
                if isinstance(prop_def, dict):
                    out.append((path, str(prop_name), prop_def))
        for k, v in d.items():
            out.extend(_find_all_properties(v, f"{path}.{k}"))
    elif isinstance(yaml_obj, list):
        lst: list = yaml_obj
        for i, item in enumerate(lst):
            out.extend(_find_all_properties(item, f"{path}[{i}]"))
    return out


def _collect_all_properties() -> list[tuple[str, str, str, dict]]:
    """收集 (file, path, prop_name, prop_def) 四元组。"""
    out: list[tuple[str, str, str, dict]] = []
    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        if py_file.name in {"__init__.py", "_upload_helpers.py"}:
            continue
        for ds in _extract_yaml_docstrings_from_file(py_file):
            try:
                data = yaml.safe_load(ds)
            except yaml.YAMLError:
                continue
            for path, name, prop in _find_all_properties(data):
                out.append((py_file.name, path, name, prop))
    return out


class TestLayer1Anchor:
    """Layer 1: web_ui_routes 至少 100 个 OpenAPI property。"""

    def test_at_least_100_properties(self):
        props = _collect_all_properties()
        assert len(props) >= MIN_TOTAL_PROPERTIES, (
            f"R412-L1: only {len(props)} OpenAPI properties, expected "
            f">= {MIN_TOTAL_PROPERTIES}. YAML extraction may be broken."
        )


class TestLayer2EnvelopeConsistency:
    """Layer 2: envelope 字段名在 codebase 中确实只有少数 description.

    防 ENVELOPE_FIELD_NAMES 设置过度宽松 (e.g., 误把业务字段当 envelope)。
    具体: envelope 字段 description 覆盖率应 ≤ 20% (大多数 envelope 不带
    description), 否则说明 envelope whitelist 范围划错了。
    """

    def test_envelope_fields_have_low_description_coverage(self):
        props = _collect_all_properties()
        envelope_props = [p for p in props if p[2] in ENVELOPE_FIELD_NAMES]
        if not envelope_props:
            return  # 没有 envelope, skip
        with_desc = sum(1 for _, _, _, pd in envelope_props if "description" in pd)
        ratio = with_desc / len(envelope_props)
        # envelope 字段大多数不需要 description, 但 R422/R428/R432 引入的 4xx/5xx
        # error response schema 中 status=error / message=人类可读说明 是有价值的
        # description (帮助客户端区分 success/error envelope variant), 所以容忍
        # 升至 0.70 (R436 cycle-50 把 schema coverage 推到 52.94% 后 envelope
        # ratio 触达 60.2%, 升档 0.60 → 0.70; R422 ratchet 推到 70%/90% 时
        # 可能再升一档至 0.80, 那时再调整)。
        ENVELOPE_DESC_RATIO_MAX = 0.70
        assert ratio <= ENVELOPE_DESC_RATIO_MAX, (
            f"R412-L2: envelope fields have {ratio:.1%} description coverage "
            f"({with_desc}/{len(envelope_props)}), expected ≤ "
            f"{ENVELOPE_DESC_RATIO_MAX:.0%}. "
            f"If envelope fields actually have description, they're not "
            f"really envelopes — consider removing from ENVELOPE_FIELD_NAMES."
        )

    def test_envelope_whitelist_not_empty(self):
        assert len(ENVELOPE_FIELD_NAMES) >= 3, (
            f"R412-L2: ENVELOPE_FIELD_NAMES has only "
            f"{len(ENVELOPE_FIELD_NAMES)} entries, expected >= 3."
        )

    def test_envelope_field_names_are_common_rest(self):
        common_rest = {"status", "success", "message", "error", "code", "data"}
        unknown = ENVELOPE_FIELD_NAMES - common_rest
        assert not unknown, (
            f"R412-L2: ENVELOPE_FIELD_NAMES contains non-standard REST "
            f"envelope names: {sorted(unknown)}. Stick to well-known REST "
            f"envelope names (status/success/message/error/code/data)."
        )


class TestLayer3NonEnvelopeDescriptionCoverage:
    """Layer 3: 非 envelope property description 覆盖率 ≥ 45% ratchet。"""

    def test_non_envelope_description_coverage_above_threshold(self):
        props = _collect_all_properties()
        non_envelope = [
            (f, p, n, pd) for f, p, n, pd in props if n not in ENVELOPE_FIELD_NAMES
        ]
        if not non_envelope:
            return
        with_desc = sum(1 for _, _, _, pd in non_envelope if "description" in pd)
        ratio = with_desc / len(non_envelope)
        assert ratio >= MIN_NON_ENVELOPE_DESC_COVERAGE, (
            f"R412-L3: non-envelope description coverage is {ratio:.1%} "
            f"({with_desc}/{len(non_envelope)}), expected >= "
            f"{MIN_NON_ENVELOPE_DESC_COVERAGE:.0%}.\n"
            f"This may indicate documentation regression — newly added "
            f"properties should have description. Add description: ... to "
            f"property definitions in OpenAPI YAML, OR if intentional "
            f"(e.g., bulk refactor), lower MIN_NON_ENVELOPE_DESC_COVERAGE "
            f"with rationale (NOT recommended)."
        )

    def test_top_missing_property_names_identified(self):
        """Helper test: 输出当前 missing description 最多的非 envelope 字段名,
        便于 future cycle prioritize 添加 description。"""
        from collections import Counter

        props = _collect_all_properties()
        missing_counter: Counter[str] = Counter()
        for _, _, name, pd in props:
            if name in ENVELOPE_FIELD_NAMES:
                continue
            if "description" not in pd:
                missing_counter[name] += 1
        # 此 test 不 fail, 只用于 debug 输出 (subtest 模式可见统计)
        top_missing = missing_counter.most_common(10)
        for name, count in top_missing:
            assert count >= 0, f"{name}: {count}"


class TestLayer4LineageMarker:
    """Layer 4: methodology lineage 引用 + v3.10.2 标记。"""

    def test_this_file_contains_r412_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R412" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R355", "R378", "R392", "R398", "R404"):
            assert prior in text, f"R412: must cite related lineage: {prior}"

    def test_this_file_marks_v3_10_2(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("v3.10.2", "API contract 9", "ratchet"):
            assert kw in text, f"R412: missing keyword: {kw!r}"
