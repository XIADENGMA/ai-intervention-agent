# task_queue

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/task_queue.md`](../api/task_queue.md)

任务队列管理 - 线程安全、状态管理、自动清理、延迟删除、持久化。

## 类

### `class TaskStatus`

任务状态枚举（StrEnum 使其与纯字符串完全兼容）

### `class Task`

任务数据结构：task_id, prompt, options, status, result

#### 方法

##### `get_remaining_time(self) -> int`

计算剩余倒计时（使用单调时间）

##### `get_deadline_monotonic(self) -> float`

获取截止时间的单调时间戳

##### `is_expired(self) -> bool`

检查任务是否已超时

【新增】使用单调时间判断任务是否已超时。

返回:
    bool: True 表示已超时，False 表示未超时

### `class TaskQueue`

任务队列管理器（线程安全）

提供任务的添加、查询、状态管理和自动清理功能。

## 核心特性

### 1. 线程安全
- 所有公共方法使用 `threading.Lock` 保护
- 支持多线程并发访问
- 内部数据结构（_tasks, _task_order）始终保持一致

### 2. 单活动任务模式
- 同一时间只有一个任务处于 `active` 状态
- 其他任务处于 `pending` 状态
- 活动任务完成后自动激活下一个pending任务

### 3. 延迟删除机制
- 任务完成后不立即删除
- 标记 `completed_at` 时间戳
- 后台线程延迟10秒后自动删除
- 避免前端轮询时遇到404错误

### 4. 后台清理线程
- 守护线程（daemon=True）
- 每5秒检查一次
- 清理完成10秒以上的任务
- 应用退出时自动停止

## 数据结构

### 内部字段
- `_tasks`: dict[str, Task] - 任务字典，key为task_id（Python 3.7+ 保持插入顺序）
- `_lock`: ReadWriteLock - 读写锁，多读者并发，写者独占（R22.2 起）
- `_active_task_id`: str | None - 当前活动任务ID
- `_stop_cleanup`: Event - 停止清理线程的事件
- `_cleanup_thread`: Thread - 后台清理线程

### 性能优化说明
- **移除了冗余的 `_task_order` 列表**：Python 3.7+ dict 已保持插入顺序
- **删除操作从 O(n) 优化到 O(1)**：不再需要 list.remove() 操作
- **内存占用减少**：不再维护额外的任务ID列表

## 任务状态管理

```
add_task()       → status = "pending" 或 "active"（如果是第一个）
set_active_task() → status = "active"（旧的变为pending）
complete_task()   → status = "completed"（10秒后删除）
remove_task()     → 直接删除
```

## 线程安全保证（R22.2 重构后）

所有公共方法均通过 ``self._lock`` 保护，但读路径走 ``read_lock()``、
写路径走 ``write_lock()``，读读并发、读写仍互斥、写写仍互斥：

- **写路径**（互斥）：``add_task`` / ``set_active_task`` /
  ``complete_task`` / ``remove_task`` / ``clear_completed_tasks`` /
  ``cleanup_completed_tasks`` / ``clear_all_tasks`` /
  ``update_auto_resubmit_timeout_for_all``
- **读路径**（可并发）：``get_task`` / ``get_all_tasks`` /
  ``get_active_task`` / ``get_task_count`` / ``_persist`` 内部读快照

禁忌：禁止在已持锁的线程中再次获取本锁（``ReadWriteLock`` 不支持
递归 / 升级 / 降级）。当前所有写后副作用（``_persist`` /
``_trigger_status_change``）均在锁外触发，无嵌套风险。

## 性能考虑

- **Lock 类型**：``ReadWriteLock``（读写分离）
  - R22.2 起：读读并发，写者独占；多 client 高频读路径不再互相阻塞
  - 适用场景：读多写少（GET /api/tasks SSE / 倒计时刷新 ≫ add/complete）
  - 注意：写者饥饿风险存在但实测可接受（写频次 ≪ 读频次）

- **内存占用**：O(n)，n为任务数量
  - 每个任务约1KB（取决于prompt和options）
  - 最多max_tasks个任务同时存在
  - 完成的任务会在10秒后清理

- **时间复杂度（优化后）**：
  - add_task: O(1)
  - get_task: O(1)
  - get_all_tasks: O(n)
  - remove_task: O(1)（原来是 O(n)，优化后使用 dict.pop()）
  - complete_task: O(n)（需要查找下一个pending任务）
  - cleanup_completed_tasks: O(n)

## 注意事项

- 必须在应用关闭时调用 `stop_cleanup()` 停止后台线程
- 任务ID必须全局唯一
- 队列满时 add_task 会返回 False
- completed 任务会在10秒后自动删除
- 不要在锁内执行耗时操作

属性:
    max_tasks (int): 最大并发任务数

#### 方法

##### `__init__(self, max_tasks: int = 10, persist_path: str | None = None)`

初始化任务队列

创建任务队列实例并启动后台清理线程。

参数:
    max_tasks (int): 最大并发任务数，默认10
    persist_path (str|None): 持久化文件路径。设置后任务状态变更自动写入磁盘，
        重启时自动恢复未完成任务。传 None 禁用持久化（纯内存模式）。

##### `clear_all_tasks(self) -> int`

清理所有任务（重置队列）

删除所有任务并重置队列状态，用于服务启动时清理残留任务。

##### `add_task(self, task_id: str, prompt: str, predefined_options: list[str] | None = None, auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT, predefined_options_defaults: list[bool] | None = None) -> bool`

添加任务，无活动任务时自动激活

##### `get_task(self, task_id: str) -> Task | None`

获取指定任务

通过任务ID查询任务对象，返回任务的当前状态快照。

**注意**：返回的是任务对象的直接引用（非深拷贝）。调用方在锁外读取
属性时，可能与其他线程对同一 Task 的写操作产生竞态。当前所有调用点
均为只读访问（读 task_id/prompt/status），GIL 保证了单属性读取的安全，
但如需一致的多字段快照，应自行加锁或在锁内完成读取。

参数:
    task_id (str): 任务唯一标识符

返回:
    Task | None: 任务对象，不存在则返回 None
        - Task对象包含所有任务信息
        - None表示任务不存在或已被删除

线程安全:
    查询本身线程安全（使用 Lock 保护），但返回值的后续访问不受锁保护。

时间复杂度:
    O(1) - 字典查询

##### `get_all_tasks(self) -> list[Task]`

获取所有任务列表

##### `update_auto_resubmit_timeout_for_all(self, auto_resubmit_timeout: int) -> int`

更新所有未完成任务的 auto_resubmit_timeout

用于配置热更新场景：当用户在运行中修改 feedback.frontend_countdown
（或旧名称 auto_resubmit_timeout）时，希望**已经在倒计时中的任务**也能立即生效。

更新策略：
- 仅更新 status != "completed" 的任务（pending/active/expired）
- 直接修改任务对象的 auto_resubmit_timeout 字段
- 不修改 created_at/created_at_monotonic（倒计时基准保持任务创建时刻）

注意：
- 如果将超时时间调小到小于已过去时间，任务可能会立刻显示 remaining_time=0
- auto_resubmit_timeout=0 在语义上表示“禁用自动重调”，上层需要配合前端逻辑避免误触发

参数:
    auto_resubmit_timeout: 新的前端倒计时（秒）

返回:
    int: 实际更新的任务数量

##### `get_active_task(self) -> Task | None`

获取当前活动任务

##### `set_active_task(self, task_id: str) -> bool`

手动切换活动任务

##### `complete_task(self, task_id: str, result: dict[str, Any]) -> bool`

完成任务并标记为延迟删除（核心方法）

将任务标记为已完成并保存结果，**不立即删除**。

## 延迟删除机制

**为什么不立即删除？**
- 前端可能正在轮询任务状态
- 立即删除会导致前端收到404错误
- 延迟10秒给前端足够时间获取结果

**删除时机**：
- 后台清理线程每5秒检查一次
- 删除完成10秒以上的任务
- 也可以手动调用 remove_task 立即删除

## 自动激活下一个任务

如果完成的任务是活动任务，会自动激活下一个pending任务：
1. 清空 _active_task_id
2. 遍历任务字典（按插入顺序）
3. 找到第一个 status='pending' 的任务并将其设置为 active

参数:
    task_id (str): 要完成的任务ID
    result (dict[str, Any]): 任务执行结果
        - 通常包含 'feedback', 'selected_options' 等键
        - 格式由调用方决定
        - 示例：{'feedback': '用户输入', 'selected_options': ['选项1']}

返回:
    bool: 是否成功完成
        - True: 成功标记为完成
        - False: 任务不存在

线程安全:
    线程安全（使用 Lock 保护）

副作用:
    - 设置 task.status = 'completed'
    - 设置 task.result
    - 设置 task.completed_at
    - 可能清空 _active_task_id
    - 可能自动激活下一个任务
    - 记录日志

时间复杂度:
    O(n) - 最坏情况下需要遍历任务字典以查找下一个 pending 任务

说明:
    - 任务完成后10秒内仍可查询
    - 前端应在收到完成状态后停止轮询
    - 自动激活逻辑只查找pending状态的任务
    - 如果没有pending任务，_active_task_id 保持为 None

##### `remove_task(self, task_id: str) -> bool`

移除任务（立即删除）

立即从队列中删除指定任务，不等待延迟删除。

**与complete_task的区别**：
- `complete_task`: 标记为完成，10秒后自动删除
- `remove_task`: 立即删除，适用于取消或清理

**自动激活逻辑**：
如果删除的是活动任务，会自动激活下一个pending/active任务

参数:
    task_id (str): 要移除的任务ID

返回:
    bool: 是否成功移除
        - True: 成功移除
        - False: 任务不存在

线程安全:
    线程安全（使用 Lock 保护）

副作用:
    - 从 _tasks 删除任务（Python 3.7+ dict.pop() 是 O(1)）
    - 可能更新 _active_task_id
    - 可能自动激活下一个任务
    - 记录日志

时间复杂度:
    - 若删除的不是活动任务：O(1)（dict.pop()）
    - 若删除的是活动任务：最坏 O(n)（需要遍历查找下一个任务）

说明:
    - 适用于手动取消任务
    - 不推荐用于正常完成的任务（应使用complete_task）
    - 删除后任务立即不可查询

##### `clear_completed_tasks(self) -> int`

清理所有已完成的任务（立即删除）

删除所有 status='completed' 的任务，不管完成时间。

**使用场景**：
- 手动清理所有已完成任务
- 测试时清理环境
- 队列维护操作

**与cleanup_completed_tasks的区别**：
- `clear_completed_tasks`: 清理所有completed任务（不限时间）
- `cleanup_completed_tasks`: 只清理超过指定时间的completed任务

返回:
    int: 清理的任务数量（>=0）

线程安全:
    线程安全（使用 Lock 保护）

副作用:
    - 删除所有completed任务
    - 记录日志（如果有清理）

时间复杂度:
    O(n) - 需要遍历所有任务

说明:
    - 不检查completed_at时间
    - 适用于需要立即清理的场景
    - 后台清理线程使用的是cleanup_completed_tasks

##### `cleanup_completed_tasks(self, age_seconds: int = 10) -> int`

清理超过指定时间的已完成任务（后台清理核心方法）

删除完成时间超过 age_seconds 的任务。

**延迟删除机制的关键方法**：
- 后台清理线程每5秒调用一次
- 默认清理完成10秒以上的任务
- 避免前端轮询时遇到404

**清理逻辑**：
1. 检查任务status='completed'
2. 检查completed_at是否存在
3. 计算任务完成时长
4. 如果超过age_seconds则删除

参数:
    age_seconds (int): 任务完成后保留的秒数
        - 默认值：10秒
        - 建议值：5-30秒
        - 过小：前端可能遇到404
        - 过大：内存占用增加

返回:
    int: 清理的任务数量（>=0）

线程安全:
    线程安全（使用 Lock 保护）

副作用:
    - 删除过期的completed任务
    - 记录日志（如果有清理）

时间复杂度:
    O(n) - 需要遍历所有任务并计算时间差

说明:
    - completed_at为None的任务不会被清理
    - 后台线程默认使用 age_seconds=10
    - 可以手动调用来立即清理

##### `cleanup_completed_tasks_throttled(self, age_seconds: int = 10, throttle_seconds: float = 30.0) -> int`

节流版 cleanup —— 用于 hot path（如 GET /api/tasks）的兜底调用。

与未节流的 ``cleanup_completed_tasks`` 行为一致，但**距离上次执行
不足 ``throttle_seconds`` 时直接返回 0**（不加 ``self._lock``）。

why
---
历史上 ``GET /api/tasks`` 在每次请求都会调用一次未节流 cleanup，配合
前端 2s 轮询 + 后台清理线程的 5s 节奏，导致 cleanup 调用频率被 hot
path 放大到后台节奏的 ~5-10x。每次 cleanup 都要：

1. ``acquire(self._lock)`` — 与 ``add_task`` / ``complete_task`` /
   ``get_all_tasks`` 共用同一把粗粒度锁，hot-path 命中会增加 lock
   contention（虽然单次 critical section ~5µs，但乘以高频后非零）；
2. ``datetime.now(UTC)`` — Python 层的 syscall + tz 处理；
3. 遍历 ``self._tasks`` (O(n))，即使没有任何任务到期。

本方法把 hot-path 的真实 cleanup 频率封顶到 ``1 / throttle_seconds``，
与后台 5s 主节奏正交叠加，cleanup 总频率从 ``polls/s + 1/5`` 降为
``1/30 + 1/5 ≈ 0.23/s``，且 99% 的请求在快路径（非锁的原子读写
+ 一次时间戳比较）上完成。

参数
----
age_seconds : int, default 10
    任务完成后保留的秒数，与未节流版本一致。
throttle_seconds : float, default 30.0
    节流窗口长度。设为 0 时退化为未节流行为（不推荐，仅用于测试）。

返回
----
int
    清理的任务数量；节流命中或队列空时返回 0。

线程安全
--------
``self._hotpath_cleanup_lock`` 仅保护 ``_last_hotpath_cleanup_monotonic``
的读写，**不**与 ``self._lock`` 嵌套（cleanup 真正执行时先释放
``_hotpath_cleanup_lock`` 再调用未节流版本）。所以本方法对常规
``add_task`` / ``complete_task`` 路径零阻塞影响。

副作用
------
- 节流未触发时：可能删除过期 completed 任务（同 cleanup_completed_tasks）。
- 节流触发时：仅一次 ``time.monotonic()`` 调用。

时间复杂度
----------
- 节流触发（fast path）：O(1)
- 节流未触发：O(n)，n = len(self._tasks)

历史背景
--------
本节流策略由 R20.5 引入；触发原因是审计 v1.5.25 后的 hot path 时
发现 ``GET /api/tasks`` 在多 client 并发场景下的冗余 cleanup 调用。

##### `stop_cleanup(self) -> None`

停止后台清理线程

优雅地停止后台清理线程，应在应用关闭时调用。

**停止流程**：
1. 设置停止事件 (_stop_cleanup.set())
2. 等待线程结束（最多2秒）
3. 检查线程是否成功停止
4. 记录停止状态

**超时处理**：
- 如果2秒内未停止，记录警告日志
- 线程可能仍在运行（极少见）
- 由于是守护线程，应用退出时会强制停止

线程安全:
    线程安全（使用Event同步）

副作用:
    - 设置停止事件
    - 阻塞最多2秒等待线程
    - 记录日志

说明:
    - 必须在应用关闭时调用
    - 不调用可能导致日志未正确flush
    - 守护线程会在主线程退出时强制停止
    - 多次调用是安全的（幂等操作）

##### `get_task_count(self) -> dict[str, int]`

获取任务统计信息

返回各状态任务的数量统计。

**统计字段**：
- `total`: 总任务数（所有状态）
- `pending`: 等待处理的任务数
- `active`: 活动任务数（应该是0或1）
- `completed`: 已完成但未删除的任务数
- `max`: 队列最大容量

**使用场景**：
- 监控队列状态
- 检查队列是否已满
- 统计任务处理进度
- 调试和日志

返回:
    dict[str, int]: 任务统计字典
        键值对：
        - 'total': int - 总任务数
        - 'pending': int - 等待任务数
        - 'active': int - 活动任务数（0或1）
        - 'completed': int - 已完成任务数
        - 'max': int - 最大容量

线程安全:
    线程安全（使用 Lock 保护）

时间复杂度:
    O(n) - 需要遍历所有任务计数

说明:
    - 返回的是新字典，可以安全修改
    - active数量应该是0或1（单活动任务模式）
    - total = pending + active + completed
    - completed任务会在10秒后被清理

##### `register_status_change_callback(self, callback: Callable[[str, str | None, str], None]) -> None`

注册任务状态变更回调函数

【功能说明】
当任务状态发生变化时（添加、激活、完成、删除），会调用所有注册的回调函数。

【参数】
callback : callable
    回调函数，接受三个参数：
    - task_id: str - 任务ID
    - old_status: str - 旧状态（添加任务时为 None）
    - new_status: str - 新状态（删除任务时为 "removed"）

    函数签名: def callback(task_id: str, old_status: str, new_status: str) -> None

【使用场景】
- 前端实时更新任务列表
- 日志记录任务状态变化
- 触发相关业务逻辑

【示例】
>>> def on_status_change(task_id, old_status, new_status):
...     print(f"任务 {task_id}: {old_status} -> {new_status}")
>>> queue.register_status_change_callback(on_status_change)

##### `unregister_status_change_callback(self, callback: Callable[[str, str | None, str], None]) -> None`

取消注册任务状态变更回调函数

【参数】
callback : callable
    要取消的回调函数
