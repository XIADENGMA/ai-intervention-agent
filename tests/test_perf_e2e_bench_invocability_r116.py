"""R116：``scripts/perf_e2e_bench.py`` 5 个 benchmark 的 invocability
回归测试。

背景与缺陷复现路径
==================
R76 (`11abdad refactor(layout-r76): adopt PyPA src/ layout`) 把
``web_ui.py`` 从 ``REPO_ROOT`` 迁到 ``src/ai_intervention_agent/web_ui.py``。
``scripts/perf_e2e_bench.py`` 里有 4 个 benchmark 用了**迁移前路径**：

1. ``bench_import_web_ui`` 跑 ``python -c "import web_ui"`` →
   ``ModuleNotFoundError: No module named 'web_ui'``。
2. ``bench_spawn_to_listen`` 跑 ``[python, "web_ui.py", ...]`` 从 ``REPO_ROOT`` →
   subprocess 立即 ``rc=2`` ``can't open file 'web_ui.py'``。
3-4. ``_start_web_ui_subprocess``（被 ``bench_api_round_trip`` 用于 health/config）
     ——同样的 ``web_ui.py`` argv 写法 → 同样的 ``rc=2``。

R116 修复改 import / argv 改成 ``ai_intervention_agent.web_ui`` /
``-m ai_intervention_agent.web_ui``。本测试守护这 4 条入口的真实可调用性，
**不**测性能数字（性能数字属 ``perf_gate.py`` + ``perf_e2e_baseline.json``
管），只断言"benchmark 函数能跑通、写入合法的 ``samples_ms``"。

为什么需要这层守护
==================
``scripts/perf_e2e_bench.py::run_all`` 里把每个 benchmark 函数包了
``try/except Exception`` —— 任何 RuntimeError 都被吞成
``{"error": str, "iterations": 0, "samples_ms": []}``。``perf_gate.py``
看到这种空 results 直接 skip 那条 bench、其余 PASS 时整体仍然 PASS
（不会让 CI red）。所以单纯依赖"perf_gate 在 CI 跑"还不够——
**必须**有一层独立的 invocability 守护，否则 R76 那种"路径漂移让
benchmark 全静默 fail"的回归会再次发生且无人察觉。

设计权衡
========
- 不用真值假设：``html_render`` 中位数 < 1 ms 是事实，但本测试只验
  ``samples_ms`` 非空且 ``>= 0``，绝对数字交给 ``perf_gate``。
- 用最少 iter（``--quick`` 路径）让本测试在 CI 跑时间维持 < 30 s。
- 不 import perf_e2e_bench 模块本身（避免在 import 期触发 subprocess
  spawn）；改成 fork 一个 subprocess 调用 ``--quick``，与生产路径一致。
- 每条 benchmark 都用源码包含字符串校验"R116 修复字符串"是否存在，
  形成"代码事实"层的反退化护栏（``import ai_intervention_agent.web_ui``
  / ``-m ai_intervention_agent.web_ui``），即便未来又有人误改成
  ``import web_ui``，本测试也能立即 fail。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PERF_BENCH_PATH = REPO_ROOT / "scripts" / "perf_e2e_bench.py"
EXPECTED_BENCHMARKS = (
    "import_web_ui",
    "web_ui_construct",
    "web_ui_route_setup",
    "socket_listen_after_construct",
    "spawn_to_listen",
    "html_render",
    "api_health_round_trip",
    "api_config_round_trip",
)
BASELINE_BENCHMARKS = (
    "import_web_ui",
    "spawn_to_listen",
    "html_render",
    "api_health_round_trip",
    "api_config_round_trip",
)


def _collect_subprocess_argv_string_literals(source: str) -> list[str]:
    """提取 ``subprocess.{run,Popen}(...)`` 第一个位置参数（list literal）
    里的所有字符串字面量。

    这样可以**精确**判断 R76-broken 的 ``"web_ui.py"`` argv 是不是真的
    出现在某次 subprocess 调用里，而不会误命中 docstring / comment 里的
    历史性引用文字。
    """
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # 必须形如 ``subprocess.X(...)``
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
            and func.attr in {"run", "Popen", "call", "check_call", "check_output"}
        ):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.List):
            continue
        for elt in first.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                found.append(elt.value)
    return found


def _collect_subprocess_run_dash_c_payloads(source: str) -> list[str]:
    """提取 ``subprocess.run([..., "-c", "..."], ...)`` 的 ``-c`` 后字符串。

    专门给 ``bench_import_web_ui`` 那种把 Python 表达式拼成 ``-c`` payload
    的场景；payload 里 import 哪个模块直接决定 R76 是否 silent-break。
    可能由 string concatenation 拼成（CPython AST 把 ``"a " "b"`` 折叠为
    单个 Constant，但 ``"a " + "b"`` 不会折叠），本函数只看连续 string
    literals 与单 Constant，足够覆盖项目实际写法。
    """
    tree = ast.parse(source)
    payloads: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
            and func.attr in {"run", "Popen", "call", "check_call", "check_output"}
        ):
            continue
        if not node.args or not isinstance(node.args[0], ast.List):
            continue
        elts = node.args[0].elts
        # 找 "-c" 元素位置
        for i, elt in enumerate(elts):
            if (
                isinstance(elt, ast.Constant)
                and elt.value == "-c"
                and i + 1 < len(elts)
            ):
                next_elt = elts[i + 1]
                if isinstance(next_elt, ast.Constant) and isinstance(
                    next_elt.value, str
                ):
                    payloads.append(next_elt.value)
                # 处理形如 ``"a " "b"`` Python 隐式 concat 已被 AST 合并为
                # 单 Constant；不处理 ``a + b`` 表达式（项目当前没用）。
    return payloads


class TestPerfBenchSourceContainsR116Fix(unittest.TestCase):
    """**反向防御**：守护 R116 修复在 ``perf_e2e_bench.py`` AST 层活着。

    用 AST 精确扫描 ``subprocess`` 调用 argv，避免把 docstring / comment
    里"R76 之前长这样"的历史性引用误报为 silent-break 复发。
    """

    def setUp(self) -> None:
        self.assertTrue(
            PERF_BENCH_PATH.exists(),
            f"{PERF_BENCH_PATH} 必须存在（perf_e2e_bench.py 是 R116 修复目标）",
        )
        self.src = PERF_BENCH_PATH.read_text(encoding="utf-8")

    def test_import_web_ui_dash_c_payload_uses_qualified_module(self) -> None:
        """所有 ``-c`` payload 必须 import 完整包路径，禁止裸 ``import web_ui``。

        R76 之前是 ``import web_ui``——R76 把模块迁到 ``src/`` 后这条
        永远 ``ModuleNotFoundError``，但被 ``run_all`` 的 try/except 静默
        吞成 results 里的 ``error`` 字段，``perf_gate`` 当时也没在 CI 里
        跑，于是回归完全失明。R116 改成
        ``from ai_intervention_agent import web_ui``。
        """
        payloads = _collect_subprocess_run_dash_c_payloads(self.src)
        self.assertGreater(
            len(payloads), 0, "没找到任何 subprocess `-c` payload，AST 扫描可能漂移"
        )
        for payload in payloads:
            with self.subTest(payload=payload[:60]):
                # 必须出现新写法
                self.assertIn(
                    "from ai_intervention_agent import web_ui",
                    payload,
                    "subprocess `-c` payload 必须用完整包路径 import",
                )
                # 不允许残留旧写法（在 -c 字符串里 import web_ui 就是裸名）
                # 用单词边界判断避免命中 ``ai_intervention_agent.web_ui``
                # 的子串
                lines = payload.split(";")
                for line in lines:
                    stripped = line.strip()
                    self.assertFalse(
                        stripped.startswith("import web_ui")
                        and not stripped.startswith("import web_ui_"),
                        f"`-c` payload 里残留 R76-broken 的 `import web_ui`: "
                        f"{stripped!r}",
                    )

    def test_subprocess_argv_uses_dash_m_module_invocation(self) -> None:
        """``subprocess.{Popen,run}`` argv 不能含 ``"web_ui.py"``，必须含
        ``"-m"`` + ``"ai_intervention_agent.web_ui"`` 配对。

        R76 之前 argv 是 ``[python, "web_ui.py", ...]``，R76 之后 ``web_ui.py``
        不在 ``REPO_ROOT``，subprocess 立刻 ``rc=2`` ``can't open file`` 退出，
        被 wrapper 转换成 ``Web UI subprocess exited before listening``——
        长得像服务端 crash，没人会去查文件名。R116 改成
        ``[python, "-m", "ai_intervention_agent.web_ui", ...]``。
        """
        argv_strings = _collect_subprocess_argv_string_literals(self.src)
        self.assertGreater(
            len(argv_strings),
            0,
            "没找到任何 subprocess argv 字面量，AST 扫描可能漂移",
        )
        # 反向：旧写法不能存在于任何 subprocess argv
        self.assertNotIn(
            "web_ui.py",
            argv_strings,
            f"subprocess argv 里残留 R76-broken 的 `web_ui.py`: argv={argv_strings}",
        )
        # 正向：新写法的两个元素必须都存在
        self.assertIn(
            "-m",
            argv_strings,
            "subprocess argv 应该有 `-m` 元素（R116 引入）",
        )
        self.assertIn(
            "ai_intervention_agent.web_ui",
            argv_strings,
            "subprocess argv 应该有 `ai_intervention_agent.web_ui` 元素（R116 引入）",
        )

    def test_r116_marker_present_in_source(self) -> None:
        """守护源码 ``R116`` 标记不被未来重构无意识抹掉。"""
        self.assertIn(
            "R116",
            self.src,
            "perf_e2e_bench.py 必须保留 R116 标记，否则 grep 不到无法追溯",
        )


class TestPerfBenchAllBenchmarksActuallyRun(unittest.TestCase):
    """**核心**：真跑一次 ``perf_e2e_bench.py --quick`` 验证全部 benchmark
    都能产出非空 ``samples_ms``。

    这是反 ``run_all`` 那条 ``try/except Exception`` 把 RuntimeError 吞成
    ``error`` 字段的最后防线。
    """

    @classmethod
    def setUpClass(cls) -> None:
        # 不能在 import 期跑——会拖测试导入时间到 ~10 s。
        # ``--quick`` 把 iterations 砍到最少（import_web_ui=2、spawn=2、
        # html_render=30、api_*=5），整段 wall < 30 s。
        env = {
            **os.environ,
            "AI_INTERVENTION_AGENT_NO_BROWSER": "1",
        }
        # ``capture_output=True`` 让 stdout/stderr 不污染 pytest output。
        # ``check=False`` 让 non-zero exit code 不抛——我们要看 stdout 的
        # JSON 内容判定具体哪条 bench fail。
        result = subprocess.run(
            [
                sys.executable,
                str(PERF_BENCH_PATH),
                "--quick",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            check=False,
        )
        cls._result = result
        # ``perf_e2e_bench.py`` 把 JSON dump 到 stdout。
        try:
            cls._payload = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            cls._payload = {}
            cls._json_error = (
                f"perf_e2e_bench.py stdout 不是合法 JSON: {e}; "
                f"stdout[:500]={result.stdout[:500]!r}; "
                f"stderr[:500]={result.stderr[:500]!r}"
            )
        else:
            cls._json_error = None

    def test_subprocess_exited_zero(self) -> None:
        """``perf_e2e_bench.py --quick`` 整体 exit code 必须 0。"""
        self.assertIsNone(
            self._json_error,
            f"R116 修复后 ``--quick`` 模式必须能跑通: {self._json_error}",
        )
        self.assertEqual(
            self._result.returncode,
            0,
            f"perf_e2e_bench.py --quick rc={self._result.returncode}; "
            f"stderr={self._result.stderr[:1000]}",
        )

    def test_all_benchmarks_present_in_payload(self) -> None:
        """所有 benchmark 名都要在 payload top-level（结构锁）。"""
        self.assertIsNone(self._json_error, self._json_error)
        for name in EXPECTED_BENCHMARKS:
            self.assertIn(
                name,
                self._payload,
                f"benchmark {name!r} 缺失，可能被新一轮 refactor 漏掉",
            )

    def test_all_benchmarks_have_samples(self) -> None:
        """每条 benchmark 必须产出非空 ``samples_ms``，且 ``iterations > 0``。

        R116 之前 4/5 broken 时这里的 ``samples_ms`` 是 ``[]`` ——本测试
        即可立即 fail，无须人工肉眼比 baseline。
        """
        self.assertIsNone(self._json_error, self._json_error)
        for name in EXPECTED_BENCHMARKS:
            with self.subTest(benchmark=name):
                bench = self._payload[name]
                self.assertNotIn(
                    "error",
                    bench,
                    f"{name} 报错: {bench.get('error', '')}; R116 修复未生效",
                )
                samples = bench.get("samples_ms", [])
                self.assertGreater(
                    len(samples),
                    0,
                    f"{name} samples_ms 为空 —— benchmark 没真跑",
                )
                self.assertGreater(
                    bench.get("iterations", 0),
                    0,
                    f"{name} iterations=0 —— benchmark 没真跑",
                )
                self.assertGreaterEqual(
                    float(bench.get("median_ms", -1.0)),
                    0.0,
                    f"{name} median_ms 非数字或负数: {bench.get('median_ms')!r}",
                )


class TestPerfGateAlsoSeesRefreshedBaseline(unittest.TestCase):
    """守护：本次 R116 一并刷新的 ``tests/data/perf_e2e_baseline.json``
    是合法的 perf_gate 输入，且包含旧 5 条 release-gate benchmark。

    这是结构层断言，不绑定具体数字（数字会随机器漂移）。
    """

    def test_baseline_json_loads_and_has_release_gate_benchmarks(self) -> None:
        baseline_path = REPO_ROOT / "tests" / "data" / "perf_e2e_baseline.json"
        self.assertTrue(
            baseline_path.exists(),
            f"perf baseline {baseline_path} 必须存在",
        )
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        self.assertIn(
            "benchmarks",
            payload,
            "baseline JSON top-level 必须有 ``benchmarks`` 字段（perf_gate 期望）",
        )
        bench = payload["benchmarks"]
        for name in BASELINE_BENCHMARKS:
            with self.subTest(benchmark=name):
                self.assertIn(
                    name,
                    bench,
                    f"baseline 缺 benchmark {name!r}（R116 baseline 刷新漏）",
                )
                self.assertIn("median_ms", bench[name])
                self.assertGreater(
                    float(bench[name]["median_ms"]),
                    0.0,
                    f"baseline {name} median_ms <= 0",
                )


if __name__ == "__main__":
    unittest.main()
