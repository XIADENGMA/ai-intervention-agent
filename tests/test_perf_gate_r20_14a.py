"""R20.14-A perf gate 单元 + 不变量测试。

覆盖目标
========

锁定 ``scripts/perf_gate.py`` 在以下边界条件下的判定行为，避免后续重构
意外松绑回归阈值或破坏 update-baseline 写盘逻辑：

1. **基线 / results 解析**：扁平 vs 嵌套 (``benchmarks: {…}``) 两种 JSON
   layout 都能被解析。
2. **阈值模型**：百分比阈值 + 绝对噪声地板的「取较宽」语义；逐 benchmark
   覆写优先级（CLI > baseline JSON > 全局 default）。
3. **verdict 维度**：``pass`` / ``regression`` / ``new`` / ``dropped`` /
   ``error`` 五种状态都能正确产出。
4. **退出码契约**：``run()`` 的 0 = PASS / 1 = FAIL 不能反转。
5. **--update-baseline 行为**：写盘后 ``thresholds`` 字段保留，``benchmarks``
   被新数据覆盖；目录不存在时自动创建。
6. **源码不变量**：脚本里的关键函数名 / argparse 选项 / 默认阈值常量
   不能被无意识改名，保护下游 CI 引用稳定。

不测什么
--------

不真跑 ``perf_e2e_bench.py`` 的 5 道 benchmark —— 那是 ``perf_e2e_bench``
自己的 smoke-test 范畴，gate 只看 JSON。
"""

from __future__ import annotations

import io
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import scripts.perf_gate as perf_gate

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_bench(median: float, *, p90: float | None = None) -> dict[str, Any]:
    """造一个 benchmark 的最小字典（median 必填，其它字段对 gate 是无关项）。"""
    return {
        "median_ms": median,
        "p90_ms": p90 if p90 is not None else median * 1.1,
        "min_ms": median * 0.9,
        "max_ms": median * 1.2,
        "iterations": 5,
        "samples_ms": [median] * 5,
    }


class TestExtractBenchmarks(unittest.TestCase):
    """``_extract_benchmarks`` 必须容忍 perf_e2e_bench 的扁平输出 + 嵌套基线。"""

    def test_flat_layout_passes_through(self) -> None:
        # perf_e2e_bench.py --output 写出来就是这种扁平结构
        payload = {
            "import_web_ui": _make_bench(150.0),
            "html_render": _make_bench(0.07),
        }
        out = perf_gate._extract_benchmarks(payload)
        self.assertEqual(set(out.keys()), {"import_web_ui", "html_render"})
        self.assertEqual(out["import_web_ui"]["median_ms"], 150.0)

    def test_nested_layout_unwraps_benchmarks_key(self) -> None:
        # update-baseline 写出来 / 手工 baseline 是嵌套结构
        payload = {
            "benchmarks": {"import_web_ui": _make_bench(150.0)},
            "thresholds": {"import_web_ui": 0.20},  # 不应该泄漏到 benchmarks
        }
        out = perf_gate._extract_benchmarks(payload)
        self.assertEqual(set(out.keys()), {"import_web_ui"})
        self.assertNotIn("thresholds", out)

    def test_skips_entries_without_median(self) -> None:
        # 防御坏数据：metadata / 杂项字段不应该被当成 benchmark
        payload = {
            "import_web_ui": _make_bench(150.0),
            "metadata": {"git": "abc123"},  # 没 median_ms
            "some_string": "not-a-dict",  # 不是 dict
        }
        out = perf_gate._extract_benchmarks(payload)
        self.assertEqual(set(out.keys()), {"import_web_ui"})


class TestPerBenchThresholdParsing(unittest.TestCase):
    """逐 benchmark 阈值覆写：JSON 顶层 + CLI 两条路。"""

    def test_extract_thresholds_from_baseline(self) -> None:
        payload = {
            "benchmarks": {"x": _make_bench(10.0)},
            "thresholds": {"import_web_ui": 0.20, "html_render": "0.50"},
        }
        out = perf_gate._extract_per_bench_thresholds(payload)
        self.assertEqual(out, {"import_web_ui": 0.20, "html_render": 0.50})

    def test_extract_thresholds_ignores_non_numeric(self) -> None:
        # 防御坏数据：非数字阈值应该被静默丢掉，而不是 raise
        payload = {"thresholds": {"a": 0.30, "b": "not-a-number", "c": None}}
        out = perf_gate._extract_per_bench_thresholds(payload)
        self.assertEqual(out, {"a": 0.30})

    def test_extract_thresholds_missing_field(self) -> None:
        self.assertEqual(perf_gate._extract_per_bench_thresholds({}), {})

    def test_parse_cli_basic(self) -> None:
        out = perf_gate._parse_per_bench_cli(["import_web_ui=0.20", "html_render=0.50"])
        self.assertEqual(out, {"import_web_ui": 0.20, "html_render": 0.50})

    def test_parse_cli_handles_whitespace(self) -> None:
        out = perf_gate._parse_per_bench_cli(["  import_web_ui = 0.20"])
        self.assertEqual(out, {"import_web_ui": 0.20})

    def test_parse_cli_rejects_missing_equals(self) -> None:
        with self.assertRaises(ValueError):
            perf_gate._parse_per_bench_cli(["import_web_ui:0.20"])

    def test_parse_cli_rejects_non_numeric(self) -> None:
        with self.assertRaises(ValueError):
            perf_gate._parse_per_bench_cli(["import_web_ui=fast"])

    def test_parse_cli_none_input(self) -> None:
        self.assertEqual(perf_gate._parse_per_bench_cli(None), {})


class TestEvaluatePassPaths(unittest.TestCase):
    """``evaluate`` 的 PASS 判定 —— 只要在容忍区内就 ok。"""

    def test_exact_match_passes(self) -> None:
        cur = {"a": _make_bench(100.0)}
        base = {"a": _make_bench(100.0)}
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertTrue(v["ok"])
        self.assertEqual(v["results"][0]["verdict"], "pass")
        self.assertEqual(v["results"][0]["delta_ms"], 0.0)

    def test_improvement_passes(self) -> None:
        # current 比 baseline 更快（负 delta）必须 PASS
        cur = {"a": _make_bench(50.0)}
        base = {"a": _make_bench(100.0)}
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertTrue(v["ok"])
        self.assertEqual(v["results"][0]["verdict"], "pass")
        self.assertLess(v["results"][0]["delta_ms"], 0)

    def test_within_pct_threshold_passes(self) -> None:
        # 100ms baseline + 30% pct + 5ms abs → 容忍 30ms（max 30 vs 5）
        # 130ms 是边界值（恰好 ≤ 30ms 增长），按定义 PASS
        cur = {"a": _make_bench(130.0)}
        base = {"a": _make_bench(100.0)}
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertTrue(v["ok"])

    def test_within_abs_floor_passes_for_subms_bench(self) -> None:
        # 0.07ms baseline + 30% pct + 5ms abs floor → 容忍 5.0ms（abs 主导）
        # 4.5ms 增长虽然百分比是 6400%，但绝对值 < 5ms 地板，应 PASS
        cur = {"html_render": _make_bench(4.5)}
        base = {"html_render": _make_bench(0.07)}
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertTrue(v["ok"])
        self.assertEqual(v["results"][0]["verdict"], "pass")
        self.assertEqual(v["results"][0]["tolerance_ms"], 5.0)


class TestEvaluateRegressionPaths(unittest.TestCase):
    """``evaluate`` 的 FAIL 判定 —— 大于容忍区即 regression。"""

    def test_exceeds_pct_threshold_fails(self) -> None:
        # 100ms baseline，current 200ms，超过 100 + max(30, 5) = 130
        cur = {"a": _make_bench(200.0)}
        base = {"a": _make_bench(100.0)}
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertFalse(v["ok"])
        self.assertEqual(v["results"][0]["verdict"], "regression")
        self.assertGreater(v["results"][0]["delta_ms"], 0)
        self.assertEqual(len(v["regressions"]), 1)

    def test_exceeds_abs_floor_for_subms_bench_fails(self) -> None:
        # html_render 从 0.07ms 涨到 6.0ms（abs 5ms 地板被穿）
        cur = {"html_render": _make_bench(6.0)}
        base = {"html_render": _make_bench(0.07)}
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertFalse(v["ok"])
        self.assertEqual(v["results"][0]["verdict"], "regression")

    def test_per_bench_threshold_override_tightens(self) -> None:
        # 全局 30%，但 import_web_ui 单独收紧到 10%
        # 100 → 120ms（+20%）：全局规则 PASS，但 per-bench 10% 应该 FAIL
        cur = {"import_web_ui": _make_bench(120.0)}
        base = {"import_web_ui": _make_bench(100.0)}
        v_loose = perf_gate.evaluate(current=cur, baseline=base)
        self.assertTrue(v_loose["ok"])  # 全局 30% 容忍
        v_strict = perf_gate.evaluate(
            current=cur,
            baseline=base,
            per_bench_threshold={"import_web_ui": 0.10},
        )
        # 100 + max(10, 5) = 110，但 abs_floor 5 让容忍度 = max(10, 5) = 10
        # 当前 120 > 110，应该 FAIL
        self.assertFalse(v_strict["ok"])

    def test_multiple_regressions_aggregated(self) -> None:
        cur = {
            "a": _make_bench(200.0),  # regression
            "b": _make_bench(100.0),  # pass
            "c": _make_bench(500.0),  # regression
        }
        base = {
            "a": _make_bench(100.0),
            "b": _make_bench(100.0),
            "c": _make_bench(100.0),
        }
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertFalse(v["ok"])
        self.assertEqual(len(v["regressions"]), 2)
        self.assertEqual({r["name"] for r in v["regressions"]}, {"a", "c"})


class TestEvaluateEdgeVerdicts(unittest.TestCase):
    """new / dropped / error 三种特殊 verdict。"""

    def test_new_benchmark_does_not_fail(self) -> None:
        cur = {"new_bench": _make_bench(50.0)}
        base: dict[str, Any] = {}
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertTrue(v["ok"], "new benchmark 不应触发 FAIL，只是提示")
        self.assertEqual(v["results"][0]["verdict"], "new")

    def test_dropped_benchmark_fails(self) -> None:
        # 基线里有但 current 没了 —— 测量覆盖意外掉了，比真退化更值得告警
        cur: dict[str, Any] = {}
        base = {"old_bench": _make_bench(50.0)}
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertFalse(v["ok"])
        self.assertEqual(v["results"][0]["verdict"], "dropped")
        self.assertEqual(len(v["regressions"]), 1)

    def test_non_numeric_median_yields_error_verdict(self) -> None:
        # bench 跑挂了 / median_ms 字段缺失 / 是 None
        cur = {"a": {"median_ms": None, "iterations": 0}}
        base = {"a": _make_bench(100.0)}
        v = perf_gate.evaluate(current=cur, baseline=base)
        # error 既不算 pass 也不算 regression（不挂 CI，但写在 results 里）
        self.assertEqual(v["results"][0]["verdict"], "error")
        # error 不计入 regressions —— 这是设计意图：bench 自身坏掉应该让
        # bench 那一步先挂，gate 不重复告警
        self.assertEqual(len(v["regressions"]), 0)
        self.assertTrue(v["ok"])

    def test_bool_is_not_treated_as_number(self) -> None:
        # Python 里 True/False 是 int 子类，``isinstance(True, (int, float))``
        # 是 True —— 必须显式排除，否则 ``True - 100.0 = -99`` 会被当成
        # 「巨幅性能改善」，误判 PASS
        cur = {"a": {"median_ms": True, "iterations": 1}}
        base = {"a": _make_bench(100.0)}
        v = perf_gate.evaluate(current=cur, baseline=base)
        self.assertEqual(v["results"][0]["verdict"], "error")


class TestRunEntryPoint(unittest.TestCase):
    """``run()`` —— 端到端 IO + 退出码契约。"""

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_run_pass_returns_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            results = tmp_dir / "current.json"
            baseline = tmp_dir / "baseline.json"
            self._write(results, {"a": _make_bench(100.0)})
            self._write(baseline, {"benchmarks": {"a": _make_bench(100.0)}})
            stdout = io.StringIO()
            stderr = io.StringIO()
            rc = perf_gate.run(
                results_path=results,
                baseline_path=baseline,
                pct_threshold=0.30,
                abs_floor_ms=5.0,
                per_bench_threshold={},
                update_baseline=False,
                output_format="text",
                verbose=False,
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(rc, 0)
            # PASS 时不应往 stderr 喷东西（但允许往 stdout 写概要）
            self.assertEqual(stderr.getvalue(), "")

    def test_run_fail_returns_one_and_writes_stderr(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            results = tmp_dir / "current.json"
            baseline = tmp_dir / "baseline.json"
            self._write(results, {"a": _make_bench(500.0)})
            self._write(baseline, {"benchmarks": {"a": _make_bench(100.0)}})
            stdout = io.StringIO()
            stderr = io.StringIO()
            rc = perf_gate.run(
                results_path=results,
                baseline_path=baseline,
                pct_threshold=0.30,
                abs_floor_ms=5.0,
                per_bench_threshold={},
                update_baseline=False,
                output_format="text",
                verbose=False,
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(rc, 1)
            # FAIL 必须把详情打到 stderr —— CI 抓 stderr 报 review
            self.assertIn("FAIL", stderr.getvalue())
            self.assertIn("a", stderr.getvalue())

    def test_run_json_format_emits_structured_verdict(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            results = tmp_dir / "current.json"
            baseline = tmp_dir / "baseline.json"
            self._write(results, {"a": _make_bench(100.0)})
            self._write(baseline, {"benchmarks": {"a": _make_bench(100.0)}})
            stdout = io.StringIO()
            stderr = io.StringIO()
            rc = perf_gate.run(
                results_path=results,
                baseline_path=baseline,
                pct_threshold=0.30,
                abs_floor_ms=5.0,
                per_bench_threshold={},
                update_baseline=False,
                output_format="json",
                verbose=False,
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertIn("ok", payload)
            self.assertIn("results", payload)
            self.assertIn("regressions", payload)
            self.assertTrue(payload["ok"])

    def test_run_missing_results_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            baseline = tmp_dir / "baseline.json"
            self._write(baseline, {"benchmarks": {}})
            with self.assertRaises(FileNotFoundError):
                perf_gate.run(
                    results_path=tmp_dir / "missing.json",
                    baseline_path=baseline,
                    pct_threshold=0.30,
                    abs_floor_ms=5.0,
                    per_bench_threshold={},
                    update_baseline=False,
                    output_format="text",
                    verbose=False,
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )


class TestUpdateBaseline(unittest.TestCase):
    """``--update-baseline`` 模式。"""

    def test_update_writes_current_into_baseline(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            results = tmp_dir / "current.json"
            baseline = tmp_dir / "deep" / "baseline.json"  # 故意嵌套，验证自动创建目录
            with results.open("w", encoding="utf-8") as fh:
                json.dump({"a": _make_bench(123.45)}, fh)

            stdout = io.StringIO()
            rc = perf_gate.run(
                results_path=results,
                baseline_path=baseline,
                pct_threshold=0.30,
                abs_floor_ms=5.0,
                per_bench_threshold={},
                update_baseline=True,
                output_format="text",
                verbose=False,
                stdout=stdout,
                stderr=io.StringIO(),
            )
            self.assertEqual(rc, 0)
            self.assertTrue(baseline.exists())
            written = json.loads(baseline.read_text(encoding="utf-8"))
            self.assertIn("benchmarks", written)
            self.assertEqual(written["benchmarks"]["a"]["median_ms"], 123.45)

    def test_update_preserves_existing_thresholds(self) -> None:
        # 已有 baseline 里手工配的 thresholds 字段不应被 results 自动覆写
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            results = tmp_dir / "current.json"
            baseline = tmp_dir / "baseline.json"
            with results.open("w", encoding="utf-8") as fh:
                json.dump({"a": _make_bench(150.0)}, fh)
            with baseline.open("w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "benchmarks": {"a": _make_bench(100.0)},
                        "thresholds": {"a": 0.10},  # 手工收紧到 10%
                    },
                    fh,
                )
            rc = perf_gate.run(
                results_path=results,
                baseline_path=baseline,
                pct_threshold=0.30,
                abs_floor_ms=5.0,
                per_bench_threshold={},
                update_baseline=True,
                output_format="text",
                verbose=False,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
            self.assertEqual(rc, 0)
            written = json.loads(baseline.read_text(encoding="utf-8"))
            self.assertEqual(written["benchmarks"]["a"]["median_ms"], 150.0)
            # 阈值字段必须保留 —— 手工策略不应被自动 update 抹掉
            self.assertEqual(written.get("thresholds"), {"a": 0.10})

    def test_update_json_output(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            results = tmp_dir / "current.json"
            baseline = tmp_dir / "baseline.json"
            with results.open("w", encoding="utf-8") as fh:
                json.dump({"a": _make_bench(100.0)}, fh)
            stdout = io.StringIO()
            rc = perf_gate.run(
                results_path=results,
                baseline_path=baseline,
                pct_threshold=0.30,
                abs_floor_ms=5.0,
                per_bench_threshold={},
                update_baseline=True,
                output_format="json",
                verbose=False,
                stdout=stdout,
                stderr=io.StringIO(),
            )
            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertTrue(payload.get("updated"))
            self.assertIn("a", payload.get("benchmarks", []))


class TestSourceInvariants(unittest.TestCase):
    """源码层不变量 —— 关键 API / 默认值不能被无意识改名。"""

    SCRIPT_PATH = REPO_ROOT / "scripts" / "perf_gate.py"

    def setUp(self) -> None:
        self.src = self.SCRIPT_PATH.read_text(encoding="utf-8")

    def test_default_pct_threshold_is_30_percent(self) -> None:
        self.assertEqual(perf_gate.DEFAULT_PCT_THRESHOLD, 0.30)

    def test_default_abs_floor_ms_is_5(self) -> None:
        self.assertEqual(perf_gate.DEFAULT_ABS_FLOOR_MS, 5.0)

    def test_default_baseline_path(self) -> None:
        self.assertEqual(
            perf_gate.DEFAULT_BASELINE,
            REPO_ROOT / "tests" / "data" / "perf_e2e_baseline.json",
        )

    def test_evaluate_function_signature(self) -> None:
        # 锁住 evaluate() 的关键 keyword 参数，因为外部脚本可能直接调它
        import inspect

        sig = inspect.signature(perf_gate.evaluate)
        self.assertIn("current", sig.parameters)
        self.assertIn("baseline", sig.parameters)
        self.assertIn("pct_threshold", sig.parameters)
        self.assertIn("abs_floor_ms", sig.parameters)
        self.assertIn("per_bench_threshold", sig.parameters)

    def test_run_function_signature(self) -> None:
        # ``run()`` 是 CLI + tests 共享的入口，签名锁死避免重构破坏 CI 调用
        import inspect

        sig = inspect.signature(perf_gate.run)
        for required in (
            "results_path",
            "baseline_path",
            "pct_threshold",
            "abs_floor_ms",
            "per_bench_threshold",
            "update_baseline",
            "output_format",
            "verbose",
        ):
            self.assertIn(required, sig.parameters)

    def test_cli_has_required_options(self) -> None:
        # argparse 选项不能被无意识改名 —— CI 脚本可能直接 invoke
        for option in (
            "--results",
            "--baseline",
            "--threshold",
            "--abs-floor-ms",
            "--per-benchmark-threshold",
            "--update-baseline",
            "--format",
            "--verbose",
        ):
            self.assertIn(option, self.src, f"CLI option {option!r} 不应被删")

    def test_verdict_strings_are_documented(self) -> None:
        # verdict 字符串是 JSON contract 的一部分，下游可能 grep
        for verdict in ("pass", "regression", "new", "dropped", "error"):
            # 必须在源码 docstring 或者 evaluate 实现里出现
            pattern = re.compile(rf"\b{re.escape(verdict)}\b")
            self.assertIsNotNone(
                pattern.search(self.src),
                f"verdict {verdict!r} 在源码里找不到，contract 被破坏",
            )


class TestMainCli(unittest.TestCase):
    """``_main`` argparse 入口，最薄一层 smoke。"""

    def test_main_pass_returns_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            results = tmp_dir / "current.json"
            baseline = tmp_dir / "baseline.json"
            with results.open("w", encoding="utf-8") as fh:
                json.dump({"a": _make_bench(100.0)}, fh)
            with baseline.open("w", encoding="utf-8") as fh:
                json.dump({"benchmarks": {"a": _make_bench(100.0)}}, fh)
            rc = perf_gate._main(
                ["--results", str(results), "--baseline", str(baseline)]
            )
            self.assertEqual(rc, 0)

    def test_main_fail_returns_one(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            results = tmp_dir / "current.json"
            baseline = tmp_dir / "baseline.json"
            with results.open("w", encoding="utf-8") as fh:
                json.dump({"a": _make_bench(500.0)}, fh)
            with baseline.open("w", encoding="utf-8") as fh:
                json.dump({"benchmarks": {"a": _make_bench(100.0)}}, fh)
            rc = perf_gate._main(
                ["--results", str(results), "--baseline", str(baseline)]
            )
            self.assertEqual(rc, 1)

    def test_main_per_benchmark_threshold_override(self) -> None:
        # CLI 收紧某条 benchmark 阈值，让原本 PASS 变 FAIL
        with TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            results = tmp_dir / "current.json"
            baseline = tmp_dir / "baseline.json"
            with results.open("w", encoding="utf-8") as fh:
                json.dump({"a": _make_bench(120.0)}, fh)  # +20%
            with baseline.open("w", encoding="utf-8") as fh:
                json.dump({"benchmarks": {"a": _make_bench(100.0)}}, fh)
            rc_default = perf_gate._main(
                ["--results", str(results), "--baseline", str(baseline)]
            )
            self.assertEqual(rc_default, 0)
            rc_strict = perf_gate._main(
                [
                    "--results",
                    str(results),
                    "--baseline",
                    str(baseline),
                    "--per-benchmark-threshold",
                    "a=0.10",
                    "--abs-floor-ms",
                    "0.0",  # 关掉 abs 地板，让 pct 主导
                ]
            )
            self.assertEqual(rc_strict, 1)


class TestRealBaselineSelfCompare(unittest.TestCase):
    """在 repo 真正落地的 ``tests/data/perf_e2e_baseline.json`` 自比通过。

    这条等价于「baseline 文件自身格式合法 + 能被 gate 解析」的烟测；
    若有人手抖把 baseline 删了或改坏了 schema，CI 会立刻炸。
    """

    def test_baseline_file_exists_and_is_valid(self) -> None:
        path = REPO_ROOT / "tests" / "data" / "perf_e2e_baseline.json"
        self.assertTrue(path.exists(), f"baseline 文件 {path} 缺失")
        payload = json.loads(path.read_text(encoding="utf-8"))
        benchmarks = perf_gate._extract_benchmarks(payload)
        # R20.14-A 设计目标：5 道 benchmark 都要在 baseline 里
        self.assertEqual(
            set(benchmarks.keys()),
            {
                "import_web_ui",
                "spawn_to_listen",
                "html_render",
                "api_health_round_trip",
                "api_config_round_trip",
            },
            "baseline 必须覆盖全部 5 道 R20.14-A benchmark",
        )

    def test_baseline_self_compare_passes(self) -> None:
        # 把 baseline 当 results + 当 baseline 自比，必须 PASS
        path = REPO_ROOT / "tests" / "data" / "perf_e2e_baseline.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        benchmarks = perf_gate._extract_benchmarks(payload)
        v = perf_gate.evaluate(current=benchmarks, baseline=benchmarks)
        self.assertTrue(
            v["ok"], f"baseline 自比应 PASS，实际 regressions={v['regressions']}"
        )

    def test_baseline_medians_within_reasonable_bounds(self) -> None:
        # 「合理上限」断言：哨兵阻止某天 update-baseline 把一个明显坏掉的
        # 数字写进基线（比如 import_web_ui 因为冷启动机器太慢测出 5000 ms）
        path = REPO_ROOT / "tests" / "data" / "perf_e2e_baseline.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        benchmarks = perf_gate._extract_benchmarks(payload)
        upper_bounds = {
            "import_web_ui": 1500.0,  # R20.4 之前就 425 ms，给 3.5× 余量
            "spawn_to_listen": 5000.0,  # R20.11 之前 1922 ms，给 2.6× 余量
            "html_render": 100.0,  # 模板渲染没理由超过 100 ms
            "api_health_round_trip": 200.0,  # localhost ping 不该超过 200 ms
            "api_config_round_trip": 200.0,
        }
        for name, upper in upper_bounds.items():
            with self.subTest(benchmark=name):
                median = benchmarks[name]["median_ms"]
                self.assertLess(
                    median,
                    upper,
                    f"baseline {name} median {median}ms 超过哨兵上限 {upper}ms — "
                    "可能被一次坏运行污染了，不应固化进基线",
                )


if __name__ == "__main__":
    unittest.main()
