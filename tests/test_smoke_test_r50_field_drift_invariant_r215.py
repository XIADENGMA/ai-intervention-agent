"""R215 / Cycle 10 · F-205-4 · ``scripts/smoke_test_r50.py needed`` ↔
``SSEBusStatsSnapshot`` forward-compat parity invariant。

设计目标
========

``scripts/smoke_test_r50.py`` 在 R47/R50 cycle 写定时, 用一个硬编码
``needed`` 元组验证 ``GET /api/system/sse-stats`` JSON 必须暴露的核心字
段。R205 (cycle 9) 给 ``_SSEBus.stats_snapshot()`` 加了
``schema_validate_mode`` / ``schema_violation_total`` 两个 R205 schema
validation feature 暴露字段, **但 smoke test ``needed`` 列表没同步**。

历史教训剧本 (R215 修复的核心 silent decay 路径)
---------------------------------------------------

如果运维想验证「生产部署的 R205 schema validation feature 还活着吗」：

1. 跑 ``python scripts/smoke_test_r50.py``;
2. smoke 走 ``_check_stats_endpoint()`` -> 检查 ``needed`` 列表 -> 全
   过 -> 输出「✅ smoke 通过」;
3. **但实际上 ``sse_stats`` route 可能被 refactor 误 strip 掉了
   ``schema_validate_mode`` 字段** (e.g. 有人 cleanup 时把 R47 老字段
   whitelist 写死), R205 feature 在 production 已 invisible 但 smoke
   全绿;
4. 运维 alertmanager 也拿不到 ``aiia_sse_schema_violation_total``
   metric → R205 cycle 的 schema 错误检测 silent broken。

这是与 R212 ``TestStatsEndpointJsonRoundTrip`` 同款的 HTTP edge gap：
pytest 测的是 in-process bus.stats_snapshot() Python dict 暴露,
smoke 测的是 HTTP boundary, 两者覆盖维度不同, smoke 必须独立守。

R215 修复
----------

A. 更新 ``smoke_test_r50.py _check_stats_endpoint`` ``needed`` 列表加
   ``schema_validate_mode`` / ``schema_violation_total`` 两字段;
B. 本 invariant test 守 forward-compat parity——一旦未来给
   ``SSEBusStatsSnapshot`` TypedDict 加新的 top-level scalar 字段
   (int / str / bool / float, 不含 nested dict ``emit_by_type`` /
   ``latency_ms`` —— 这些 smoke 不深入校验)，本 test 会强制 smoke
   ``needed`` 列表也加上, 防止 silent drift。

设计契约
========

1. **R205 字段强制守 (硬编码守)**: smoke ``needed`` 必须包含
   ``schema_validate_mode`` + ``schema_violation_total`` 字面字符串。
   反向 regression 守: 防止有人误删 R215 改动让 smoke 退化到 R50
   原始覆盖范围。

2. **TypedDict scalar 字段全覆盖**: smoke ``needed`` 必须涵盖
   ``SSEBusStatsSnapshot.__annotations__`` 中所有 scalar 类型字段
   (int / str / bool / float), 不允许 missing。允许 needed 包含 dict
   类型 (向后兼容); 但 dict 字段不要求 smoke 校验存在性 (smoke 只
   校验 keys, dict 字段存在性应由 in-process pytest 守)。

3. **needed 元素都是字符串**: 防止 needed = (1, 2) 这种语法错误未被
   pytest 抓到。

4. **HEAD-of-line 字段保持**: ``emit_total`` / ``latest_event_id``
   两个 R47 原始字段必须仍在 needed 中 (这是 SSE bus 最基础的两个
   counter, smoke 不能跳过)。

实施于 2026-05-14, 共 6 个测试用例 (3 类 invariant)。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_PY = REPO_ROOT / "scripts" / "smoke_test_r50.py"
TASK_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"

R205_REQUIRED_KEYS = ("schema_validate_mode", "schema_violation_total")
HEAD_OF_LINE_KEYS = ("emit_total", "latest_event_id")


def _extract_needed_tuple_from_smoke() -> tuple[str, ...]:
    """从 smoke_test_r50.py 中 AST-parse ``_check_stats_endpoint`` 函数体里
    的 ``needed = (...)`` 元组字面量, 返回字符串元素列表。

    用 AST 而非 regex 是为了:
    1. 容错: 注释 / 多行 / trailing comma 都不影响;
    2. 类型安全: 只接受字面字符串元素, 拒绝表达式 / 变量引用 (防止有人
       把 needed 写成 ``needed = OLD + NEW`` 这种动态构造导致 invariant
       难以静态检查);
    3. 与 ``check_changelog_diff_scope.py`` 等其它 invariant scanner 风格
       一致。

    找不到 / 解析失败 → AssertionError, 让测试给出明确诊断信息。
    """
    source = SMOKE_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SMOKE_PY))

    func_node: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_check_stats_endpoint":
            func_node = node
            break
    if func_node is None:
        raise AssertionError(
            "smoke_test_r50.py 必须存在 _check_stats_endpoint 函数 (R215 invariant)"
        )

    for stmt in func_node.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not (len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)):
            continue
        if stmt.targets[0].id != "needed":
            continue
        if not isinstance(stmt.value, ast.Tuple):
            raise AssertionError(
                f"_check_stats_endpoint.needed 必须是 tuple 字面量, "
                f"实际是 {type(stmt.value).__name__} (R215 静态检查依赖此结构)"
            )
        elements: list[str] = []
        for elt in stmt.value.elts:
            if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
                raise AssertionError(
                    f"_check_stats_endpoint.needed 元素必须是字面字符串, "
                    f"实际是 {ast.dump(elt)} (R215 拒绝动态构造)"
                )
            elements.append(elt.value)
        return tuple(elements)

    raise AssertionError(
        "_check_stats_endpoint 函数体中必须有 `needed = (...)` 元组字面赋值"
    )


def _extract_sse_bus_typeddict_scalar_keys() -> set[str]:
    """从 task.py 中 AST-parse ``SSEBusStatsSnapshot`` TypedDict, 返回
    其中所有 scalar 类型 (int / str / bool / float) 字段名集合。

    nested 类型 (e.g. ``dict[str, int]`` / ``SSELatencySnapshot`` /
    带 generic 参数的容器) 不算 scalar, 不返回——这些应由 in-process
    pytest 守, smoke test 只校验 scalar 字段存在性。
    """
    source = TASK_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(TASK_PY))

    scalar_type_names = {"int", "str", "bool", "float"}
    scalar_keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name != "SSEBusStatsSnapshot":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign):
                continue
            if not isinstance(stmt.target, ast.Name):
                continue
            ann = stmt.annotation
            if isinstance(ann, ast.Name) and ann.id in scalar_type_names:
                scalar_keys.add(stmt.target.id)
        break
    return scalar_keys


class TestR205RequiredKeysHardcoded(unittest.TestCase):
    """硬编码守: smoke needed 必须包含 R205 两字段字面字符串。

    这是 R215 修复的核心断言——防止反向 regression (有人 cleanup smoke
    时 mistakenly 删掉 R205 字段守回 R50 cycle 原始覆盖)。
    """

    def setUp(self) -> None:
        self.needed = _extract_needed_tuple_from_smoke()

    def test_smoke_needed_includes_schema_validate_mode(self) -> None:
        self.assertIn(
            "schema_validate_mode",
            self.needed,
            "smoke_test_r50.py needed 必须包含 R205 'schema_validate_mode' 字段。"
            "缺失会让 smoke 无法守 R205 schema validation feature 在 production "
            "/api/system/sse-stats 真的暴露 — silent decay risk (见模块 docstring)。",
        )

    def test_smoke_needed_includes_schema_violation_total(self) -> None:
        self.assertIn(
            "schema_violation_total",
            self.needed,
            "smoke_test_r50.py needed 必须包含 R205 'schema_violation_total' 字段 "
            "(R207 Prometheus mirror 的 in-process counter)。"
            "缺失会让 smoke 无法守 R207 alertmanager rule 数据源完整性。",
        )


class TestTypedDictScalarParity(unittest.TestCase):
    """forward-compat parity: 一旦 SSEBusStatsSnapshot 加新的 scalar
    字段, smoke needed 必须同步加, 否则本 test 立刻 fail 强制同步。
    """

    def setUp(self) -> None:
        self.needed = set(_extract_needed_tuple_from_smoke())
        self.scalar_keys = _extract_sse_bus_typeddict_scalar_keys()

    def test_all_typeddict_scalar_keys_covered_by_smoke(self) -> None:
        """每个 SSEBusStatsSnapshot 中 scalar 字段都必须在 smoke needed 里。"""
        # 至少抓到几个 scalar key 才算 AST parsing 成功; 否则可能 TypedDict
        # 结构变了 (e.g. 改成 dataclass) 导致本 test 误绿。
        self.assertGreaterEqual(
            len(self.scalar_keys),
            6,
            f"SSEBusStatsSnapshot scalar 字段抓取结果异常 ({self.scalar_keys!r}), "
            "可能 TypedDict 类已被重构 — 请修复本 test 的 AST parsing 逻辑而不是绕过。",
        )
        missing = self.scalar_keys - self.needed
        self.assertFalse(
            missing,
            f"SSEBusStatsSnapshot 中的 scalar 字段 {sorted(missing)!r} 没在 smoke "
            "needed 列表里。R215 invariant 要求 smoke ``_check_stats_endpoint`` "
            "守 stats_snapshot 全部 top-level scalar 字段, 防止 sse_stats route "
            "被 refactor 误 strip 字段时 smoke 全绿但 production 字段已消失。"
            "\n修复: 把 missing 字段加到 scripts/smoke_test_r50.py 的 needed 元组。",
        )

    def test_head_of_line_keys_present(self) -> None:
        """R47 原始的两个 head-of-line 字段必须仍在 needed (smoke 最基础 SSE counter)。"""
        for key in HEAD_OF_LINE_KEYS:
            with self.subTest(key=key):
                self.assertIn(
                    key,
                    self.needed,
                    f"smoke needed 必须保留 R47 head-of-line 字段 '{key}', "
                    "这是 SSE bus 最基础的 counter, smoke 跳过它就失去意义。",
                )


class TestNeededTupleStructure(unittest.TestCase):
    """结构校验: needed 必须是字面 tuple of str, 拒绝动态构造。"""

    def test_needed_is_nonempty_str_tuple(self) -> None:
        needed = _extract_needed_tuple_from_smoke()
        self.assertIsInstance(needed, tuple)
        self.assertGreater(
            len(needed), 5, f"smoke needed 至少守 6 个核心字段 (实际 {len(needed)})"
        )
        for item in needed:
            self.assertIsInstance(item, str, f"needed 元素 {item!r} 必须是 str")


if __name__ == "__main__":
    unittest.main()
