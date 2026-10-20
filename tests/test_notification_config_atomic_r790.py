"""R790 — a refused notification-config update must not leave part of it applied.

``NotificationManager.update_config_without_save`` assigned the fields one by one.
The config model validates every assignment (``validate_assignment=True``), so a value
pydantic cannot turn into a boolean (``null``, a list, ``"maybe"``) raised halfway
through the loop: the fields *before* it were already in force, the ones after it never
were.  ``POST /api/update-notification-config`` then answered ``500 "Update failed"``
while the process went on running with half of the request applied — web
notifications switched off, volume at 10 % — and ``config.toml`` still holding the
old values, so memory and file disagreed until the next restart.  The caller was told
the update had failed.

The update is now all or nothing:

* ``update_config_without_save`` puts every field it already assigned back before it
  re-raises, and only touches the Bark provider after the whole update went through;
* the route turns the model's ``ValidationError`` into ``400`` with
  ``{"status": "error", "error": "invalid_value", "fields": [...], "message": ...}``
  (a value the caller got wrong is not a server fault) and persists nothing.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient
from pydantic import ValidationError

from ai_intervention_agent.notification_manager import (
    NotificationConfig,
    NotificationManager,
)
from ai_intervention_agent.web_ui import WebFeedbackUI

BOOLEAN_FIELDS = [
    "enabled",
    "web_enabled",
    "web_permission_auto_request",
    "macos_native_enabled",
    "sound_enabled",
    "sound_mute",
    "mobile_optimized",
    "mobile_vibrate",
    "bark_enabled",
]
NOT_A_BOOLEAN: list[Any] = [None, [], {}, "maybe"]


def _manager() -> NotificationManager:
    """A manager that is not the process singleton (``__new__`` would hand that one out)."""
    mgr = object.__new__(NotificationManager)
    mgr.config = NotificationConfig()
    mgr._config_lock = threading.RLock()
    return mgr


# ---------------------------------------------------------------------------
# The manager
# ---------------------------------------------------------------------------
class TestTheManagerAppliesAnUpdateAllOrNothing:
    def test_a_valid_update_is_applied_in_full(self) -> None:
        mgr = _manager()
        mgr.update_config_without_save(
            web_enabled=False, sound_volume=0.1, mobile_vibrate=False, web_icon="x.png"
        )
        assert mgr.config.web_enabled is False
        assert mgr.config.sound_volume == pytest.approx(0.1)
        assert mgr.config.mobile_vibrate is False
        assert mgr.config.web_icon == "x.png"

    @pytest.mark.parametrize("field", BOOLEAN_FIELDS)
    @pytest.mark.parametrize("bad", NOT_A_BOOLEAN, ids=repr)
    def test_a_refused_value_puts_back_what_was_already_assigned(
        self, field: str, bad: Any
    ) -> None:
        mgr = _manager()
        # Fields that come before AND after the bad one, none at its default.
        mgr.config.web_icon = "kept.png"
        mgr.config.sound_volume = 0.5
        before = mgr.config.model_dump()

        updates: dict[str, Any] = {
            "web_icon": "changed.png",
            "sound_volume": 0.1,
            field: bad,
            "bark_url": "https://example.test/push",
        }
        with pytest.raises(ValidationError):
            mgr.update_config_without_save(**updates)

        assert mgr.config.model_dump() == before

    def test_the_bark_provider_is_left_alone_when_the_update_is_refused(self) -> None:
        mgr = _manager()
        with patch.object(mgr, "_update_bark_provider") as update_provider:
            with pytest.raises(ValidationError):
                mgr.update_config_without_save(bark_enabled=True, mobile_vibrate=None)
        update_provider.assert_not_called()
        assert mgr.config.bark_enabled is False

    def test_the_bark_provider_follows_an_update_that_went_through(self) -> None:
        mgr = _manager()
        with patch.object(mgr, "_update_bark_provider") as update_provider:
            mgr.update_config_without_save(bark_enabled=True)
        update_provider.assert_called_once()

    def test_keys_the_config_does_not_have_are_still_ignored(self) -> None:
        mgr = _manager()
        mgr.update_config_without_save(nonexistent_key_xyz="value", web_enabled=False)
        assert not hasattr(mgr.config, "nonexistent_key_xyz")
        assert mgr.config.web_enabled is False

    def test_what_comes_back_is_what_the_model_held_not_what_was_asked_for(
        self,
    ) -> None:
        """``sound_volume=5.0`` is clamped to 1.0 on assignment; the rollback must
        restore the 0.5 from before the call, not the clamped value or the request."""
        mgr = _manager()
        mgr.config.sound_volume = 0.5
        with pytest.raises(ValidationError):
            mgr.update_config_without_save(sound_volume=5.0, sound_mute="maybe")
        assert mgr.config.sound_volume == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client() -> FlaskClient:
    ui = WebFeedbackUI(
        prompt="r790", task_id="r790-task", auto_resubmit_timeout=0, port=19790
    )
    ui.app.config["TESTING"] = True
    ui.limiter.enabled = False
    return ui.app.test_client()


@contextmanager
def _route_with(mgr: NotificationManager) -> Iterator[MagicMock]:
    """Run the route against ``mgr`` with a config manager that records what is persisted."""
    module = "ai_intervention_agent.web_ui_routes.notification"
    with (
        patch.multiple(module, notification_manager=mgr, NOTIFICATION_AVAILABLE=True),
        patch(f"{module}.get_config") as get_config,
    ):
        get_config.return_value.get_section.return_value = {}
        yield get_config.return_value


class TestTheRouteRefusesAValueItCannotUseWithA400:
    @pytest.mark.parametrize(
        ("request_key", "field"),
        [
            ("enabled", "enabled"),
            ("webEnabled", "web_enabled"),
            ("soundMute", "sound_mute"),
            ("mobileVibrate", "mobile_vibrate"),
            ("barkEnabled", "bark_enabled"),
            ("mobile_optimized", "mobile_optimized"),
        ],
    )
    @pytest.mark.parametrize("bad", NOT_A_BOOLEAN, ids=repr)
    def test_400_names_the_field_and_changes_nothing(
        self, client: FlaskClient, request_key: str, field: str, bad: Any
    ) -> None:
        mgr = _manager()
        before = mgr.config.model_dump()
        body = {"webIcon": "changed.png", "soundVolume": 10, request_key: bad}
        with _route_with(mgr) as config_mgr:
            resp = client.post("/api/update-notification-config", json=body)

        assert resp.status_code == 400, resp.get_data(as_text=True)
        payload = resp.get_json()
        assert payload["status"] == "error"
        assert payload["error"] == "invalid_value"
        assert payload["fields"] == [field]
        assert field in payload["message"]
        assert mgr.config.model_dump() == before
        config_mgr.update_section.assert_not_called()

    def test_the_message_follows_the_request_language(
        self, client: FlaskClient
    ) -> None:
        with _route_with(_manager()):
            resp = client.post(
                "/api/update-notification-config",
                json={"mobileVibrate": None},
                headers={"Accept-Language": "zh-CN"},
            )
        assert resp.status_code == 400
        assert "mobile_vibrate" in resp.get_json()["message"]
        assert "无效" in resp.get_json()["message"]

    def test_a_valid_request_is_still_applied_and_persisted(
        self, client: FlaskClient
    ) -> None:
        mgr = _manager()
        with _route_with(mgr) as config_mgr:
            resp = client.post(
                "/api/update-notification-config",
                json={"webEnabled": False, "soundVolume": 10, "mobileVibrate": False},
            )

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"
        assert mgr.config.web_enabled is False
        assert mgr.config.sound_volume == pytest.approx(0.1)
        assert mgr.config.mobile_vibrate is False
        config_mgr.update_section.assert_called_once()

    def test_a_server_side_failure_is_still_a_500(self, client: FlaskClient) -> None:
        """Only a value the *caller* got wrong becomes a 400."""
        mgr = _manager()
        with _route_with(mgr) as config_mgr:
            config_mgr.update_section.side_effect = OSError("disk full")
            resp = client.post(
                "/api/update-notification-config", json={"webEnabled": False}
            )
        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"
