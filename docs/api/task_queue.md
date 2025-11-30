# task_queue

任务队列管理模块

提供线程安全的任务队列管理功能，支持多任务并发处理、状态管理、自动清理等核心功能。

## 核心功能

1. **任务管理**
   - 添加/查询/删除任务
   - 任务状态管理（pending/active/completed/expired）
   - 活动任务切换
   - 最大并发数限制

2. **线程安全**
   - 使用 threading.Lock 保护共享数据
   - 所有公共方法都是线程安全的
   - 支持多线程并发访问

3. **自动清理**
   - 后台清理线程定期清理过期任务
   - 延迟删除机制（避免前端轮询404）
   - 可配置的清理间隔和保留时间

4. **状态管理**
   - pending: 等待处理的任务
   - active: 当前正在处理的任务（同时只有一个）
   - completed: 已完成的任务（延迟10秒删除）
   - expired: 已过期的任务

## 使用场景

- Web应用的异步任务队列
- 用户交互反馈收集
- AI对话会话管理
- 多任务并发处理

## 设计考虑

### 为什么延迟删除？
当任务完成时，前端可能正在轮询任务状态。如果立即删除任务，
前端会收到404错误，导致不必要的错误处理。通过延迟10秒删除，
前端有足够时间获取任务结果并停止轮询。

### 为什么后台清理线程？
使用独立的守护线程定期清理过期任务，避免任务堆积和内存泄漏，
同时不影响主线程的性能。

### 线程安全策略
所有修改共享数据的操作都使用 with self._lock 保护，
确保并发访问时的数据一致性。

## 注意事项

- 任务ID必须唯一
- 同一时间只有一个活动任务
- 完成的任务会在10秒后自动删除
- 队列满时无法添加新任务
- 所有方法都是线程安全的

## 性能特性

- Lock 粒度：方法级别（较粗粒度，但简单可靠）
- 后台清理：每5秒一次，清理10秒前完成的任务
- 内存占用：每个任务约1KB（取决于prompt和options大小）
- 并发性能：适合中低并发场景（<100 QPS）
- **数据结构优化**：Python 3.7+ dict 保持插入顺序，删除操作 O(1)

## 依赖项

- Python 3.7+
- threading (标准库)
- dataclasses (标准库)
- datetime (标准库)

## 类

### `class Task`

任务数据结构

不可变的任务数据容器，使用dataclass自动生成__init__、__repr__等方法。

## 状态转换流程

```
pending (等待) → active (激活) → completed (完成) → [延迟10秒删除]
                  ↓
               expired (过期，未使用)
```

## 字段说明

### 必填字段
- `task_id`: 任务唯一标识符（建议使用UUID或时间戳）
- `prompt`: 任务提示信息（显示给用户的问题或说明）

### 可选字段
- `predefined_options`: 预定义选项列表（如["同意", "拒绝"]）
- `auto_resubmit_timeout`: 自动重新提交超时（240-290秒）
- `created_at`: 任务创建时间（自动生成）
- `status`: 任务状态（自动管理）
- `result`: 任务执行结果（完成时设置）
- `completed_at`: 任务完成时间（用于延迟删除判断）

## 超时配置说明

`auto_resubmit_timeout` 字段控制前端倒计时：
- 默认值：240秒（4分钟）
- 最大值：290秒（强制限制）
- 用途：前端自动重新提交前的等待时间
- 注意：后端超时应大于此值（后端=max(前端+60, 300)秒）

## 注意事项

- task_id 必须全局唯一
- 一旦创建，task_id 和 prompt 不应修改
- status 和 completed_at 由 TaskQueue 自动管理
- auto_resubmit_timeout 会被自动限制在290秒以内
- dataclass 不保证线程安全，需要外部同步

Attributes:
    task_id (str): 任务唯一标识符，建议使用UUID
    prompt (str): 任务提示信息，显示给用户的问题
    predefined_options (Optional[List[str]]): 预定义选项列表，None表示无选项
    auto_resubmit_timeout (int): 自动重新提交超时时间（秒），默认240，最大290
    created_at (datetime): 任务创建时间，自动生成
    status (str): 任务状态，可选值：pending/active/completed/expired
    result (Optional[Dict[str, str]]): 任务执行结果，完成时由complete_task设置
    completed_at (Optional[datetime]): 任务完成时间，用于延迟删除判断

#### 方法

##### `get_remaining_time(self) -> int`

计算剩余倒计时时间（秒）

基于任务创建时间和配置的超时时间，计算当前剩余的倒计时秒数。
用于服务器端跟踪倒计时状态，解决页面刷新后倒计时重置的问题。

**计算公式**：
    elapsed = now - created_at
    remaining = auto_resubmit_timeout - elapsed

**返回值范围**：
    - 最大值：auto_resubmit_timeout（刚创建时）
    - 最小值：0（倒计时结束或已超时）

Returns:
    int: 剩余秒数，范围 [0, auto_resubmit_timeout]

Note:
    - 已完成的任务返回 0
    - 负数会被截断为 0
    - 使用 UTC 时间，支持跨时区部署

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
- `_tasks`: Dict[str, Task] - 任务字典，key为task_id（Python 3.7+ 保持插入顺序）
- `_lock`: Lock - 线程锁，保护共享数据
- `_active_task_id`: Optional[str] - 当前活动任务ID
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

## 线程安全保证

所有以下方法都使用 `with self._lock:` 保护：
- add_task, get_task, get_all_tasks
- set_active_task, get_active_task
- complete_task, remove_task
- clear_completed_tasks, cleanup_completed_tasks
- get_task_count, clear_all_tasks

## 性能考虑

- **Lock粒度**：方法级别（粗粒度）
  - 优点：实现简单，不易出错
  - 缺点：高并发时可能成为瓶颈
  - 适用场景：中低并发（<100 QPS）

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

Attributes:
    max_tasks (int): 最大并发任务数

#### 方法

##### `__init__(self, max_tasks: int = 10)`

初始化任务队列

创建任务队列实例并启动后台清理线程。

Args:
    max_tasks (int): 最大并发任务数，默认10
        - 建议值：5-20（根据实际需求）
        - 过大：内存占用增加
        - 过小：容易达到上限

Raises:
    无：所有异常都会被捕获并记录日志

Side Effects:
    - 启动守护线程 TaskQueueCleanup
    - 记录初始化日志

Thread Safety:
    线程安全（使用 Lock 保护共享数据）

##### `clear_all_tasks(self)`

清理所有任务（重置队列）

删除所有任务并重置队列状态，用于服务启动时清理残留任务。

**使用场景**：
- 服务启动时清理上次运行的残留任务
- 测试时重置队列状态
- 发生异常需要重置时

**操作内容**：
- 清空任务字典 (_tasks)
- 重置活动任务ID (_active_task_id)
- 记录清理日志

Returns:
    int: 清理的任务数量（包括pending/active/completed所有状态）

Thread Safety:
    线程安全（使用 Lock 保护）

Side Effects:
    - 清空所有内部数据结构
    - 记录日志
    - 所有任务引用将失效

Note:
    - 此方法会立即删除所有任务，包括completed状态的任务
    - 不会等待后台清理线程的延迟删除机制
    - 调用后队列恢复到初始状态

##### `add_task(self, task_id: str, prompt: str, predefined_options: Optional[List[str]] = None, auto_resubmit_timeout: int = 240) -> bool`

添加新任务到队列

创建新任务并添加到队列中。如果当前没有活动任务，新任务自动成为活动任务。

**状态设置逻辑**：
- 如果是第一个任务（无活动任务）→ 状态为 `active`
- 如果已有活动任务 → 状态为 `pending`

**失败条件**：
1. 队列已满（达到 max_tasks 限制）
2. task_id 已存在（重复添加）

**超时限制**：
- auto_resubmit_timeout 会被自动限制在290秒以内
- 这是前端倒计时的最大值
- 后端超时应该更长（见 server.py 中的计算逻辑）

Args:
    task_id (str): 任务唯一标识符
        - 必须全局唯一
        - 建议使用UUID或时间戳
        - 示例：f"task-{uuid.uuid4()}"
    prompt (str): 任务提示信息
        - 显示给用户的问题或说明
        - 不应包含HTML标签（前端会转义）
    predefined_options (Optional[List[str]]): 预定义选项列表
        - None表示无选项（纯文本输入）
        - 空列表也表示无选项
        - 示例：["同意", "拒绝", "需要更多信息"]
    auto_resubmit_timeout (int): 自动重新提交超时（秒）
        - 默认值：240秒（4分钟）
        - 最大值：290秒（自动限制）
        - 前端倒计时时间

Returns:
    bool: 添加是否成功
        - True: 成功添加
        - False: 失败（队列满或ID重复）

Thread Safety:
    线程安全（使用 Lock 保护）

Side Effects:
    - 添加任务到 _tasks（Python 3.7+ 保持插入顺序）
    - 可能设置 _active_task_id（如果是第一个任务）
    - 记录日志

Note:
    - 不验证 prompt 和 predefined_options 的内容
    - 超时值会被自动调整，无需手动限制
    - 任务添加后立即可查询
    - 建议在添加前检查队列是否已满（get_task_count）

##### `get_task(self, task_id: str) -> Optional[Task]`

获取指定任务

通过任务ID查询任务对象，返回任务的当前状态快照。

**注意**：返回的是任务对象引用，修改其属性可能影响队列状态
（虽然不推荐直接修改，应使用提供的方法）

Args:
    task_id (str): 任务唯一标识符

Returns:
    Optional[Task]: 任务对象，不存在则返回 None
        - Task对象包含所有任务信息
        - None表示任务不存在或已被删除

Thread Safety:
    线程安全（使用 Lock 保护）

Time Complexity:
    O(1) - 字典查询

##### `get_all_tasks(self) -> List[Task]`

获取所有任务（按添加顺序）

返回队列中所有任务的列表，按照添加顺序排列。

**包含的状态**：
- pending: 等待处理的任务
- active: 当前活动任务
- completed: 已完成但未删除的任务（10秒内）

**排序规则**：
- 按照 add_task 的调用顺序
- 不是按状态或创建时间排序

Returns:
    List[Task]: 任务对象列表（可能为空）
        - 按添加顺序排列
        - 不包含已删除的任务
        - 返回的是新列表，修改不影响队列

Thread Safety:
    线程安全（使用 Lock 保护）

Time Complexity:
    O(n) - 需要遍历 _tasks 并构建列表

Note:
    - 返回的列表是新创建的，可以安全修改
    - 但修改列表中的Task对象会影响队列状态
    - 如果需要只读视图，考虑使用dataclass的replace()

##### `get_active_task(self) -> Optional[Task]`

获取当前活动任务

返回当前正在处理的活动任务（status='active'）。

**活动任务规则**：
- 同一时间只有一个活动任务
- 第一个添加的任务自动成为活动任务
- 活动任务完成后，自动激活下一个pending任务
- 可通过 set_active_task 手动切换

Returns:
    Optional[Task]: 活动任务对象，不存在则返回 None
        - Task对象（status='active'）
        - None表示队列为空或所有任务都已完成

Thread Safety:
    线程安全（使用 Lock 保护）

Time Complexity:
    O(1) - 直接通过 _active_task_id 查询

Note:
    - 返回的Task对象与get_task返回的是同一个对象
    - 通常用于前端轮询当前需要处理的任务
    - 活动任务完成后会自动切换到下一个

##### `set_active_task(self, task_id: str) -> bool`

设置活动任务（手动切换）

将指定任务设置为活动任务，原活动任务变为pending状态。

**状态变化**：
- 原活动任务: `active` → `pending`
- 新活动任务: `pending` → `active`

**使用场景**：
- 用户手动切换到另一个任务
- 前端任务列表点击切换
- 优先处理某个任务

**失败条件**：
- 指定的task_id不存在

Args:
    task_id (str): 要激活的任务ID
        - 必须是已存在的任务
        - 可以是任何状态的任务（通常是pending）

Returns:
    bool: 是否成功切换
        - True: 成功切换
        - False: 任务不存在

Thread Safety:
    线程安全（使用 Lock 保护）

Side Effects:
    - 更新 _active_task_id
    - 修改旧任务和新任务的status
    - 记录切换日志

Note:
    - 可以将completed状态的任务重新激活（不推荐）
    - 旧活动任务只有在status='active'时才会变为pending
    - 不会影响任务在 _task_order 中的顺序

##### `complete_task(self, task_id: str, result: Dict[str, str]) -> bool`

完成任务并标记为延迟删除 ⭐核心方法

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
2. 遍历 _task_order
3. 找到第一个 status='pending' 的任务
4. 将其设置为 active

Args:
    task_id (str): 要完成的任务ID
    result (Dict[str, str]): 任务执行结果
        - 通常包含 'feedback', 'selected_options' 等键
        - 格式由调用方决定
        - 示例：{'feedback': '用户输入', 'selected_options': ['选项1']}

Returns:
    bool: 是否成功完成
        - True: 成功标记为完成
        - False: 任务不存在

Thread Safety:
    线程安全（使用 Lock 保护）

Side Effects:
    - 设置 task.status = 'completed'
    - 设置 task.result
    - 设置 task.completed_at
    - 可能清空 _active_task_id
    - 可能自动激活下一个任务
    - 记录日志

Time Complexity:
    O(n) - 需要遍历 _task_order 查找下一个pending任务

Note:
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

Args:
    task_id (str): 要移除的任务ID

Returns:
    bool: 是否成功移除
        - True: 成功移除
        - False: 任务不存在

Thread Safety:
    线程安全（使用 Lock 保护）

Side Effects:
    - 从 _tasks 删除任务（Python 3.7+ dict.pop() 是 O(1)）
    - 可能更新 _active_task_id
    - 可能自动激活下一个任务
    - 记录日志

Time Complexity:
    O(1) - 【性能优化】使用 dict.pop() 代替 list.remove()

Note:
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

Returns:
    int: 清理的任务数量（>=0）

Thread Safety:
    线程安全（使用 Lock 保护）

Side Effects:
    - 删除所有completed任务
    - 记录日志（如果有清理）

Time Complexity:
    O(n) - 需要遍历所有任务

Note:
    - 不检查completed_at时间
    - 适用于需要立即清理的场景
    - 后台清理线程使用的是cleanup_completed_tasks

##### `cleanup_completed_tasks(self, age_seconds: int = 10) -> int`

清理超过指定时间的已完成任务 ⭐后台清理核心方法

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

Args:
    age_seconds (int): 任务完成后保留的秒数
        - 默认值：10秒
        - 建议值：5-30秒
        - 过小：前端可能遇到404
        - 过大：内存占用增加

Returns:
    int: 清理的任务数量（>=0）

Thread Safety:
    线程安全（使用 Lock 保护）

Side Effects:
    - 删除过期的completed任务
    - 记录日志（如果有清理）

Time Complexity:
    O(n) - 需要遍历所有任务并计算时间差

Note:
    - completed_at为None的任务不会被清理
    - 后台线程默认使用 age_seconds=10
    - 可以手动调用来立即清理

##### `stop_cleanup(self)`

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

Thread Safety:
    线程安全（使用Event同步）

Side Effects:
    - 设置停止事件
    - 阻塞最多2秒等待线程
    - 记录日志

Note:
    - 必须在应用关闭时调用
    - 不调用可能导致日志未正确flush
    - 守护线程会在主线程退出时强制停止
    - 多次调用是安全的（幂等操作）

##### `get_task_count(self) -> Dict[str, int]`

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

Returns:
    Dict[str, int]: 任务统计字典
        键值对：
        - 'total': int - 总任务数
        - 'pending': int - 等待任务数
        - 'active': int - 活动任务数（0或1）
        - 'completed': int - 已完成任务数
        - 'max': int - 最大容量

Thread Safety:
    线程安全（使用 Lock 保护）

Time Complexity:
    O(n) - 需要遍历所有任务计数

Note:
    - 返回的是新字典，可以安全修改
    - active数量应该是0或1（单活动任务模式）
    - total = pending + active + completed
    - completed任务会在10秒后被清理

##### `register_status_change_callback(self, callback: callable)`

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

##### `unregister_status_change_callback(self, callback: callable)`

取消注册任务状态变更回调函数

【参数】
callback : callable
    要取消的回调函数
