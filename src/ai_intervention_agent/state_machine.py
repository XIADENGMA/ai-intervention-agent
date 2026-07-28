"""统一状态机常量与迁移规则（前后端契约的 Python 源头）。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


class ConnectionStatus:
    """连接状态机（SSE / WebSocket / 轮询 fallback）。"""

    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RETRYING = "retrying"
    CLOSED = "closed"

    ALL: tuple[str, ...] = (IDLE, CONNECTING, CONNECTED, DISCONNECTED, RETRYING, CLOSED)


class ContentStatus:
    """内容渲染状态机（首屏骨架 → 加载 → 就绪 / 错误）。"""

    SKELETON = "skeleton"
    LOADING = "loading"
    READY = "ready"
    EMPTY = "empty"
    ERROR = "error"

    ALL: tuple[str, ...] = (SKELETON, LOADING, READY, EMPTY, ERROR)


class InteractionPhase:
    """用户交互阶段（浏览 / 编辑 / 提交 / 冷却）。"""

    VIEWING = "viewing"
    COMPOSING = "composing"
    SUBMITTING = "submitting"
    COOLDOWN = "cooldown"

    ALL: tuple[str, ...] = (VIEWING, COMPOSING, SUBMITTING, COOLDOWN)


TRANSITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "connection": {
        ConnectionStatus.IDLE: (ConnectionStatus.CONNECTING, ConnectionStatus.CLOSED),
        ConnectionStatus.CONNECTING: (
            ConnectionStatus.CONNECTED,
            ConnectionStatus.DISCONNECTED,
            ConnectionStatus.CLOSED,
        ),
        ConnectionStatus.CONNECTED: (
            ConnectionStatus.DISCONNECTED,
            ConnectionStatus.CLOSED,
        ),
        ConnectionStatus.DISCONNECTED: (
            ConnectionStatus.RETRYING,
            ConnectionStatus.CLOSED,
        ),
        ConnectionStatus.RETRYING: (
            ConnectionStatus.CONNECTING,
            ConnectionStatus.CLOSED,
        ),
        ConnectionStatus.CLOSED: (ConnectionStatus.IDLE,),
    },
    "content": {
        ContentStatus.SKELETON: (ContentStatus.LOADING, ContentStatus.READY),
        ContentStatus.LOADING: (
            ContentStatus.READY,
            ContentStatus.EMPTY,
            ContentStatus.ERROR,
        ),
        ContentStatus.READY: (
            ContentStatus.LOADING,
            ContentStatus.EMPTY,
            ContentStatus.ERROR,
        ),
        ContentStatus.EMPTY: (ContentStatus.LOADING, ContentStatus.READY),
        ContentStatus.ERROR: (ContentStatus.LOADING, ContentStatus.SKELETON),
    },
    "interaction": {
        InteractionPhase.VIEWING: (InteractionPhase.COMPOSING,),
        InteractionPhase.COMPOSING: (
            InteractionPhase.VIEWING,
            InteractionPhase.SUBMITTING,
        ),
        InteractionPhase.SUBMITTING: (
            InteractionPhase.COOLDOWN,
            InteractionPhase.COMPOSING,
        ),
        InteractionPhase.COOLDOWN: (
            InteractionPhase.VIEWING,
            InteractionPhase.COMPOSING,
        ),
    },
}


class InvalidTransition(ValueError):
    """状态机检测到非法迁移时抛出。"""


class StateMachine:
    """最小可用状态机：校验迁移合法性 + 订阅变化。"""

    def __init__(self, kind: str, *, initial: str) -> None:
        if kind not in TRANSITIONS:
            raise ValueError(f"未知状态机种类: {kind!r}")
        if initial not in TRANSITIONS[kind]:
            raise ValueError(f"{kind} 初始态 {initial!r} 不在合法态列表中")
        self._kind = kind
        self._status = initial
        self._listeners: list[Callable[[str, str], Any]] = []

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def status(self) -> str:
        return self._status

    def transition(self, target: str) -> None:
        """尝试迁移到 ``target``；非法则抛 ``InvalidTransition``。"""
        if target == self._status:
            return
        allowed = TRANSITIONS[self._kind].get(self._status, ())
        if target not in allowed:
            raise InvalidTransition(
                f"{self._kind}: {self._status!r} -> {target!r} 不合法，"
                f"允许迁移: {list(allowed)}"
            )
        previous = self._status
        self._status = target
        for cb in list(self._listeners):
            try:
                cb(previous, target)
            except Exception:
                pass

    def on_change(self, cb: Callable[[str, str], Any]) -> Callable[[], None]:
        """订阅变化；返回 unsubscribe 闭包。"""
        self._listeners.append(cb)

        def _unsubscribe() -> None:
            try:
                self._listeners.remove(cb)
            except ValueError:
                pass

        return _unsubscribe

    def reset(self, to: str) -> None:
        """跳过合法性校验直接复位到 ``to``（例如测试夹具 / 异常恢复用）。"""
        if to not in TRANSITIONS[self._kind]:
            raise ValueError(f"{self._kind} 复位目标 {to!r} 不在合法态列表")
        self._status = to


def list_all_states() -> dict[str, tuple[str, ...]]:
    """返回每个状态机的全部合法状态。"""
    return {
        "connection": ConnectionStatus.ALL,
        "content": ContentStatus.ALL,
        "interaction": InteractionPhase.ALL,
    }


def list_transitions() -> dict[str, dict[str, tuple[str, ...]]]:
    """返回完整迁移表（浅拷贝）。"""
    return {kind: rules.copy() for kind, rules in TRANSITIONS.items()}


def flatten_targets(kind: str) -> set[str]:
    """返回某个状态机所有作为 target 出现过的状态名，用于校验『无孤岛』。"""
    if kind not in TRANSITIONS:
        raise ValueError(kind)
    result: set[str] = set()
    for targets in TRANSITIONS[kind].values():
        result.update(targets)
    return result


def validate_transition_table() -> None:
    """自检：每个 target 必须是该种状态机的合法状态。"""
    all_states = list_all_states()
    for kind, rules in TRANSITIONS.items():
        legal = set(all_states[kind])
        for src, targets in rules.items():
            if src not in legal:
                raise RuntimeError(f"{kind}: 起始态 {src!r} 不在合法列表 {legal}")
            for t in targets:
                if t not in legal:
                    raise RuntimeError(
                        f"{kind}: {src!r} 的迁移目标 {t!r} 不在合法列表 {legal}"
                    )


validate_transition_table()


__all__ = [
    "TRANSITIONS",
    "ConnectionStatus",
    "ContentStatus",
    "InteractionPhase",
    "InvalidTransition",
    "StateMachine",
    "flatten_targets",
    "list_all_states",
    "list_transitions",
    "validate_transition_table",
]


def _iter_all_states() -> Iterable[tuple[str, str]]:
    """调试用：遍历所有 (kind, state) 组合。"""
    for kind, states in list_all_states().items():
        for s in states:
            yield kind, s
