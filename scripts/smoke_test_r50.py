"""R50 端到端物理冒烟脚本。

目的：在没有 mock 的真实进程里验证：

  1. ``/api/system/sse-stats`` 端点真的能返回有效 JSON（R47 端点活着，R50-A
     依赖它跨进程拉取计数器）。
  2. ``_emit_config_changed_to_sse_bus`` 真的让 ``/api/events`` 流式 endpoint
     吐出 ``event: config_changed`` 帧（R48 端到端通路）。
  3. 在 250 ms 内连续触发 5 次 emit，``/api/events`` 只收到 1 帧（R50-B debounce
     真的生效）。
  4. ``stats_snapshot`` 的 ``emit_total`` 在 step (3) 之后增量 == 1（不是 5），
     再次交叉验证 debounce。

执行约束：
- 用 werkzeug 内置 dev server 在 127.0.0.1 random port 起，不依赖外网；
- 用 httpx 同步 client streaming 抓 SSE，超时 5 秒避免死循环；
- 全程在单 process 内完成，便于 CI 工作流复用。

退出码：
- 0：所有 4 项校验通过；
- 1：任意一项失败，stderr 写人类可读的 reason。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 顺序敏感：必须在 sys.path 注入 REPO_ROOT 之后才能 import 项目模块。
import httpx  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

import ai_intervention_agent.web_ui_config_sync as web_ui_config_sync  # noqa: E402
from ai_intervention_agent.web_ui import WebFeedbackUI  # noqa: E402


def _abort(reason: str) -> None:
    print(f"❌ smoke 失败：{reason}", file=sys.stderr)
    sys.exit(1)


def _start_web_ui_in_thread() -> tuple[Any, str, int]:
    """起一个最小可用的 Flask app（不阻塞真正交互流程），返回 (server, host, port)。"""
    ui = WebFeedbackUI(prompt="(smoke r50)", auto_resubmit_timeout=0)
    # WebFeedbackUI.__init__ 已经构造好了 self.app（Flask），我们直接用 werkzeug 起。
    server = make_server("127.0.0.1", 0, ui.app, threaded=True)
    actual_port = server.server_address[1]
    thread = threading.Thread(
        target=server.serve_forever, name="r50-smoke-werkzeug", daemon=True
    )
    thread.start()
    # 给 server 0.5 s 启动
    time.sleep(0.5)
    return server, "127.0.0.1", int(actual_port)


def _check_stats_endpoint(host: str, port: int) -> dict[str, Any]:
    url = f"http://{host}:{port}/api/system/sse-stats"
    try:
        resp = httpx.get(url, timeout=2.0)
    except Exception as e:
        _abort(f"GET {url} 抛异常：{e!r}")
    if resp.status_code != 200:
        _abort(f"GET {url} 状态码 {resp.status_code}（期望 200）")
    body = resp.json()
    if not body.get("success"):
        _abort(f"sse-stats 返回 success=False：{body!r}")
    needed = (
        "emit_total",
        "latest_event_id",
        "gap_warnings_emitted",
        "backpressure_discards",
        "subscriber_count",
        "history_size",
    )
    for key in needed:
        if key not in body:
            _abort(f"sse-stats 缺字段：{key!r}（实际 keys={list(body.keys())}）")
    return cast(dict[str, Any], body)


def _consume_events_in_thread(
    host: str, port: int, found_events: list[str], stop_event: threading.Event
) -> threading.Thread:
    url = f"http://{host}:{port}/api/events"

    def _run() -> None:
        try:
            with httpx.stream("GET", url, timeout=10.0) as resp:
                if resp.status_code != 200:
                    found_events.append(f"!STATUS={resp.status_code}")
                    return
                # SSE 协议：行为 "event: foo\ndata: bar\n\n"
                current_event = None
                for raw_line in resp.iter_lines():
                    if stop_event.is_set():
                        return
                    line = raw_line.strip() if isinstance(raw_line, str) else ""
                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:") and current_event:
                        found_events.append(current_event)
                        current_event = None
        except Exception as e:
            found_events.append(f"!EXC={type(e).__name__}:{e}")

    t = threading.Thread(target=_run, name="r50-smoke-sse-consumer", daemon=True)
    t.start()
    return t


def main() -> None:
    print("[1/5] 启动 Web UI ...", flush=True)
    server, host, port = _start_web_ui_in_thread()
    print(f"  ✓ http://{host}:{port}", flush=True)

    # ---- 场景 1：sse-stats 端点 ----
    print("[2/5] 探测 /api/system/sse-stats 端点 ...", flush=True)
    snap0 = _check_stats_endpoint(host, port)
    print(f"  ✓ 初始 emit_total={snap0['emit_total']}", flush=True)

    # ---- 场景 2 & 3：debounce + SSE 端到端 ----
    print("[3/5] 启动 /api/events 流式消费者 ...", flush=True)
    found_events: list[str] = []
    stop_event = threading.Event()
    consumer = _consume_events_in_thread(host, port, found_events, stop_event)
    time.sleep(0.5)  # 给 consumer 时间订阅

    # 重置 debounce state，确保第一次 emit 一定能过
    web_ui_config_sync._last_emit_monotonic = 0.0

    print("[4/5] 在 100 ms 内连续 emit 5 次（应被 debounce 压成 1 次）...", flush=True)
    burst_start = time.monotonic()
    for _ in range(5):
        web_ui_config_sync._emit_config_changed_to_sse_bus()
        time.sleep(0.02)
    burst_elapsed = (time.monotonic() - burst_start) * 1000
    print(f"  ✓ 5 次调用耗时 {burst_elapsed:.0f} ms", flush=True)

    # 等 1 秒让 consumer 收到事件（远远超过 debounce window）
    time.sleep(1.0)

    # 现在再 emit 一次（已经过了 debounce window）—— 应该收到第二帧
    web_ui_config_sync._emit_config_changed_to_sse_bus()
    time.sleep(0.5)

    stop_event.set()
    consumer.join(timeout=2.0)

    print("[5/5] 校验结果 ...", flush=True)
    config_changed_count = sum(1 for ev in found_events if ev == "config_changed")
    print(f"  收到的 config_changed 帧数：{config_changed_count}", flush=True)
    print(f"  收到的所有事件帧：{found_events}", flush=True)

    # 期望：5 次 burst → 1 帧；window 后的单独 emit → 1 帧；总共 2
    if config_changed_count != 2:
        _abort(
            f"debounce 行为不对：期望 2 帧 config_changed（5 burst 压成 1 + 1 隔离），"
            f"实际 {config_changed_count}（事件流：{found_events}）"
        )

    # 再调一次 sse-stats，emit_total 应该是初始 + 2
    snap1 = _check_stats_endpoint(host, port)
    delta = int(snap1["emit_total"]) - int(snap0["emit_total"])
    print(f"  emit_total delta = {delta}（期望 2）", flush=True)
    if delta != 2:
        _abort(
            f"emit_total delta 不对：期望 2，实际 {delta}（snap0={snap0}, snap1={snap1}）"
        )

    server.shutdown()
    print(
        json.dumps(
            {
                "result": "OK",
                "stats_initial": snap0,
                "stats_final": snap1,
                "events_observed": found_events,
                "burst_elapsed_ms": int(burst_elapsed),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
