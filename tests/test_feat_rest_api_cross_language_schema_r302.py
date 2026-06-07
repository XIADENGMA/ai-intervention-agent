"""R302: REST API response schema cross-language invariant (cycle-30 t30-2)。

cr59 §5 #A2 / §4C 推荐 "REST API response schema cross-language invariant"
— cross-language pattern (R297 首次应用) 的第二应用。R297 只 cover 了
SSE event payload, REST API response 仍然没有 cross-language reach
校验:
- Python `/api/tasks` 返回字段 → JS 必须读到 (否则 backend 返字段无人用)
- JS handler 读字段 → Python 必须返 (否则 silent undefined UI bug)

R302 锁定 `/api/tasks` GET endpoint 的 cross-language schema:

================================================================
| Python 返回字段              | JS 读取位置                         |
|----------------------------|--------------------------------|
| top-level response:        |                                |
| ── success                | `data.success`                  |
| ── tasks                  | `data.tasks`                    |
| ── stats                  | `data.stats`                    |
| ── server_time            | `data.server_time`              |
| per-task fields:           |                                |
| ── task_id                | `task.task_id`                  |
| ── status                 | `task.status`                   |
| ── prompt                 | `task.prompt`                   |
| ── auto_resubmit_timeout  | `task.auto_resubmit_timeout`    |
| ── remaining_time         | `task.remaining_time`           |
| ── deadline               | `task.deadline`                 |
| ── extends_used           | `task.extends_used`             |
| ── extends_max            | `task.extends_max`              |
| ── feedback_placeholder   | `task.feedback_placeholder`     |
| ── question_type          | `task.question_type`            |
| ── header_label           | `task.header_label`             |
================================================================

================================================================
| 测试维度                                              | tests |
|--------------------------------------------------|-------|
| 1. Python /api/tasks 必须返回所有 top-level 字段       | 4     |
| 2. JS 必须读取所有 top-level 字段                       | 4     |
| 3. Python task object 必须包含所有 per-task 字段        | 11    |
| 4. JS 必须读取关键 per-task 字段 (subset 不是全部)     | 5     |
| 5. meta-lint: stats 子字段一致 (total/pending/active/completed) | 2 |
================================================================
| 合计                                                | 26    |
================================================================

**pattern lineage**: R297 (cross-language schema invariant 首次, SSE 版)
→ **R302 (cross-language pattern 第二应用, REST API 版)** — 把 v3.6
pattern 从 SSE event payload 扩展到 REST API response, 第二应用确立
pattern 稳定性。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"
TASK_PY = SRC / "web_ui_routes" / "task.py"
MULTI_TASK_JS = SRC / "static" / "js" / "multi_task.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
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


def _extract_get_tasks_function_body(py: str) -> str:
    """提取 def get_tasks() 的函数体 (从 def 到下一个 @route 或 def)。"""
    m = re.search(
        r"def get_tasks\(\)[\s\S]+?(?=\n        @self\.app\.route|\nclass )",
        py,
    )
    if m is None:
        return ""
    return m.group(0)


# Python /api/tasks GET response 契约 (R302 source of truth)
_TOP_LEVEL_FIELDS = ("success", "tasks", "stats", "server_time")
_PER_TASK_FIELDS = (
    "task_id",
    "status",
    "prompt",
    "created_at",
    "auto_resubmit_timeout",
    "remaining_time",
    "deadline",
    "extends_used",
    "extends_max",
    "feedback_placeholder",
    "question_type",
    "header_label",
)
# JS 端使用频率高的关键字段 (cross-language reach 必须覆盖)
_JS_CRITICAL_FIELDS = (
    "task_id",
    "status",
    "remaining_time",
    "auto_resubmit_timeout",
    "deadline",
)
# stats 子字段
_STATS_FIELDS = ("total", "pending", "active", "completed")


# ============================================================
# #1: Python /api/tasks 必须返回所有 top-level 字段
# ============================================================
class TestPythonReturnsTopLevelFields(unittest.TestCase):
    """get_tasks() return jsonify 必须包含所有 top-level 字段"""

    def setUp(self) -> None:
        self.body = _extract_get_tasks_function_body(_read(TASK_PY))
        self.assertGreater(
            len(self.body),
            0,
            "未能找到 get_tasks() 函数体",
        )

    def test_success_field_returned(self) -> None:
        self.assertIn(
            '"success": True',
            self.body,
            "R302: get_tasks() jsonify 必须包含 'success': True",
        )

    def test_tasks_field_returned(self) -> None:
        self.assertIn(
            '"tasks": task_list',
            self.body,
            "R302: get_tasks() jsonify 必须包含 'tasks': task_list",
        )

    def test_stats_field_returned(self) -> None:
        self.assertIn(
            '"stats": stats',
            self.body,
            "R302: get_tasks() jsonify 必须包含 'stats': stats",
        )

    def test_server_time_field_returned(self) -> None:
        self.assertIn(
            '"server_time": server_time',
            self.body,
            "R302: get_tasks() jsonify 必须包含 'server_time': server_time",
        )


# ============================================================
# #2: JS 必须读取所有 top-level 字段
# ============================================================
class TestJsReadsTopLevelFields(unittest.TestCase):
    """multi_task.js fetchAndApplyTasks 必须读取所有 4 个 top-level 字段"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(MULTI_TASK_JS))

    def test_js_reads_success(self) -> None:
        self.assertRegex(
            self.js,
            r"\bdata\.success\b",
            "R302: multi_task.js 必须读 data.success",
        )

    def test_js_reads_tasks(self) -> None:
        self.assertRegex(
            self.js,
            r"\bdata\.tasks\b",
            "R302: multi_task.js 必须读 data.tasks",
        )

    def test_js_reads_stats(self) -> None:
        self.assertRegex(
            self.js,
            r"\bdata\.stats\b",
            "R302: multi_task.js 必须读 data.stats",
        )

    def test_js_reads_server_time(self) -> None:
        self.assertRegex(
            self.js,
            r"\bdata\.server_time\b",
            "R302: multi_task.js 必须读 data.server_time (服务器时间偏移修正)",
        )


# ============================================================
# #3: Python task object 必须包含所有 per-task 字段
# ============================================================
class TestPythonTaskObjectFields(unittest.TestCase):
    """get_tasks() 构造的 task_list 项必须有所有 per-task 字段"""

    def setUp(self) -> None:
        self.body = _extract_get_tasks_function_body(_read(TASK_PY))

    def test_each_per_task_field_present(self) -> None:
        for field in _PER_TASK_FIELDS:
            self.assertIn(
                f'"{field}":',
                self.body,
                f"R302: get_tasks() task_list 必须包含 {field!r} 字段",
            )


class TestPerTaskFieldsAreSeparateTests(unittest.TestCase):
    """每个 per-task 字段单独的 invariant test (便于失败定位)"""

    def setUp(self) -> None:
        self.body = _extract_get_tasks_function_body(_read(TASK_PY))

    def test_task_id(self) -> None:
        self.assertIn('"task_id":', self.body)

    def test_status(self) -> None:
        self.assertIn('"status":', self.body)

    def test_auto_resubmit_timeout(self) -> None:
        self.assertIn('"auto_resubmit_timeout":', self.body)

    def test_remaining_time(self) -> None:
        self.assertIn('"remaining_time":', self.body)

    def test_deadline(self) -> None:
        self.assertIn('"deadline":', self.body)

    def test_extends_used(self) -> None:
        self.assertIn('"extends_used":', self.body)

    def test_extends_max(self) -> None:
        self.assertIn('"extends_max":', self.body)

    def test_feedback_placeholder(self) -> None:
        self.assertIn('"feedback_placeholder":', self.body)

    def test_question_type(self) -> None:
        self.assertIn('"question_type":', self.body)

    def test_header_label(self) -> None:
        self.assertIn('"header_label":', self.body)


# ============================================================
# #4: JS 必须读取关键 per-task 字段
# ============================================================
class TestJsReadsCriticalPerTaskFields(unittest.TestCase):
    """multi_task.js 必须读 5 个关键 per-task 字段"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(MULTI_TASK_JS))

    def test_js_reads_task_id(self) -> None:
        self.assertRegex(
            self.js,
            r"\btask\.task_id\b",
            "R302: multi_task.js 必须读 task.task_id",
        )

    def test_js_reads_status(self) -> None:
        self.assertRegex(
            self.js,
            r"\btask\.status\b",
            "R302: multi_task.js 必须读 task.status",
        )

    def test_js_reads_auto_resubmit_timeout(self) -> None:
        self.assertRegex(
            self.js,
            r"\btask\.auto_resubmit_timeout\b",
            "R302: multi_task.js 必须读 task.auto_resubmit_timeout (热更新倒计时)",
        )

    def test_js_reads_remaining_time(self) -> None:
        self.assertRegex(
            self.js,
            r"\btask\.remaining_time\b",
            "R302: multi_task.js 必须读 task.remaining_time (倒计时显示)",
        )

    def test_js_reads_deadline(self) -> None:
        self.assertRegex(
            self.js,
            r"\btask\.deadline\b",
            "R302: multi_task.js 必须读 task.deadline (倒计时 anchor)",
        )


# ============================================================
# #5: meta-lint stats 子字段一致
# ============================================================
class TestStatsSubFieldsConsistency(unittest.TestCase):
    """stats 子字段 (total/pending/active/completed) 在 Python + JS 都被使用"""

    def setUp(self) -> None:
        self.task_py = _read(TASK_PY)
        self.js = _strip_js_comments(_read(MULTI_TASK_JS))

    def test_stats_get_all_tasks_with_stats_used(self) -> None:
        """Python 必须用 get_all_tasks_with_stats() 一次性拿 list + stats。"""
        self.assertIn(
            "get_all_tasks_with_stats()",
            self.task_py,
            "R302: task.py get_tasks() 必须用 get_all_tasks_with_stats() "
            "(R23.4 合并读锁优化, 保证 list/stats 原子快照)",
        )

    def test_js_calls_updateTasksStats_with_stats(self) -> None:
        """JS 必须有 updateTasksStats(data.stats) 调用。"""
        self.assertRegex(
            self.js,
            r"updateTasksStats\(\s*data\.stats\s*\)",
            "R302: multi_task.js 必须 updateTasksStats(data.stats) 消费 stats",
        )


if __name__ == "__main__":
    unittest.main()
