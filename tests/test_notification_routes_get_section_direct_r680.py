from __future__ import annotations

import inspect

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.web_ui_routes.notification import NotificationRoutesMixin


def test_notification_routes_use_get_section_snapshot_directly() -> None:
    source = inspect.getsource(NotificationRoutesMixin._setup_notification_routes)

    assert 'notification_config = config_mgr.get_section("notification")' in source
    assert 'feedback_config = config_mgr.get_section("feedback")' in source
    assert 'current = config_mgr.get_section("feedback")' in source
    assert 'dict(config_mgr.get_section("notification"))' not in source
    assert 'dict(config_mgr.get_section("feedback"))' not in source


def test_config_manager_get_section_returns_independent_route_snapshots() -> None:
    manager = ConfigManager()

    notification = manager.get_section("notification")
    feedback = manager.get_section("feedback")

    assert isinstance(notification, dict)
    assert isinstance(feedback, dict)

    notification["__r680_probe"] = True
    feedback["__r680_probe"] = True

    assert "__r680_probe" not in manager.get_section("notification")
    assert "__r680_probe" not in manager.get_section("feedback")
