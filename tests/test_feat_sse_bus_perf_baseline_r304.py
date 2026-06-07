"""R304: SSE bus + JS backoff perf-baseline 第二轮 (cycle-30 t30-4)。

cr59 §5 #A3 推荐 "第二轮 perf-baseline" — perf pattern (R296 首次)
第二应用。R296 锁了 5 个 hot-path 时间常量 (heartbeat / cleanup /
throttle / health check), R304 把 perf-baseline pattern 扩展到 **SSE bus
内部 buffer/cap 常量 + JS backoff multiplier**, 这些数值 drift 会引起:
- `_OVERSIZE_LIMIT_BYTES` 改小 → 合法 task_changed event 被替换为 oversize_drop
- `_HISTORY_MAXLEN` 改小 → SSE resume 后客户端经常拿不到 history → 频繁 full resync
- `_QUEUE_MAXSIZE` 改大 → 消费慢的客户端不被踢, backpressure 失灵, 内存增长
- `_BACKPRESSURE_THRESHOLD` 算式变 → 与 `_QUEUE_MAXSIZE * 3/4` 不再 atomic
- `_LATENCY_SAMPLES_MAXLEN` 改大 → metrics sort O(n log n) 拖慢 scrape
- `_EMIT_BY_TYPE_MAX_CARDINALITY` 改大 → R203 cardinality cap 失效, Prometheus 爆
- JS `getNextBackoffMs` multiplier 1.7 改 → 网络抖动后重连速度 drift

================================================================
| Const                              | Value     | Source                          |
|------------------------------------|-----------|---------------------------------|
| 1. _OVERSIZE_LIMIT_BYTES           | 256 * 1024 | web_ui_routes/task.py _SSEBus  |
| 2. _HISTORY_MAXLEN                 | 128       | web_ui_routes/task.py _SSEBus   |
| 3. _QUEUE_MAXSIZE                  | 64        | web_ui_routes/task.py _SSEBus   |
| 4. _BACKPRESSURE_THRESHOLD         | = max*3//4 | web_ui_routes/task.py _SSEBus  |
| 5. _LATENCY_SAMPLES_MAXLEN         | 512       | web_ui_routes/task.py _SSEBus   |
| 6. _EMIT_BY_TYPE_MAX_CARDINALITY   | 100       | web_ui_routes/task.py _SSEBus   |
| 7. JS getNextBackoffMs multiplier  | 1.7       | static/js/multi_task.js         |
================================================================

================================================================
| Tests | 维度                                                  |
|-------|----------------------------------------------------|
| 6     | 5 SSE const + 1 backpressure derivation 锁定           |
| 2     | JS backoff multiplier 1.7 + jitter 0.1 锁定           |
| 3     | meta: history < queue / backpressure < queue ratio     |
================================================================
| 11 总计 |                                                      |
================================================================

**pattern lineage**: R296 (perf-baseline 首次, hot-path 时间常量)
→ **R304 (perf-baseline 第二应用, buffer/cap/multiplier 常量)** — v3.6
perf pattern 从 "时间" 维度扩展到 "容量/系数" 维度。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src" / "ai_intervention_agent"
TASK_PY = SRC / "web_ui_routes" / "task.py"
MULTI_TASK_JS = SRC / "static" / "js" / "multi_task.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    out = re.sub(r"/\*[\s\S]*?\*/", "", src)
    cleaned: list[str] = []
    for line in out.split("\n"):
        in_str: str | None = None
        i = 0
        n = len(line)
        cut = n
        while i < n:
            c = line[i]
            if in_str:
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            else:
                if c in ('"', "'", "`"):
                    in_str = c
                elif c == "/" and i + 1 < n and line[i + 1] == "/":
                    cut = i
                    break
            i += 1
        cleaned.append(line[:cut])
    return "\n".join(cleaned)


# ============================================================
# 5 SSE buffer/cap 常量 + 1 推导式
# ============================================================
class TestSseBusBufferCapConst(unittest.TestCase):
    """SSE _SSEBus 6 个 buffer/cap 常量必须保持当前值不 drift"""

    def setUp(self) -> None:
        self.py = _read(TASK_PY)

    def test_oversize_limit_256kb(self) -> None:
        """_OVERSIZE_LIMIT_BYTES 必须为 256 * 1024 (256KB)。"""
        m = re.search(
            r"_OVERSIZE_LIMIT_BYTES:\s*int\s*=\s*256\s*\*\s*1024",
            self.py,
        )
        self.assertIsNotNone(
            m,
            "R304: _OVERSIZE_LIMIT_BYTES 必须 = 256 * 1024 (R58 SSE 单事件字节上限)",
        )

    def test_history_maxlen_128(self) -> None:
        m = re.search(
            r"_HISTORY_MAXLEN\s*=\s*128\b",
            self.py,
        )
        self.assertIsNotNone(
            m,
            "R304: _HISTORY_MAXLEN 必须 = 128 (R40-S2 SSE history evict 边界)",
        )

    def test_queue_maxsize_64(self) -> None:
        m = re.search(
            r"_QUEUE_MAXSIZE\s*=\s*64\b",
            self.py,
        )
        self.assertIsNotNone(
            m,
            "R304: _QUEUE_MAXSIZE 必须 = 64 (订阅者 queue 上限)",
        )

    def test_backpressure_threshold_3_4_of_max(self) -> None:
        """_BACKPRESSURE_THRESHOLD 必须 = _QUEUE_MAXSIZE * 3 // 4 (推导)。"""
        m = re.search(
            r"_BACKPRESSURE_THRESHOLD\s*=\s*_QUEUE_MAXSIZE\s*\*\s*3\s*//\s*4",
            self.py,
        )
        self.assertIsNotNone(
            m,
            "R304: _BACKPRESSURE_THRESHOLD 必须 = _QUEUE_MAXSIZE * 3 // 4 "
            "(原子推导, 防与 _QUEUE_MAXSIZE drift)",
        )

    def test_latency_samples_maxlen_512(self) -> None:
        m = re.search(
            r"_LATENCY_SAMPLES_MAXLEN:\s*int\s*=\s*512\b",
            self.py,
        )
        self.assertIsNotNone(
            m,
            "R304: _LATENCY_SAMPLES_MAXLEN 必须 = 512 (R134 emit→deliver 延迟样本数)",
        )

    def test_emit_by_type_max_cardinality_100(self) -> None:
        m = re.search(
            r"_EMIT_BY_TYPE_MAX_CARDINALITY:\s*int\s*=\s*100\b",
            self.py,
        )
        self.assertIsNotNone(
            m,
            "R304: _EMIT_BY_TYPE_MAX_CARDINALITY 必须 = 100 (R203 Prometheus cardinality cap)",
        )


# ============================================================
# JS backoff multiplier 1.7 + jitter 0.1
# ============================================================
class TestJsBackoffMultiplier(unittest.TestCase):
    """multi_task.js getNextBackoffMs 必须用 1.7 multiplier + 0.1 jitter"""

    def setUp(self) -> None:
        self.js = _strip_js_comments(_read(MULTI_TASK_JS))

    def test_multiplier_is_1_7(self) -> None:
        """getNextBackoffMs 内 currentMs * 1.7 必须保持 1.7 (黄金分割 ~ φ 启发)。"""
        m = re.search(
            r"function getNextBackoffMs\([\s\S]{0,200}?currentMs\s*\*\s*1\.7\b",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "R304: getNextBackoffMs 必须用 currentMs * 1.7 (不 * 2 太激进 / 不 * 1.5 太慢)",
        )

    def test_jitter_is_0_1(self) -> None:
        """jitter 必须为 0.1 (10% 随机性, 避免雷群效应)。"""
        m = re.search(
            r"function getNextBackoffMs\([\s\S]{0,200}?next\s*\*\s*0\.1\s*\*\s*Math\.random",
            self.js,
        )
        self.assertIsNotNone(
            m,
            "R304: getNextBackoffMs jitter 必须 = next * 0.1 * Math.random() "
            "(雷群预防, 同时不破坏 1.7 主曲线)",
        )


# ============================================================
# meta-lint: 容量比例合理性 (history/queue/backpressure 之间)
# ============================================================
class TestSseCapacityRatios(unittest.TestCase):
    """容量比例语义检查 (防 history > queue 等不合理 drift)"""

    def setUp(self) -> None:
        self.py = _read(TASK_PY)

    def test_history_double_of_queue(self) -> None:
        """history (128) 必须等于 queue (64) 的 2 倍 — 给 evict 留缓冲。"""
        h_m = re.search(r"_HISTORY_MAXLEN\s*=\s*(\d+)", self.py)
        q_m = re.search(r"_QUEUE_MAXSIZE\s*=\s*(\d+)", self.py)
        self.assertIsNotNone(h_m, "未找到 _HISTORY_MAXLEN 定义")
        self.assertIsNotNone(q_m, "未找到 _QUEUE_MAXSIZE 定义")
        assert h_m is not None and q_m is not None
        h = int(h_m.group(1))
        q = int(q_m.group(1))
        self.assertEqual(
            h,
            q * 2,
            f"R304: _HISTORY_MAXLEN ({h}) 必须 = _QUEUE_MAXSIZE ({q}) * 2 "
            f"— 给慢消费者断线重连时留 2 倍历史空间",
        )

    def test_backpressure_ratio_3_4(self) -> None:
        """backpressure (= 64 * 3 // 4 = 48) 必须严格小于 queue (64)。"""
        q_m = re.search(r"_QUEUE_MAXSIZE\s*=\s*(\d+)", self.py)
        self.assertIsNotNone(q_m, "未找到 _QUEUE_MAXSIZE 定义")
        assert q_m is not None
        q = int(q_m.group(1))
        bp = q * 3 // 4
        self.assertEqual(
            bp,
            48,
            f"R304: backpressure 推导出 {bp}, 但 _QUEUE_MAXSIZE=64 * 3//4 应为 48",
        )
        self.assertLess(
            bp,
            q,
            "R304: backpressure 必须 < queue, 否则永远不触发 evict",
        )

    def test_oversize_limit_under_typical_proxy_buffer(self) -> None:
        """_OVERSIZE_LIMIT_BYTES (256KB) 必须 < 1 MB (常见反代 buffer 极限)。"""
        m = re.search(
            r"_OVERSIZE_LIMIT_BYTES:\s*int\s*=\s*(\d+)\s*\*\s*(\d+)",
            self.py,
        )
        self.assertIsNotNone(m, "未找到 _OVERSIZE_LIMIT_BYTES 定义")
        assert m is not None
        a, b = int(m.group(1)), int(m.group(2))
        limit_bytes = a * b
        self.assertEqual(
            limit_bytes,
            256 * 1024,
            f"R304: _OVERSIZE_LIMIT_BYTES = {a} * {b} = {limit_bytes}, "
            f"应为 256 * 1024 = {256 * 1024}",
        )
        self.assertLess(
            limit_bytes,
            1024 * 1024,
            "R304: _OVERSIZE_LIMIT_BYTES 必须 < 1 MB (nginx/CF Free proxy buffer 极限)",
        )


if __name__ == "__main__":
    unittest.main()
