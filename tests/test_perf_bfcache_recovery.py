"""perf-bfcache 回归契约：

Web 页面从浏览器 BFCache (back-forward cache) 还原时，``multi_task.js``
应当主动重启 polling + 健康检查 —— 否则用户看到的是冻结时刻的
任务列表 + 全部 timer 实际已暂停，要 ``Cmd+R`` 才能恢复。

这是 BUG5 的姊妹问题：
- BUG5 修"网络从离线恢复"（``online`` event）
- 本修补修"页面从 BFCache 恢复"（``pageshow`` event with persisted=true）

为什么必须锁定为 invariant
--------------------------
1. BFCache 是 Safari iOS / Chrome 96+ / Firefox 的**默认**行为，不是
   边缘场景；
2. 没有 ``pageshow`` 监听，从其他 tab 返回后任务列表静止、SSE 也死
   连接，但 UI 上一切正常 —— 用户唯一感知就是"突然不更新了"，
   debug 路径非常隐蔽（控制台看起来正常，network 看不到新请求）；
3. ``visibilitychange`` 在 BFCache 还原路径**不一定**触发（取决于
   浏览器实现 + 是否同时切回 tab）；
4. 既有 BUG5 ``online`` event 修补在 BFCache 路径也不会触发（网络
   一直在线，只是 JS 被冻结）。

锁定的不变量
------------
1. ``pageshow`` 必须被注册为 window listener；
2. handler 必须检查 ``event.persisted`` —— 非 BFCache 路径（正常
   加载）不应误触发；
3. handler 必须尊重 ``document.hidden``（避免 hidden tab 中 BFCache
   恢复后浪费资源）；
4. handler 必须调用 ``startTasksPolling`` + ``startTasksHealthCheck``
   两个幂等函数（与 ``online`` 事件路径完全对称）；
5. 整段必须包 try/catch，避免 init 主流程被 listener 注册失败破坏；
6. 与 BUG5 ``online`` 监听**互不依赖**（两者都注册），允许两者
   独立触发恢复路径。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _strip_js_comments(src: str) -> str:
    """剥除 // 行注释 + /* */ 块注释 —— 让 regex 不会被注释里的字符串误命中。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


class TestPageShowListenerRegistered(unittest.TestCase):
    """``pageshow`` 必须被注册为 window listener。"""

    def setUp(self) -> None:
        self.full = MULTI_TASK_JS.read_text(encoding="utf-8")
        self.code = _strip_js_comments(self.full)

    def test_pageshow_listener_present(self) -> None:
        self.assertRegex(
            self.code,
            r"window\.addEventListener\s*\(\s*['\"]pageshow['\"]",
            "multi_task.js 必须注册 window.addEventListener('pageshow', ...) "
            "处理 BFCache 还原",
        )

    def test_checks_event_persisted(self) -> None:
        """handler 必须检查 ``event.persisted``，否则正常加载会被误触发。"""
        # 找到 pageshow handler 体
        m = re.search(
            r"window\.addEventListener\s*\(\s*['\"]pageshow['\"]\s*,\s*function\s*\(\s*(\w+)\s*\)\s*\{(.*?)\}\s*\)",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 pageshow handler 函数体")
        assert m is not None
        param_name, body = m.group(1), m.group(2)
        self.assertIn(
            f"{param_name}.persisted",
            body,
            "pageshow handler 必须检查 ``event.persisted`` 区分 BFCache 还原 "
            "与普通加载（否则首次访问 / Cmd+R 也会重启 polling，浪费资源）",
        )

    def test_respects_document_hidden(self) -> None:
        m = re.search(
            r"window\.addEventListener\s*\(\s*['\"]pageshow['\"]\s*,\s*function\s*\(\s*\w+\s*\)\s*\{(.*?)\}\s*\)",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 pageshow handler 函数体")
        assert m is not None
        body = m.group(1)
        self.assertIn(
            "document.hidden",
            body,
            "pageshow handler 必须尊重 document.hidden —— 隐藏 tab 中"
            "BFCache 恢复不应启动 timer",
        )

    def test_calls_both_recovery_functions(self) -> None:
        m = re.search(
            r"window\.addEventListener\s*\(\s*['\"]pageshow['\"]\s*,\s*function\s*\(\s*\w+\s*\)\s*\{(.*?)\}\s*\)",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(1)
        self.assertIn(
            "startTasksPolling",
            body,
            "pageshow handler 必须调用 startTasksPolling 恢复任务轮询",
        )
        self.assertIn(
            "startTasksHealthCheck",
            body,
            "pageshow handler 必须调用 startTasksHealthCheck 恢复 30s 健康检查",
        )

    def test_wrapped_in_try_catch(self) -> None:
        """pageshow 监听 + 整段处理必须包在 try/catch，避免 init 主流程被破。"""
        m = re.search(
            r"try\s*\{[^}]*?window\.addEventListener\s*\(\s*['\"]pageshow['\"]",
            self.full,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "pageshow listener 注册必须包在 try {} catch 内（与 BUG5 online "
            "监听同样的鲁棒性模式）",
        )

    def test_perf_bfcache_anchor_in_comment(self) -> None:
        """注释里必须有 perf-bfcache 锚点，便于 grep / blame。"""
        self.assertIn(
            "perf-bfcache",
            self.full,
            "源码注释里必须有 ``perf-bfcache`` 锚点，便于追踪修复脉络",
        )


class TestParityWithOnlineEventListener(unittest.TestCase):
    """pageshow 与既有 online 监听必须独立 + 对称（同样的恢复函数对、
    同样的 ``document.hidden`` 检查、同样的 try/catch 兜底）。"""

    def setUp(self) -> None:
        self.full = MULTI_TASK_JS.read_text(encoding="utf-8")
        self.code = _strip_js_comments(self.full)

    def test_online_listener_still_present(self) -> None:
        """BUG5 既有的 online 监听不应被本修补意外破坏。"""
        self.assertRegex(
            self.code,
            r"window\.addEventListener\s*\(\s*['\"]online['\"]",
            "BUG5 既有的 online listener 必须保留",
        )

    def test_two_independent_listeners(self) -> None:
        """两个 listener 应分别注册（独立 try/catch + 独立 handler），
        而不是合并 fallthrough。"""
        online_count = len(
            re.findall(
                r"window\.addEventListener\s*\(\s*['\"]online['\"]",
                self.code,
            )
        )
        pageshow_count = len(
            re.findall(
                r"window\.addEventListener\s*\(\s*['\"]pageshow['\"]",
                self.code,
            )
        )
        self.assertEqual(online_count, 1, "online listener 应恰好注册 1 次")
        self.assertEqual(pageshow_count, 1, "pageshow listener 应恰好注册 1 次")


if __name__ == "__main__":
    unittest.main()
