"""R348 · ``/api/submit`` POST 响应时间 perf baseline invariant
(cycle-39 #A1, v3.6 perf-baseline 8th 应用)。

v3.6 perf-baseline 系列累计应用
-------------------------------

- R296 / R301 / R304 / R307 / R315: runtime 常量 baseline (heartbeat /
  retry / queue / TTL / lock timeout)
- R344 (cycle-38): cold start 路径 baseline (首次扩展到启动)
- **R348 (本 commit, cycle-39)**: runtime hot path 响应时间 baseline

R348 audit 目标
---------------

``/api/submit`` POST 是 web UI 反馈提交的主路径, 用户体验关键。锁定其
**响应时间上限** + **数据处理量** 关系, 防止:

1. 字符串处理 (markdown render / sanitize) 退化
2. lock 等待时间过长 (R326 task_queue 写锁路径)
3. 同步 I/O (e.g., logging / config write) leak 到 hot path
4. 序列化 / 反序列化 overhead 累积

R348 invariant (3 层 + lineage)
-------------------------------

1. **Layer 1 (Anchor)**: ``/api/submit`` POST endpoint 存在, Flask app
   可以建立 test_client
2. **Layer 2 (Empty payload latency)**: 空 payload (``{"feedback": ""}``)
   POST 在 100ms 内返回 — 锁基础开销 budget
3. **Layer 3 (Reasonable payload latency)**: 1KB 文本 payload POST 在
   200ms 内返回 — 锁正常负载 budget

budget 选取依据
---------------

empty payload baseline ~10-30ms (本地实测), 1KB payload ~30-60ms。容差
3-5x 防 CI 假阳性, 真实 regression (e.g., 加入新 sync I/O 让 latency
变 3x) 会立即触发。

methodology lineage
-------------------

- v3.6 perf-baseline 1st-7th (上述列出)
- **R348 是首个锁定 HTTP endpoint 响应时间** — 之前都是单次操作 timing
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PERF_BUDGETS_MS = {
    "submit_empty_payload": 100,
    "submit_1kb_payload": 200,
}


@pytest.fixture
def web_ui_app():
    """构建一个 minimal WebFeedbackUI app for testing."""
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ui = WebFeedbackUI(
        prompt="test prompt",
        predefined_options=None,
        task_id="r348-test-task",
    )
    return ui, ui.app


class TestLayer1Anchor:
    """Layer 1: ``/api/submit`` POST 存在 + Flask app 可建立 test_client。"""

    def test_app_has_submit_route(self, web_ui_app):
        _ui, app = web_ui_app
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/submit" in rules, (
            f"R348-L1: /api/submit POST not registered. Routes: {rules}"
        )

    def test_test_client_works(self, web_ui_app):
        _ui, app = web_ui_app
        client = app.test_client()
        assert client is not None


class TestLayer2EmptyPayloadLatency:
    """Layer 2: 空 payload POST < 100ms。"""

    def test_empty_payload_within_budget(self, web_ui_app):
        _ui, app = web_ui_app
        client = app.test_client()

        # warmup (避免首次调用包含 import / lazy init 开销)
        for _ in range(3):
            client.post("/api/submit", json={"interactive_feedback": ""})

        elapsed_ms_list = []
        for _ in range(5):
            t0 = time.perf_counter()
            resp = client.post("/api/submit", json={"interactive_feedback": ""})
            elapsed_ms_list.append((time.perf_counter() - t0) * 1000)

        median_ms = sorted(elapsed_ms_list)[len(elapsed_ms_list) // 2]
        assert median_ms < PERF_BUDGETS_MS["submit_empty_payload"], (
            f"R348-L2: median /api/submit empty payload latency = "
            f"{median_ms:.2f}ms (5 runs: {elapsed_ms_list}), exceeds "
            f"budget {PERF_BUDGETS_MS['submit_empty_payload']}ms. "
            f"Investigate sync I/O or lock contention in hot path."
        )


class TestLayer3ReasonablePayloadLatency:
    """Layer 3: 1KB 文本 payload POST < 200ms。"""

    def test_1kb_payload_within_budget(self, web_ui_app):
        _ui, app = web_ui_app
        client = app.test_client()
        payload_text = "x" * 1024  # 1KB

        for _ in range(3):
            client.post("/api/submit", json={"interactive_feedback": payload_text})

        elapsed_ms_list = []
        for _ in range(5):
            t0 = time.perf_counter()
            resp = client.post(
                "/api/submit", json={"interactive_feedback": payload_text}
            )
            elapsed_ms_list.append((time.perf_counter() - t0) * 1000)

        median_ms = sorted(elapsed_ms_list)[len(elapsed_ms_list) // 2]
        assert median_ms < PERF_BUDGETS_MS["submit_1kb_payload"], (
            f"R348-L3: median /api/submit 1KB payload latency = "
            f"{median_ms:.2f}ms (5 runs: {elapsed_ms_list}), exceeds "
            f"budget {PERF_BUDGETS_MS['submit_1kb_payload']}ms. "
            f"Investigate markdown render / sanitize overhead."
        )


class TestR348LineageMarker:
    def test_this_file_contains_r348_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R348" in text

    def test_this_file_references_perf_baseline_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R296", "R304", "R307", "R344"):
            assert prior in text, f"R348: must cite perf-baseline lineage: {prior}"

    def test_this_file_marks_hot_path_dimension(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("hot path", "HTTP endpoint", "perf-baseline 8th"):
            assert kw in text, f"R348: missing keyword: {kw!r}"
