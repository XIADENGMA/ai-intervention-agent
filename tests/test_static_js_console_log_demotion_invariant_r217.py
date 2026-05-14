"""R217 / Cycle 11 · F-cycle10-1 · static/js/ console.log demotion invariant。

设计目标
========

R216 把 ``notification-manager.js`` 27 个 ``console.log`` demote 为
``console.debug``, 浏览器 DevTools 默认 hide Verbose 级别让 INFO 日志
不再淹没真正的 warn / error 信号。R217 把同款 demotion 扩展到 ``src/
ai_intervention_agent/static/js/`` 目录下的其它 9 个项目自有 JS 文件:

  1. ``app.js`` (17 console.log → console.debug)
  2. ``image-upload.js`` (8)
  3. ``settings-manager.js`` (7)
  4. ``keyboard-shortcuts.js`` (3)
  5. ``theme.js`` (3)
  6. ``mathjax-loader.js`` (3)
  7. ``validation-utils.js`` (1)
  8. ``mathjax-config.js`` (1)
  9. ``state.js`` (1, JSDoc 示例)

累计 44 处 demotion (R216 27 处 + R217 44 处 = 71 处总)。剩余两类
保留:

A. **multi_task.js** (46 处 ``console.log``): 已有 ``_debugLog`` helper
   guarded by ``test_multi_task_sse_console_noise.py``, 应统一改用
   ``_debugLog`` 而非 ``console.debug`` — 留 R218 处理 (scope 太大,
   一次性改 46 行风险高)。
B. **vendor 文件** (``tex-mml-chtml.js`` MathJax bundle / ``prism.js``
   Prism / ``marked.js`` / ``lottie.min.js``): 第三方代码, R217 不动。
C. **dom-security.js** (2 处, 均在 JSDoc 注释 / 字符串字面值中):
   这些是 API 文档的示例代码, 不是真实调用, 保留作为接口说明。

设计契约
========

本 invariant test 守 R217 的核心契约:

1. **R217 处理过的 9 个文件 zero ``console.log(`` 调用**: 防止反向
   regression 把任何文件的 console.debug 改回 console.log。
2. **vendor allow-list 严格**: vendor 列表 hardcode 在测试里, 防止
   未来有人把项目自有 JS 误标为 vendor 绕过测试。
3. **multi_task.js + dom-security.js 单独 budget**: multi_task.js 在
   R218 处理前允许 ≤ 50 console.log (近 baseline); dom-security.js
   允许 ≤ 3 (JSDoc 示例 budget)。
4. **console.warn / console.error 不被本测试限制**: R217 不动这两个
   channel, 它们是真正应当被看见的信号 (R216 同款契约)。

为什么不一刀切整个 static/js/ 目录？
======================================

multi_task.js 是 task-state hot path, 它的 console.log 主要走 ``_debugLog``
helper (gated by ``window.AIIA_DEBUG`` flag), 与 R216/R217 的 "method
rename" 策略不同。强行批量 rename 会破坏 multi_task.js 的 _debugLog
contract 同时与 ``test_multi_task_sse_console_noise.py`` 的现有
invariant 冲突。R218 将单独处理 multi_task.js 的 console.log → _debugLog
migration (需要更细致的 case-by-case 替换)。

实施于 2026-05-14, 共 5 个测试用例 (4 类 invariant) + 11 subtests。
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"

R217_DEMOTED_FILES = (
    "app.js",
    "image-upload.js",
    "settings-manager.js",
    "keyboard-shortcuts.js",
    "theme.js",
    "mathjax-loader.js",
    "validation-utils.js",
    "mathjax-config.js",
    "state.js",
)

VENDOR_FILES = (
    "tex-mml-chtml.js",
    "prism.js",
    "marked.js",
    "lottie.min.js",
    # 也排除 R216 / 现有 invariant 已覆盖的:
    "notification-manager.js",  # R216 已守, 不重复
)

# 单独 budget 文件
MULTI_TASK_FILE = "multi_task.js"
DOM_SECURITY_FILE = "dom-security.js"

# R218 完成 multi_task.js 的 console.log → _debugLog migration 后, budget
# 从 50 收紧到 0 — 该文件应 zero console.log( 调用 (改用 _debugLog
# 通过 window.AIIA_DEBUG flag 控制是否真正输出)。
MULTI_TASK_BUDGET = 0  # R218 完成后收紧 (R217 当时是 50, R218 = 0)
DOM_SECURITY_BUDGET = 3  # JSDoc 示例 budget

# R218: multi_task.js 应有充足的 _debugLog 调用证明 migration 真发生
# (R218 前已有少量 _debugLog 在 _connectSSE 体内, R218 把全文 46 个
# console.log → _debugLog, baseline 约 ≥ 50)
MULTI_TASK_DEBUGLOG_MIN = 45


class TestR217DemotedFilesZeroConsoleLog(unittest.TestCase):
    """R217 处理过的 9 个文件 zero ``console.log(`` 调用。"""

    def test_all_r217_files_have_zero_console_log_calls(self) -> None:
        offenders: dict[str, int] = {}
        for fname in R217_DEMOTED_FILES:
            path = STATIC_JS_DIR / fname
            with self.subTest(file=fname):
                self.assertTrue(path.exists(), f"R217 文件缺失: {fname}")
                src = path.read_text(encoding="utf-8")
                count = src.count("console.log(")
                if count > 0:
                    offenders[fname] = count
                self.assertEqual(
                    count,
                    0,
                    f"{fname} 残留 {count} 个 console.log( 调用 (R217 invariant 要求 zero)。"
                    "请替换为 console.debug( (DevTools 默认 hide), 避免污染浏览器 Console。",
                )
        # 双保险全局断言, 给一个清晰汇总
        self.assertFalse(
            offenders,
            f"R217 违规文件总览: {offenders!r}; 全部应当 0 个 console.log(",
        )


class TestVendorAllowlistStrictness(unittest.TestCase):
    """vendor allow-list 必须严格 hardcode, 不允许项目自有 JS 进入。"""

    def test_vendor_files_distinct_from_r217(self) -> None:
        """vendor 列表 与 R217 处理列表 必须无交集 (防 typo / 误分类)。"""
        overlap = set(R217_DEMOTED_FILES) & set(VENDOR_FILES)
        self.assertFalse(
            overlap,
            f"R217 列表和 vendor 列表不应有交集, 实际交集 = {overlap!r}; "
            "可能某个项目自有 JS 被误标为 vendor。请审查 VENDOR_FILES 定义。",
        )

    def test_known_third_party_files_in_vendor_list(self) -> None:
        """vendor 列表必须包含 R217 已知的第三方库 (MathJax / Prism / marked / lottie)。"""
        expected = ("tex-mml-chtml.js", "prism.js", "marked.js", "lottie.min.js")
        for name in expected:
            with self.subTest(file=name):
                self.assertIn(
                    name,
                    VENDOR_FILES,
                    f"已知第三方库 {name} 应在 VENDOR_FILES; 否则 R217 invariant 会误报为违规。",
                )


class TestSpecialBudgetFiles(unittest.TestCase):
    """multi_task.js + dom-security.js 单独 budget 守 (前者 R218 处理, 后者 JSDoc 示例)。"""

    def test_multi_task_js_under_budget(self) -> None:
        """multi_task.js console.log( count ≤ MULTI_TASK_BUDGET (R218 已收紧到 0)。"""
        path = STATIC_JS_DIR / MULTI_TASK_FILE
        src = path.read_text(encoding="utf-8")
        count = src.count("console.log(")
        self.assertLessEqual(
            count,
            MULTI_TASK_BUDGET,
            f"{MULTI_TASK_FILE} console.log( = {count}, 超过 budget {MULTI_TASK_BUDGET}。"
            "R218 已完成 multi_task.js 的全部 console.log → _debugLog migration, "
            "此文件应 zero console.log( 调用。新加 console.log 请改用 _debugLog (定义在文件开头)。",
        )

    def test_multi_task_js_uses_debug_log_helper(self) -> None:
        """multi_task.js 应有 ≥ MULTI_TASK_DEBUGLOG_MIN 个 _debugLog( 调用证明 R218 migration 真发生。"""
        path = STATIC_JS_DIR / MULTI_TASK_FILE
        src = path.read_text(encoding="utf-8")
        count = src.count("_debugLog(")
        self.assertGreaterEqual(
            count,
            MULTI_TASK_DEBUGLOG_MIN,
            f"{MULTI_TASK_FILE} _debugLog( = {count}, 少于 R218 baseline {MULTI_TASK_DEBUGLOG_MIN}。"
            "可能 (a) 有人把 _debugLog 改回 console.log; (b) 误删大量诊断 log。"
            "请审查 git diff 找回根因。R218 后 multi_task.js 应有充足 _debugLog 调用 "
            "(被 window.AIIA_DEBUG flag 门控, 默认 production silent)。",
        )

    def test_dom_security_js_under_jsdoc_budget(self) -> None:
        """dom-security.js console.log( count ≤ DOM_SECURITY_BUDGET (JSDoc 示例 budget)。"""
        path = STATIC_JS_DIR / DOM_SECURITY_FILE
        src = path.read_text(encoding="utf-8")
        count = src.count("console.log(")
        self.assertLessEqual(
            count,
            DOM_SECURITY_BUDGET,
            f"{DOM_SECURITY_FILE} console.log( = {count}, 超过 JSDoc 示例 budget {DOM_SECURITY_BUDGET}。"
            "如果是真实调用应改为 console.debug(; 如果是 JSDoc 示例 demonstrating "
            "API 用法可以保留, 但需要扩大 budget 并加注释说明。",
        )


class TestForwardCompatNewFilesCheck(unittest.TestCase):
    """守 forward-compat: ``static/js/`` 中新加入的非-vendor非-special-budget JS 文件
    必须 zero console.log( (强制 contributor 一开始就用 console.debug)。"""

    def test_no_orphan_files_with_console_log(self) -> None:
        """扫整个 static/js/ 目录, 排除 vendor + special budget 后, 不在 R217 列表里的
        文件应该 zero console.log(。如果发现新文件违规, 测试给出明确诊断让 contributor
        知道要么加进 R217 列表 + demote, 要么 explicit 加 budget。
        """
        all_js = sorted(p.name for p in STATIC_JS_DIR.glob("*.js"))
        # 排除 .min.js 缩小后的 (例如 app.min.js — 是 build artifact, 不是源码)
        all_js = [n for n in all_js if not n.endswith(".min.js")]
        known = (
            set(R217_DEMOTED_FILES)
            | set(VENDOR_FILES)
            | {MULTI_TASK_FILE, DOM_SECURITY_FILE}
        )
        orphans = [n for n in all_js if n not in known]
        # 对每个 orphan 文件检查 console.log
        violations: dict[str, int] = {}
        for fname in orphans:
            path = STATIC_JS_DIR / fname
            src = path.read_text(encoding="utf-8")
            count = src.count("console.log(")
            if count > 0:
                violations[fname] = count
        self.assertFalse(
            violations,
            f"以下 static/js/ 文件不在 R217 已知列表里, 但含 console.log( 调用: {violations!r}。"
            "R217 forward-compat 要求新文件 (或之前未涵盖的文件) 也用 console.debug(。"
            "请: (a) 把文件加进 R217_DEMOTED_FILES 并 demote 调用; "
            "(b) 如果是 vendor 第三方, 加进 VENDOR_FILES; "
            "(c) 如果有特殊原因要保留 console.log (e.g. JSDoc), 加 special budget。"
            f"\n当前 orphan 文件列表: {orphans!r}",
        )


if __name__ == "__main__":
    unittest.main()
