from __future__ import annotations

import inspect
from unittest.mock import patch

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.config_modules.io_operations import IOOperationsMixin


def test_import_config_reuses_single_network_security_filtered_snapshot() -> None:
    source = inspect.getsource(IOOperationsMixin.import_config)

    assert "config_without_network_security = actual_config.copy()" in source
    assert 'config_without_network_security.pop("network_security", None)' in source
    assert "self._deep_merge(self._config, config_without_network_security)" in source
    assert "self._pending_changes.update(config_without_network_security)" in source
    assert "tmp = dict(actual_config)" not in source


def test_import_config_merge_save_filters_network_security_once() -> None:
    manager = ConfigManager()
    data = {
        "config": {
            "notification": {
                "enabled": True,
                "sound_enabled": True,
            },
            "web_ui": {
                "host": "127.0.0.1",
                "port": 18080,
            },
            "network_security": {
                "bind_interface": "127.0.0.1",
                "allowed_networks": ["127.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            },
        }
    }

    with (
        patch.object(manager, "_save_config") as save_config,
        patch.object(manager, "set_network_security_config") as set_network_security,
    ):
        assert manager.import_config(data, merge=True, save=True)

    save_config.assert_called_once_with()
    set_network_security.assert_called_once_with(
        data["config"]["network_security"],
        save=True,
        trigger_callbacks=False,
    )
    assert "network_security" not in manager._pending_changes
    assert manager._pending_changes["notification"] == {
        "enabled": True,
        "sound_enabled": True,
    }
    assert manager._pending_changes["web_ui"] == {
        "host": "127.0.0.1",
        "port": 18080,
    }
    assert "network_security" in data["config"]


def test_import_config_override_save_keeps_config_independent_from_pending() -> None:
    manager = ConfigManager()
    data = {
        "config": {
            "notification": {
                "enabled": True,
            },
            "network_security": {
                "bind_interface": "127.0.0.1",
                "allowed_networks": ["127.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            },
        }
    }

    with (
        patch.object(manager, "_save_config"),
        patch.object(manager, "set_network_security_config"),
    ):
        assert manager.import_config(data, merge=False, save=True)

    assert manager._config is not manager._pending_changes
    assert "network_security" not in manager._config
    assert "network_security" not in manager._pending_changes
    manager._pending_changes["injected"] = True
    assert "injected" not in manager._config
