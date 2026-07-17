from __future__ import annotations

import inspect
import json
import tempfile
from pathlib import Path

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.config_modules.io_operations import IOOperationsMixin


def test_restore_config_uses_dict_copy_snapshots() -> None:
    source = inspect.getsource(IOOperationsMixin.restore_config)

    assert "restored_config = actual_config.copy()" in source
    assert "restored_config = backup_data.copy()" in source
    assert "restored_config = dict(actual_config)" not in source
    assert "restored_config = dict(backup_data)" not in source


def test_restore_config_wrapped_backup_still_merges_network_security() -> None:
    with tempfile.TemporaryDirectory() as td:
        config_path = Path(td) / "config.json"
        backup_path = Path(td) / "backup.json"
        backup_data = {
            "config": {"notification": {"enabled": False}},
            "network_security": {
                "bind_interface": "127.0.0.1",
                "allowed_networks": ["127.0.0.0/8"],
                "blocked_ips": [],
                "access_control_enabled": True,
            },
        }
        backup_path.write_text(json.dumps(backup_data), encoding="utf-8")

        manager = ConfigManager(str(config_path))

        assert manager.restore_config(str(backup_path)) is True

        restored = json.loads(config_path.read_text(encoding="utf-8"))
        assert restored["notification"]["enabled"] is False
        assert restored["network_security"]["bind_interface"] == "127.0.0.1"


def test_restore_config_raw_backup_still_restores_top_level_config() -> None:
    with tempfile.TemporaryDirectory() as td:
        config_path = Path(td) / "config.json"
        backup_path = Path(td) / "backup.json"
        backup_data = {
            "notification": {"enabled": False},
            "web_ui": {"host": "127.0.0.1", "port": 8765},
        }
        backup_path.write_text(json.dumps(backup_data), encoding="utf-8")

        manager = ConfigManager(str(config_path))

        assert manager.restore_config(str(backup_path)) is True

        restored = json.loads(config_path.read_text(encoding="utf-8"))
        assert restored["notification"]["enabled"] is False
        assert restored["web_ui"]["port"] == 8765
