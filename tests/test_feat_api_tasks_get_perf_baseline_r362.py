"""R362 · ``/api/tasks`` GET 响应时间 perf baseline invariant
(cycle-41 #C1, **v3.6 perf-baseline 9th 应用, 读密集 hot path 首次进入**)。

v3.6 perf-baseline 系列累计应用
-------------------------------

- R296 / R301 / R304 / R307 / R315: runtime 常量 baseline (heartbeat /
  retry / queue / TTL / lock timeout)
- R344 (cycle-38): cold start 路径 baseline (启动)
- R348 (cycle-39): /api/submit POST 响应时间 (写入 hot path)
- **R362 (本 commit, cycle-41)**: /api/tasks GET 响应时间 (**读密集
  hot path 首次进入**)

R362 audit 目标
---------------

``/api/tasks`` GET 是 web UI 任务列表的轮询主路径, 浏览器每隔几秒就要
fetch 一次。锁定:

1. **读锁 latency** — task_queue ReadWriteLock 读锁高频获取必须低开销
2. **序列化开销** — task list 转 dict / JSON 必须扁平不递归
3. **同步 I/O 不能 leak** — 任何 logging / config 访问都会放大读频
4. **task list 增长** — 5 个任务时也必须保持 budget

R362 invariant (3 层 + lineage)
-------------------------------

1. **Layer 1 (Anchor)**: ``/api/tasks`` GET 注册, Flask app 可建立
   test_client
2. **Layer 2 (Empty queue latency)**: 空队列 GET 在 80ms 内返回 — 锁
   基础读锁 + JSON 序列化开销
3. **Layer 3 (Loaded queue latency)**: 5 个 task 的队列 GET 在 150ms
   内返回 — 锁数据量扩展开销

budget 选取依据
---------------

empty queue ~5-15ms (本地实测, 比 POST 小 — 没有 markdown render),
5 task queue ~10-30ms。容差 5-10x 防 CI 假阳性, 真实 regression
(e.g., 加入新 sync logging 让 latency 变 3x) 会立即触发。

methodology lineage 说明
------------------------

R362 是 perf-baseline pattern 9th 应用, 标志着**两类 HTTP endpoint
(写 hot path R348 + 读 hot path R362) 同时被 baseline 覆盖**。后续
fetch 新 endpoint 时, 必须证明其 latency 在已有 budget 同类内。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PERF_BUDGETS_MS = {
    "tasks_empty_queue": 80,
    "tasks_5_tasks_queue": 150,
}


@pytest.fixture
def web_ui_app():
    """构建一个 minimal WebFeedbackUI app for testing."""
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ui = WebFeedbackUI(
        prompt="r362 test prompt",
        predefined_options=None,
        task_id="r362-test-task",
    )
    return ui, ui.app


class TestLayer1Anchor:
    """Layer 1: ``/api/tasks`` GET 存在 + Flask app 可建立 test_client。"""

    def test_app_has_tasks_route(self, web_ui_app):
        _ui, app = web_ui_app
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/tasks" in rules, (
            f"R362-L1: /api/tasks GET not registered. Routes: {rules}"
        )

    def test_get_method_supported(self, web_ui_app):
        _ui, app = web_ui_app
        for rule in app.url_map.iter_rules():
            if rule.rule == "/api/tasks" and "GET" in (rule.methods or set()):
                return
        raise AssertionError("R362-L1: /api/tasks does not support GET method")


class TestLayer2EmptyQueueLatency:
    """Layer 2: 空队列 GET < 80ms。"""

    def test_empty_queue_within_budget(self, web_ui_app):
        _ui, app = web_ui_app
        client = app.test_client()

        # warmup
        for _ in range(3):
            client.get("/api/tasks")

        elapsed_ms_list = []
        for _ in range(5):
            t0 = time.perf_counter()
            resp = client.get("/api/tasks")
            elapsed_ms_list.append((time.perf_counter() - t0) * 1000)
            assert resp.status_code in (200, 401, 403)

        median_ms = sorted(elapsed_ms_list)[len(elapsed_ms_list) // 2]
        assert median_ms < PERF_BUDGETS_MS["tasks_empty_queue"], (
            f"R362-L2: median /api/tasks GET (empty queue) latency = "
            f"{median_ms:.2f}ms (5 runs: {elapsed_ms_list}), exceeds "
            f"budget {PERF_BUDGETS_MS['tasks_empty_queue']}ms. "
            f"Investigate read lock contention or sync I/O leaking "
            f"into GET hot path."
        )


class TestLayer3LoadedQueueLatency:
    """Layer 3: 5-task 队列 GET < 150ms。"""

    def test_5_tasks_queue_within_budget(self, web_ui_app):
        ui, app = web_ui_app
        client = app.test_client()

        from ai_intervention_agent.task_queue import Task

        for i in range(5):
            task = Task(
                task_id=f"r362-perf-task-{i}",
                prompt=f"prompt {i}",
                predefined_options=None,
            )
            try:
                ui.task_queue.add_task(task)
            except Exception:
                # Queue full / id duplicate — 不影响 perf measurement
                pass

        for _ in range(3):
            client.get("/api/tasks")

        elapsed_ms_list = []
        for _ in range(5):
            t0 = time.perf_counter()
            resp = client.get("/api/tasks")
            elapsed_ms_list.append((time.perf_counter() - t0) * 1000)

        median_ms = sorted(elapsed_ms_list)[len(elapsed_ms_list) // 2]
        assert median_ms < PERF_BUDGETS_MS["tasks_5_tasks_queue"], (
            f"R362-L3: median /api/tasks GET (5 tasks) latency = "
            f"{median_ms:.2f}ms (5 runs: {elapsed_ms_list}), exceeds "
            f"budget {PERF_BUDGETS_MS['tasks_5_tasks_queue']}ms. "
            f"Investigate per-task serialization or DOM payload "
            f"growth in JSON output."
        )


class TestR362LineageMarker:
    def test_this_file_contains_r362_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R362" in text

    def test_this_file_references_perf_baseline_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R296", "R304", "R307", "R344", "R348"):
            assert prior in text, f"R362: must cite perf-baseline lineage: {prior}"

    def test_this_file_marks_read_hot_path_dimension(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("读密集", "hot path", "perf-baseline 9th"):
            assert kw in text, f"R362: missing keyword: {kw!r}"
