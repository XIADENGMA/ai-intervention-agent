# state_machine

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/state_machine.md`](../api/state_machine.md)

统一状态机常量与迁移规则（前后端契约的 Python 源头）。

为什么要集中定义？
------------------
在实现过程中，多个模块（webview-ui.js、multi_task.js、extension.ts）各自
维护了布尔标记 ``_sseConnected`` / ``_connecting``，带来三个问题：

1. **命名发散**：同一个概念在不同文件叫不同的名字，搜索和审查成本高。
2. **状态缺失**：布尔只能表达两种状态，""retrying"" / ""cooldown"" 之类
   的中间状态只能靠多个标记位组合出来，组合爆炸后必现矛盾态。
3. **迁移无约束**：任何代码都可以任意翻转布尔，没有集中校验非法迁移。

本模块提供单一事实源：

- ``ConnectionStatus``：连接状态（SSE / WebSocket / 轮询 fallback）
- ``ContentStatus``：内容区渲染状态（首屏 / 加载 / 就绪 / 错误）
- ``InteractionPhase``：用户交互阶段（浏览 / 编辑 / 提交 / 冷却）
- ``TRANSITIONS``：每个状态机的合法迁移表
- ``StateMachine``：一个最小可用的状态机实现（校验 + 事件回调）

前端 ``static/js/state.js`` 与 ``packages/vscode/webview-state.js`` 保持
**相同常量名与字符串值**；``tests/test_state_machine.py`` 会正则抓取 JS
文件进行对比回归，任何一侧漏同步都会失败。

## 函数

### `list_all_states() -> dict[str, tuple[str, ...]]`

返回每个状态机的全部合法状态。

用于 JS 常量同步回归测试：Python 侧列表 == JS 文件正则抓取结果。

### `list_transitions() -> dict[str, dict[str, tuple[str, ...]]]`

返回完整迁移表（浅拷贝）。

### `flatten_targets(kind: str) -> set[str]`

返回某个状态机所有作为 target 出现过的状态名，用于校验『无孤岛』。

### `validate_transition_table() -> None`

自检：每个 target 必须是该种状态机的合法状态。

在模块导入时调用一次，类似 ""assertions at load time""；失败说明
上面表写错了，需要本地修复后再发版。

### `_iter_all_states() -> Iterable[tuple[str, str]]`

调试用：遍历所有 (kind, state) 组合。

## 类

### `class ConnectionStatus`

连接状态机（SSE / WebSocket / 轮询 fallback）。

典型迁移序列::

    IDLE -> CONNECTING -> CONNECTED          (首次连接成功)
    CONNECTED -> DISCONNECTED -> RETRYING    (网络抖动)
    RETRYING -> CONNECTING -> CONNECTED      (自动重连成功)
    ANY -> CLOSED                            (用户主动关闭)

前端应把 ``_sseConnected = true/false`` 重构为 status == CONNECTED。

### `class ContentStatus`

内容渲染状态机（首屏骨架 → 加载 → 就绪 / 错误）。

``SKELETON`` 是 BM-7 骨架屏的初始态，首帧渲染前即就位；``LOADING`` 表示
异步 fetch 在途；``READY`` 是内容可交互。``ERROR`` 捕获渲染失败（降级
到骨架或错误提示页）。

### `class InteractionPhase`

用户交互阶段（浏览 / 编辑 / 提交 / 冷却）。

``SUBMITTING`` → ``COOLDOWN`` 是后端 auto-resubmit 超时保护区间，该期
间再次提交应被降速或禁用，避免重复生成任务。

### `class InvalidTransition`

状态机检测到非法迁移时抛出。

### `class StateMachine`

最小可用状态机：校验迁移合法性 + 订阅变化。

设计目标是让 Python 单元测试可以复用同一套迁移规则去验证 JS 端：
``TRANSITIONS`` 是常量表，JS 端也按相同表手写一份；
``tests/test_state_machine.py`` 通过正则抓取 JS 文件做一致性回归。

用法示例::

    conn = StateMachine("connection", initial=ConnectionStatus.IDLE)
    conn.on_change(lambda s: log.info("conn -> %s", s))
    conn.transition(ConnectionStatus.CONNECTING)
    conn.transition(ConnectionStatus.CONNECTED)

#### 方法

##### `__init__(self, kind: str) -> None`

##### `kind(self) -> str`

##### `status(self) -> str`

##### `transition(self, target: str) -> None`

尝试迁移到 ``target``；非法则抛 ``InvalidTransition``。

与 JS 侧约定：target 必须出现在 ``TRANSITIONS[kind][current]`` 中，
``current == target`` 时视为 no-op 不触发 listener。

##### `on_change(self, cb: Callable[[str, str], Any]) -> Callable[[], None]`

订阅变化；返回 unsubscribe 闭包。

##### `reset(self, to: str) -> None`

跳过合法性校验直接复位到 ``to``（例如测试夹具 / 异常恢复用）。
