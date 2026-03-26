"""web_ui_routes — WebFeedbackUI 路由 Mixin 模块。

将 web_ui.py 中 setup_routes 的 ~2300 行路由代码拆分为四个职责清晰的 Mixin 类，
由 WebFeedbackUI 通过多重继承组合使用。每个 Mixin 定义一个 _setup_xxx_routes(self) 方法，
内部的闭包路由通过 self 访问 WebFeedbackUI 实例的所有属性和方法，因此路由逻辑零改动。
"""

from web_ui_routes.feedback import FeedbackRoutesMixin
from web_ui_routes.notification import NotificationRoutesMixin
from web_ui_routes.static import StaticRoutesMixin
from web_ui_routes.task import TaskRoutesMixin

__all__ = [
    "TaskRoutesMixin",
    "FeedbackRoutesMixin",
    "NotificationRoutesMixin",
    "StaticRoutesMixin",
]
