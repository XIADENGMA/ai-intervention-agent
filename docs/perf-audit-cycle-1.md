# 后端性能审计 cycle-1

## 0. 阅读引导

本 cycle 把"性能"狭义聚焦到 **`task_queue.py` 内部数据结构与并发**、
**`_SSEBus` 事件分发与背压**、以及 **`_upload_helpers` 图片入站
edge** 三条 hot path；其余子系统（数据库迁移、日志、HTTP 路由层、
i18n 加载）由之前的 R 系列优化稿已经覆盖。

如果你在调查**前端性能**，请直接看 `perf-audit-cycle-1-frontend.md`
（CR#30 follow-up 已 ship 的 BFCache 修复 / R20.x 系列）。

阅读优先级建议：

1. §1 是结论与下一步行动（无新增 work 的话就到这里结束）；
2. §2~§4 是逐子系统证据，按发现-评估-决策三段式行文；
3. §5 是被显式 *defer* 的 future tracks（带 ROI 估算与触发条件）。

---

## 1. 结论摘要

| 子系统 | 当前状态 | 本 cycle 是否需要新增 work |
| --- | --- | --- |
| TaskQueue (ReadWriteLock + 单调时间快照) | ✅ 已优化至当前抽象层极限（R22.2/R23.4） | 否（只 ship 1 个 API hardening：`extend_deadline` 必填 keyword）|
| `_SSEBus` (背压 + history ring + cardinality cap + latency P50/P95) | ✅ 已成熟（R40-S2 / R58 / R134 / R203） | 否 |
| `_upload_helpers` (4 层分层防御 + 单文件 cap + 累计 cap) | ✅ 已强化（R17.6） | 否 |
| `Task.extend_deadline` keyword 默认值漂移 | ⚠️ low risk drift (cr32 §3.3) | **是** — 此 cycle 修复，强制 caller 显式传 |

**新增 commit：** 1 个 hardening + 1 个本 doc。

**defer (见 §5):** 4 个 future track，预算 cycle-2+。

---

## 2. TaskQueue 现状

### 2.1 并发原语

- `_lock` 使用项目内 `ReadWriteLock`（R22.2 引入），不是 `threading.Lock`。
  - 读端 `read_lock()` 走 readers 计数 + 单一 condition；多读者并发不互斥。
  - 写端 `write_lock()` 等所有 reader 退出。
  - `_watched_write_lock()` 是 write_lock 的 instrumented 版本，记录 wait
    time 用于 R134 性能采样。
- `_persist()` 走 tmpfile + `fsync(fileno())` + `os.replace()` 原子写
  （详见 R-cycle 文档；本 cycle 不动）。

### 2.2 hot path 合并 — `get_all_tasks_with_stats`

- 旧路径 `/api/tasks`: `get_all_tasks()` + `get_task_count()` = 2× 入锁。
- 新路径（R23.4）合并成单 read_lock：~400-900 ns saved per call。
  - 量级：前端默认 2s 轮询 + 扩展 3s 兜底；2-5 并发客户端 ⇒ ~50-150 calls/min。
  - **绝对值小**（40-90 µs/min），但语义价值更大：**list / stats
    完全一致**，消除了 1-step skew。
- **结论**：当前抽象层下不再有可合并的读端路径。

### 2.3 写端 — `extend_task_deadline` facade

- cr32 §3.1 已修复 race（详见 `tests/test_cr32_extend_race.py`）。
- 本 cycle hardening (§4)：keyword-only 参数 `max_extends/min_seconds/
  max_seconds` 改为**必填**，杜绝 server_config 调整后 caller 仍用旧值的
  silent drift。

### 2.4 没有找到的 hot path

- ❌ `_persist()` 频率：仅在 add/complete/expire 时触发，远低于 read 端
  压力；当前 fsync 成本可接受。
- ❌ task list 长度上限：`max_tasks` 默认 50；O(N) 操作（如 `get_all_tasks`
  的 list view 重建）成本 50 × ~10ns = 0.5µs，远小于 lock acquire 成本。

---

## 3. `_SSEBus` 现状

### 3.1 已有 hardening

| 风险 | 防御 | 引入版本 |
| --- | --- | --- |
| 队列满导致 emit 阻塞所有 thread | `Queue(maxsize=64)` + 3/4 阈值预警丢弃 | 初始设计 |
| 客户端断开后 queue 泄漏 | emit 时检测 Full → 移除 + `_SSE_DISCONNECT_SENTINEL` 让 generator return | 初始设计 |
| 浏览器断线后状态丢失 | Last-Event-ID 重放 + `_HISTORY_MAXLEN=128` 环形 buffer | R40-S2 |
| 单条事件 payload 过大导致 nginx/CloudFlare 卡顿 | `_OVERSIZE_LIMIT_BYTES=256KB` + 替换为 `oversize_drop` warning | R58 |
| Prometheus exposition payload 因动态 event_type 爆炸 | `_emit_by_type` cardinality cap (100 keys) + `__other__` overflow bucket | R203 |
| 「现在有多慢」缺乏定量信号 | emit→deliver 延迟 P50/P95 滑窗，`_LATENCY_SAMPLES_MAXLEN=512` | R134 |

### 3.2 待办（**不在本 cycle**）

- cr32 §3.6 [info]：`extend` POST 当前不广播 `task_extended` SSE 事件，
  其他 client 靠 ~5s 轮询同步。Schema 加 1 个 event type + emit 1 行，
  ROI 高但需要前端配套消费逻辑，留到 cycle-2 配合 Feature Mining cycle-2
  其他 SSE-related 调整一起做。

---

## 4. `_upload_helpers` 现状

### 4.1 4 层分层防御

1. `MAX_CONTENT_LENGTH = MAX_TOTAL_UPLOAD_BYTES + 1MB` → Flask
   multipart 解析阶段就拒，OWASP "Limit upload size" 推荐。
2. `MAX_FILE_SIZE_BYTES = 10MB` → 即使 (1) 被上游 reverse proxy strip 掉
   `Content-Length` 头，单 part 读取也被 cap。
3. `MAX_IMAGES_PER_REQUEST = 10` + `MAX_TOTAL_UPLOAD_BYTES = 100MB` →
   累计预算，超过即跳过后续 file（已通过的不回滚，避免全有/全无突变）。
4. `validate_uploaded_file` → magic-number / extension / content scan。

### 4.2 base64 编码开销

- 编码点：`base64.b64encode(file_content)` 单文件 10MB 极限 ≈ 13.3MB
  base64，编码耗时 ~25-40 ms（CPython 3.13 C 实现）。
- 频率：每 file 一次，单请求最多 10 file ⇒ ~250-400 ms 累计；这是用户
  显式上传操作的端到端预算的一部分，不在常驻 hot path。
- **结论**：当前实现合理；任何"流式 base64"改造都会牵动 DB schema /
  前端协议，ROI 不值。

---

## 5. Defer 列表 (future tracks)

按 ROI 降序：

### 5.1 SSE `task_extended` 广播 (medium ROI)

- **触发条件**：观察到多 client 并发 + 用户报告"我点了 extend 但其他
  设备没更新"。
- **预算**：~30 LoC backend + ~20 LoC frontend + ~50 LoC test = 1 commit
  ≈ 0.5 day。
- **依赖**：与 Feature Mining cycle-2 中可能新增的其他 SSE event
  schema 一起 batch 评审，避免 schema 多次升级。

### 5.2 TaskQueue auto-cleanup of expired tasks (low ROI)

- 当前 `max_tasks=50`，到达后 `add_task` 直接 reject。expired 状态的
  task 占用槽位。如果未来调到 max=500 / 5000 用于 batch agent 场景，
  需要后台清理协程。
- **触发条件**：用户配置 `max_tasks ≥ 500` 或观察到 expired 占比 > 50%。

### 5.3 Image streaming upload (low ROI)

- 当前一次性 read 整个 file_content 进内存。理论上 10MB×10 = 100MB
  内存峰值。
- **触发条件**：大客户场景，单进程并发 > 5 个上传 + per upload > 50MB。
  当前完全没看到这种 telemetry。

### 5.4 `_persist()` debounce (low ROI)

- 当前每次 add/complete/expire 都同步 fsync 一次。如果未来 task 频次飙到
  > 100/s，可以加 50ms debounce + dirty flag。
- **触发条件**：未观察到；当前 task add 频率 < 0.1/s 量级。

---

## 6. Reproducibility — 如何重做本审计

```bash
# 1. lint hot path 文件
rg -n 'extend_deadline|get_all_tasks|_SSEBus|extract_uploaded_images' \
   src/ai_intervention_agent/

# 2. invariant test
uv run pytest tests/test_feat_countdown_extend.py \
              tests/test_cr32_extend_race.py \
              tests/test_web_ui_routes.py -x

# 3. 检查 R 系列文档对应的 commit
git log --grep='R22.2\|R23.4\|R40-S2\|R58\|R134\|R203'
```

## 7. 关联文档

- `docs/code-reviews/cr30.md` ~ `cr32.md` — 历史 code review
- `docs/feature-mining-cycle-1.md` — Feature backlog（已清空 §3.1-§3.5）
- `docs/perf-audit-cycle-1-frontend.md`（如存在）— 对应前端审计
- `tests/test_cr32_extend_race.py` — extend race fix 的 threading
  invariant
