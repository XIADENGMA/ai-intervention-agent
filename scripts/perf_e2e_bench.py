"""R20.14-A · End-to-end performance benchmark harness.

设计目标
========

R20.4-R20.13 累积四轮性能优化，把"AI 调用 ``interactive_feedback`` →
用户看到 Web UI"的端到端延迟从 1980 ms 压到 360 ms（-82%）。这些数字
散落在各个 commit message 和测试断言里，缺一个统一的入口让运维 / CI /
未来的优化作者：

1. 一条命令拿到当前真实测得的延迟数字（不是凭印象 / 翻 commit message）；
2. 知道哪个环节是当前最大的瓶颈（指导下一轮优化方向）；
3. 在 ``perf_gate.py`` 里定阈值阻断回归（``ci_gate`` 集成可选）。

本模块只做测量与报告，**不做断言** —— 阈值检查归 ``perf_gate.py``。

5 道 benchmark
==============

1. **import_web_ui**：``subprocess.run`` 隔离的 ``import web_ui`` 时间。
   反映 R20.4-R20.10 的主进程冷启动压缩成果。R20.10 实测 156 ms 中位数。

2. **spawn_to_listen**：``subprocess.Popen([python, web_ui.py])`` 到
   ``socket.create_connection`` 成功的 wall-time。反映 R20.11 的
   mDNS async-publish 收益。R20.11 实测 203 ms 中位数。

3. **html_render**：``WebFeedbackUI._get_template_context()`` + 完整
   ``render_template`` 一次的 wall-time。反映 R20.12-B inline locale
   缓存的实际命中率。post-R20.12 实测 cache-hit 中位数 < 1 ms。

4. **api_health_round_trip**：完整 Web UI 子进程起来后 ``GET /api/health``
   一次的 round-trip wall-time。反映 Flask 路由分发 + 响应序列化的
   稳态吞吐。预期 < 20 ms 在本机 loopback。

5. **api_config_round_trip**：``GET /api/config`` 一次 round-trip。比
   ``/api/health`` 多吃一次 ``ConfigManager.load()``，是 mDNS / 服务器
   配置 readback 的主要路径。预期 < 30 ms。

为什么是这 5 道而不是其他
=========================

- 不测 webview HTML render（需要 Node + VSCode API mock，CI fragile）—
  只锁源码 invariant 在 ``tests/test_vscode_perf_r20_13.py`` 里
- 不测 SSE 事件流（事件需要从 task lifecycle 触发，难以孤立）
- 不测前端 FCP / LCP（需要真实浏览器，nightly batch 跑可以但 CI gate 不
  适合）
- 这 5 道全部 Python-only，无外部依赖（除了 Python stdlib + uv 已装的
  Flask + 项目自身），CI 上稳定可重复

输出
====

JSON 字典写到 stdout（默认）或 ``--output PATH`` 文件。每个 benchmark
返回 ``{name: {median_ms, p90_ms, min_ms, max_ms, iterations, samples_ms}}``。
``samples_ms`` 是原始数据数组，后续工具可以在上面跑 trend / outlier 分析。

用法示例
========

    uv run python scripts/perf_e2e_bench.py
    uv run python scripts/perf_e2e_bench.py --quick    # 快跑（少 iterations）
    uv run python scripts/perf_e2e_bench.py --output bench.json --quiet
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    """选一个空闲端口（与 ``test_mdns_async_publish`` 同模式）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _percentile(samples: list[float], p: float) -> float:
    """简易 p90 / p95 计算（避免引入 numpy 依赖）。"""
    if not samples:
        return float("nan")
    sorted_samples = sorted(samples)
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    k = (len(sorted_samples) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_samples) - 1)
    if f == c:
        return sorted_samples[f]
    return sorted_samples[f] + (k - f) * (sorted_samples[c] - sorted_samples[f])


def _summarize(samples_ms: list[float]) -> dict[str, Any]:
    """把原始毫秒采样压成统计字典。"""
    if not samples_ms:
        return {
            "median_ms": None,
            "p90_ms": None,
            "min_ms": None,
            "max_ms": None,
            "iterations": 0,
            "samples_ms": [],
        }
    return {
        "median_ms": round(statistics.median(samples_ms), 2),
        "p90_ms": round(_percentile(samples_ms, 0.9), 2),
        "min_ms": round(min(samples_ms), 2),
        "max_ms": round(max(samples_ms), 2),
        "iterations": len(samples_ms),
        "samples_ms": [round(s, 2) for s in samples_ms],
    }


# ---------------------------------------------------------------------------
# 1. import_web_ui — subprocess-isolated cold import
# ---------------------------------------------------------------------------


def bench_import_web_ui(iterations: int) -> list[float]:
    """每次起一个全新 Python 解释器，``import web_ui`` 计时。"""
    samples: list[float] = []
    for _ in range(iterations):
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import time; t=time.monotonic(); import web_ui; "
                "print(f'{(time.monotonic()-t)*1000:.3f}')",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ},
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"import web_ui subprocess failed: rc={proc.returncode}, "
                f"stderr={proc.stderr[:500]}"
            )
        try:
            samples.append(float(proc.stdout.strip()))
        except ValueError as e:
            raise RuntimeError(
                f"import web_ui subprocess produced unparseable stdout: {proc.stdout!r}"
            ) from e
    return samples


# ---------------------------------------------------------------------------
# 2. spawn_to_listen — full Web UI subprocess cold start
# ---------------------------------------------------------------------------


def bench_spawn_to_listen(iterations: int) -> list[float]:
    """``subprocess.Popen([python, web_ui.py, ...])`` 到 socket 可连接的 wall time。"""
    samples: list[float] = []
    for _ in range(iterations):
        port = _free_port()
        env = {
            **os.environ,
            "AI_INTERVENTION_AGENT_NO_BROWSER": "1",
        }
        t0 = time.monotonic()
        proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "web_ui.py",
                "--prompt",
                "perf-bench",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            elapsed_ms: float | None = None
            deadline = t0 + 30.0  # 30s 超时上限
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                        elapsed_ms = (time.monotonic() - t0) * 1000.0
                        break
                except (ConnectionRefusedError, OSError, TimeoutError) as conn_err:
                    if proc.poll() is not None:
                        raise RuntimeError(
                            "Web UI subprocess exited before listening; "
                            f"rc={proc.returncode}"
                        ) from conn_err
                    time.sleep(0.005)
            if elapsed_ms is None:
                raise RuntimeError("Web UI subprocess did not listen within 30s")
            samples.append(elapsed_ms)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
    return samples


# ---------------------------------------------------------------------------
# 3. html_render — in-process template render wall time
# ---------------------------------------------------------------------------


def bench_html_render(iterations: int) -> list[float]:
    """In-process 调用 ``_get_template_context`` + ``render_template`` 一次。"""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="perf-bench", port=0)

        with ui.app.test_request_context("/"):
            from flask import render_template

            # 预热一次，让 R20.12-B 的 ``_read_inline_locale_json`` lru_cache /
            # Jinja 模板编译缓存都进入稳态；不预热的话 max 会比 median 高 80×
            # （第一次 ~6 ms vs 稳态 0.07 ms），p90 也会被这条 outlier 拉偏。
            warmup_ctx = ui._get_template_context()
            _warmup_html = render_template("web_ui.html", **warmup_ctx)
            if not _warmup_html or "<!doctype html>" not in _warmup_html.lower():
                raise RuntimeError(
                    "render_template warmup produced empty / invalid HTML"
                )

            samples: list[float] = []
            for _ in range(iterations):
                t = time.perf_counter()
                ctx = ui._get_template_context()
                html = render_template("web_ui.html", **ctx)
                samples.append((time.perf_counter() - t) * 1000.0)
                if not html or "<!doctype html>" not in html.lower():
                    raise RuntimeError(
                        "render_template produced empty / invalid HTML; "
                        "likely a template lookup failure"
                    )
        return samples
    finally:
        try:
            sys.path.remove(str(REPO_ROOT))
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# 4 & 5. api_*_round_trip — full HTTP round-trip via Web UI subprocess
# ---------------------------------------------------------------------------


def _start_web_ui_subprocess(port: int) -> subprocess.Popen[bytes]:
    """启动 Web UI 子进程，等到 socket 可连接才返回。"""
    env = {
        **os.environ,
        "AI_INTERVENTION_AGENT_NO_BROWSER": "1",
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "web_ui.py",
            "--prompt",
            "perf-bench-api",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                return proc
        except (ConnectionRefusedError, OSError, TimeoutError) as conn_err:
            if proc.poll() is not None:
                proc.terminate()
                raise RuntimeError(
                    f"Web UI subprocess exited before listening; rc={proc.returncode}"
                ) from conn_err
            time.sleep(0.01)
    proc.terminate()
    raise RuntimeError("Web UI subprocess did not listen within 30s")


def _cleanup_subprocess(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


def _http_get(url: str, *, timeout: float = 5.0) -> tuple[int, bytes]:
    """极简 HTTP GET — 不引外部 dep。"""
    import http.client
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, body
    finally:
        conn.close()


def bench_api_round_trip(endpoint: str, iterations: int) -> list[float]:
    """启动一次 Web UI 子进程，对同一端点跑 ``iterations`` 次 round-trip。

    一次启动多次打 — round-trip 测的是「Flask 路由分发 + 响应序列化 +
    HTTP/1.1 keep-alive」，而不是「Web UI 子进程冷启动」（那是 #2）。
    """
    port = _free_port()
    proc = _start_web_ui_subprocess(port)
    try:
        url = f"http://127.0.0.1:{port}{endpoint}"
        # 预热一次：第一个 request 会触发 lazy-load（R20.10 设计），不计时
        try:
            _http_get(url, timeout=3.0)
        except Exception:
            pass

        samples: list[float] = []
        for i in range(iterations):
            # web_ui.py 配置 ``default_limits=['60 per minute', '10 per second']``，
            # 不间断打 ``/api/health`` 会很快触发 429。每次请求间 sleep 110 ms
            # 留 1 ms 余量保证稳定 < 10 req/s（10 iters × 110 ms ≈ 1.1 s 总
            # 间隔时间，远小于 60 req/min 限速窗口）。被测的是 round-trip
            # latency 而不是吞吐量，所以 sleep 不污染测量值。
            if i > 0:
                time.sleep(0.11)
            t = time.perf_counter()
            status, _body = _http_get(url, timeout=3.0)
            elapsed_ms = (time.perf_counter() - t) * 1000.0
            if status != 200:
                raise RuntimeError(f"GET {url} returned status {status}, expected 200")
            samples.append(elapsed_ms)
        return samples
    finally:
        _cleanup_subprocess(proc)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


BENCHMARKS: dict[str, Callable[[int], list[float]]] = {
    "import_web_ui": bench_import_web_ui,
    "spawn_to_listen": bench_spawn_to_listen,
    "html_render": bench_html_render,
    "api_health_round_trip": lambda n: bench_api_round_trip("/api/health", n),
    "api_config_round_trip": lambda n: bench_api_round_trip("/api/config", n),
}

DEFAULT_ITERATIONS: dict[str, int] = {
    "import_web_ui": 3,
    "spawn_to_listen": 3,
    "html_render": 100,
    "api_health_round_trip": 10,
    "api_config_round_trip": 10,
}

QUICK_ITERATIONS: dict[str, int] = {
    "import_web_ui": 2,
    "spawn_to_listen": 2,
    "html_render": 30,
    "api_health_round_trip": 5,
    "api_config_round_trip": 5,
}


def run_all(
    *,
    quick: bool = False,
    select: list[str] | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """跑所有 / 部分 benchmark，返回 ``{name: summary}`` 字典。"""
    iters = QUICK_ITERATIONS if quick else DEFAULT_ITERATIONS
    targets = select if select else list(BENCHMARKS.keys())

    out: dict[str, Any] = {}
    for name in targets:
        if name not in BENCHMARKS:
            raise SystemExit(f"unknown benchmark: {name}")
        if not quiet:
            print(
                f"[perf_bench] running {name} ({iters[name]} iters)…", file=sys.stderr
            )
        try:
            samples = BENCHMARKS[name](iters[name])
            out[name] = _summarize(samples)
        except Exception as e:
            out[name] = {
                "error": f"{type(e).__name__}: {e}",
                "iterations": 0,
                "samples_ms": [],
            }
            if not quiet:
                print(f"[perf_bench] FAILED {name}: {e}", file=sys.stderr)
    return out


def _format_human_table(results: dict[str, Any]) -> str:
    """渲染人类可读表格（CI / 本地终端）。"""
    rows: list[str] = []
    rows.append(
        f"{'benchmark':<28} {'median':>10} {'p90':>10} {'min':>10} {'max':>10} {'iters':>6}"
    )
    rows.append("-" * 80)
    for name, info in results.items():
        if "error" in info:
            rows.append(f"{name:<28} ERROR: {info['error']}")
            continue
        rows.append(
            f"{name:<28} "
            f"{info['median_ms']:>9.2f}ms "
            f"{info['p90_ms']:>9.2f}ms "
            f"{info['min_ms']:>9.2f}ms "
            f"{info['max_ms']:>9.2f}ms "
            f"{info['iterations']:>6d}"
        )
    return "\n".join(rows)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="R20.x 端到端性能 benchmark — 测量 ai-intervention-agent 五条关键路径"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快跑模式（少 iterations，~10s 完成）",
    )
    parser.add_argument(
        "--select",
        action="append",
        choices=list(BENCHMARKS.keys()),
        help="只跑指定 benchmark（可多次指定）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="把 JSON 结果写到该文件（默认 stdout）",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="抑制 stderr 进度输出",
    )
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="输出格式（默认 json）",
    )
    args = parser.parse_args(argv)

    results = run_all(quick=args.quick, select=args.select, quiet=args.quiet)

    if args.format == "table":
        text = _format_human_table(results)
    else:
        text = json.dumps(results, ensure_ascii=False, indent=2)

    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
