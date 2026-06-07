"""R298: AbortController 内存泄漏审计 + invariant 测试。

cycle-29 #D (cr58 §5)：`fetchWithTimeout` (app.js) 和
`tasksPollAbortController` (multi_task.js) 是 hot-path 上使用 AbortController
的两处主入口。AbortController + addEventListener 是 JS 常见的内存泄漏
源（listener 不 removeEventListener / timer 不 clearTimeout / controller
不释放引用），但**当前没有 invariant 锁定这些清理路径**，未来 refactor
极易引入 silent leak。

R298 锁定 6 个关键 cleanup invariant:

================================================================
| 维度                                                | tests |
|-----------------------------------------------------|-------|
| 1. fetchWithTimeout fallback path 必须 finally cleanup | 4    |
| 2. fetchWithTimeout 必须用 { once: true } 防 listener 累积 | 2 |
| 3. tasksPollAbortController 必须 abort 旧 controller (防 race) | 2 |
| 4. tasksPollAbortController 硬超时必须 finally clearTimeout | 2 |
| 5. tasksPollAbortController 必须 finally 释放 = null | 2 |
| 6. catch AbortError 必须静默 (不报 user error)        | 2     |
================================================================
| 合计                                                | 14    |
================================================================

**新 pattern**: **lifecycle-cleanup invariant** — 锁定 try/finally /
addEventListener+removeEventListener / once 配对，防止 AbortController
listener / timer 引用泄漏导致长期运行（≥1 小时）的 web 客户端内存
持续增长，最终触发浏览器 OOM kill 或人工 reload。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"
APP_JS = SRC / "static" / "js" / "app.js"
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


def _extract_function_body(src: str, fn_pattern: str) -> str:
    """提取函数体（含闭合大括号 balance）。返回完整 body 或空字符串。"""
    m = re.search(fn_pattern, src)
    if m is None:
        return ""
    body_start = src.find("{", m.end() - 1)
    if body_start < 0:
        return ""
    depth = 0
    i = body_start
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[body_start : i + 1]
        i += 1
    return ""


# ============================================================
# #1: fetchWithTimeout fallback path 必须 finally cleanup
# ============================================================
class TestFetchWithTimeoutFallbackCleanup(unittest.TestCase):
    """app.js fetchWithTimeout fallback path 必须 clearTimeout + removeEventListener"""

    def setUp(self) -> None:
        js = _strip_js_comments(_read(APP_JS))
        self.body = _extract_function_body(
            js, r"function fetchWithTimeout\(url,\s*options,\s*timeoutMs\)"
        )
        self.assertGreater(
            len(self.body),
            0,
            "未能找到 fetchWithTimeout 函数体",
        )

    def test_fallback_has_finally_clause(self) -> None:
        """fallback path 必须用 .finally() 做 cleanup。"""
        self.assertRegex(
            self.body,
            r"\.finally\(\s*function",
            "fetchWithTimeout fallback 必须有 .finally(function() {...}) 清理",
        )

    def test_fallback_calls_cleartimeout(self) -> None:
        """fallback 的 .finally 必须 clearTimeout(timer)。"""
        self.assertRegex(
            self.body,
            r"\.finally\([\s\S]+?clearTimeout\(\s*timer\s*\)",
            "fetchWithTimeout fallback .finally 必须 clearTimeout(timer)",
        )

    def test_fallback_removes_user_listener(self) -> None:
        """fallback 的 .finally 必须 userSignal.removeEventListener('abort', onUserAbort)。"""
        self.assertRegex(
            self.body,
            r"\.finally\([\s\S]+?userSignal\.removeEventListener\(\s*['\"]abort['\"]\s*,\s*onUserAbort",
            "fetchWithTimeout fallback .finally 必须 userSignal.removeEventListener('abort', onUserAbort)",
        )

    def test_fallback_uses_addEventListener_once_option(self) -> None:
        """fallback 的 userSignal.addEventListener 必须用 { once: true } (双保险)。"""
        self.assertRegex(
            self.body,
            r"userSignal\.addEventListener\(\s*['\"]abort['\"]\s*,\s*onUserAbort\s*,\s*\{\s*once\s*:\s*true\s*\}",
            "fetchWithTimeout fallback userSignal.addEventListener 必须 { once: true }",
        )


# ============================================================
# #2: fetchWithTimeout 必须用 { once: true } 防 listener 累积
# ============================================================
class TestFetchWithTimeoutOnceOption(unittest.TestCase):
    """`{ once: true }` 是双保险，即便 removeEventListener 漏调，listener 也只触发一次自销毁"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(APP_JS))

    def test_once_true_present_in_addEventListener(self) -> None:
        once_count = len(
            re.findall(
                r"addEventListener\([\s\S]{0,100}?\{\s*once\s*:\s*true\s*\}",
                self.js,
            )
        )
        self.assertGreaterEqual(
            once_count,
            1,
            "app.js 必须至少有 1 处 addEventListener 用 { once: true } 做双保险",
        )

    def test_userSignal_check_aborted_before_listener_attach(self) -> None:
        """fetchWithTimeout 必须先 check userSignal.aborted 再 addEventListener (避免对已 aborted signal 注册无意义 listener)。"""
        body = _extract_function_body(
            self.js, r"function fetchWithTimeout\(url,\s*options,\s*timeoutMs\)"
        )
        m = re.search(
            r"if\s*\(\s*userSignal\.aborted\s*\)[\s\S]{0,200}?userSignal\.addEventListener",
            body,
        )
        self.assertIsNotNone(
            m,
            "fetchWithTimeout 必须先 if (userSignal.aborted) { controller.abort() } "
            "再走 else userSignal.addEventListener(...) 路径 — 避免对已 aborted "
            "signal 注册 listener",
        )


# ============================================================
# #3: tasksPollAbortController 必须 abort 旧 controller (防 race)
# ============================================================
class TestTasksPollAbortRaceGuard(unittest.TestCase):
    """multi_task.js fetchAndApplyTasks 必须先 abort 旧 controller 再 new"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(MULTI_TASK_JS))

    def test_old_controller_aborted_before_new(self) -> None:
        """模式: if (tasksPollAbortController && abort) tasksPollAbortController.abort();
        然后 tasksPollAbortController = new AbortController()。"""
        m = re.search(
            r"if\s*\(\s*tasksPollAbortController\s*&&[\s\S]{0,200}?tasksPollAbortController\.abort\(\)[\s\S]{0,800}?tasksPollAbortController\s*=\s*new\s+AbortController\(\)",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "multi_task.js 必须先 if (tasksPollAbortController) abort() 再 new "
            "AbortController — 防止 race 让旧 in-flight fetch 占用",
        )

    def test_abort_wrapped_in_try_catch(self) -> None:
        """tasksPollAbortController.abort() 必须用 try/catch 包裹（部分浏览器 abort 抛异常）。"""
        m = re.search(
            r"try\s*\{[\s\S]{0,200}?tasksPollAbortController\.abort\(\)",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "tasksPollAbortController.abort() 调用必须包在 try/catch 内 — "
            "某些浏览器 abort() 在异常状态下会 throw",
        )


# ============================================================
# #4: tasksPollAbortController 硬超时必须 finally clearTimeout
# ============================================================
class TestTasksPollHardTimeoutCleanup(unittest.TestCase):
    """multi_task.js 硬超时 timer 必须 finally clearTimeout (成功 + 异常路径都要)"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(MULTI_TASK_JS))

    def test_hard_timeout_var_declared(self) -> None:
        """硬超时变量 tasksTimeoutId 必须声明并初始化为 null。"""
        self.assertRegex(
            self.js,
            r"let\s+tasksTimeoutId\s*=\s*null",
            "multi_task.js 必须 let tasksTimeoutId = null (硬超时 timer id)",
        )

    def test_finally_clears_hard_timeout(self) -> None:
        """finally 块必须 clearTimeout(tasksTimeoutId) — 成功 + 异常路径都要。"""
        m = re.search(
            r"finally\s*\{[\s\S]{0,400}?clearTimeout\(\s*tasksTimeoutId\s*\)",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "fetchAndApplyTasks finally 必须 clearTimeout(tasksTimeoutId) — "
            "不在 finally 清理则异常路径 leak setTimeout 引用",
        )


# ============================================================
# #5: tasksPollAbortController 必须 finally 释放 = null
# ============================================================
class TestTasksPollControllerRelease(unittest.TestCase):
    """multi_task.js fetchAndApplyTasks finally 必须释放 controller = null (避免长期持有)"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(MULTI_TASK_JS))

    def test_finally_nulls_controller(self) -> None:
        """finally 必须 tasksPollAbortController = null。"""
        m = re.search(
            r"finally\s*\{[\s\S]{0,400}?tasksPollAbortController\s*=\s*null",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "fetchAndApplyTasks finally 必须 tasksPollAbortController = null — "
            "controller 长期持有引用会让浏览器 GC 不能回收 underlying signal",
        )

    def test_global_controller_var_declared(self) -> None:
        """tasksPollAbortController 必须是 module-level var (避免每次 fetch 创新引用空间)。"""
        self.assertRegex(
            self.js,
            r"var\s+tasksPollAbortController\s*=\s*null",
            "multi_task.js 必须 var tasksPollAbortController = null (module-level)",
        )


# ============================================================
# #6: catch AbortError 必须静默 (不报 user error)
# ============================================================
class TestAbortErrorSilent(unittest.TestCase):
    """AbortError 是正常 cancel 路径，不应该 surface 为 user-visible error"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(MULTI_TASK_JS))

    def test_aborterror_check_present(self) -> None:
        """fetchAndApplyTasks catch 必须 check error.name === 'AbortError'。"""
        self.assertRegex(
            self.js,
            r'error\.name\s*===\s*["\']AbortError["\']',
            "multi_task.js catch 必须 check error.name === 'AbortError' (避免把正常 cancel 计为错误)",
        )

    def test_aborterror_handled_with_return_false(self) -> None:
        """AbortError 分支必须 return false (不是 throw 也不是 console.error)。"""
        m = re.search(
            r'error\.name\s*===\s*["\']AbortError["\'][\s\S]{0,200}?return\s+false',
            self.js,
        )
        self.assertIsNotNone(
            m,
            "AbortError 分支必须 return false — 让上层 backoff/重试逻辑接管，"
            "而不是抛错或弹 toast 让用户感知到 cancel 是错误",
        )


if __name__ == "__main__":
    unittest.main()
