"""R198 / Cycle 7 · SSE event schema registry tests。

锁定 ``sse_event_schemas`` 模块的:

1. **Registry well-formedness**: 每个 ``EVENT_SCHEMAS`` 条目结构合规 (4 cases)
2. **Validation API correctness**: ``validate_payload`` 正确识别 5 类
   违规 (5 cases)
3. **Public API stability**: ``get_known_event_types`` / ``get_schema``
   返回类型契约 (2 cases)
4. **Source-coverage AST guard**: 整 source tree 里所有
   ``_sse_bus.emit("<literal>", ...)`` 调用的 event_type literal **必须
   在 EVENT_SCHEMAS** —— 加新 emit 类型不同步注册的 commit 会被这
   个测试 catch (4 cases)
5. **emit-site payload coverage**: 已知 emit site 的 payload literal
   字段必须 ⊆ required ∪ optional (3 cases)

总计 18 cases。
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.sse_event_schemas import (
    EVENT_SCHEMAS,
    EventSchema,
    get_known_event_types,
    get_schema,
    validate_payload,
)

# ---------------------------------------------------------------------------
# 1. Registry well-formedness
# ---------------------------------------------------------------------------


class TestSchemaRegistryWellFormed(unittest.TestCase):
    def test_all_schemas_are_eventschema_instances(self) -> None:
        for event_type, schema in EVENT_SCHEMAS.items():
            self.assertIsInstance(
                schema, EventSchema, f"{event_type} schema is not EventSchema"
            )

    def test_schema_name_matches_registry_key(self) -> None:
        """``EVENT_SCHEMAS["task_changed"].name == "task_changed"`` 一致, 防止
        future refactor 重命名 dict key 但忘了同步 ``.name``。"""
        for event_type, schema in EVENT_SCHEMAS.items():
            self.assertEqual(
                schema.name,
                event_type,
                f"schema.name {schema.name!r} != registry key {event_type!r}",
            )

    def test_required_and_optional_fields_are_frozenset(self) -> None:
        for event_type, schema in EVENT_SCHEMAS.items():
            self.assertIsInstance(
                schema.required_fields,
                frozenset,
                f"{event_type}.required_fields not frozenset",
            )
            self.assertIsInstance(
                schema.optional_fields,
                frozenset,
                f"{event_type}.optional_fields not frozenset",
            )

    def test_required_and_optional_fields_disjoint(self) -> None:
        """同一字段不应同时出现在 required 和 optional ——逻辑 confusion。"""
        for event_type, schema in EVENT_SCHEMAS.items():
            overlap = schema.required_fields & schema.optional_fields
            self.assertEqual(
                overlap,
                frozenset(),
                f"{event_type}: fields {overlap} appear in BOTH required and optional",
            )


# ---------------------------------------------------------------------------
# 2. validate_payload correctness
# ---------------------------------------------------------------------------


class TestValidatePayload(unittest.TestCase):
    def test_valid_payload_returns_empty_violations(self) -> None:
        violations = validate_payload(
            "task_changed",
            {
                "task_id": "t1",
                "old_status": "pending",
                "new_status": "active",
            },
        )
        self.assertEqual(violations, [])

    def test_valid_payload_with_optional_field(self) -> None:
        violations = validate_payload(
            "task_changed",
            {
                "task_id": "t1",
                "old_status": "pending",
                "new_status": "active",
                "stats": {"active": 1, "pending": 0},
            },
        )
        self.assertEqual(violations, [])

    def test_missing_required_field_flagged(self) -> None:
        violations = validate_payload(
            "task_changed",
            {"task_id": "t1", "old_status": "pending"},  # missing new_status
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("new_status", violations[0])

    def test_unexpected_field_flagged(self) -> None:
        violations = validate_payload(
            "task_changed",
            {
                "task_id": "t1",
                "old_status": "pending",
                "new_status": "active",
                "evil_drift_field": "oops",
            },
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("evil_drift_field", violations[0])

    def test_unknown_event_type_flagged(self) -> None:
        violations = validate_payload("totally_made_up", {"foo": "bar"})
        self.assertEqual(len(violations), 1)
        self.assertIn("unknown event_type", violations[0])


# ---------------------------------------------------------------------------
# 3. Public API stability
# ---------------------------------------------------------------------------


class TestPublicApiContract(unittest.TestCase):
    def test_get_known_event_types_returns_sorted_tuple(self) -> None:
        result = get_known_event_types()
        self.assertIsInstance(result, tuple)
        self.assertEqual(
            list(result),
            sorted(result),
            "get_known_event_types should return alphabetical tuple",
        )
        # 当前应该至少有 4 个 (task_changed / config_changed /
        # log_level_changed / oversize_drop)
        self.assertGreaterEqual(len(result), 4)

    def test_get_schema_returns_none_for_unknown_event(self) -> None:
        self.assertIsNone(get_schema("not_a_real_event_type"))
        self.assertIsNotNone(get_schema("task_changed"))


# ---------------------------------------------------------------------------
# 4. Source-coverage AST guard
# ---------------------------------------------------------------------------


def _find_sse_emit_call_sites_in_source_tree() -> list[tuple[str, int, str | None]]:
    """扫整个 ``src/ai_intervention_agent/`` source tree, 找所有
    ``_sse_bus.emit(...)`` / ``sse_bus.emit(...)`` 调用。

    返回 ``(file_path, lineno, event_type_literal_or_None)`` 三元组列表。
    ``event_type_literal`` 是首参数 (字符串 literal); 如果 emit 用变量
    传递, literal 是 None (跳过 ——AST 静态识别不了 dynamic event type)。
    """
    src_root = REPO_ROOT / "src" / "ai_intervention_agent"
    results: list[tuple[str, int, str | None]] = []
    for py_file in src_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # 期望: ``something.emit(...)`` 且 something attribute 名包含 ``sse_bus``
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "emit":
                continue
            # value 应该是 ``_sse_bus`` / ``sse_bus`` (Name or Attribute)
            value_node = node.func.value
            value_name: str | None = None
            if isinstance(value_node, ast.Name):
                value_name = value_node.id
            elif isinstance(value_node, ast.Attribute):
                value_name = value_node.attr
            if value_name is None or "sse_bus" not in value_name:
                continue
            # 首参数 = event_type
            event_literal: str | None = None
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                event_literal = node.args[0].value
            rel_path = py_file.relative_to(REPO_ROOT).as_posix()
            results.append((rel_path, node.lineno, event_literal))
    return results


class TestSourceCoverageAstGuard(unittest.TestCase):
    """整 source tree 里所有 ``_sse_bus.emit("<literal>", ...)`` 调用的
    event_type literal 必须在 ``EVENT_SCHEMAS``。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.call_sites = _find_sse_emit_call_sites_in_source_tree()

    def test_finds_at_least_known_emit_call_sites(self) -> None:
        """sanity: 至少找到我们已知的 3 个 emit (task / config / log_level)。
        如果未来重构把 emit 改名 (比如统一到 ``sse_bus.send``), 这个测试
        会先 fail 提示。"""
        literals = [t[2] for t in self.call_sites if t[2] is not None]
        self.assertGreaterEqual(
            len(literals),
            3,
            f"expected ≥3 known _sse_bus.emit literal call sites, "
            f"found {len(literals)}; full list: {self.call_sites!r}",
        )

    def test_every_literal_event_type_is_registered(self) -> None:
        """每个 ``_sse_bus.emit("<literal>", ...)`` 调用的 event_type
        literal 必须在 ``EVENT_SCHEMAS``。新加 emit type 而忘了同步注册
        的 commit 会在这里 fail。"""
        known_types = set(EVENT_SCHEMAS)
        for file_path, lineno, literal in self.call_sites:
            if literal is None:
                # dynamic event type (变量传参) —— 静态识别不了, 跳过
                continue
            self.assertIn(
                literal,
                known_types,
                f"{file_path}:{lineno} emits event_type {literal!r} "
                "which is NOT in EVENT_SCHEMAS — register it in "
                "sse_event_schemas.py before merging.",
            )

    def test_no_emit_without_event_type_literal(self) -> None:
        """``_sse_bus.emit(variable, ...)`` 形式只允许 bus 内部 oversize_drop
        替换路径 (line 414 替换 event_type 后调用)。所有 *feature* emit
        都应该用 string literal —— 利于 AST guard 锁定 contract。"""
        non_literal_sites = [(f, ln) for (f, ln, lit) in self.call_sites if lit is None]
        # 期望: 没有 feature code 用 variable event_type
        # 实际可能有 0 个 (本测试更多是 documentation guard, 防止以后
        # 有人偷工省事把 event_type 改成变量)
        for file_path, lineno in non_literal_sites:
            # 允许的例外: web_ui_routes/task.py 内部 emit (bus 实现自身)
            self.assertEqual(
                file_path,
                "src/ai_intervention_agent/web_ui_routes/task.py",
                f"{file_path}:{lineno} uses variable event_type — feature "
                "emit code should use string literals for AST guard. "
                "If you really need dynamic event_type, document in "
                "the source comment and add the exception path here.",
            )

    def test_every_known_emit_site_module_path_recorded_in_schema(self) -> None:
        """每个 emit 站的 module path 必须出现在它发出的 event 的
        ``EventSchema.emitted_by`` tuple 里。如果未来把 emit 移到别的
        module 而忘了同步 schema, 测试会 fail 提示。"""
        for file_path, lineno, literal in self.call_sites:
            if literal is None:
                continue
            schema = EVENT_SCHEMAS.get(literal)
            self.assertIsNotNone(
                schema, f"unregistered event {literal!r} (covered by other test)"
            )
            self.assertIn(
                file_path,
                schema.emitted_by,
                f"{file_path}:{lineno} emits {literal!r} but schema's "
                f"emitted_by tuple is {schema.emitted_by!r} — update "
                "sse_event_schemas.py.",
            )


# ---------------------------------------------------------------------------
# 5. emit-site payload coverage (best-effort static check)
# ---------------------------------------------------------------------------


class TestEmitSitePayloadCoverage(unittest.TestCase):
    """检查 src/ 下每个 ``_sse_bus.emit("<literal>", {...dict literal...})``
    的 payload dict literal 字段 ⊆ schema.required ∪ schema.optional。

    只检 dict literal 形式; 变量 payload (像 task.py 的 ``_sse_bus.emit(
    "task_changed", payload)``) 跳过 ——payload 在变量里需要数据流分析,
    本测试不做。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.src_root = REPO_ROOT / "src" / "ai_intervention_agent"

    def _extract_payload_dict_literal_keys(
        self, call_node: ast.Call
    ) -> frozenset[str] | None:
        """如果 emit 的 payload 是 dict literal, 返回 keys (frozenset);
        否则 ``None``。"""
        if len(call_node.args) < 2:
            return None
        payload_node = call_node.args[1]
        if not isinstance(payload_node, ast.Dict):
            return None
        keys: set[str] = set()
        for k in payload_node.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
            else:
                # dynamic key (e.g. ``**spread``) → 放弃 static check
                return None
        return frozenset(keys)

    def test_config_changed_emit_payload_keys_match_schema(self) -> None:
        """``web_ui_config_sync.py`` 里的 config_changed emit payload (dict
        literal) 字段必须 ⊆ schema required ∪ optional, 且必须 ⊇ required。"""
        path = self.src_root / "web_ui_config_sync.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        schema = EVENT_SCHEMAS["config_changed"]
        all_allowed = schema.required_fields | schema.optional_fields
        any_emit_found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "emit"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "config_changed"
            ):
                continue
            keys = self._extract_payload_dict_literal_keys(node)
            if keys is None:
                continue
            any_emit_found = True
            self.assertTrue(
                keys.issubset(all_allowed),
                f"config_changed emit at line {node.lineno} has fields "
                f"{keys - all_allowed} not in schema (allowed: "
                f"{all_allowed!r})",
            )
            self.assertTrue(
                schema.required_fields.issubset(keys),
                f"config_changed emit at line {node.lineno} missing "
                f"required {schema.required_fields - keys}",
            )
        self.assertTrue(
            any_emit_found,
            "no config_changed dict-literal emit found in web_ui_config_sync.py",
        )

    def test_log_level_changed_emit_payload_keys_match_schema(self) -> None:
        path = self.src_root / "web_ui_routes" / "system.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        schema = EVENT_SCHEMAS["log_level_changed"]
        all_allowed = schema.required_fields | schema.optional_fields
        any_emit_found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "emit"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "log_level_changed"
            ):
                continue
            keys = self._extract_payload_dict_literal_keys(node)
            if keys is None:
                continue
            any_emit_found = True
            self.assertTrue(
                keys.issubset(all_allowed),
                f"log_level_changed emit at line {node.lineno} has fields "
                f"{keys - all_allowed} not in schema (allowed: "
                f"{all_allowed!r})",
            )
            self.assertTrue(
                schema.required_fields.issubset(keys),
                f"log_level_changed emit at line {node.lineno} missing "
                f"required {schema.required_fields - keys}",
            )
        self.assertTrue(
            any_emit_found,
            "no log_level_changed dict-literal emit found in system.py",
        )

    def test_oversize_drop_internal_replacement_payload(self) -> None:
        """``oversize_drop`` 是 bus 内部替换路径, 不在 emit() 调用站点
        看; 通过直接 inspect ``data = {...}`` 赋值看它的 dict literal
        fields。"""
        path = self.src_root / "web_ui_routes" / "task.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        schema = EVENT_SCHEMAS["oversize_drop"]
        all_allowed = schema.required_fields | schema.optional_fields
        # 找 emit(..) function 内紧跟在 event_type = "oversize_drop" 之后
        # 的 data = {...} 赋值。直接简化: 全文搜 dict literal 后 keys
        # 集合刚好等于 ``original_event_type / size_bytes / limit_bytes``。
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            keys: set[str] = set()
            for k in node.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
            if keys == set(schema.required_fields):
                found = True
                self.assertEqual(
                    frozenset(keys),
                    schema.required_fields,
                    "oversize_drop internal data dict keys should match "
                    "schema.required_fields exactly",
                )
                # 不退出 loop —— 可能 task.py 里有多个 dict literals 都
                # 偶然 match 这组 keys; 至少 schema 命中即可。
        self.assertTrue(
            found,
            f"no dict literal with keys == {schema.required_fields!r} found "
            "in web_ui_routes/task.py — oversize_drop replacement data?",
        )


if __name__ == "__main__":
    unittest.main()
