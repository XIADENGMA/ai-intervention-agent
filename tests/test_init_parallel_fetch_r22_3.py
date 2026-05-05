"""R22.3 · Web 前端 ``initMultiTaskSupport`` 冷启关键路径并行化的不变量与运行时验证。

背景
----
``static/js/multi_task.js::initMultiTaskSupport`` 是 Web UI 启动后任务面板
的初始化入口（被 ``app.js::initializeApp`` 在 ``loadConfig().then(...)``
内异步调用），R22.3 之前的代码形如：

    await fetchFeedbackPromptsFresh()  // GET /api/get-feedback-prompts
    await refreshTasksList()           // GET /api/tasks

这两个 endpoint 互相独立——前者只回写 ``window.feedbackPrompts`` 与设置面板
``config-file-path`` 输入框，后者只回写任务列表 UI——但被串行 ``await``
等于把两次独立的网络往返叠加成 ``2× RTT``。在典型 LAN/loopback 链路 RTT
单次 ~5-15 ms 的场景，这是 ~10-30 ms 的纯阻塞延迟，落在用户感知最敏感的
"页面已加载但任务区还在转圈"窗口里。

R22.3 修复：把两个 await 合并成 ``await Promise.all([..., ...])``，让两个
fetch 在同一个事件循环 tick 内并行下发，关键路径压到 ``max(RTT_a, RTT_b)``。

本测试覆盖三个层面：

1.  **源码不变量**：``initMultiTaskSupport`` 函数体里包含 ``Promise.all([...])``
    且其中显式引用了 ``fetchFeedbackPromptsFresh`` / ``refreshTasksList``，
    禁止再次出现旧的 ``await fetchFeedbackPromptsFresh(); await refreshTasksList();``
    串行写法。
2.  **文档契约**：函数体附近的注释 / docstring 提到 ``R22.3`` 与 ``Promise.all``
    设计要点，便于 ``git grep R22.3`` 定位上下文。
3.  **运行时行为**（仅当本机有 ``node``）：在 Node sandbox 里把两个目标函数
    替换成可控的 stub，确认 ``initMultiTaskSupport`` 真的并发触发它们而不是
    顺序触发。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_PATH = REPO_ROOT / "static" / "js" / "multi_task.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _read_source() -> str:
    assert MULTI_TASK_PATH.is_file(), f"multi_task.js 缺失: {MULTI_TASK_PATH}"
    return MULTI_TASK_PATH.read_text(encoding="utf-8")


def _extract_init_function(source: str) -> str:
    """提取 ``async function initMultiTaskSupport() { ... }`` 的函数体（含大括号）。

    采用括号配对扫描，避免简单正则在 docstring 内出现 ``}`` 时误匹配。
    """
    marker = "async function initMultiTaskSupport()"
    start = source.find(marker)
    assert start >= 0, "找不到 initMultiTaskSupport 定义"
    brace_open = source.find("{", start)
    assert brace_open >= 0, "initMultiTaskSupport 缺少 ``{``"

    depth = 0
    in_str: str | None = None
    in_template = False
    in_line_comment = False
    in_block_comment = False
    i = brace_open
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        prev = source[i - 1] if i > 0 else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if in_template:
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                in_template = False
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == "`":
            in_template = True
            i += 1
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace_open : i + 1]
        i += 1

    raise AssertionError("initMultiTaskSupport 函数体没有正确闭合")


# ---------------------------------------------------------------------------
# 1. 源码不变量
# ---------------------------------------------------------------------------


class TestSourceInvariants(unittest.TestCase):
    """``initMultiTaskSupport`` 内部必须用 ``Promise.all`` 并行两个独立 fetch。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()
        cls.init_body = _extract_init_function(cls.source)

    def test_init_function_exists(self) -> None:
        self.assertIn("async function initMultiTaskSupport()", self.source)

    def test_init_body_contains_promise_all(self) -> None:
        self.assertIn(
            "Promise.all(",
            self.init_body,
            "initMultiTaskSupport 必须使用 Promise.all 并行两个独立 fetch",
        )

    def test_promise_all_includes_both_targets(self) -> None:
        """``Promise.all([...])`` 数组里必须同时引用两个目标函数。"""
        match = re.search(
            r"Promise\.all\s*\(\s*\[(?P<inner>[\s\S]*?)\]\s*\)",
            self.init_body,
        )
        self.assertIsNotNone(match, "找不到 Promise.all([...]) 调用")
        assert match is not None
        inner = match.group("inner")
        self.assertIn(
            "fetchFeedbackPromptsFresh",
            inner,
            "Promise.all 数组必须包含 fetchFeedbackPromptsFresh()",
        )
        self.assertIn(
            "refreshTasksList",
            inner,
            "Promise.all 数组必须包含 refreshTasksList()",
        )

    def test_no_legacy_serial_awaits(self) -> None:
        """禁止再次出现串行 ``await fetchFeedbackPromptsFresh(...); await refreshTasksList(...)``。"""
        # 把空白与潜在分号统一压扁，再扫一段窗口
        flattened = re.sub(r"\s+", " ", self.init_body)
        legacy_pattern = re.compile(
            r"await\s+fetchFeedbackPromptsFresh\(\s*\)\s*;?\s*"
            r"(?!.*Promise\.all)await\s+refreshTasksList\(\s*\)"
        )
        self.assertIsNone(
            legacy_pattern.search(flattened),
            "initMultiTaskSupport 中仍存在旧的串行 await 写法",
        )

    def test_promise_all_is_awaited(self) -> None:
        """``Promise.all([...])`` 必须被 ``await``，否则后续 ``startTasksPolling`` 会先跑。"""
        # 简单宽松匹配：函数体里出现 `await Promise.all(`
        self.assertRegex(
            self.init_body,
            r"await\s+Promise\.all\s*\(",
            "Promise.all 必须被 await，否则 fire-and-forget 会与后续语句交错",
        )

    def test_start_tasks_polling_after_promise_all(self) -> None:
        """``startTasksPolling()`` 必须出现在 ``await Promise.all(...)`` 之后。"""
        all_idx = self.init_body.find("Promise.all(")
        polling_idx = self.init_body.find("startTasksPolling()")
        self.assertGreater(all_idx, -1, "找不到 Promise.all 调用位置")
        self.assertGreater(polling_idx, -1, "找不到 startTasksPolling 调用")
        self.assertGreater(
            polling_idx,
            all_idx,
            "startTasksPolling 必须在 Promise.all 之后调用，否则两者关系反转",
        )

    def test_only_one_promise_all_in_init(self) -> None:
        """``initMultiTaskSupport`` 当前只需要一处 ``Promise.all``；多了就要解释。"""
        count = self.init_body.count("Promise.all(")
        self.assertEqual(
            count,
            1,
            f"initMultiTaskSupport 内只允许一个 Promise.all（实际 {count} 个），"
            "如需新增请同步更新这条不变量与 docstring",
        )


# ---------------------------------------------------------------------------
# 2. 文档契约
# ---------------------------------------------------------------------------


class TestDocstringContract(unittest.TestCase):
    """函数附近的注释 / docstring 必须解释 R22.3 的并行化理由。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.init_body = _extract_init_function(_read_source())

    def test_init_body_mentions_r22_3(self) -> None:
        self.assertIn(
            "R22.3",
            self.init_body,
            "initMultiTaskSupport 内必须出现 R22.3 标记，便于 git grep 回溯",
        )

    def test_init_body_explains_parallel_intent(self) -> None:
        """注释里至少出现一次 ``并行`` / ``parallel`` / ``Promise.all`` 之类的词。"""
        keywords = ("并行", "parallel", "Promise.all", "RTT")
        hits = [k for k in keywords if k in self.init_body]
        self.assertTrue(
            hits,
            "initMultiTaskSupport 注释应说明并行化动机（包含: 并行 / parallel / Promise.all / RTT 任一）",
        )


# ---------------------------------------------------------------------------
# 3. 运行时行为（仅在本机有 node 时跑）
# ---------------------------------------------------------------------------


class TestRuntimeBehavior(unittest.TestCase):
    """用 Node 子进程把两个目标函数替换成 stub，确认它们被并发触发。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not _node_available():
            raise unittest.SkipTest("本机未安装 node，跳过运行时验证")

    def _run_node_harness(self) -> dict[str, Any]:
        """构造一个 minimal harness：

        - 用正则从 multi_task.js 抽出 initMultiTaskSupport 函数源码
        - 在 Node 沙箱里 stub 掉
          ``fetchFeedbackPromptsFresh`` / ``refreshTasksList`` /
          ``startTasksPolling`` / ``console`` / ``setInterval`` / ``document`` 等
        - 记录两个 stub 被调用的相对时序
        """
        src = _read_source()
        init_body = _extract_init_function(src)

        # 把 init_body 做成可执行函数源
        # （我们只需要函数体本身，不要外面的 ``async function ...() ``）
        # init_body 形如 ``{ ... }``，直接拼成 ``async function harness() <init_body>``
        async_fn_src = f"async function harness() {init_body}"

        with tempfile.TemporaryDirectory() as td:
            harness_path = Path(td) / "harness.js"
            harness_src = textwrap.dedent(
                """
                'use strict';

                const calls = [];
                let p1Resolve, p2Resolve;

                async function fetchFeedbackPromptsFresh() {
                  const t = Date.now();
                  calls.push({ fn: 'fetchFeedbackPromptsFresh', enter: t });
                  return new Promise((resolve) => {
                    p1Resolve = () => {
                      calls.push({ fn: 'fetchFeedbackPromptsFresh', exit: Date.now() });
                      resolve('ok-1');
                    };
                  });
                }

                async function refreshTasksList() {
                  const t = Date.now();
                  calls.push({ fn: 'refreshTasksList', enter: t });
                  return new Promise((resolve) => {
                    p2Resolve = () => {
                      calls.push({ fn: 'refreshTasksList', exit: Date.now() });
                      resolve('ok-2');
                    };
                  });
                }

                function startTasksPolling() {
                  calls.push({ fn: 'startTasksPolling', enter: Date.now() });
                }

                // 兼容 init body 内可能引用的浏览器 API
                // 把 console 静默掉：init body 里 ``console.log('Initializing…')``
                // 会污染 stdout，让父进程拿不到干净 JSON。warn / error 也吞掉，
                // 因为 multi_task.js 在 stub 化之后某些 fallback 路径会 warn 出来。
                globalThis.console = { log: () => {}, warn: () => {}, error: () => {}, info: () => {}, debug: () => {} };
                globalThis.setInterval = () => 0;
                globalThis.document = {
                  hidden: false,
                  getElementById: () => null,
                  addEventListener: () => undefined,
                };
                globalThis.window = globalThis;

                __ASYNC_FN_SRC__

                (async () => {
                  const harnessPromise = harness();
                  // 两个 stub 应都进入了 enter 状态
                  await new Promise((r) => setTimeout(r, 50));

                  // 两个 stub 同时 resolve（顺序无关）
                  if (typeof p1Resolve === 'function') p1Resolve();
                  if (typeof p2Resolve === 'function') p2Resolve();

                  await harnessPromise;
                  process.stdout.write(JSON.stringify(calls));
                })();
                """
            ).replace("__ASYNC_FN_SRC__", async_fn_src)
            harness_path.write_text(harness_src, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(harness_path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                env={**os.environ, "NO_COLOR": "1"},
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    "node 退出码 "
                    f"{proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
                )
            stdout = proc.stdout.strip()
            if not stdout:
                raise RuntimeError(
                    "node harness 输出为空；stderr="
                    f"{proc.stderr!r}\nstdout={proc.stdout!r}"
                )
            return {
                "calls": json.loads(stdout),
                "stderr": proc.stderr,
            }

    def test_both_stubs_dispatched_before_either_resolves(self) -> None:
        """两个 stub 必须都进入 ``enter`` 阶段后再有任何 ``exit``（即并发派发）。"""
        result = self._run_node_harness()
        calls: list[dict[str, Any]] = cast(list[dict[str, Any]], result["calls"])

        enters: list[dict[str, Any]] = [c for c in calls if "enter" in c]
        exits: list[dict[str, Any]] = [c for c in calls if "exit" in c]

        prompt_enter: dict[str, Any] | None = next(
            (c for c in enters if c.get("fn") == "fetchFeedbackPromptsFresh"), None
        )
        tasks_enter: dict[str, Any] | None = next(
            (c for c in enters if c.get("fn") == "refreshTasksList"), None
        )
        self.assertIsNotNone(
            prompt_enter, f"fetchFeedbackPromptsFresh 未被调用: {calls}"
        )
        self.assertIsNotNone(tasks_enter, f"refreshTasksList 未被调用: {calls}")
        self.assertGreater(len(exits), 0, f"两个 stub 都应该 exit: {calls}")
        assert prompt_enter is not None  # for type-narrowing
        assert tasks_enter is not None

        # exits 必须发生在两个 enters 都完成之后 —— 这是并行的强信号
        # （串行实现会先等第一个 exit 才让第二个 enter）
        first_exit_idx: int = calls.index(exits[0])
        first_prompt_enter_idx: int = calls.index(prompt_enter)
        first_tasks_enter_idx: int = calls.index(tasks_enter)
        self.assertLess(
            first_prompt_enter_idx,
            first_exit_idx,
            "fetchFeedbackPromptsFresh 必须在任何 exit 之前 enter（并行的必要条件）",
        )
        self.assertLess(
            first_tasks_enter_idx,
            first_exit_idx,
            "refreshTasksList 必须在任何 exit 之前 enter（并行的必要条件）",
        )

    def test_start_polling_after_both_resolved(self) -> None:
        """``startTasksPolling`` 必须发生在两个 fetch 全部 ``exit`` 之后。"""
        result = self._run_node_harness()
        calls: list[dict[str, Any]] = cast(list[dict[str, Any]], result["calls"])

        polling_idx: int | None = next(
            (i for i, c in enumerate(calls) if c.get("fn") == "startTasksPolling"),
            None,
        )
        self.assertIsNotNone(polling_idx, f"startTasksPolling 未被调用: {calls}")
        assert polling_idx is not None  # type-narrowing
        exit_indices: list[int] = [i for i, c in enumerate(calls) if "exit" in c]
        self.assertEqual(len(exit_indices), 2, f"应该有恰好两个 exit 事件: {calls}")
        for ex in exit_indices:
            self.assertLess(
                ex,
                polling_idx,
                "startTasksPolling 必须在两个 fetch 都完成后才执行",
            )


if __name__ == "__main__":
    unittest.main()
