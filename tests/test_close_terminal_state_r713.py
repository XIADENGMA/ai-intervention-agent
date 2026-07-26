"""R713 回归护栏：「关闭 Web UI」成功后渲染终态卡片，而非刷新到错误页。

背景（深巡「关闭后显示的页面」）：

旧流程 ``closeInterface`` 在 ``/api/close`` 成功后固定 2 秒
``window.location.reload()``——但服务端 0.5s 后已经 shutdown，reload
只能落到 PWA Service Worker 的 ``offline.html``（「无法连接 + 重试」
故障语义页：重试按钮永远无效、后台指数退避 ping 空转），无 SW 时更
是浏览器原生错误页。用户明明是**主动关闭**，看到的却是"出故障了"。

R713 契约：

1. ``/api/close`` 成功分支调用 ``renderClosedTerminalState()`` 原地
   渲染「已关闭」终态卡片并 ``return``——**不再刷新**；失败分支保留
   ``refreshPageSafely`` 兜底（服务可能仍在运行，刷新可恢复视图）。
2. ``renderClosedTerminalState`` 必须：停 SSE（含重连定时器，走
   ``_disconnectSSE``）、销毁 Lottie 生命周期、换 closedTitle /
   closedHint 文案（并摘 data-i18n 防 translateDOM 迟到覆盖）、隐藏
   等待进度条 / 关闭按钮 / SSE 徽章。
3. 三语 locale 必须提供 ``status.closedTitle`` / ``status.closedHint``。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"function\s+{name}\s*\([^)]*\)\s*\{{", source)
    assert match is not None, f"missing function {name}"
    depth = 0
    for idx in range(match.end() - 1, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.end() : idx]
    raise AssertionError(f"could not parse body for {name}")


class TestCloseInterfaceContract(unittest.TestCase):
    """closeInterface：成功 → 终态渲染 + return；失败 → 刷新兜底。"""

    def setUp(self) -> None:
        self.body = _function_body(APP_JS.read_text(encoding="utf-8"), "closeInterface")

    def test_success_branch_renders_terminal_state(self) -> None:
        self.assertIn("renderClosedTerminalState()", self.body)

    def test_success_branch_returns_before_refresh(self) -> None:
        render_idx = self.body.find("renderClosedTerminalState()")
        refresh_idx = self.body.find("refreshPageSafely()")
        self.assertGreater(render_idx, 0)
        self.assertGreater(refresh_idx, 0, "失败路径必须保留刷新兜底")
        self.assertLess(
            render_idx,
            refresh_idx,
            "成功分支的终态渲染必须先于刷新兜底出现（return 短路）",
        )
        after_render = self.body[render_idx : render_idx + 200]
        self.assertIn(
            "return",
            after_render,
            "R713: 终态渲染后必须 return，绝不能落入 reload——"
            "服务已 shutdown，reload 只会把用户带到「无法连接」错误页",
        )

    def test_no_success_refresh_status_key(self) -> None:
        # 旧的「已关闭，正在刷新页面…」文案键随行为一起移除
        self.assertNotIn("closedRefreshing", self.body)


class TestTerminalStateRenderer(unittest.TestCase):
    """renderClosedTerminalState：终态卡片的最低完整性。"""

    def setUp(self) -> None:
        self.app = APP_JS.read_text(encoding="utf-8")
        self.body = _function_body(self.app, "renderClosedTerminalState")

    def test_stops_sse_with_full_disconnect(self) -> None:
        self.assertIn(
            "_disconnectSSE",
            self.body,
            "终态页必须走 _disconnectSSE（含全部重连定时器清理），"
            "否则角落 SSE 徽章转红报警 + 后台空转重连",
        )

    def test_disposes_lottie_lifecycle(self) -> None:
        self.assertIn("disposeHourglassAnimationLifecycle()", self.body)

    def test_swaps_copy_to_closed_keys(self) -> None:
        self.assertIn('t("status.closedTitle")', self.body)
        self.assertIn('t("status.closedHint")', self.body)

    def test_strips_data_i18n_before_writing_copy(self) -> None:
        # R709 教训：不摘 data-i18n，translateDOM 迟到会把终态文案
        # 覆盖回「暂无交互反馈请求」
        self.assertIn('removeAttribute("data-i18n")', self.body)

    def test_hides_waiting_affordances(self) -> None:
        self.assertIn("no-content-progress", self.body)
        self.assertIn('setElementDisplayById("no-content-buttons", "none")', self.body)
        self.assertIn("sse-status-indicator", self.body)


class TestLocaleKeys(unittest.TestCase):
    """三语 locale 必须提供终态文案键。"""

    def test_closed_keys_present_in_all_locales(self) -> None:
        for locale in ("en", "zh-CN", "zh-TW"):
            data = json.loads(
                (LOCALES_DIR / f"{locale}.json").read_text(encoding="utf-8")
            )
            status = data.get("status", {})
            self.assertIn("closedTitle", status, f"{locale} 缺 status.closedTitle")
            self.assertIn("closedHint", status, f"{locale} 缺 status.closedHint")
            self.assertNotIn(
                "closedRefreshing",
                status,
                f"{locale} 的 closedRefreshing 应随 R713 一起移除（orphan）",
            )


if __name__ == "__main__":
    unittest.main()
