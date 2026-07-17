"""R702：显式 per-task timeout 不被 config 热更新覆盖（幽灵提交根因修复）。

背景（受控实验 + 提交指纹日志定位，2026-07）
--------------------------------------------------
用户配置 ``feedback.frontend_countdown = 30``。服务重启后第一个
task/config 请求触发 ``_ensure_feedback_timeout_hot_reload_callback_
registered``，历史实现会在注册时**立刻执行一次同步**，把所有未完成任务
的 ``auto_resubmit_timeout``（包括 HTTP API 显式传入 3600s 的）无差别
覆盖为 30。30 秒后前端倒计时如实归零并自动提交 resubmit_prompt——
表现为「任务莫名其妙消失/被提交」，且只有重启后第一批任务中招（之后
基准已记录，回调 no-op），因此呈间歇性、极难定位。

修复两层：

A. ``Task.auto_resubmit_timeout_explicit``：API 调用方显式传 timeout 的
   任务打标记，``update_auto_resubmit_timeout_for_all`` 永远跳过它们
   （per-task 显式值优先于全局配置）。
B. 回调注册时只记录基准（``_LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT``），
   不执行覆盖——注册不等于配置变更。

本文件的护栏级断言保证两层修复都不被回归。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ai_intervention_agent.task_queue import TaskQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_SYNC = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_config_sync.py"
TASK_ROUTES = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"


def _make_queue() -> TaskQueue:
    """无持久化的纯内存队列（单测隔离）。"""
    return TaskQueue(persist_path=None)


class TestExplicitTimeoutSkipsHotReloadSync(unittest.TestCase):
    """方案 A：显式任务不被 ``update_auto_resubmit_timeout_for_all`` 覆盖。"""

    def test_explicit_task_keeps_its_timeout(self) -> None:
        q = _make_queue()
        try:
            q.add_task(
                "explicit-1",
                "p",
                auto_resubmit_timeout=3600,
                auto_resubmit_timeout_explicit=True,
            )
            updated = q.update_auto_resubmit_timeout_for_all(30)
            task = q.get_task("explicit-1")
            assert task is not None
            self.assertEqual(task.auto_resubmit_timeout, 3600)
            self.assertEqual(updated, 0)
        finally:
            q.stop_cleanup()

    def test_implicit_task_still_follows_config(self) -> None:
        q = _make_queue()
        try:
            q.add_task("implicit-1", "p", auto_resubmit_timeout=240)
            updated = q.update_auto_resubmit_timeout_for_all(30)
            task = q.get_task("implicit-1")
            assert task is not None
            self.assertEqual(task.auto_resubmit_timeout, 30)
            self.assertEqual(updated, 1)
        finally:
            q.stop_cleanup()

    def test_mixed_tasks_only_implicit_updated(self) -> None:
        q = _make_queue()
        try:
            q.add_task(
                "e",
                "p",
                auto_resubmit_timeout=3600,
                auto_resubmit_timeout_explicit=True,
            )
            q.add_task("i", "p", auto_resubmit_timeout=240)
            updated = q.update_auto_resubmit_timeout_for_all(60)
            te = q.get_task("e")
            ti = q.get_task("i")
            assert te is not None and ti is not None
            self.assertEqual(te.auto_resubmit_timeout, 3600)
            self.assertEqual(ti.auto_resubmit_timeout, 60)
            self.assertEqual(updated, 1)
        finally:
            q.stop_cleanup()

    def test_default_flag_is_false_for_backward_compat(self) -> None:
        """旧持久化快照没有该字段——pydantic 默认 False，行为与修复前一致。"""
        q = _make_queue()
        try:
            q.add_task("legacy", "p", auto_resubmit_timeout=240)
            task = q.get_task("legacy")
            assert task is not None
            self.assertFalse(task.auto_resubmit_timeout_explicit)
        finally:
            q.stop_cleanup()


class TestRouteMarksExplicitTimeout(unittest.TestCase):
    """HTTP API 路由把显式 timeout 标记传给 ``add_task``（源码契约）。"""

    def test_route_passes_explicit_flag(self) -> None:
        src = TASK_ROUTES.read_text(encoding="utf-8")
        self.assertIn("auto_resubmit_timeout_explicit=timeout_explicit", src)
        # timeout_explicit 的判定必须同时覆盖两个别名字段
        self.assertIn(
            'timeout_explicit = "auto_resubmit_timeout" in data or "timeout" in data',
            src,
        )


class TestRegistrationDoesNotSync(unittest.TestCase):
    """方案 B：回调注册时只记录基准，不执行覆盖（源码契约）。

    历史 bug 形态是注册后紧跟 ``_sync_existing_tasks_timeout_from_config()``
    直接调用。修复后注册路径只允许写 ``_LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT``
    基准，绝不能在注册路径上调用同步函数本体。
    """

    def test_registration_records_baseline_without_syncing(self) -> None:
        src = CONFIG_SYNC.read_text(encoding="utf-8")
        idx = src.find("def _ensure_feedback_timeout_hot_reload_callback_registered")
        self.assertGreater(idx, 0)
        body = src[idx:]
        # 注册函数体内不允许直接调用同步函数（跟在 register 之后的历史形态）
        self.assertNotIn("            _sync_existing_tasks_timeout_from_config()", body)
        # 必须记录基准
        self.assertIn("_LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT", body)
        self.assertIn("R702", body)


if __name__ == "__main__":
    unittest.main()
