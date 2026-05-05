"""R20.14-A · End-to-end performance regression gate.

设计目标
========

``perf_e2e_bench.py`` 给的是「现在多快」的快照；本脚本是「相比基线有没有
退化」的判定器。两者职责严格分离：bench 不写阈值，gate 不跑测量。

工作流
------

1. 跑一次 ``perf_e2e_bench.py --output current.json``；
2. 跑一次 ``perf_gate.py --results current.json --baseline baseline.json``；
3. 退出码：0 = PASS（没有 benchmark 越过阈值），1 = FAIL（至少一个超出）。
4. 若想刷新基线（例如刚做完一轮优化想固化新数字），加 ``--update-baseline``，
   gate 会把 results 写回 baseline 路径并退出 0（PASS）。

阈值模型
========

对每条 benchmark：

    tolerance_ms = max(baseline_median * pct_threshold, abs_floor_ms)
    regress      = current_median - baseline_median
    is_fail      = regress > tolerance_ms

- ``pct_threshold`` 默认 0.30（允许中位数最多增长 30%）；
- ``abs_floor_ms`` 默认 5.0（绝对噪声地板，保护亚毫秒 benchmark 不被噪点
  误杀 —— html_render 0.07 → 0.10 ms 在 CI 上是常态，不是回归）。

两条同时生效，取「绝对地板」与「百分比」中较宽松的那个，目的是在 CI 上
**只在真实回归时报警**，避免狼来了。

每条 benchmark 也支持单独覆写阈值（``--per-benchmark-threshold name=pct``
或基线 JSON 顶层 ``thresholds`` 字段），给 ``import_web_ui`` 这种本身有
明确 SLA 的环节单独收紧。

输出
====

PASS 时静默（除非 ``--verbose``）；FAIL 时把每条越界的 benchmark 详情
打到 stderr，并以 exit code 1 终止。``--format=json`` 把 verdict 数据
吐到 stdout，方便 CI 做后续 annotation / dashboard。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / "tests" / "data" / "perf_e2e_baseline.json"

DEFAULT_PCT_THRESHOLD = 0.30
DEFAULT_ABS_FLOOR_MS = 5.0


def _load_json(path: Path) -> dict[str, Any]:
    """读 JSON，允许 ``perf_e2e_bench.py`` 的输出（顶层 ``benchmarks``）也允许
    扁平的 ``{name: {...}}``，以便基线和 results 文件能复用同一份解析器。"""
    if not path.exists():
        raise FileNotFoundError(f"perf gate: file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"perf gate: {path} top-level must be JSON object")
    return data


def _extract_benchmarks(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """从 results / baseline JSON 里抽出 ``{bench_name: {median_ms, ...}}``。

    ``perf_e2e_bench.py`` 的输出结构是
    ``{"benchmarks": {name: {median_ms, ...}}, "metadata": {...}}``；
    历史 / 手写 baseline 也可能直接是 ``{name: {median_ms, ...}}``。
    两种都接，取第一个看起来像 benchmark 字典的位置。
    """
    if "benchmarks" in payload and isinstance(payload["benchmarks"], dict):
        out = payload["benchmarks"]
    else:
        out = payload
    cleaned: dict[str, dict[str, Any]] = {}
    for name, info in out.items():
        if not isinstance(info, dict):
            continue
        if "median_ms" not in info:
            continue
        cleaned[name] = info
    return cleaned


def _extract_per_bench_thresholds(payload: dict[str, Any]) -> dict[str, float]:
    """基线 JSON 可以在顶层放 ``thresholds: {name: pct}``，单独覆盖某条
    benchmark 的容忍度。例如 ``{import_web_ui: 0.20}`` 把它收紧到 +20%。
    """
    raw = payload.get("thresholds")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for name, value in raw.items():
        try:
            out[name] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _parse_per_bench_cli(values: list[str] | None) -> dict[str, float]:
    """解析 CLI 里 ``--per-benchmark-threshold name=0.20``（可重复）。"""
    out: dict[str, float] = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(
                f"--per-benchmark-threshold expects name=value, got: {raw!r}"
            )
        name, value = raw.split("=", 1)
        try:
            out[name.strip()] = float(value)
        except ValueError as exc:
            raise ValueError(
                f"--per-benchmark-threshold: cannot parse value as float: {raw!r}"
            ) from exc
    return out


def evaluate(
    *,
    current: dict[str, dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    pct_threshold: float = DEFAULT_PCT_THRESHOLD,
    abs_floor_ms: float = DEFAULT_ABS_FLOOR_MS,
    per_bench_threshold: dict[str, float] | None = None,
) -> dict[str, Any]:
    """对比 current vs baseline，对每条 benchmark 给出 verdict。

    返回结构：

        {
          "ok": bool,
          "results": [
            {
              "name": "import_web_ui",
              "current_ms": 148.25, "baseline_ms": 156.27,
              "delta_ms": -8.02, "tolerance_ms": 46.88,
              "pct_threshold": 0.30, "abs_floor_ms": 5.0,
              "verdict": "pass",   # pass | regression | new | dropped | error
              "message": "..."
            }, …
          ],
          "regressions": [<verdicts where verdict != 'pass'>],
        }

    ``verdict`` 取值含义：

    - ``pass``        — current ≤ baseline + tolerance
    - ``regression``  — current 越过阈值（FAIL 主因）
    - ``new``         — current 里有但 baseline 没有（不计为 FAIL，只是提示）
    - ``dropped``     — baseline 里有但 current 没有（计为 FAIL —— 测试覆盖
                        意外掉了，更值得告警）
    - ``error``       — current 或 baseline 缺 ``median_ms`` / 不是数字
    """
    per_bench_threshold = per_bench_threshold or {}
    results: list[dict[str, Any]] = []

    all_names = set(current.keys()) | set(baseline.keys())
    for name in sorted(all_names):
        cur = current.get(name)
        base = baseline.get(name)

        if cur is None and base is not None:
            results.append(
                {
                    "name": name,
                    "current_ms": None,
                    "baseline_ms": base.get("median_ms"),
                    "delta_ms": None,
                    "tolerance_ms": None,
                    "pct_threshold": per_bench_threshold.get(name, pct_threshold),
                    "abs_floor_ms": abs_floor_ms,
                    "verdict": "dropped",
                    "message": (
                        f"benchmark {name!r} present in baseline but missing from "
                        "current results — coverage regression"
                    ),
                }
            )
            continue

        if base is None and cur is not None:
            results.append(
                {
                    "name": name,
                    "current_ms": cur.get("median_ms"),
                    "baseline_ms": None,
                    "delta_ms": None,
                    "tolerance_ms": None,
                    "pct_threshold": per_bench_threshold.get(name, pct_threshold),
                    "abs_floor_ms": abs_floor_ms,
                    "verdict": "new",
                    "message": (
                        f"benchmark {name!r} not in baseline — run "
                        "``--update-baseline`` to record it"
                    ),
                }
            )
            continue

        # 这里 cur/base 都不是 None；但 ``median_ms`` 可能是 None
        # （bench 跑 0 iters 或 raise 了）。任一为 None / 非数字就算 error。
        cur_ms = cur.get("median_ms") if cur else None
        base_ms = base.get("median_ms") if base else None

        def _is_num(x: Any) -> bool:
            return isinstance(x, (int, float)) and not isinstance(x, bool)

        if not _is_num(cur_ms) or not _is_num(base_ms):
            results.append(
                {
                    "name": name,
                    "current_ms": cur_ms,
                    "baseline_ms": base_ms,
                    "delta_ms": None,
                    "tolerance_ms": None,
                    "pct_threshold": per_bench_threshold.get(name, pct_threshold),
                    "abs_floor_ms": abs_floor_ms,
                    "verdict": "error",
                    "message": (
                        f"benchmark {name!r}: current_median={cur_ms!r}, "
                        f"baseline_median={base_ms!r} — at least one is not a "
                        "number; benchmark may have failed at runtime"
                    ),
                }
            )
            continue

        # ty 看不穿 ``_is_num`` 这种自定义 helper 的 narrowing；显式
        # ``isinstance`` 既是 runtime 二次防护，也帮 type checker 把
        # ``cur_ms / base_ms`` 收窄成 ``int | float``，避免 invalid-argument-type。
        assert isinstance(cur_ms, (int, float)) and not isinstance(cur_ms, bool)
        assert isinstance(base_ms, (int, float)) and not isinstance(base_ms, bool)
        cur_ms_f = float(cur_ms)
        base_ms_f = float(base_ms)

        pct = per_bench_threshold.get(name, pct_threshold)
        tolerance_ms = max(base_ms_f * pct, abs_floor_ms)
        delta_ms = cur_ms_f - base_ms_f
        is_regression = delta_ms > tolerance_ms

        results.append(
            {
                "name": name,
                "current_ms": round(cur_ms_f, 2),
                "baseline_ms": round(base_ms_f, 2),
                "delta_ms": round(delta_ms, 2),
                "tolerance_ms": round(tolerance_ms, 2),
                "pct_threshold": pct,
                "abs_floor_ms": abs_floor_ms,
                "verdict": "regression" if is_regression else "pass",
                "message": (
                    f"current {cur_ms_f:.2f}ms exceeds baseline "
                    f"{base_ms_f:.2f}ms by {delta_ms:+.2f}ms "
                    f"(tolerance {tolerance_ms:.2f}ms = max("
                    f"{pct * 100:.0f}% × {base_ms_f:.2f}, {abs_floor_ms:.2f}))"
                )
                if is_regression
                else (
                    f"current {cur_ms_f:.2f}ms within tolerance of baseline "
                    f"{base_ms_f:.2f}ms (Δ={delta_ms:+.2f}ms, "
                    f"tolerance ±{tolerance_ms:.2f}ms)"
                ),
            }
        )

    regressions = [r for r in results if r["verdict"] in {"regression", "dropped"}]
    return {
        "ok": len(regressions) == 0,
        "results": results,
        "regressions": regressions,
    }


def _format_human(verdict: dict[str, Any], *, verbose: bool) -> str:
    """把 verdict 渲染成给人看的多行报告。verbose=True 也打 PASS 行。"""
    lines: list[str] = []
    if verdict["ok"]:
        lines.append(f"perf gate: PASS ({len(verdict['results'])} benchmarks checked)")
    else:
        lines.append(
            f"perf gate: FAIL ({len(verdict['regressions'])} of "
            f"{len(verdict['results'])} benchmarks regressed)"
        )
    for r in verdict["results"]:
        if r["verdict"] == "pass" and not verbose:
            continue
        marker = {
            "pass": " ok ",
            "regression": "FAIL",
            "new": "new ",
            "dropped": "DROP",
            "error": "ERR ",
        }.get(r["verdict"], "????")
        lines.append(f"  [{marker}] {r['name']}: {r['message']}")
    return "\n".join(lines)


def run(
    *,
    results_path: Path,
    baseline_path: Path,
    pct_threshold: float,
    abs_floor_ms: float,
    per_bench_threshold: dict[str, float],
    update_baseline: bool,
    output_format: str,
    verbose: bool,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
) -> int:
    """主入口（脚本 + 测试都调它），返回 exit code。"""
    results_payload = _load_json(results_path)
    current = _extract_benchmarks(results_payload)

    if update_baseline:
        # ``--update-baseline``：把 current 当成新基线写回 baseline_path。
        # 保留 baseline 现有的 ``thresholds`` 字段（若有）—— 阈值是手工管理
        # 的策略，不应该被 results 自动覆写。
        existing_thresholds: dict[str, float] = {}
        if baseline_path.exists():
            try:
                existing_payload = _load_json(baseline_path)
                existing_thresholds = _extract_per_bench_thresholds(existing_payload)
            except Exception:
                existing_thresholds = {}
        new_baseline: dict[str, Any] = {"benchmarks": current}
        if existing_thresholds:
            new_baseline["thresholds"] = existing_thresholds
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        with baseline_path.open("w", encoding="utf-8") as fh:
            json.dump(new_baseline, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        msg = (
            f"perf gate: baseline updated at {baseline_path} "
            f"({len(current)} benchmarks)"
        )
        if output_format == "json":
            json.dump(
                {"ok": True, "updated": True, "benchmarks": list(current.keys())},
                stdout,
                indent=2,
            )
            stdout.write("\n")
        else:
            print(msg, file=stdout)
        return 0

    baseline_payload = _load_json(baseline_path)
    baseline = _extract_benchmarks(baseline_payload)
    baseline_thresholds = _extract_per_bench_thresholds(baseline_payload)
    merged_per_bench = {**baseline_thresholds, **per_bench_threshold}

    verdict = evaluate(
        current=current,
        baseline=baseline,
        pct_threshold=pct_threshold,
        abs_floor_ms=abs_floor_ms,
        per_bench_threshold=merged_per_bench,
    )

    if output_format == "json":
        json.dump(verdict, stdout, indent=2)
        stdout.write("\n")
    else:
        report = _format_human(verdict, verbose=verbose or not verdict["ok"])
        target = stdout if verdict["ok"] else stderr
        print(report, file=target)

    return 0 if verdict["ok"] else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="R20.14-A perf regression gate (compare bench results to baseline)"
    )
    parser.add_argument(
        "--results",
        required=True,
        type=Path,
        help="path to perf_e2e_bench.py output JSON (the 'current' run)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help=f"path to baseline JSON (default: {DEFAULT_BASELINE.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--threshold",
        dest="pct_threshold",
        type=float,
        default=DEFAULT_PCT_THRESHOLD,
        help=(
            "global per-benchmark percent regression tolerance "
            f"(default: {DEFAULT_PCT_THRESHOLD:.2f} = +30%%)"
        ),
    )
    parser.add_argument(
        "--abs-floor-ms",
        type=float,
        default=DEFAULT_ABS_FLOOR_MS,
        help=(
            "absolute milliseconds noise floor — regressions strictly within "
            f"this much are tolerated regardless of percent (default: {DEFAULT_ABS_FLOOR_MS}ms)"
        ),
    )
    parser.add_argument(
        "--per-benchmark-threshold",
        action="append",
        default=None,
        metavar="NAME=PCT",
        help=(
            "override percent threshold for a single benchmark "
            "(repeatable, e.g. --per-benchmark-threshold import_web_ui=0.20)"
        ),
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="write current results as new baseline and exit PASS (no comparison)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="output verdict as human-readable text (default) or JSON",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print all benchmarks (including PASS) in human format",
    )
    return parser


def _main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    per_bench = _parse_per_bench_cli(args.per_benchmark_threshold)
    return run(
        results_path=args.results,
        baseline_path=args.baseline,
        pct_threshold=args.pct_threshold,
        abs_floor_ms=args.abs_floor_ms,
        per_bench_threshold=per_bench,
        update_baseline=args.update_baseline,
        output_format=args.output_format,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(_main())
