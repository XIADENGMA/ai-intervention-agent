"""R20.14-A perf bench harness 单元测试。

只测 ``perf_e2e_bench.py`` 里的 pure-function 工具 + 模块级常量，**不真跑**
5 道 benchmark —— 那是 ``perf_e2e_bench.py`` 自己 ``--quick`` 模式的事，跑
一次 5 秒以上，不适合放进单元测试套件。

覆盖内容
========

1. ``_percentile`` 在 0 / 1 / 多元素 / 边界（p=0 / p=1）下的正确性；
2. ``_summarize`` 的字段 contract（``median_ms`` / ``p90_ms`` / 等）；
3. ``_free_port`` 真的返回一个 listen-able 端口；
4. ``BENCHMARKS`` 字典严格包含 R20.14-A 设计的 5 道；
5. ``DEFAULT_ITERATIONS`` / ``QUICK_ITERATIONS`` 字典 key 与 ``BENCHMARKS``
   完全对齐（任意一边 typo 都会让 ``--select`` 模式悄悄失效）；
6. CLI argparse 接受 ``--quick`` / ``--select`` / ``--output`` / ``--format``。
"""

from __future__ import annotations

import socket
import unittest
from pathlib import Path

import scripts.perf_e2e_bench as perf_bench

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPercentile(unittest.TestCase):
    """``_percentile`` —— 简易 p90/p95 计算（不依赖 numpy）。"""

    def test_empty_returns_nan(self) -> None:
        # 空样本返回 nan，不是 raise；调用方决定怎么 surface
        result = perf_bench._percentile([], 0.9)
        self.assertNotEqual(result, result)  # nan != nan 是 nan 的唯一合法判定

    def test_single_sample(self) -> None:
        # 单元素时任何 p 都返回那个值
        self.assertEqual(perf_bench._percentile([42.0], 0.9), 42.0)
        self.assertEqual(perf_bench._percentile([42.0], 0.0), 42.0)
        self.assertEqual(perf_bench._percentile([42.0], 1.0), 42.0)

    def test_p0_is_min_p1_is_max(self) -> None:
        samples = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(perf_bench._percentile(samples, 0.0), 1.0)
        self.assertEqual(perf_bench._percentile(samples, 1.0), 5.0)

    def test_p50_matches_median(self) -> None:
        # 奇数样本 p50 必须 = 中位数
        samples = [10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertEqual(perf_bench._percentile(samples, 0.5), 30.0)

    def test_p90_interpolates(self) -> None:
        # 10 个 [1..10]：p90 严格定义在第 9.0 位 = 10.0（线性插值）
        # 显式构造 list[float]，避免 ``list[int]`` 触发 ty 的不变式契约校验
        samples: list[float] = [float(i) for i in range(1, 11)]
        self.assertAlmostEqual(perf_bench._percentile(samples, 0.9), 9.1, places=5)

    def test_handles_unsorted_input(self) -> None:
        # _percentile 必须先排序，不能假设输入有序
        sorted_p = perf_bench._percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.9)
        unsorted_p = perf_bench._percentile([5.0, 1.0, 4.0, 2.0, 3.0], 0.9)
        self.assertEqual(sorted_p, unsorted_p)


class TestSummarize(unittest.TestCase):
    """``_summarize`` —— 把毫秒采样压成统计字典，contract 不能漂。"""

    def test_empty_samples_returns_zeros_and_none(self) -> None:
        out = perf_bench._summarize([])
        self.assertEqual(out["iterations"], 0)
        self.assertIsNone(out["median_ms"])
        self.assertIsNone(out["p90_ms"])
        self.assertIsNone(out["min_ms"])
        self.assertIsNone(out["max_ms"])
        self.assertEqual(out["samples_ms"], [])

    def test_required_keys_present(self) -> None:
        out = perf_bench._summarize([1.0, 2.0, 3.0])
        for key in (
            "median_ms",
            "p90_ms",
            "min_ms",
            "max_ms",
            "iterations",
            "samples_ms",
        ):
            self.assertIn(key, out, f"summarize 必须返回 {key}")

    def test_min_max_correct(self) -> None:
        out = perf_bench._summarize([3.0, 1.0, 5.0, 2.0, 4.0])
        self.assertEqual(out["min_ms"], 1.0)
        self.assertEqual(out["max_ms"], 5.0)
        self.assertEqual(out["iterations"], 5)

    def test_median_correct(self) -> None:
        out = perf_bench._summarize([10.0, 20.0, 30.0])
        self.assertEqual(out["median_ms"], 20.0)

    def test_samples_rounded_to_2_decimals(self) -> None:
        # 输出 JSON 体积控制：原始采样四舍五入到 2 位小数
        out = perf_bench._summarize([1.234567, 2.345678])
        self.assertEqual(out["samples_ms"], [1.23, 2.35])


class TestFreePort(unittest.TestCase):
    """``_free_port`` —— 必须返回一个真正能 bind 的端口。"""

    def test_returns_int(self) -> None:
        port = perf_bench._free_port()
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        self.assertLess(port, 65536)

    def test_port_can_be_listened(self) -> None:
        # _free_port 返回后，该端口必须立即可重新 bind（OS 已释放）
        port = perf_bench._free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                s.listen(1)
            except OSError as exc:
                self.fail(f"_free_port 返回的端口 {port} 立即 bind 失败: {exc}")


class TestBenchmarkRegistry(unittest.TestCase):
    """5 道 benchmark 的 registry —— 名字 / iterations 字典必须对齐。"""

    EXPECTED_BENCH_NAMES = {
        "import_web_ui",
        "spawn_to_listen",
        "html_render",
        "api_health_round_trip",
        "api_config_round_trip",
    }

    def test_benchmarks_dict_complete(self) -> None:
        self.assertEqual(set(perf_bench.BENCHMARKS.keys()), self.EXPECTED_BENCH_NAMES)

    def test_benchmark_callables(self) -> None:
        # 每条 benchmark 必须是 callable，否则 run_all 会 raise
        for name, fn in perf_bench.BENCHMARKS.items():
            self.assertTrue(callable(fn), f"{name} 不是 callable")

    def test_default_iterations_aligned(self) -> None:
        # DEFAULT_ITERATIONS keys 必须严格 = BENCHMARKS keys
        self.assertEqual(
            set(perf_bench.DEFAULT_ITERATIONS.keys()),
            self.EXPECTED_BENCH_NAMES,
            "DEFAULT_ITERATIONS 漏了某条 benchmark，--select 会用默认 0 跑",
        )

    def test_quick_iterations_aligned(self) -> None:
        self.assertEqual(
            set(perf_bench.QUICK_ITERATIONS.keys()),
            self.EXPECTED_BENCH_NAMES,
            "QUICK_ITERATIONS 漏了某条 benchmark",
        )

    def test_quick_iterations_smaller_than_default(self) -> None:
        # --quick 必须真的「快」一点 —— 各 benchmark iterations 不大于 default
        for name in self.EXPECTED_BENCH_NAMES:
            with self.subTest(benchmark=name):
                self.assertLessEqual(
                    perf_bench.QUICK_ITERATIONS[name],
                    perf_bench.DEFAULT_ITERATIONS[name],
                    f"{name}: QUICK iters > DEFAULT iters，违反语义",
                )


class TestSourceInvariants(unittest.TestCase):
    """源码不变量 —— 锁住关键 CLI 选项 / 公共常量名字。"""

    SCRIPT_PATH = REPO_ROOT / "scripts" / "perf_e2e_bench.py"

    def setUp(self) -> None:
        self.src = self.SCRIPT_PATH.read_text(encoding="utf-8")

    def test_cli_has_required_options(self) -> None:
        # argparse 选项不能改名 —— CI / 文档 / perf_gate 都依赖它们
        for opt in ("--quick", "--select", "--output", "--format", "--quiet"):
            self.assertIn(opt, self.src, f"CLI 选项 {opt!r} 不应被删")

    def test_repo_root_exposed(self) -> None:
        # REPO_ROOT 必须指向项目根（包含 web_ui.py）
        self.assertTrue(
            (perf_bench.REPO_ROOT / "web_ui.py").exists(),
            f"REPO_ROOT={perf_bench.REPO_ROOT} 似乎不是项目根目录",
        )

    def test_run_all_signature(self) -> None:
        import inspect

        sig = inspect.signature(perf_bench.run_all)
        # 三个关键 kwarg 不能换名
        for required in ("quick", "select", "quiet"):
            self.assertIn(required, sig.parameters)


class TestSubprocessIsolationPattern(unittest.TestCase):
    """``import_web_ui`` / ``spawn_to_listen`` 必须真在 subprocess 里跑。

    这是测量正确性的根：如果 import 在主进程做（被 lru_cache / module
    sys.modules 缓存住），第二次起就会接近 0 ms，掩盖真实冷启动开销。
    """

    SCRIPT_PATH = REPO_ROOT / "scripts" / "perf_e2e_bench.py"

    def test_import_web_ui_uses_subprocess_run(self) -> None:
        src = self.SCRIPT_PATH.read_text(encoding="utf-8")
        # 在 bench_import_web_ui 函数体里必须 spawn 一个新 Python 解释器
        match_idx = src.find("def bench_import_web_ui")
        self.assertGreaterEqual(match_idx, 0, "bench_import_web_ui 函数找不到")
        # 取函数体一段（往后 1500 char 足够覆盖整个 body）
        body = src[match_idx : match_idx + 1500]
        self.assertIn(
            "subprocess.run",
            body,
            "bench_import_web_ui 必须用 subprocess.run 隔离，否则 lru_cache 会污染",
        )
        self.assertIn(
            "sys.executable",
            body,
            "subprocess 必须用 sys.executable 而不是 'python'，避免 PATH 漂",
        )

    def test_spawn_to_listen_uses_subprocess_popen(self) -> None:
        src = self.SCRIPT_PATH.read_text(encoding="utf-8")
        match_idx = src.find("def bench_spawn_to_listen")
        self.assertGreaterEqual(match_idx, 0)
        body = src[match_idx : match_idx + 2500]
        self.assertIn("subprocess.Popen", body)


if __name__ == "__main__":
    unittest.main()
