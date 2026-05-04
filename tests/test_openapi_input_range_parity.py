"""``web_ui_routes/*.py`` OpenAPI input spec 的数值边界必须与
``shared_types.SECTION_MODELS`` 的 Pydantic ``BeforeValidator`` 一致。

历史背景：
- 三个端点接受同一个语义字段 ``auto_resubmit_timeout`` /
  ``frontend_countdown``：
    1. ``POST /api/add-task`` (web_ui_routes/task.py)
    2. ``POST /api/update-feedback`` (web_ui_routes/feedback.py)
    3. ``POST /api/update-feedback-config`` (web_ui_routes/notification.py)
  其中 (3) 已正确写出 ``minimum: 0`` + ``maximum: 3600``。
- 而 (1) (2) 的 OpenAPI input spec 长期只有 ``type: number`` +
  ``description``，没有 ``minimum`` / ``maximum``。
- 这意味着任何按 OpenAPI 规范生成 client / 跑 swagger-validator 的
  下游消费者，都看不到边界约束——必须看 description 文字才知道
  范围 [10, 3600]。属于 OpenAPI 工具链眼里的"无边界"，是文档面的
  silent truncation 等价物。
- v1.5.x round-8 audit 把 (1) (2) 补齐；本测试锁住该对齐不再回退。

实现：
- 用 Python ``ast`` 模块解析 endpoint function 的 docstring。
- 用 ``yaml`` 解析 ``---`` 之后的 OpenAPI block。
- 遍历 properties / 嵌套 schema 找出每一个名字符合
  ``SAME_AS_FEEDBACK_TIMEOUT`` 集合的字段。
- 断言其 ``minimum`` / ``maximum`` 与 ``SECTION_MODELS::feedback.frontend_countdown``
  的 Pydantic ``BeforeValidator`` closure cell 中的边界一致。

边界点：
- 仅校验 ``parameters.in == body`` 中的字段（response schema 中的
  字段没有外部约束意义）。
- 兼容 Pydantic 实际允许的 ``[10, 3600]`` 与 OpenAPI 选用的
  ``[0, 3600]``（其中 0 是"禁用"特殊值，非纯 Pydantic 范围）。
  断言以 ``maximum`` 为锚——它必须严格等于 Pydantic max（3600）；
  ``minimum`` 允许为 0（因为 0 被 task_queue 当作"禁用"处理，
  不进入 ``_clamp_int`` 路径）。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml

from shared_types import SECTION_MODELS
from tests.test_config_docs_range_parity import _introspect_field_bounds

ROUTES_DIR = REPO_ROOT / "web_ui_routes"

# 这些字段在 OpenAPI input spec 中代表 feedback.frontend_countdown 的同义。
# 加新别名时同步 ``server_config`` 的注释——它们都该走相同的 [0, 3600] 边界。
SAME_AS_FEEDBACK_FRONTEND_COUNTDOWN = frozenset(
    {"auto_resubmit_timeout", "frontend_countdown"}
)


def _extract_yaml_blocks(source_path: Path) -> list[dict]:
    """每个 endpoint 函数的 docstring 解析成 OpenAPI dict 列表。

    跳过没有 ``---`` 起始行的 docstring（不是 OpenAPI 块）。
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    blocks: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        # OpenAPI block 起点：``---``（YAML doc 分隔符）。
        m = re.search(r"^\s*---\s*$", doc, flags=re.MULTILINE)
        if not m:
            continue
        yaml_text = doc[m.end() :]
        try:
            spec = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            continue
        if isinstance(spec, dict):
            blocks.append(spec)
    return blocks


def _find_body_property_specs(
    spec: dict, target_names: frozenset[str]
) -> list[tuple[str, dict]]:
    """从 OpenAPI block 中收集 ``parameters[in=body].schema.properties.<name>`` 命中的子 schema。

    返回 ``(field_name, sub_schema_dict)`` 的列表；同一份 spec 同一字段
    多次命中视为多条。
    """
    out: list[tuple[str, dict]] = []
    parameters = spec.get("parameters")
    if not isinstance(parameters, list):
        return out
    for param in parameters:
        if not isinstance(param, dict) or param.get("in") != "body":
            continue
        schema = param.get("schema")
        if not isinstance(schema, dict):
            continue
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        for prop_name, prop_schema in properties.items():
            if prop_name in target_names and isinstance(prop_schema, dict):
                out.append((prop_name, prop_schema))
    return out


def test_all_feedback_countdown_inputs_have_bounds() -> None:
    """三处 ``frontend_countdown`` / ``auto_resubmit_timeout`` 输入都必须有
    与 Pydantic max 相符的 ``maximum``，和合理的 ``minimum``。

    如果未来新增第 4 个 endpoint 接收同一字段，本测试会自动覆盖
    （只要字段名命中 ``SAME_AS_FEEDBACK_FRONTEND_COUNTDOWN``）。
    """
    feedback_bounds = _introspect_field_bounds(SECTION_MODELS["feedback"])
    _, pydantic_max = feedback_bounds["frontend_countdown"]
    found_specs: list[tuple[Path, str, dict]] = []
    for source_path in sorted(ROUTES_DIR.glob("*.py")):
        for spec in _extract_yaml_blocks(source_path):
            for prop_name, prop_schema in _find_body_property_specs(
                spec, SAME_AS_FEEDBACK_FRONTEND_COUNTDOWN
            ):
                found_specs.append((source_path, prop_name, prop_schema))

    assert len(found_specs) >= 3, (
        f"expected ≥3 feedback-countdown input specs across web_ui_routes/, "
        f"got {len(found_specs)}: {[(p.name, n) for p, n, _ in found_specs]}; "
        "did one of the endpoints lose its OpenAPI block?"
    )

    failures: list[str] = []
    for source_path, prop_name, prop_schema in found_specs:
        location = f"{source_path.name}::{prop_name}"
        if "minimum" not in prop_schema:
            failures.append(
                f"{location} missing 'minimum' (expected 0 for disable-sentinel)"
            )
        elif prop_schema["minimum"] != 0:
            failures.append(
                f"{location} minimum={prop_schema['minimum']!r} != 0 "
                "(0 is the documented disable sentinel)"
            )
        if "maximum" not in prop_schema:
            failures.append(
                f"{location} missing 'maximum' (Pydantic side is {pydantic_max})"
            )
        elif prop_schema["maximum"] != pydantic_max:
            failures.append(
                f"{location} maximum={prop_schema['maximum']!r} != Pydantic {pydantic_max}; "
                "OpenAPI clamp would silently truncate values that the schema accepts"
            )

    assert not failures, (
        "OpenAPI feedback-countdown input parity drifted from "
        "shared_types.SECTION_MODELS::feedback:\n  - " + "\n  - ".join(failures)
    )


# ═══════════════════════════════════════════════════════════════════════════
# R13·B3 · OpenAPI response schema 缩进契约
# ═══════════════════════════════════════════════════════════════════════════
def test_get_tasks_response_includes_deadline_under_items_properties() -> None:
    """``GET /api/tasks`` 的 response 中 ``tasks.items.properties.deadline`` 必须存在。

    历史 bug：docstring 里 ``deadline`` 一行的缩进比 ``remaining_time``
    少 2 列，YAML 把它解析成 ``items`` 自己的 key（即和 ``type``/
    ``properties`` 同级），而不是 ``items.properties`` 下的字段。后果：

      tasks:
        items:
          type: object
          properties:           ← 这里 deadline 应该出现
            task_id:
            status:
            ...
            remaining_time:
          deadline:             ← 实际错误位置：items 自己的 key

    swagger UI / OpenAPI client generators 看到的 task 对象 schema 会
    缺失 deadline 字段说明，调用方实现 deserializer 时会忽略它，再加
    上字段名又是合法 YAML key（不会触发 yaml.safe_load 异常），整个
    bug 沉默——本测试直接走 yaml 解析后断言字段位置正确，是这种
    "YAML 合法 / 语义错位" 的最便宜防御。
    """
    source_path = ROUTES_DIR / "task.py"
    blocks = _extract_yaml_blocks(source_path)

    # 找 GET /api/tasks 的 200 响应 schema —— 它的 properties.tasks.items 必须有 deadline。
    target_items_properties: dict | None = None
    for spec in blocks:
        responses = spec.get("responses")
        if not isinstance(responses, dict):
            continue
        ok = responses.get(200)
        if not isinstance(ok, dict):
            continue
        schema = ok.get("schema")
        if not isinstance(schema, dict):
            continue
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        tasks_field = properties.get("tasks")
        if not isinstance(tasks_field, dict):
            continue
        items = tasks_field.get("items")
        if not isinstance(items, dict):
            continue
        items_props = items.get("properties")
        # 仅匹配 task list response：properties 里至少有 task_id + status，
        # 区别于碰巧也带 ``tasks`` 字段的其他 endpoint。
        if (
            isinstance(items_props, dict)
            and "task_id" in items_props
            and "status" in items_props
        ):
            target_items_properties = items_props
            break

    assert target_items_properties is not None, (
        "未在 web_ui_routes/task.py 任何 endpoint 的 responses[200].schema 中找到 "
        "tasks[].items.properties.{task_id,status,...} —— GET /api/tasks 的 OpenAPI "
        "spec 是否被改名/重构？请同步本测试。"
    )

    assert "deadline" in target_items_properties, (
        "`deadline` 必须出现在 ``tasks.items.properties`` 之下；如果你看到这条 "
        "失败信息，先去检查 `web_ui_routes/task.py::get_tasks` 的 docstring，"
        "确认 `deadline:` 这一行的缩进与 `task_id`/`status`/`remaining_time` "
        "对齐（同列）。任何低 2 列以上的缩进都会让 yaml 把它解析为 items 自己 "
        "的 key，swagger UI / OpenAPI client generator 看到的 task schema 就会 "
        "缺失 deadline 字段说明 —— 这是 v1.5.x 修过的回归点。"
    )
