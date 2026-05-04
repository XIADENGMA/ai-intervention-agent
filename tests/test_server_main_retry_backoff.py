"""``server.main()`` MCP 重启循环的指数退避 + jitter 不变量锁试。

历史背景：
- 历史实现是 ``time.sleep(1)`` 固定 1s 间隔，多实例并发场景（一台机器
  同时跑 Cursor + VS Code 两个 MCP client）会让所有重启撞向同一个下游
  资源——thundering herd 反模式。
- v1.5.x round-15 改为 ``base × 2^(n-1) + jitter``，base=1s、cap=4s、
  jitter=[0, base × 0.5)。本测试同时锁两个层面：

1. **静态**：AST 解析 ``server.py::main``，确认重试代码块包含指数退避
   关键字（``2 **`` 幂运算 + ``random.uniform`` jitter + ``min(...,``
   cap），且没有再硬编码 ``time.sleep(1)``。
2. **行为**：mock ``mcp.run`` 抛异常，mock ``time.sleep`` / ``sys.exit``
   / ``cleanup_services`` 拦截副作用，验证 sleep 实参随 retry_count 指
   数增长（第 1 次 ∈ [1, 1.5)，第 2 次 ∈ [2, 3)），并最终 sys.exit(1)。

未来如果把 ``time.sleep(1)`` 复活会让 (1) 和 (2) 同时 fail，给重构者
明确的指向。
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_main_function_source() -> str:
    """提取 ``server.main`` 函数的源码字符串供静态断言用。"""
    src = (REPO_ROOT / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return ast.unparse(node)
    raise AssertionError("server.py 中找不到 def main，是不是改名了？")


class TestMainRetryStaticInvariants(unittest.TestCase):
    """静态层面：``server.main`` 必须包含指数退避 + jitter 关键字。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.main_src = _load_main_function_source()

    def test_uses_exponential_growth(self) -> None:
        """重试 delay 必须包含 ``2 **`` 幂运算（指数退避）。"""
        self.assertIn(
            "2 **",
            self.main_src,
            "server.main 必须使用指数退避（``2 ** (retry_count - 1)``）；"
            "如果你看到这条 fail，说明退避策略被改回固定间隔——重新引入 thundering herd 风险",
        )

    def test_uses_random_jitter(self) -> None:
        """重试 delay 必须叠加 ``random.uniform`` jitter（去同步化）。"""
        self.assertIn(
            "random.uniform",
            self.main_src,
            "server.main 必须叠加 jitter（``random.uniform(0.0, ...)``）；"
            "无 jitter 的指数退避在多实例同步失败时仍会 lockstep 重试，违背 AWS/Google SRE 最佳实践",
        )

    def test_uses_max_cap(self) -> None:
        """指数退避必须有上界 ``min(...)``，避免 retry_count 调大后单次等待爆炸。"""
        self.assertIn(
            "min(",
            self.main_src,
            "server.main 的退避计算必须用 ``min(base × 2^n, cap)`` 设上界；"
            "无 cap 时如果未来 max_retries 从 3 调到 10，单次等待会膨胀到 512s 量级",
        )

    def test_no_hardcoded_one_second_sleep(self) -> None:
        """``time.sleep(1)`` 等不带变量的固定整秒等待不应再出现在重试块。"""
        # 允许 ``time.sleep(delay)`` / ``time.sleep(delay_seconds)`` 等变量化用法；
        # 仅拒绝硬编码的 ``time.sleep(1)`` / ``time.sleep(1.0)`` / ``time.sleep(2)``。
        forbidden = (
            "time.sleep(1)",
            "time.sleep(1.0)",
            "time.sleep(2)",
            "time.sleep(2.0)",
        )
        for needle in forbidden:
            self.assertNotIn(
                needle,
                self.main_src,
                f"server.main 不应硬编码 ``{needle}``；"
                f"应使用变量化的退避计算结果（如 ``time.sleep(delay)``）",
            )


class TestMainRetryBackoffBehaviour(unittest.TestCase):
    """行为层面：模拟 mcp.run 连续抛异常，sleep 时长必须随 retry 指数增长。"""

    def _drive_main_with_mocked_run(
        self, *, run_exception: BaseException
    ) -> tuple[list[float], int | None]:
        """让 ``server.main()`` 跑完 max_retries 次失败循环，返回 (sleep 实参列表, exit code)。"""
        import server

        sleep_args: list[float] = []
        exit_code_box: list[int | None] = [None]

        def fake_sleep(seconds: float) -> None:
            sleep_args.append(float(seconds))

        def fake_exit(code: int = 0) -> None:
            exit_code_box[0] = int(code)
            # 真正退出测试 runner 不行，抛特殊异常让 main() 跳出循环
            raise SystemExit(int(code))

        # mcp.run 持续抛异常，驱动 except 分支
        mock_mcp = MagicMock()
        mock_mcp.run.side_effect = run_exception

        with (
            patch.object(server, "mcp", mock_mcp),
            patch.object(server, "cleanup_services"),
            patch("server.time.sleep", side_effect=fake_sleep),
            patch("server.sys.exit", side_effect=fake_exit),
        ):
            try:
                server.main()
            except SystemExit:
                # fake_exit 抛的，预期路径
                pass

        return sleep_args, exit_code_box[0]

    def test_sleep_times_grow_exponentially(self) -> None:
        """两次重试的 sleep 实参必须呈指数增长（第 2 次 ≥ 第 1 次 × 2）。"""
        sleeps, exit_code = self._drive_main_with_mocked_run(
            run_exception=RuntimeError("simulated mcp.run failure")
        )

        # max_retries=3：失败 1 → sleep → 失败 2 → sleep → 失败 3 → sys.exit(1)
        # 即应该有恰好 2 次 sleep。
        self.assertEqual(
            len(sleeps),
            2,
            f"max_retries=3 时应该有 2 次 sleep（失败 1、失败 2 各一次）；实际: {sleeps}",
        )
        self.assertEqual(exit_code, 1, "max_retries 用尽后应 sys.exit(1)")

        # 第 1 次 base=1s，jitter ∈ [0, 0.5) → delay ∈ [1.0, 1.5)
        self.assertGreaterEqual(sleeps[0], 1.0)
        self.assertLess(sleeps[0], 1.5)

        # 第 2 次 base=2s，jitter ∈ [0, 1.0) → delay ∈ [2.0, 3.0)
        self.assertGreaterEqual(sleeps[1], 2.0)
        self.assertLess(sleeps[1], 3.0)

        # 关键：第 2 次必须严格大于第 1 次（指数增长）
        self.assertGreater(
            sleeps[1],
            sleeps[0],
            "退避 delay 必须随 retry_count 单调递增——这是指数退避的核心契约；"
            f"实际: 第 1 次 {sleeps[0]:.3f}s vs 第 2 次 {sleeps[1]:.3f}s",
        )

    def test_keyboard_interrupt_does_not_sleep_or_exit(self) -> None:
        """``KeyboardInterrupt`` 必须立即跳出循环，不重试、不 sleep、不 sys.exit。"""
        sleeps, exit_code = self._drive_main_with_mocked_run(
            run_exception=KeyboardInterrupt()
        )
        self.assertEqual(
            len(sleeps),
            0,
            f"KeyboardInterrupt 不应触发任何 sleep；实际: {sleeps}",
        )
        self.assertIsNone(exit_code, "KeyboardInterrupt 应优雅 break 而非 sys.exit")


if __name__ == "__main__":
    unittest.main()
