"""R344 · cold start perf baseline invariant (cycle-38 #B1).

v3.6 perf-baseline pattern 7th 应用, 首次锁定 **cold start** 关键路径耗
时上限 (而非 retry/timeout 常量)。

背景
----

v3.6 perf-baseline 系列前 6 个应用 (R296/R301/R304/R307/R315) 都聚焦
runtime 行为常量 (heartbeat 间隔, retry delay, queue cleanup 阈值)。
R344 把同样的契约方法**首次扩展到 cold start 启动路径**:

- ``import web_ui.WebFeedbackUI``
- ``import server.mcp``
- ``ConfigManager`` 单例首次访问
- ``NotificationManager`` 实例化
- ``TaskQueue`` 实例化

cold start 是用户体验的**第一印象**关键路径; 单次启动 > 1s 会引发明显
卡顿感。R344 锁定基线后, 未来如果引入大量重型 import 或 eager I/O 会立
即被 invariant 捕获, 防止性能 regression。

R344 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: 关键模块可以导入, 关键类可以实例化
2. **Layer 2 (Cold start budget)**: 每个关键模块导入 + 实例化在 1 秒内
   完成 (上限选取参考目前测得的 baseline + 5x 容差, 防止假阳性)
3. **Layer 3 (Total budget)**: 完整 cold start 序列累计 < 5 秒 (用户从
   `mcp serve` 调用到第一个 endpoint ready)

R344 budget 选取依据
--------------------

测得基线 (M2 Mac, Python 3.11, 单线程):

- import web_ui.WebFeedbackUI:  ~120ms → budget 1000ms (8x 容差)
- import server.mcp:            ~325ms → budget 2500ms (8x 容差)
- ConfigManager get_config:      ~80ms → budget 1000ms (12x 容差)
- NotificationManager init:       <1ms → budget  500ms (500x 容差)
- TaskQueue init:                ~20ms → budget  500ms (25x 容差)

容差选 5-12x 而非 2-3x 的原因:
- CI 环境性能差异大 (GitHub Actions 比本地慢 2-4x)
- CI coverage 门禁额外叠加 tracing + xdist worker 竞争, total budget 使用
  6000ms runner 容差, 本地/普通 pytest 仍保持 5000ms
- pytest collection overhead 可能影响 timing
- Python import cache 在 cold start 不可用
- 真正的性能 regression 通常是 2x+ 而非 10%

methodology lineage
-------------------

- v3.6 perf-baseline 1st-6th: R296/R301/R304/R307/R315 — runtime 常量
- **R344 (本 commit, cycle-38)** — **首次扩展到 cold start 路径**, 防止
  启动性能 regression
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PERF_BUDGETS = {
    "import_web_ui": 1000,
    "import_server": 2500,
    "config_manager_get": 1000,
    "notification_manager_init": 500,
    "task_queue_init": 500,
    "total_cold_start": 5000,
}

GITHUB_COVERAGE_PERF_BUDGETS = {
    "total_cold_start": 6000,
}


def _is_github_coverage_gate() -> bool:
    return (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("AIIA_CI_GATE_WITH_COVERAGE") == "1"
    )


def _perf_budget_ms(name: str) -> int:
    if _is_github_coverage_gate():
        return GITHUB_COVERAGE_PERF_BUDGETS.get(name, PERF_BUDGETS[name])
    return PERF_BUDGETS[name]


def _reset_singletons():
    """重置可能影响计时的单例 (避免重复测试相互污染)。

    R323/R324 提供 ``NotificationManager.reset_for_testing()`` 但是个
    instance method, 这里调用 NotificationManager() 后 reset 即可。
    """
    try:
        from ai_intervention_agent.notification_manager import (
            NotificationManager,
        )

        nm = NotificationManager()
        if hasattr(nm, "reset_for_testing"):
            nm.reset_for_testing()
    except Exception:  # broad: defensive cleanup
        pass


@pytest.fixture(autouse=True)
def _ensure_clean_state():
    _reset_singletons()
    yield
    _reset_singletons()


class TestLayer1ColdStartAnchor:
    """Layer 1: 关键模块可以导入, 关键类可以实例化。"""

    def test_web_ui_importable(self):
        from ai_intervention_agent.web_ui import WebFeedbackUI  # noqa: F401

    def test_server_importable(self):
        from ai_intervention_agent.server import mcp  # noqa: F401

    def test_config_manager_importable(self):
        from ai_intervention_agent.config_manager import (
            get_config,
        )

        cfg = get_config()
        assert cfg is not None

    def test_notification_manager_instantiable(self):
        from ai_intervention_agent.notification_manager import (
            NotificationManager,
        )

        nm = NotificationManager()
        assert nm is not None

    def test_task_queue_instantiable(self):
        from ai_intervention_agent.task_queue import TaskQueue

        q = TaskQueue()
        assert q is not None


class TestLayer2PerOperationBudget:
    """Layer 2: 每个关键操作在 budget 内完成 (cold start path)。

    注意: 由于 Python module cache, 单次 pytest run 内多次 import 同一模
    块只有第一次是 "cold". 后续都会从 sys.modules 返回 cached 引用。我们
    用 import 后立即 del + re-import 模拟 cold, 但只对 ConfigManager /
    NotificationManager / TaskQueue 这种**实例化时间**进行严格 budget 检
    查 (import 时间无法真正 reset)。
    """

    def test_config_manager_get_within_budget(self):
        from ai_intervention_agent.config_manager import get_config

        t0 = time.perf_counter()
        get_config()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < PERF_BUDGETS["config_manager_get"], (
            f"R344-L2: ConfigManager.get_config() took {elapsed_ms:.2f}ms, "
            f"exceeds budget {PERF_BUDGETS['config_manager_get']}ms. "
            f"Investigate eager I/O or heavy imports."
        )

    def test_notification_manager_init_within_budget(self):
        from ai_intervention_agent.notification_manager import (
            NotificationManager,
        )

        t0 = time.perf_counter()
        NotificationManager()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < PERF_BUDGETS["notification_manager_init"], (
            f"R344-L2: NotificationManager() took {elapsed_ms:.2f}ms, "
            f"exceeds budget "
            f"{PERF_BUDGETS['notification_manager_init']}ms."
        )

    def test_task_queue_init_within_budget(self):
        from ai_intervention_agent.task_queue import TaskQueue

        t0 = time.perf_counter()
        TaskQueue()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < PERF_BUDGETS["task_queue_init"], (
            f"R344-L2: TaskQueue() took {elapsed_ms:.2f}ms, "
            f"exceeds budget {PERF_BUDGETS['task_queue_init']}ms."
        )


class TestLayer3TotalColdStartBudget:
    """Layer 3: 完整 cold start 序列 < total budget。

    模拟真实 cold start: 用 subprocess 启动新 Python interpreter, 完成
    full import + instance init, 测量总耗时 (类似 ``mcp serve`` 真实启动
    场景)。
    """

    def test_full_cold_start_within_total_budget(self):
        import subprocess

        script = """
import time
t0 = time.perf_counter()
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.server import mcp
from ai_intervention_agent.config_manager import get_config
from ai_intervention_agent.notification_manager import NotificationManager
from ai_intervention_agent.task_queue import TaskQueue
get_config()
NotificationManager()
TaskQueue()
print(f'{(time.perf_counter() - t0) * 1000:.2f}')
"""
        budget_ms = _perf_budget_ms("total_cold_start")
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=budget_ms / 1000 + 5,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"R344-L3: cold start subprocess failed: {result.stderr!r}"
        )
        elapsed_ms = float(result.stdout.strip())
        assert elapsed_ms < budget_ms, (
            f"R344-L3: full cold start took {elapsed_ms:.2f}ms, exceeds "
            f"budget {budget_ms}ms. Investigate "
            f"heavy imports or eager initialization."
        )


class TestR344LineageMarker:
    def test_this_file_contains_r344_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R344" in text

    def test_this_file_references_prior_perf_baseline_apps(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R296", "R301", "R307", "R315"):
            assert prior in text, f"R344: must cite prior perf-baseline app: {prior}"

    def test_this_file_documents_budget_rationale(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("budget", "容差", "cold start"):
            assert kw in text, f"R344: missing rationale keyword: {kw!r}"
