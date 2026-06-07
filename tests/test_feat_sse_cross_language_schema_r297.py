"""R297: SSE event payload schema cross-language invariant 测试。

cycle-29 #B (cr58 §5)：当前 SSE event payload schema 只有 Python-side
source of truth (`src/ai_intervention_agent/sse_event_schemas.py`)，**JS
端 (`static/js/multi_task.js`) 没有 schema 镜像**。这导致 2 类风险:

1. **Python schema 加新 event_type / 字段**，但 JS 端漏接 handler →
   功能 silent 退化（heartbeat 没人监听 / config_changed 不弹 toast）。
2. **JS 端用 `detail.fieldName` 读字段**，但 Python schema 没声明该
   字段 → 字段实际为 undefined 但 UI 不报错，silent UI bug。

R197 / R198 已经覆盖了 Python-side schema validation 与 emit-site AST
guard，但**没有 cross-language reach 检查**。R297 补齐这层守护。

================================================================
| 检查维度                              | tests count |
|--------------------------------------|-------------|
| 1. JS handler 集 ⊆ Python schema ∪ 内置 | 3           |
| 2. Python schema 必须有 JS handler (除内置) | 3       |
| 3. JS 读字段 ⊆ Python schema 字段       | 4           |
| 4. Python schema 字段 ⊆ JS 读字段 (除可选) | 3        |
| 5. 内置 SSE 事件 (heartbeat/gap_warning) 必须有 JS handler | 2 |
================================================================
| 合计                                  | 15          |
================================================================

**新 pattern**: **cross-language schema coverage invariant**
(methodology v3.6 推荐 pattern #2 - cross-language event payload)
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"

from ai_intervention_agent.sse_event_schemas import EVENT_SCHEMAS

MULTI_TASK_JS = SRC / "static" / "js" / "multi_task.js"


# 内置 SSE bus 事件 (非 emit 路径)：
# - heartbeat: q.get 超时时 generator yield 的 keep-alive 帧 (R51-B)
# - gap_warning: subscribe(after_id=N) 命中 evict 时塞入的补偿事件 (R40-S2)
_BUILTIN_SSE_EVENTS = frozenset({"heartbeat", "gap_warning"})

# Server-only events: Python emit 出去, 但**仅用于运维/observability**,
# 客户端 UI 不需要 handler (e.g. oversize_drop 是 bus 自我警告;
# log_level_changed 是 future 用 admin dashboard, 当前无 client UI)
_SERVER_ONLY_EVENTS = frozenset({"oversize_drop", "log_level_changed"})


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    """剥离 JS 注释（保留字符串内的 //）。"""
    out = re.sub(r"/\*[\s\S]*?\*/", "", src)
    cleaned: list[str] = []
    for line in out.split("\n"):
        in_str: str | None = None
        i = 0
        n = len(line)
        cut = n
        while i < n:
            c = line[i]
            if in_str:
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            else:
                if c in ('"', "'", "`"):
                    in_str = c
                elif c == "/" and i + 1 < n and line[i + 1] == "/":
                    cut = i
                    break
            i += 1
        cleaned.append(line[:cut])
    return "\n".join(cleaned)


def _extract_js_event_handlers(js: str) -> set[str]:
    """提取所有 `source.addEventListener("event_name", ...)` 的 event_name。"""
    cleaned = _strip_js_comments(js)
    matches = re.findall(
        r'source\.addEventListener\(\s*["\']([a-z_][a-z0-9_]*)["\']', cleaned
    )
    return set(matches)


def _extract_js_detail_fields(js: str, event_name: str) -> set[str]:
    """从指定 event handler 函数体内提取 `detail.fieldName` 字段读取。

    限制：只看 handler 函数闭合大括号内的字段访问。简化为
    `addEventListener("event_name", ...) { ... }` 之间的内容（含嵌套，
    用 brace counting 收尾）。
    """
    cleaned = _strip_js_comments(js)
    m = re.search(
        rf'source\.addEventListener\(\s*["\']{re.escape(event_name)}["\']\s*,\s*function[^{{]*\{{',
        cleaned,
    )
    if m is None:
        return set()
    body_start = m.end() - 1
    depth = 0
    i = body_start
    while i < len(cleaned):
        c = cleaned[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                body = cleaned[body_start : i + 1]
                fields = re.findall(r"\bdetail\.([a-z_][a-z0-9_]*)", body)
                return set(fields)
        i += 1
    return set()


# ============================================================
# #1: JS handler 集 ⊆ Python schema ∪ 内置事件
#    防止 JS 监听 Python 不发出的 event (typo / 残留代码)
# ============================================================
class TestJsHandlerSubsetOfPythonSchema(unittest.TestCase):
    """JS addEventListener 集必须 ⊆ Python schema keys ∪ 内置 SSE 事件"""

    def setUp(self) -> None:
        self.js = _read(MULTI_TASK_JS)
        self.js_handlers = _extract_js_event_handlers(self.js)
        self.python_events = set(EVENT_SCHEMAS.keys())
        self.allowed = self.python_events | _BUILTIN_SSE_EVENTS

    def test_js_handler_count_nonzero(self) -> None:
        """至少必须 extract 出几个 handler，否则正则 broken。"""
        self.assertGreaterEqual(
            len(self.js_handlers),
            3,
            f"multi_task.js 必须有 >= 3 个 addEventListener (task_changed / "
            f"config_changed / heartbeat 最起码)，实际找到: {self.js_handlers}",
        )

    def test_no_orphan_js_handlers(self) -> None:
        """JS 监听的每个 event 都必须是 Python emit 或 SSE bus 内置事件。"""
        orphans = self.js_handlers - self.allowed
        self.assertEqual(
            orphans,
            set(),
            f"R297: JS multi_task.js 监听了 {orphans} 但 Python 既不在 "
            f"EVENT_SCHEMAS 也不是 SSE bus 内置事件 → typo 或 dead code。",
        )

    def test_handler_names_are_lowercase_snake(self) -> None:
        """所有 SSE event_name 必须 snake_case (lowercase + underscore)。"""
        for name in self.js_handlers:
            self.assertRegex(
                name,
                r"^[a-z][a-z0-9_]*$",
                f"R297: JS handler event_name {name!r} 不符合 snake_case 规范",
            )


# ============================================================
# #2: Python schema 必须有 JS handler (除内部 server-only)
#    防止 Python 加新 event 但 JS 漏接 → silent feature loss
# ============================================================
class TestPythonSchemaHasJsHandler(unittest.TestCase):
    """Python EVENT_SCHEMAS keys (除 server-only) 必须每个都有 JS handler"""

    def setUp(self) -> None:
        self.js_handlers = _extract_js_event_handlers(_read(MULTI_TASK_JS))
        self.python_events = set(EVENT_SCHEMAS.keys())

    def test_client_consumed_events_have_js_handler(self) -> None:
        client_events = self.python_events - _SERVER_ONLY_EVENTS
        missing = client_events - self.js_handlers
        self.assertEqual(
            missing,
            set(),
            f"R297: Python EVENT_SCHEMAS 注册了 {missing} 但 JS multi_task.js "
            f"没有 addEventListener handler → 该 event 在前端 silent 丢失。"
            f"\n如果是 server-only event 请加入 _SERVER_ONLY_EVENTS 白名单。"
            f"\n当前 client_events: {client_events}, js_handlers: {self.js_handlers}",
        )

    def test_server_only_events_are_in_schema(self) -> None:
        """_SERVER_ONLY_EVENTS 必须在 Python EVENT_SCHEMAS 注册 (避免 stale 白名单)。"""
        not_in_schema = _SERVER_ONLY_EVENTS - self.python_events
        self.assertEqual(
            not_in_schema,
            set(),
            f"R297: _SERVER_ONLY_EVENTS 中 {not_in_schema} 不在 EVENT_SCHEMAS。"
            f"白名单 stale → 清理 _SERVER_ONLY_EVENTS 或在 schema 中重新注册。",
        )

    def test_no_overlap_builtin_vs_schema(self) -> None:
        """内置 SSE 事件不应该也注册在 Python EVENT_SCHEMAS (语义冲突)。"""
        overlap = _BUILTIN_SSE_EVENTS & set(EVENT_SCHEMAS.keys())
        self.assertEqual(
            overlap,
            set(),
            f"R297: SSE 内置事件 {overlap} 同时在 EVENT_SCHEMAS 注册 → "
            f"语义不清, bus 不通过 emit() 路径发它们, schema 不适用。",
        )


# ============================================================
# #3: JS handler 读的字段 ⊆ Python schema (required ∪ optional)
#    防止 JS 读未定义字段 → undefined silent UI bug
# ============================================================
class TestJsFieldsSubsetOfSchema(unittest.TestCase):
    """JS handler body 内 `detail.fieldName` 必须 ⊆ Python schema 字段"""

    def setUp(self) -> None:
        self.js = _read(MULTI_TASK_JS)
        self.python_events = set(EVENT_SCHEMAS.keys())

    def test_task_changed_js_fields_subset(self) -> None:
        if "task_changed" not in self.python_events:
            self.skipTest("task_changed not in EVENT_SCHEMAS")
        js_fields = _extract_js_detail_fields(self.js, "task_changed")
        schema = EVENT_SCHEMAS["task_changed"]
        allowed = schema.required_fields | schema.optional_fields
        unknown = js_fields - allowed
        self.assertEqual(
            unknown,
            set(),
            f"R297: JS task_changed handler 读 {unknown} 但 Python schema "
            f"未声明 → undefined silent UI bug。schema fields: {allowed}",
        )

    def test_config_changed_js_fields_subset(self) -> None:
        if "config_changed" not in self.python_events:
            self.skipTest("config_changed not in EVENT_SCHEMAS")
        js_fields = _extract_js_detail_fields(self.js, "config_changed")
        schema = EVENT_SCHEMAS["config_changed"]
        allowed = schema.required_fields | schema.optional_fields
        unknown = js_fields - allowed
        self.assertEqual(
            unknown,
            set(),
            f"R297: JS config_changed handler 读 {unknown} 但 Python schema "
            f"未声明 → undefined silent UI bug。schema fields: {allowed}",
        )

    def test_task_changed_required_fields_all_read_by_js(self) -> None:
        """task_changed 的 required 字段必须全部被 JS 读到 (否则 Python emit 浪费)。"""
        if "task_changed" not in self.python_events:
            self.skipTest("task_changed not in EVENT_SCHEMAS")
        js_fields = _extract_js_detail_fields(self.js, "task_changed")
        schema = EVENT_SCHEMAS["task_changed"]
        missing = schema.required_fields - js_fields
        self.assertEqual(
            missing,
            set(),
            f"R297: Python task_changed required {schema.required_fields} "
            f"但 JS 漏读 {missing} → emit 浪费/前端 dead path。"
            f"\nJS 读到: {js_fields}",
        )

    def test_field_names_are_snake_case(self) -> None:
        """所有 schema 字段名必须 snake_case (与 JS 端访问语义一致)。"""
        for event_type, schema in EVENT_SCHEMAS.items():
            all_fields = schema.required_fields | schema.optional_fields
            for field_name in all_fields:
                self.assertRegex(
                    field_name,
                    r"^[a-z][a-z0-9_]*$",
                    f"R297: schema {event_type!r} 字段 {field_name!r} 不符合 snake_case",
                )


# ============================================================
# #4: 内置 SSE 事件必须有 JS handler (heartbeat / gap_warning)
#    它们是 SSE bus 自身契约, 没人监听 = 设计意图丢失
# ============================================================
class TestBuiltinSseEventsHaveJsHandlers(unittest.TestCase):
    """SSE 内置事件 heartbeat / gap_warning 必须有 JS handler"""

    def setUp(self) -> None:
        self.js_handlers = _extract_js_event_handlers(_read(MULTI_TASK_JS))

    def test_heartbeat_has_js_handler(self) -> None:
        self.assertIn(
            "heartbeat",
            self.js_handlers,
            "R297: heartbeat 是 SSE 内置 keep-alive 事件 (R51-B), JS 必须 listen 用于估算 RTT",
        )

    def test_gap_warning_has_js_handler(self) -> None:
        self.assertIn(
            "gap_warning",
            self.js_handlers,
            "R297: gap_warning 是 SSE bus history evict 补偿事件 (R40-S2), JS 必须 listen 用于 full resync",
        )


# ============================================================
# #5: meta - cross-cutting integrity (schema 模块导入与契约稳定)
# ============================================================
class TestSchemaIntegrity(unittest.TestCase):
    """meta-lint: EVENT_SCHEMAS 模块结构 + R297 白名单与现实匹配"""

    def test_schema_has_emitted_by_for_traceability(self) -> None:
        """每个 EVENT_SCHEMAS 条目必须有 emitted_by tuple, 不能为空。"""
        for event_type, schema in EVENT_SCHEMAS.items():
            self.assertGreater(
                len(schema.emitted_by),
                0,
                f"R297: EVENT_SCHEMAS[{event_type!r}].emitted_by 为空 → "
                f"reviewer 无法定位 emit-site",
            )

    def test_server_only_count_makes_sense(self) -> None:
        """_SERVER_ONLY_EVENTS 数量应为 EVENT_SCHEMAS 的子集, 且不超过半数。"""
        self.assertLessEqual(
            len(_SERVER_ONLY_EVENTS),
            len(EVENT_SCHEMAS) // 2 + 1,
            "R297: _SERVER_ONLY_EVENTS 占比过高，大部分 event 应该客户端可消费",
        )


if __name__ == "__main__":
    unittest.main()
