"""通知领域模型：枚举与事件结构（避免 manager/provider 循环依赖）。"""

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationType(Enum):
    """通知类型枚举：WEB(浏览器)、SOUND(声音)、BARK(iOS推送)、SYSTEM(系统)"""

    WEB = "web"
    SOUND = "sound"
    BARK = "bark"
    SYSTEM = "system"


class NotificationTrigger(Enum):
    """通知触发时机：立即/延迟/重复/反馈收到/错误"""

    IMMEDIATE = "immediate"
    DELAYED = "delayed"
    REPEAT = "repeat"
    FEEDBACK_RECEIVED = "feedback_received"
    ERROR = "error"


class NotificationPriority(Enum):
    """通知优先级：用于路由/降级/节流（阶段 A 先完成数据结构与可观测性）。"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationEvent(BaseModel):
    """通知事件 - 封装一次通知的标题/消息/类型/触发时机/重试信息。"""

    model_config = ConfigDict(validate_assignment=True)

    id: str
    title: str
    message: str
    trigger: NotificationTrigger
    types: list[NotificationType] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

    @field_validator("metadata", mode="before")
    @classmethod
    def coerce_none_metadata(cls, v: Any) -> dict[str, Any]:
        if v is None:
            return {}
        return v

    retry_count: int = 0
    max_retries: int = 3
    priority: NotificationPriority = NotificationPriority.NORMAL
    source: str | None = None
    dedupe_key: str | None = None

    # R396 (cycle-45 #A1): Pydantic field validator coverage 4th 应用
    # 锁 retry_count / max_retries 必须非负且有合理上限, 防 silent bug:
    # - retry_count < 0 → ``while event.retry_count < event.max_retries``
    #   死循环 (条件永远 true);
    # - max_retries 极大 (e.g., 99999) → notification spam 9 分钟 +
    #   retry queue 阻塞其他 event;
    # 实际 codebase 通过 NotificationManager 兜底 (event.max_retries =
    # config.retry_count, config 端有 clamp), 但直接构造 NotificationEvent
    # 或从持久化反序列化时绕过 manager, 此处显式 model-layer clamp 是
    # 最后一道防线。
    @field_validator("retry_count", mode="before")
    @classmethod
    def _clamp_retry_count(cls, v: Any) -> int:
        try:
            n = int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0
        return max(0, min(n, 100))

    @field_validator("max_retries", mode="before")
    @classmethod
    def _clamp_max_retries(cls, v: Any) -> int:
        try:
            n = int(v) if v is not None else 3
        except (TypeError, ValueError):
            return 3
        return max(0, min(n, 100))
