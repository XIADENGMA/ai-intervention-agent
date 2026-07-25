"""R705 回归护栏：预定义选项渲染单一真源 + 详情加载失败自愈。

背景（TODO#38「加载网页后只显示主体内容，多选选项没有正确显示」）：

选项区域此前有两条互不知情的渲染路径：

1. ``app.js loadConfig``（``/api/config``）：append 选项后只设 inline
   ``style.display = "block"``——但 ``#options-container`` 初始
   ``class="hidden"`` 对应 ``display: none !important``，inline 值
   永远盖不过它，**选项渲染进 DOM 却完全不可见**；
2. ``multi_task.js updateOptionsDisplay``（``loadTaskDetails`` /
   ``/api/tasks/{id}``）：清空重建 + classList 切换，渲染正确。

平时页面"能看到选项"全靠路径 2 在 1-2s 内覆盖路径 1 的隐形产物。
一旦 ``loadTaskDetails`` 失败（移动端网络抖动 / 页面后台恢复 / 服务
重启窗口），旧轮询条件在 pending 任务场景（serverActiveTask 不存在、
activeTaskChanged 已回落 false）下**永不重试**——选项永久不可见，
页面只剩主体内容。CLI ``--prompt`` 单任务模式（任务不进 TaskQueue）
下路径 2 根本不存在，选项 100% 不可见。

R705 契约：

1. **单一真源**：``loadConfig`` 的选项渲染委托 ``updateOptionsDisplay``
   （multi_task.js 以 defer 排在 app.js 之前，函数必然已定义）；
   本地回退分支仅作测试桩兜底，且必须用 classList 摘 ``hidden``、
   渲染前清空容器，禁止 inline ``style.display`` 控制显隐。
2. **失败自愈**：``window.lastLoadedDetailsTaskId`` 记录最近一次成功
   渲染详情的任务 ID；轮询发现 activeTaskId 尚未成功加载过详情时
   每轮重试 ``loadTaskDetails``，网络恢复即自愈。

本文件锁定上述契约，防止未来重构恢复双路径渲染或 inline display。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
APP_JS = STATIC_JS / "app.js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
CSS_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"(?:async\s+)?function\s+{name}\s*\([^)]*\)\s*\{{", source)
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


class TestLoadConfigDelegatesOptionsRender(unittest.TestCase):
    """loadConfig 必须委托 updateOptionsDisplay，回退分支禁用 inline display。"""

    def setUp(self) -> None:
        self.body = _function_body(APP_JS.read_text(encoding="utf-8"), "loadConfig")

    def test_delegates_to_update_options_display(self) -> None:
        self.assertIn('typeof updateOptionsDisplay === "function"', self.body)
        self.assertIn("updateOptionsDisplay(", self.body)

    def test_fallback_uses_classlist_not_inline_display(self) -> None:
        # 回退分支必须摘 hidden（display:none !important 只能靠 classList）
        self.assertIn('classList.remove("hidden")', self.body)
        self.assertIn('classList.add("visible")', self.body)
        # 禁止回归到 inline display 控制显隐（.hidden !important 盖过它）
        self.assertNotIn('optionsContainer.style.display = "block"', self.body)
        self.assertNotIn('separator.style.display = "block"', self.body)

    def test_fallback_clears_container_before_render(self) -> None:
        # 渲染前清空，与 updateOptionsDisplay 的清空重建语义一致，
        # 杜绝 append 导致的重复选项。
        self.assertIn('optionsContainer.innerHTML = ""', self.body)


class TestScriptOrderContract(unittest.TestCase):
    """委托前提：multi_task.js（定义 updateOptionsDisplay）先于 app.js。"""

    def test_multi_task_precedes_app_js(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        multi_idx = template.find(
            'src="/static/js/multi_task.js?v={{ multi_task_version }}"'
        )
        app_idx = template.find('src="/static/js/app.js?v={{ app_version }}"')
        self.assertGreater(multi_idx, 0)
        self.assertGreater(app_idx, 0)
        self.assertLess(
            multi_idx,
            app_idx,
            "defer 按文档顺序执行：multi_task.js 必须排在 app.js 之前，"
            "否则 loadConfig 委托 updateOptionsDisplay 时函数未定义",
        )

    def test_hidden_class_still_important(self) -> None:
        # R705 根因锚点：.hidden 是 !important——一旦这个前提变化，
        # 本护栏的威胁模型需要重新评估。
        css = CSS_PATH.read_text(encoding="utf-8")
        match = re.search(r"\.hidden\s*\{([^}]*)\}", css)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertIn("!important", match.group(1))


class TestDetailsLoadRetryWatermark(unittest.TestCase):
    """详情加载失败自愈：lastLoadedDetailsTaskId 水位 + 轮询重试条件。"""

    def setUp(self) -> None:
        self.source = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_watermark_declared(self) -> None:
        self.assertIn(
            'if (typeof window.lastLoadedDetailsTaskId === "undefined")',
            self.source,
        )

    def test_load_task_details_advances_watermark_on_success(self) -> None:
        body = _function_body(self.source, "loadTaskDetails")
        self.assertIn("window.lastLoadedDetailsTaskId = taskId", body)
        # 水位推进必须在 data.success 渲染分支内（选项渲染之后），
        # 失败路径不得推进——用 updateOptionsDisplay 调用位置近似锁定。
        options_idx = body.find("updateOptionsDisplay(")
        watermark_idx = body.find("window.lastLoadedDetailsTaskId = taskId")
        self.assertGreater(options_idx, 0)
        self.assertGreater(
            watermark_idx,
            options_idx,
            "水位必须在选项渲染成功之后推进，失败时保持原值以便下轮重试",
        )

    def test_polling_retries_until_watermark_matches(self) -> None:
        self.assertIn(
            "window.lastLoadedDetailsTaskId !== activeTaskId",
            self.source,
            "轮询条件必须包含水位比对：activeTaskId 从未成功加载过详情时"
            "每轮重试 loadTaskDetails",
        )


if __name__ == "__main__":
    unittest.main()
