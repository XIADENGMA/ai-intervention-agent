#!/usr/bin/env python3
"""通知领域模型：枚举与事件结构（避免 manager/provider 循环依赖）。"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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


@dataclass
class NotificationEvent:
    """通知事件 - 封装一次通知的标题/消息/类型/触发时机/重试信息。"""

    id: str
    title: str
    message: str
    trigger: NotificationTrigger
    types: List[NotificationType] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3
    priority: NotificationPriority = NotificationPriority.NORMAL
    source: Optional[str] = None
    dedupe_key: Optional[str] = None
