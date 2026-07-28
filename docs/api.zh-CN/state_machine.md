# state_machine

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/state_machine.md`](../api/state_machine.md)

统一状态机常量与迁移规则（前后端契约的 Python 源头）。

## 函数

### `list_all_states() -> dict[str, tuple[str, ...]]`

返回每个状态机的全部合法状态。

### `list_transitions() -> dict[str, dict[str, tuple[str, ...]]]`

返回完整迁移表（浅拷贝）。

### `flatten_targets(kind: str) -> set[str]`

返回某个状态机所有作为 target 出现过的状态名，用于校验『无孤岛』。

### `validate_transition_table() -> None`

自检：每个 target 必须是该种状态机的合法状态。

### `_iter_all_states() -> Iterable[tuple[str, str]]`

调试用：遍历所有 (kind, state) 组合。

## 类

### `class ConnectionStatus`

连接状态机（SSE / WebSocket / 轮询 fallback）。

### `class ContentStatus`

内容渲染状态机（首屏骨架 → 加载 → 就绪 / 错误）。

### `class InteractionPhase`

用户交互阶段（浏览 / 编辑 / 提交 / 冷却）。

### `class InvalidTransition`

状态机检测到非法迁移时抛出。

### `class StateMachine`

最小可用状态机：校验迁移合法性 + 订阅变化。

#### 方法

##### `__init__(self, kind: str) -> None`

##### `kind(self) -> str`

##### `status(self) -> str`

##### `transition(self, target: str) -> None`

尝试迁移到 ``target``；非法则抛 ``InvalidTransition``。

##### `on_change(self, cb: Callable[[str, str], Any]) -> Callable[[], None]`

订阅变化；返回 unsubscribe 闭包。

##### `reset(self, to: str) -> None`

跳过合法性校验直接复位到 ``to``（例如测试夹具 / 异常恢复用）。
