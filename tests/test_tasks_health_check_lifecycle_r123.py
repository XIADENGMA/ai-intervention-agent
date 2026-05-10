"""R123 — ``multi_task.js`` 健康检查 setInterval 必须有可清理句柄。

## 背景

R123 之前 ``initMultiTaskSupport`` 在文件末尾写道：

    setInterval(function () { ... }, 30000)

这条 ``setInterval`` 的返回值（IntervalID）从未被赋值给任何变量——
意味着该 timer **永远无法被 ``clearInterval``**。两个失效模式：

1. **页面隐藏路径回收不彻底**：``visibilitychange`` 事件 handler 调用
   ``stopTasksPolling()`` 把短间隔轮询暂停了，但 30s 健康检查仍然在
   后台 tick——每个 tick 进入 ``if (document.hidden) return;`` 早退，
   表面上"无害"，实际上：
   - macOS / iOS Safari 在 ``page hidden`` 状态下仍会调度 setInterval
     callback（虽然降到 1Hz），消耗背景 tab 的 CPU 与 setInterval
     调度配额。
   - tab 切回前台时，30s 健康检查可能恰好命中"polling 还没拉起"
     的 race window，触发一次冗余的 ``startTasksPolling`` 调用，
     与 ``visibilitychange`` 的同步重启冲突。
2. **``initMultiTaskSupport`` 重复调用累积 interval**：``app.js`` 的
   ``loadConfig().then(initMultiTaskSupport).catch(setTimeout(initMultiTaskSupport))``
   分支看上去 .then/.catch 互斥，但若未来加入"reconnect 后重新初始化"
   等场景，就会 leak 多个 30s 健康检查 interval，每个独立触发
   ``startTasksPolling`` / ``_connectSSE``，造成"打开越久 = SSE
   reconnect 节奏越乱"的隐性 bug。

## R123 修复策略

把无名 ``setInterval`` 改造成一对幂等启停函数：

- ``startTasksHealthCheck()``：检查 ``window.tasksHealthCheckTimer``
  是否已存在；存在则 no-op（幂等），不存在则 ``setInterval(...)`` 并
  把 id 挂到 ``window.tasksHealthCheckTimer``。
- ``stopTasksHealthCheck()``：``clearInterval(window.tasksHealthCheckTimer)``
  并置 null（幂等）。

``visibilitychange`` 与 ``beforeunload`` handler 同步调用
``stopTasksHealthCheck`` ——彻底回收，零 background tick。

## 本测试锁定的不变量

1. **``setInterval`` 必须把返回值绑到 ``window.tasksHealthCheckTimer``**
   ——AST/字符串静态扫描，避免未来重构成"裸 setInterval"形式
   重新引入 leak。
2. **``startTasksHealthCheck`` 与 ``stopTasksHealthCheck`` 都必须存在**
   ——保证 module 暴露这两个函数，让 testing / Storybook 等使用方
   可以显式控制 timer 生命周期。
3. **``visibilitychange`` handler 必须在 hidden 分支调
   ``stopTasksHealthCheck``**——防止"只 stopTasksPolling 没 stop
   health check"的 partial-fix 退化。
4. **``beforeunload`` handler 必须调 ``stopTasksHealthCheck``**——
   避免 jsdom / SPA 内嵌场景跨页面 leak timer ref。
5. **``window.multiTaskModule.startTasksHealthCheck`` /
   ``stopTasksHealthCheck`` 必须在 export 列表里**——让 caller 能
   稳定取到接口。

## 实现说明

走纯静态字符串扫描而不是 jsdom 运行时验证：

- jsdom + node-fetch 的 setup 比扫一个 ~100 KB 的 JS 文件慢 100×；
- 静态扫描已经能锁住所有契约（结构 + 命名 + 调用关系）；
- 真正的 runtime 行为由 ``manual_test.py`` 真机 smoke 覆盖（页面
  隐藏 1 分钟后回到前台，看 console 是否有"Task polling stopped;
  auto-restarting" 的多余 warning）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


class TestHealthCheckTimerHasHandle(unittest.TestCase):
    """``setInterval(...)`` 必须把返回值赋给 ``window.tasksHealthCheckTimer``。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_health_check_setinterval_assigns_to_window_handle(self) -> None:
        """``startTasksHealthCheck`` 内 ``setInterval`` 的返回值必须保存。"""
        # 锚点：``function startTasksHealthCheck() {``
        start = self.src.find("function startTasksHealthCheck()")
        self.assertGreater(
            start,
            0,
            "找不到 startTasksHealthCheck 函数定义；R123 后该函数必须存在",
        )
        # 函数体大致到 next ``\nfunction `` 或 ``\n}`` 结束
        end = self.src.find("\nfunction ", start + 1)
        self.assertGreater(end, start, "找不到 startTasksHealthCheck 函数体结束")
        body = self.src[start:end]

        # 必须有形如 ``window.tasksHealthCheckTimer = setInterval(`` 的赋值
        self.assertRegex(
            body,
            r"window\.tasksHealthCheckTimer\s*=\s*setInterval\s*\(",
            "startTasksHealthCheck 必须把 setInterval 返回值赋给 "
            "window.tasksHealthCheckTimer——pre-R123 的"
            "裸 ``setInterval(...)`` 没保存 id 导致永远无法清理，"
            "本测试守护这个修复不被回退。",
        )

        # 必须有幂等检查：已有 timer 时 return / no-op
        self.assertRegex(
            body,
            r"if\s*\(\s*window\.tasksHealthCheckTimer\s*\)\s*\{",
            "startTasksHealthCheck 必须在已有 timer 时 early-return"
            "（幂等性），避免 init 被重复调用时累积多个并行 interval",
        )

    def test_stop_health_check_clears_timer_handle(self) -> None:
        """``stopTasksHealthCheck`` 必须 ``clearInterval`` 并置 null。"""
        start = self.src.find("function stopTasksHealthCheck()")
        self.assertGreater(
            start,
            0,
            "找不到 stopTasksHealthCheck 函数定义；R123 后该函数必须存在",
        )
        end = self.src.find("\nfunction ", start + 1)
        # stopTasksHealthCheck 可能是文件最后一个函数，没有下一个 ``\nfunction ``
        if end < 0:
            end = len(self.src)
        body = self.src[start:end]

        self.assertIn(
            "clearInterval(window.tasksHealthCheckTimer)",
            body,
            "stopTasksHealthCheck 必须 clearInterval(window.tasksHealthCheckTimer)",
        )
        self.assertRegex(
            body,
            r"window\.tasksHealthCheckTimer\s*=\s*null",
            "stopTasksHealthCheck 必须把 window.tasksHealthCheckTimer 置 null"
            "（让下次 startTasksHealthCheck 能再次启动，幂等保证）",
        )

    def test_health_check_timer_global_default_null(self) -> None:
        """``window.tasksHealthCheckTimer`` 必须有 ``= null`` 的默认初始化。"""
        # 用宽松正则避免被 if-block 内部缩进格式干扰
        self.assertRegex(
            self.src,
            r"window\.tasksHealthCheckTimer\s*=\s*null",
            "必须给 window.tasksHealthCheckTimer 提供默认 null 初始化"
            "（与文件顶部 tasksPollingTimer / newTaskHintTimer 等保持"
            "对称）",
        )


class TestVisibilityChangeStopsHealthCheck(unittest.TestCase):
    """``visibilitychange`` 事件 handler hidden 分支必须 stopTasksHealthCheck。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_visibility_handler_calls_stop_health_check_on_hidden(self) -> None:
        """visibilitychange handler 的 ``document.hidden`` 分支应同步停健康检查。"""
        # 锚点：``visibilitychange``
        start = self.src.find('"visibilitychange"')
        self.assertGreater(start, 0, "找不到 visibilitychange 事件注册")
        # handler body 大致是 ``visibilitychange``, function() { ... } 一段；
        # 找下一个 ``});`` 或 ``})`` 当结尾
        end = self.src.find("});", start)
        self.assertGreater(end, start, "找不到 visibilitychange handler 结束")
        body = self.src[start:end]

        # hidden 分支必须包含 stopTasksHealthCheck
        # 用 if (document.hidden) { ... stopTasksHealthCheck ... } 的宽松匹配
        hidden_branch = re.search(
            r"if\s*\(\s*document\.hidden\s*\)\s*\{(.*?)\}\s*else",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(
            hidden_branch,
            f"找不到 if (document.hidden) {{ ... }} else 分支结构；"
            f"visibilitychange handler 应同时处理 hidden / 非 hidden 两路。"
            f"实际 handler 片段: {body[:200]!r}",
        )
        # narrowing for ty
        assert hidden_branch is not None
        hidden_body = hidden_branch.group(1)
        self.assertIn(
            "stopTasksHealthCheck()",
            hidden_body,
            "visibilitychange hidden 分支必须调 stopTasksHealthCheck()——"
            "pre-R123 只 stopTasksPolling 没停 health check，导致后台 30s "
            "tick 仍持续消耗 CPU/调度配额",
        )


class TestBeforeUnloadStopsHealthCheck(unittest.TestCase):
    """``beforeunload`` handler 必须 stopTasksHealthCheck（防 timer leak）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_beforeunload_handler_calls_stop_health_check(self) -> None:
        """beforeunload handler 必须同时调 stopTasksPolling + stopTasksHealthCheck。"""
        start = self.src.find('"beforeunload"')
        self.assertGreater(start, 0, "找不到 beforeunload 事件注册")
        end = self.src.find("});", start)
        self.assertGreater(end, start, "找不到 beforeunload handler 结束")
        body = self.src[start:end]

        self.assertIn(
            "stopTasksPolling()",
            body,
            "beforeunload 必须 stopTasksPolling（已有契约，本测试顺便锁）",
        )
        self.assertIn(
            "stopTasksHealthCheck()",
            body,
            "beforeunload 必须同时 stopTasksHealthCheck()——避免 jsdom / "
            "SPA 内嵌场景跨页面 leak timer ref",
        )


class TestModuleExportSurface(unittest.TestCase):
    """``window.multiTaskModule`` 必须 export ``start/stopTasksHealthCheck``。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_module_exports_start_health_check(self) -> None:
        # 锚点：``window.multiTaskModule = {``
        start = self.src.find("window.multiTaskModule = {")
        self.assertGreater(start, 0, "找不到 window.multiTaskModule export 块")
        end = self.src.find("};", start)
        self.assertGreater(end, start, "找不到 multiTaskModule export 块结束")
        body = self.src[start:end]

        self.assertIn(
            "startTasksHealthCheck",
            body,
            "multiTaskModule export 必须含 startTasksHealthCheck，"
            "让 caller 可以稳定取到 API",
        )

    def test_module_exports_stop_health_check(self) -> None:
        start = self.src.find("window.multiTaskModule = {")
        end = self.src.find("};", start)
        body = self.src[start:end]

        self.assertIn(
            "stopTasksHealthCheck",
            body,
            "multiTaskModule export 必须含 stopTasksHealthCheck",
        )


class TestNoBareSetIntervalInsideInitFunction(unittest.TestCase):
    """``initMultiTaskSupport`` 函数体内不应再出现裸 ``setInterval`` 写法。

    历史代码就是在这里漏写 id 保存的；本测试锁住"未来若有人再次写
    裸 ``setInterval(..., 30000)`` 必须 fail" 的不变量。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_init_function_has_no_unassigned_setinterval(self) -> None:
        # 锚点：``async function initMultiTaskSupport()``
        start = self.src.find("async function initMultiTaskSupport()")
        self.assertGreater(start, 0, "找不到 initMultiTaskSupport 函数定义")
        # 函数体大致到 ``\nfunction `` 或 ``\nasync function `` 或文件结束
        end_candidates: list[int] = []
        for marker in ("\nfunction ", "\nasync function ", "\n// =="):
            pos = self.src.find(marker, start + 1)
            if pos > 0:
                end_candidates.append(pos)
        end = min(end_candidates) if end_candidates else len(self.src)
        body = self.src[start:end]

        # 该函数体内不应再有任何形如 ``setInterval(`` 的调用——
        # 健康检查启动应统一走 ``startTasksHealthCheck()``。
        # 任务倒计时 setInterval 在别的函数 (``setupCountdownTimer`` 等)，
        # 不在本函数体内。
        bare_calls = re.findall(r"\bsetInterval\s*\(", body)
        self.assertEqual(
            len(bare_calls),
            0,
            "initMultiTaskSupport 函数体不应直接调用 setInterval；"
            f"实测找到 {len(bare_calls)} 处。R123 后所有健康检查 timer "
            "都应通过 startTasksHealthCheck() 间接启动，避免再次 leak "
            "无 id 的 interval。",
        )


if __name__ == "__main__":
    unittest.main()
