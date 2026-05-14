"""R216 / Cycle 11 · F-cycle10-1 · notification-manager.js console noise invariant。

设计目标
========

``src/ai_intervention_agent/static/js/notification-manager.js`` 原有
27 个 ``console.log(`` 调用 (init / config-change / 每次播放声音 / 每
次降级通知 等), 对通知频繁的会话, 浏览器 Console 会被刷屏, 真正的
``console.warn`` / ``console.error`` (29 处) 被淹没在 INFO-级日志里,
用户难以发现 actionable 问题。

R216 把所有 27 个 ``console.log`` 统一 demote 为 ``console.debug``——
Chrome / Firefox / Safari / Edge DevTools 默认在 Console 顶部 filter
里关掉 Verbose / Debug 级别, 非开发者打开 DevTools 时不会看到这些;
开发者主动开启 Verbose 即可看到全部历史。零 helper / 零运行时开销,
纯方法名 rename, ``console.debug.apply(console, [...args])`` 与
``console.log.apply(console, [...args])`` 在所有现代浏览器行为完全一
致, 只是 level 不同。``console.warn`` / ``console.error`` 保留, 它们
是真正应当被看见的信号。

设计契约
========

本 invariant test 守 4 类不变量：

1. **零 console.log 残留**: notification-manager.js 源文件中
   ``console.log(`` 字面 substring 必须 zero 出现, 防止未来
   contributor 不知道 R216 约定又加回 INFO 级日志。
2. **console.debug 数量充足**: 文件中 ``console.debug(`` 必须 ≥ 20,
   证明 R216 demotion 真的发生了 (不是把 log 全删光), 也防止反向
   regression 把 console.debug 全 promote 回 console.log。
3. **console.warn / console.error 保留**: 这两个 channel 是真正
   应当被看见的信号, R216 不允许碰它们; 测试守 ``console.warn(``
   存在 (≥ 10), ``console.error(`` 存在 (≥ 3)。
4. **R216 banner 注释存在**: 文件头 ``/** ... */`` 注释中必须含
   ``R216`` + ``console`` + ``demote`` 关键词, 让未来读者一眼看
   到这个约定的来源 (而不是看到一堆 console.debug 不知所云)。

为什么是 static-text invariant 而不是 JS unit test？
====================================================

与 R214 同款 — 项目无 JS test runner, 引入 jest / vitest / playwright
会大幅扩 CI 表面积。R216 改动是纯方法名 rename, 27 行 1:1 替换, 用
静态 text-presence test 守反向 regression 已经足够。沿用 R211 / R212
/ R213 / R214 / R215 模式。

实施于 2026-05-14, 共 7 个测试用例 (4 类 invariant)。
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTIF_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-manager.js"
)


class TestZeroConsoleLog(unittest.TestCase):
    """R216 核心契约: notification-manager.js 必须 zero ``console.log(`` 调用。"""

    def setUp(self) -> None:
        self.assertTrue(
            NOTIF_JS.exists(), f"notification-manager.js missing: {NOTIF_JS}"
        )
        self.source = NOTIF_JS.read_text(encoding="utf-8")

    def test_zero_console_log_calls(self) -> None:
        """统计 ``console.log(`` 出现次数, 必须 == 0。

        替换为 ``console.debug(`` (DevTools 默认 hide), 让 INFO-级
        日志不再淹没真正的 warn/error。
        """
        count = self.source.count("console.log(")
        self.assertEqual(
            count,
            0,
            f"notification-manager.js 不应再含 console.log( 调用, 实际 {count} 次。"
            "R216 要求所有 INFO-级日志改用 console.debug( (DevTools 默认 hide), "
            "避免通知频繁会话刷屏淹没真正的 warn/error 信号。"
            "\n修复: 把新加的 console.log( 替换为 console.debug(",
        )

    def test_console_log_not_in_comments_either(self) -> None:
        """关键 invariant 字面文本守: 即便注释里 ``console.log`` 字面也限制。

        本测试 deliberately 用 ``count("console.log(")`` (带括号) 排除掉文档
        段中提到 ``console.log`` 文字 (e.g. R216 banner 解释为何换成
        ``console.debug``); 只数真正的调用语法。如果未来注释/字符串里出现
        ``console.log(...)`` 写法 (e.g. example code in JSDoc), 需要明确
        允许的话再扩 invariant。
        """
        without_paren_count = self.source.count("console.log")
        with_paren_count = self.source.count("console.log(")
        # 允许少量 docstring/comment 中的 console.log 字面引用 (说明性文字),
        # 但带括号的真实调用必须 0
        self.assertEqual(
            with_paren_count,
            0,
            "带括号的 console.log( 调用必须 zero (上面测试已覆盖, 双保险)",
        )
        # 注释里允许出现 ``console.log`` 文字 (e.g. R216 banner), 但有 budget
        self.assertLessEqual(
            without_paren_count,
            5,
            f"console.log 字面 (含注释 / docstring) 出现 {without_paren_count} 次, 超过 budget=5; "
            "可能有未替换的调用或大段示例代码 - 请审查。",
        )


class TestConsoleDebugMigrationCount(unittest.TestCase):
    """守 R216 demotion 真的发生 — 而不是把 log 全删光。"""

    def setUp(self) -> None:
        self.source = NOTIF_JS.read_text(encoding="utf-8")

    def test_console_debug_count_sufficient(self) -> None:
        """``console.debug(`` 调用必须 ≥ 20, 证明 R216 的 27 个 demotion 真的发生。

        允许少量 ≤ 7 的差距 (未来 refactor 可能合并/删除少量 debug
        语句), 但大幅减少 (< 20) 视为反向 regression: 要么是有人把
        console.debug 又 promote 回 console.log (违反 R216), 要么是
        无意中删了大量 debug log (失去诊断能力)。
        """
        count = self.source.count("console.debug(")
        self.assertGreaterEqual(
            count,
            20,
            f"console.debug( 调用 {count} 次, 少于 R216 baseline (27 个 demotion 中 ≥20 应保留)。"
            "可能 (a) 有人 promote 回 console.log; (b) refactor 误删 debug 语句。"
            "请审查 git diff 找回根因。",
        )


class TestWarnAndErrorChannelsPreserved(unittest.TestCase):
    """守 console.warn / console.error 完整保留 — R216 不许碰它们。"""

    def setUp(self) -> None:
        self.source = NOTIF_JS.read_text(encoding="utf-8")

    def test_console_warn_calls_preserved(self) -> None:
        """``console.warn(`` 调用必须 ≥ 10 (R216 前 baseline 是 ~15 个)。"""
        count = self.source.count("console.warn(")
        self.assertGreaterEqual(
            count,
            10,
            f"console.warn( 调用 {count} 次, 少于 R216 baseline (≥10 期待保留)。"
            "R216 设计前提是『warn 是真正应当被看见的信号, 不许 demote』; "
            "如果有人 demote warn 到 debug, 用户会错过权限错误 / SW 注册失败等关键反馈。",
        )

    def test_console_error_calls_preserved(self) -> None:
        """``console.error(`` 调用必须 ≥ 3 (R216 前 baseline 是 ~7 个)。"""
        count = self.source.count("console.error(")
        self.assertGreaterEqual(
            count,
            3,
            f"console.error( 调用 {count} 次, 少于 R216 baseline (≥3 期待保留)。"
            "R216 设计前提是『error 是真正应当被看见的信号, 不许 demote』; "
            "demote error 会让 Sentry/Datadog Browser RUM 等错误监控丢信号。",
        )


class TestR216BannerCommentPresent(unittest.TestCase):
    """守文件头 banner 注释含 R216 标识 — 让未来读者一眼看到约定来源。"""

    def setUp(self) -> None:
        self.source = NOTIF_JS.read_text(encoding="utf-8")

    def test_banner_contains_r216_keyword(self) -> None:
        """文件头 ``/** ... */`` block 注释必须含 'R216'。"""
        # 取前 80 行作为 banner 范围
        banner = "\n".join(self.source.splitlines()[:80])
        self.assertIn(
            "R216",
            banner,
            "notification-manager.js 文件头 banner 注释必须含 'R216' 关键字, "
            "让 contributor 看到 console.debug 用法时能 grep 到约定来源, "
            "而不是误以为是 console.log 的笔误。",
        )

    def test_banner_explains_console_demote(self) -> None:
        """banner 必须含 ``console`` + ``demote`` (或 ``debug``) 关键词。"""
        banner = "\n".join(self.source.splitlines()[:80])
        banner_lower = banner.lower()
        self.assertIn("console", banner_lower, "banner 必须 mention 'console'")
        has_demote_or_debug = "demote" in banner_lower or "debug" in banner_lower
        self.assertTrue(
            has_demote_or_debug,
            "banner 必须含 'demote' 或 'debug' 词, 说明 console.log → console.debug 约定。",
        )


if __name__ == "__main__":
    unittest.main()
