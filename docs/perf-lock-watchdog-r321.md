# `_LOCK_WATCHDOG_TIMEOUT_S = 30.0` 决策记录 (R321)

**目标**: `_LOCK_WATCHDOG_TIMEOUT_S` 字面量 `30.0` (秒) 是 R315 perf-baseline
锁定 (cycle-32 #A2, 6th perf-baseline app) 的关键常量之一, R321 (cycle-34
#A1) 把背后的设计决策落到独立文档, 让任何提出"改成 10s/60s/300s"的 PR
都能立即看到取舍依据。

R321 是 v3.7 决策三层 (decision-three-layer) pattern 3rd app, 同时让 v3.7
**决策三层 pattern 进入完全工业化** (与 v3.7 三层一致性 pattern 平级)。

---

## 1. 数字本身

```python
# src/ai_intervention_agent/task_queue.py
_LOCK_WATCHDOG_TIMEOUT_S: float = 30.0
"""单次 _watched_write_lock 的 acquire+hold 上限。超过这个时长 watchdog
扫到一次就 dump 全线程栈到 logger.error。"""

_LOCK_WATCHDOG_SCAN_INTERVAL_S: float = 5.0
"""watchdog 扫描周期。_LOCK_WATCHDOG_TIMEOUT_S / _LOCK_WATCHDOG_SCAN_INTERVAL_S
≈ 6 意味着真出现 deadlock 时最快 5 s、最慢 35 s 就会有 dump 进入日志。"""
```

**类型**: `float` (秒)  
**值**: `30.0`  
**消费者**: `_scan_pending_and_dump_slow()` (task_queue.py:147),
`_lock_watchdog_loop()` (task_queue.py:173)

---

## 2. 决策依据 (为什么是 30s 不是 10s / 60s / 300s)

### 2.1 上界: 不能 < 10s

- TaskQueue 正常 write critical section (e.g. ``append_task_to_queue`` /
  ``finalize_task_completion``) **极少**超过 100ms (内存操作 + 1 次磁盘
  ``atomic_write`` JSON dump, 典型 << 50ms)
- 但**异常情况** (磁盘满 / NFS hang / fsync 慢) 可能让 ``atomic_write``
  阻塞数秒到 10s+
- 如果 watchdog 阈值 < 10s, 这些**临时 I/O 抖动**会被误报为 deadlock,
  dump 全栈到 stderr / stdout, 污染日志
- **30s 是 ``atomic_write`` 在最差 (NFS) 条件下 P99.9 的 ~3x 安全余量**

### 2.2 下界: 不能 > 60s

- 真的发生 deadlock 时, **运维 / 监控** 需要尽快看到信号 (用户已经在等)
- 用户等待 60s 还不见 task feedback 已经会怀疑系统出问题 (用户的注意力
  曲线在 30-60s 之间陡降, 见 web UI 习惯研究)
- 30s 是个**典型用户超时心理界限** (与 ``auto_resubmit_timeout=120``
  的一半相符, 让 watchdog dump 与用户体感同步)
- 如果 watchdog 阈值 > 60s, 第一次 dump 出现在 60s+5s = 65s 时, 此时用
  户体验已经"明显异常", 信号迟到

### 2.3 SCAN_INTERVAL = 5s 的 ratio

- ``_LOCK_WATCHDOG_TIMEOUT_S / _LOCK_WATCHDOG_SCAN_INTERVAL_S = 30/5 = 6``
- 意味着 watchdog 至少有 5 个 scan cycle 在 deadlock 范围内, 能避免**单
  次 missed schedule** 导致 dump 完全丢失
- R315 invariant 锁定 ``TIMEOUT / SCAN_INTERVAL >= 5`` 这条比例不可破

### 2.4 与其他数字的关联

| 名字 | 值 | 与 watchdog 的关系 |
|---|---|---|
| ``auto_resubmit_timeout`` (默认) | 120s | watchdog 阈值 = 1/4, 让运维比用户更早看到信号 |
| ``HTTP request timeout`` (Flask) | 30s (gunicorn 默认) | 同档, 让 watchdog dump 与 worker timeout 同步触发, 便于关联 |
| ``MCP tool call timeout`` | 600s 上限 | 远 > watchdog, 因 MCP 是人机交互 (人类思考) 主导 |
| ``_FETCH_RETRY_BACKOFF_S`` 总和 | 1.85s | 远 < watchdog, 因 fetch retry 是网络抖动恢复 |

---

## 3. 何时 re-tune

考虑改 ``_LOCK_WATCHDOG_TIMEOUT_S`` 前必须重新评估:

1. **加新 I/O 类型**: 如果 TaskQueue 开始用 SQLite / Redis / S3 等远程
   存储, 单次 critical section 时长分布可能整体右移, 30s 阈值可能误报
2. **改 ``atomic_write`` 实现**: 如果不再用 ``fsync``, P99.9 可能从 ~10s
   降到 ~100ms, 30s 阈值过于宽松, 错过一些早期 deadlock 信号
3. **平台改变**: 默认 30s 适合本机 (developer-friendly) 和典型 VPS。
   如果 deploy 到边缘 (高磁盘抖动) 或专用机房 (磁盘极快), 应分平台调优

re-tune 时**必须**: 更新本文档 + R321 invariant baseline + R315
invariant baseline + ``task_queue.py`` 内 docstring 中的数字提及。

---

## 4. 历史

- **R315 (cycle-32 #A2, 2d75971)**: 引入 ``_LOCK_WATCHDOG_TIMEOUT_S`` 常
  量, 用 perf-baseline pattern 锁定字面量 (6th perf-baseline app)
- **R321 (cycle-34 #A1, 本文档)**: 把数字背后的决策落到独立文档, 用
  decision-three-layer pattern 锁定 "数字 ↔ 决策 ↔ 文档" 三层一致性
  (3rd decision-three-layer app, **v3.7 决策三层 pattern 完全工业化**)

---

## 5. Pattern lineage (decision-three-layer)

- 1st app: **R308** (cr61, 80b8fb4) — CI pytest-xdist `-n 4` benchmark
  decision (`docs/perf-ci-xdist-r308.md`)
- 2nd app: **R314** (cr62, 0a6944e) — `_FETCH_RETRY_BACKOFF_S` retry
  sequence decision (`docs/perf-fetch-retry-backoff-r314.md`)
- **3rd app: R321 (本文档)** — `_LOCK_WATCHDOG_TIMEOUT_S` lock watchdog
  decision

**v3.7 完整工业化** (与 v3.6 全 pattern 同等级别):

| Pattern | 应用次数 | 状态 |
|---|---|---|
| 三层一致性 | 3 (R306+R312+R317) | 工业化 |
| **决策三层** | **3 (R308+R314+R321)** | **工业化 (cr64 R321 新达到)** |
