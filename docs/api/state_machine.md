# state_machine

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/state_machine.md`](../api.zh-CN/state_machine.md)

## Functions

### `list_all_states() -> dict[str, tuple[str, ...]]`

### `list_transitions() -> dict[str, dict[str, tuple[str, ...]]]`

### `flatten_targets(kind: str) -> set[str]`

### `validate_transition_table() -> None`

### `_iter_all_states() -> Iterable[tuple[str, str]]`

## Classes

### `class ConnectionStatus`

### `class ContentStatus`

### `class InteractionPhase`

### `class InvalidTransition`

### `class StateMachine`

#### Methods

##### `__init__(self, kind: str) -> None`

##### `kind(self) -> str`

##### `status(self) -> str`

##### `transition(self, target: str) -> None`

##### `on_change(self, cb: Callable[[str, str], Any]) -> Callable[[], None]`

##### `reset(self, to: str) -> None`
