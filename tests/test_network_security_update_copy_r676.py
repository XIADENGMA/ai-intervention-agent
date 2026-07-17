import inspect
import tempfile
from pathlib import Path
from typing import Any

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.config_modules.network_security import NetworkSecurityMixin


class CopyProbeConfigManager(ConfigManager):
    def __init__(
        self,
        config_file: str,
        current: dict[str, Any],
        captured: list[dict[str, Any]],
    ) -> None:
        super().__init__(config_file)
        self._probe_current = current
        self._probe_captured = captured

    def get_network_security_config(self) -> dict[str, Any]:
        return self._probe_current

    def _validate_network_security_config(self, raw: Any) -> dict[str, Any]:
        assert isinstance(raw, dict)
        self._probe_captured.append(raw)
        return raw.copy()


def test_update_network_security_uses_dict_copy_snapshot() -> None:
    source = inspect.getsource(NetworkSecurityMixin.update_network_security_config)

    assert "merged = current.copy()" in source
    assert "merged = dict(current)" not in source


def test_update_network_security_copy_isolates_current_mapping() -> None:
    with tempfile.TemporaryDirectory() as td:
        current = {
            "bind_interface": "127.0.0.1",
            "allowed_networks": ["127.0.0.0/8"],
            "blocked_ips": [],
            "trusted_hosts": [],
            "api_token": None,
            "api_token_rotated_at": None,
            "access_control_enabled": True,
        }
        captured: list[dict[str, Any]] = []
        manager = CopyProbeConfigManager(
            str(Path(td) / "config.toml"),
            current,
            captured,
        )

        manager.update_network_security_config(
            {
                "bind_interface": "0.0.0.0",
                "enable_access_control": False,
                "unknown_field": "ignored",
            },
            save=False,
            trigger_callbacks=False,
        )

    assert len(captured) == 1
    merged = captured[0]
    assert merged is not current
    assert merged["bind_interface"] == "0.0.0.0"
    assert merged["access_control_enabled"] is False
    assert "unknown_field" not in merged

    assert current["bind_interface"] == "127.0.0.1"
    assert current["access_control_enabled"] is True
    assert "unknown_field" not in current
