"""R296: hot-path perf baseline 常量 cross-source invariant 测试。

cycle-29 #A (cr58 §5)：当前所有 invariant 都是 functional / structural，
**无 performance regression invariant**。例如 SSE heartbeat 从 25s drift
到 5s（变重）或者 cleanup interval 从 5s drift 到 60s（变迟钝），不会被
任何 test 拦下，直到用户在生产里发现"页面卡死/CPU 飙升/任务清不掉"。

R296 锁定 5 个 hot-path perf 常量的跨源一致性：

================================================================
| Const                              | Value | Sources | Tests |
|------------------------------------|-------|---------|-------|
| 1. SSE_HEARTBEAT_TIMEOUT (秒)      | 25    | 2       | 4     |
| 2. TASK_CLEANUP_INTERVAL (秒)      | 5     | 2       | 3     |
| 3. TASK_CLEANUP_AGE_SECONDS (秒)   | 10    | 3       | 4     |
| 4. HOTPATH_CLEANUP_THROTTLE (秒)   | 30.0  | 3       | 4     |
| 5. JS_HEALTH_CHECK_INTERVAL (毫秒) | 30000 | 1       | 3     |
================================================================
| 合计                               |       | 11      | 18    |
================================================================

**为什么这 5 个 const 是 P0**：
- #1 SSE heartbeat: 客户端通过此估算 server liveness; drift → 假死/CPU 飙升
- #2 cleanup interval: 后台清理频率; drift → 任务堆积或 CPU 过载
- #3 cleanup age: completed 任务保留时长; drift → 内存泄漏或 UI 闪烁
- #4 hotpath throttle: hot-path 兜底节流; drift → 每请求都跑 cleanup
- #5 JS health check: 浏览器侧自动重连兜底; drift → 假死无法自愈

**新 pattern**: **perf-baseline invariant**（methodology v3.6 标志性 pattern）
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_python_comments(src: str) -> str:
    """剥离 Python 行注释 `# ...`（保留字符串内的 #）。

    简化策略：行内 `#` 之前的 ' / " 数量奇偶判断（不处理三引号）。
    够 R296 用，因为 task_queue.py / task.py 的 hot-path const 都在
    可执行代码行，不在 docstring 里。
    """
    out_lines: list[str] = []
    for line in src.split("\n"):
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
                if c in ('"', "'"):
                    in_str = c
                elif c == "#":
                    cut = i
                    break
            i += 1
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


def _strip_js_comments(src: str) -> str:
    """剥离 JS 单行 / 多行注释（保留字符串内的 //）。"""
    out = re.sub(r"/\*[\s\S]*?\*/", "", src)
    cleaned_lines: list[str] = []
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
        cleaned_lines.append(line[:cut])
    return "\n".join(cleaned_lines)


# ============================================================
# #1: SSE_HEARTBEAT_TIMEOUT = 25 (秒)
# 锁定: web_ui_routes/task.py 的 q.get(timeout=25)
# 锁定: static/js/multi_task.js 的 "服务端每 25 s 发一帧" 注释 anchor
# ============================================================
class TestSseHeartbeatTimeout25s(unittest.TestCase):
    """SSE heartbeat = 25s (server q.get timeout) cross-source 锁定"""

    EXPECTED = 25

    def setUp(self) -> None:
        self.py = _read(SRC / "web_ui_routes" / "task.py")
        self.js = _read(SRC / "static" / "js" / "multi_task.js")

    def test_python_q_get_timeout_is_25(self) -> None:
        """task.py 必须用 q.get(timeout=25) 而非其他值（hot-path generator）。"""
        code = _strip_python_comments(self.py)
        m = re.search(r"\bq\.get\(\s*timeout\s*=\s*(\d+)\s*\)", code)
        self.assertIsNotNone(m, "task.py generator 必须调用 q.get(timeout=X) 等待事件")
        assert m is not None
        actual = int(m.group(1))
        self.assertEqual(
            actual,
            self.EXPECTED,
            f"R296: SSE heartbeat timeout drift! q.get(timeout={actual}) != {self.EXPECTED}",
        )

    def test_python_heartbeat_total_metric_intact(self) -> None:
        """heartbeat_total Prometheus metric 必须存在（监控锚点不能丢）。"""
        self.assertIn(
            "heartbeat_total",
            self.py,
            "task.py 必须保留 heartbeat_total metric（client 监控 RTT 用）",
        )

    def test_js_documents_25s_interval(self) -> None:
        """JS 注释必须 anchor 25s 频率（client 端 awareness）。"""
        self.assertRegex(
            self.js,
            r"\b25\s*s\b",
            "multi_task.js 注释必须 anchor '25 s' 频率",
        )

    def test_js_heartbeat_event_listener_present(self) -> None:
        """JS 必须有 addEventListener('heartbeat', ...) 否则心跳无意义。"""
        self.assertRegex(
            self.js,
            r"addEventListener\(\s*['\"]heartbeat['\"]",
            "multi_task.js 必须监听 SSE 'heartbeat' named event",
        )


# ============================================================
# #2: TASK_CLEANUP_INTERVAL = 5 (秒)
# 锁定: task_queue.py 的 _stop_cleanup.wait(timeout=5)
# ============================================================
class TestTaskCleanupInterval5s(unittest.TestCase):
    """TaskQueue 后台清理循环 = 5s cross-source 锁定"""

    EXPECTED = 5

    def setUp(self) -> None:
        self.py = _read(SRC / "task_queue.py")

    def test_cleanup_loop_wait_is_5s(self) -> None:
        """_cleanup_loop 必须用 self._stop_cleanup.wait(timeout=5)。"""
        code = _strip_python_comments(self.py)
        m = re.search(r"_stop_cleanup\.wait\(\s*timeout\s*=\s*(\d+)\s*\)", code)
        self.assertIsNotNone(
            m, "task_queue.py _cleanup_loop 必须调用 _stop_cleanup.wait(timeout=X)"
        )
        assert m is not None
        actual = int(m.group(1))
        self.assertEqual(
            actual,
            self.EXPECTED,
            f"R296: cleanup interval drift! wait(timeout={actual}) != {self.EXPECTED}",
        )

    def test_docstring_5seconds_anchor(self) -> None:
        """docstring 必须 anchor 5s 频率（dev awareness）。"""
        self.assertIn(
            "5秒",
            self.py,
            "task_queue.py _cleanup_loop docstring 必须 anchor '5秒' 频率",
        )

    def test_cleanup_loop_function_exists(self) -> None:
        """_cleanup_loop 必须是 hot-path 函数（不能被 inline 优化掉）。"""
        self.assertRegex(
            self.py,
            r"def _cleanup_loop\(self\)",
            "_cleanup_loop 必须存在为命名方法",
        )


# ============================================================
# #3: TASK_CLEANUP_AGE_SECONDS = 10 (秒)
# 锁定: task_queue.py def cleanup_completed_tasks(age_seconds: int = 10)
# 锁定: task_queue.py _cleanup_loop 调用 cleanup_completed_tasks(age_seconds=10)
# 锁定: web_ui_routes/task.py 2 处 throttled 调用 age_seconds=10
# ============================================================
class TestTaskCleanupAge10s(unittest.TestCase):
    """completed 任务保留时长 = 10s cross-source 锁定"""

    EXPECTED = 10

    def setUp(self) -> None:
        self.tq_py = _read(SRC / "task_queue.py")
        self.task_py = _read(SRC / "web_ui_routes" / "task.py")

    def test_function_default_age_is_10(self) -> None:
        """cleanup_completed_tasks 默认参数必须是 age_seconds=10。"""
        code = _strip_python_comments(self.tq_py)
        m = re.search(
            r"def cleanup_completed_tasks\(\s*self,\s*age_seconds:\s*int\s*=\s*(\d+)",
            code,
        )
        self.assertIsNotNone(
            m, "cleanup_completed_tasks 必须有 age_seconds: int = X 默认参数"
        )
        assert m is not None
        actual = int(m.group(1))
        self.assertEqual(
            actual,
            self.EXPECTED,
            f"R296: cleanup age 默认值 drift! age_seconds={actual} != {self.EXPECTED}",
        )

    def test_cleanup_loop_calls_with_10(self) -> None:
        """_cleanup_loop 必须用 cleanup_completed_tasks(age_seconds=10) 显式传值。"""
        code = _strip_python_comments(self.tq_py)
        m = re.search(
            r"self\.cleanup_completed_tasks\(\s*age_seconds\s*=\s*(\d+)\s*\)",
            code,
        )
        self.assertIsNotNone(
            m, "_cleanup_loop 必须显式调用 self.cleanup_completed_tasks(age_seconds=X)"
        )
        assert m is not None
        actual = int(m.group(1))
        self.assertEqual(
            actual,
            self.EXPECTED,
            f"R296: _cleanup_loop age 调用 drift! age_seconds={actual} != {self.EXPECTED}",
        )

    def test_throttled_callers_use_10(self) -> None:
        """web_ui_routes/task.py 2 处 cleanup_completed_tasks_throttled 必须用 age_seconds=10。"""
        code = _strip_python_comments(self.task_py)
        matches = re.findall(
            r"cleanup_completed_tasks_throttled\(\s*age_seconds\s*=\s*(\d+)",
            code,
        )
        self.assertGreaterEqual(
            len(matches),
            2,
            f"task.py 必须至少 2 处调用 cleanup_completed_tasks_throttled，找到 {len(matches)}",
        )
        for actual_str in matches:
            actual = int(actual_str)
            self.assertEqual(
                actual,
                self.EXPECTED,
                f"R296: hot-path age 调用 drift! age_seconds={actual} != {self.EXPECTED}",
            )

    def test_docstring_10seconds_anchor(self) -> None:
        """docstring 必须 anchor 10s 保留时长（dev awareness）。"""
        self.assertIn(
            "10秒",
            self.tq_py,
            "task_queue.py docstring 必须 anchor '10秒' 保留时长",
        )


# ============================================================
# #4: HOTPATH_CLEANUP_THROTTLE = 30.0 (秒)
# 锁定: task_queue.py def cleanup_completed_tasks_throttled(throttle_seconds: float = 30.0)
# 锁定: web_ui_routes/task.py 2 处 throttle_seconds=30.0 显式传值
# ============================================================
class TestHotpathCleanupThrottle30s(unittest.TestCase):
    """hot-path cleanup 节流 = 30.0s cross-source 锁定"""

    EXPECTED = 30.0

    def setUp(self) -> None:
        self.tq_py = _read(SRC / "task_queue.py")
        self.task_py = _read(SRC / "web_ui_routes" / "task.py")

    def test_throttled_default_is_30(self) -> None:
        """cleanup_completed_tasks_throttled 默认 throttle_seconds=30.0。"""
        code = _strip_python_comments(self.tq_py)
        m = re.search(
            r"def cleanup_completed_tasks_throttled\([^)]*throttle_seconds:\s*float\s*=\s*([\d.]+)",
            code,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "cleanup_completed_tasks_throttled 必须有 throttle_seconds: float = X 默认参数",
        )
        assert m is not None
        actual = float(m.group(1))
        self.assertEqual(
            actual,
            self.EXPECTED,
            f"R296: hot-path throttle 默认 drift! {actual} != {self.EXPECTED}",
        )

    def test_callers_pass_30(self) -> None:
        """task.py 调用必须显式传 throttle_seconds=30.0 让 dev 一眼看到值。"""
        code = _strip_python_comments(self.task_py)
        matches = re.findall(
            r"throttle_seconds\s*=\s*([\d.]+)",
            code,
        )
        self.assertGreaterEqual(
            len(matches),
            2,
            f"task.py 必须至少 2 处显式传 throttle_seconds，找到 {len(matches)}",
        )
        for actual_str in matches:
            actual = float(actual_str)
            self.assertEqual(
                actual,
                self.EXPECTED,
                f"R296: hot-path throttle caller drift! {actual} != {self.EXPECTED}",
            )

    def test_docstring_anchors_30_or_inverse(self) -> None:
        """docstring 必须 anchor 30s 或 1/30 等价频率描述。"""
        code = self.tq_py
        self.assertTrue(
            "30" in code,
            "task_queue.py 必须 anchor '30' (秒数或反频率 1/30)",
        )

    def test_throttled_function_exists(self) -> None:
        """cleanup_completed_tasks_throttled 必须存在为命名方法。"""
        self.assertRegex(
            self.tq_py,
            r"def cleanup_completed_tasks_throttled\(",
            "cleanup_completed_tasks_throttled 必须存在",
        )


# ============================================================
# #5: JS_HEALTH_CHECK_INTERVAL = 30000 (毫秒)
# 锁定: static/js/multi_task.js setInterval(..., 30000) — tasksHealthCheckTimer
# ============================================================
class TestJsHealthCheckInterval30000ms(unittest.TestCase):
    """JS tasks health check = 30000ms cross-source 锁定"""

    EXPECTED = 30000

    def setUp(self) -> None:
        self.js = _read(SRC / "static" / "js" / "multi_task.js")

    def test_health_check_interval_is_30000(self) -> None:
        """tasksHealthCheckTimer 的 setInterval 必须用 30000ms。"""
        code = _strip_js_comments(self.js)
        m = re.search(
            r"window\.tasksHealthCheckTimer\s*=\s*setInterval\(\s*function[^)]*\)[^,]*,\s*(\d+)\s*\)",
            code,
            re.DOTALL,
        )
        if m is None:
            m = re.search(
                r"tasksHealthCheckTimer\s*=\s*setInterval\([\s\S]{1,400}?,\s*(\d+)\s*\)",
                code,
            )
        self.assertIsNotNone(
            m,
            "multi_task.js 必须有 tasksHealthCheckTimer = setInterval(fn, X)",
        )
        assert m is not None
        actual = int(m.group(1))
        self.assertEqual(
            actual,
            self.EXPECTED,
            f"R296: JS health check drift! setInterval(_, {actual}) != {self.EXPECTED}",
        )

    def test_start_stop_pair_exists(self) -> None:
        """startTasksHealthCheck / stopTasksHealthCheck 必须配对（防止 leak）。"""
        self.assertRegex(
            self.js,
            r"function startTasksHealthCheck\(\)",
            "multi_task.js 必须有 startTasksHealthCheck 函数",
        )
        self.assertRegex(
            self.js,
            r"function stopTasksHealthCheck\(\)",
            "multi_task.js 必须有 stopTasksHealthCheck 函数",
        )

    def test_idempotent_guard_present(self) -> None:
        """startTasksHealthCheck 必须有幂等守护（避免 visibilitychange race 创建 2 个 timer）。"""
        code = _strip_js_comments(self.js)
        m = re.search(
            r"function startTasksHealthCheck\(\)\s*\{[\s\S]{0,300}?if\s*\(\s*window\.tasksHealthCheckTimer\s*\)",
            code,
        )
        self.assertIsNotNone(
            m,
            "startTasksHealthCheck 必须有 `if (window.tasksHealthCheckTimer) return;` 幂等守护",
        )


# ============================================================
# Cross-cutting: 上述 5 个 perf const 不能 drift 到代码以外的地方
# ============================================================
class TestPerfBaselineMetaIntegrity(unittest.TestCase):
    """meta-lint: 确保 R296 锁定的 5 个 const 是命名 hot-path const，
    不能被 inline 散落到其他 hot-path 文件中。"""

    def test_no_other_25_in_task_py(self) -> None:
        """task.py 除 q.get(timeout=25) / heartbeat 注释外，不应有其他孤立 '25' 出现。

        meta-lint: 防止未来开发者把 25 复制到其他 hot-path 但没有同步更新。
        """
        code = _strip_python_comments(_read(SRC / "web_ui_routes" / "task.py"))
        timeout_25_matches = re.findall(r"timeout\s*=\s*25\b", code)
        self.assertEqual(
            len(timeout_25_matches),
            1,
            f"task.py 应只有 1 处 timeout=25 (SSE q.get), 找到 {len(timeout_25_matches)}",
        )

    def test_only_stop_cleanup_wait_uses_5s(self) -> None:
        """整个 task_queue.py 应只有 1 处 _stop_cleanup.wait(timeout=5),
        不能让 5s 散落到其他 wait 调用 (e.g. lock acquire, thread join)。
        """
        tq_code = _read(SRC / "task_queue.py")
        cleaned = _strip_python_comments(tq_code)
        stop_cleanup_5_matches = re.findall(
            r"_stop_cleanup\.wait\(\s*timeout\s*=\s*5\s*\)", cleaned
        )
        self.assertEqual(
            len(stop_cleanup_5_matches),
            1,
            f"task_queue.py 应有且只有 1 处 _stop_cleanup.wait(timeout=5), "
            f"找到 {len(stop_cleanup_5_matches)} 处",
        )


if __name__ == "__main__":
    unittest.main()
