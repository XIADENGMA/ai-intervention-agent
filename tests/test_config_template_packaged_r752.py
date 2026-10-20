"""R752: the commented config template ships inside the package, and a first run copies it.

``_create_default_config_file`` and the JSONC migration looked for ``config.toml.default``
next to ``config_manager.py``. Since the sources moved into ``src/`` (R76) that is not
where the file is: it sits in the repository root, and the wheel did not contain it.
Every first run therefore logged "模板文件不存在，使用默认配置创建文件" at WARNING and wrote
a file without comments and without the ``network_security`` section the guides
describe, from PyPI and from a checkout alike.

The wheel now carries the template as ``ai_intervention_agent/config.toml.default``
(``force-include``), and ``find_default_config_template()`` finds it there or, in a
source tree, in the repository root.
"""

from __future__ import annotations

import json
import logging
import tomllib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ai_intervention_agent import config_manager
from ai_intervention_agent.config_manager import ConfigManager

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "config.toml.default"
LOGGER_NAME = "ai_intervention_agent.config_manager"

LEGACY_CONFIG: dict[str, Any] = {
    "notification": {"sound_volume": 33, "debug": True},
    "web_ui": {"port": 9123},
    "network_security": {
        "bind_interface": "127.0.0.1",
        "allowed_networks": ["127.0.0.0/8", "10.1.0.0/16"],
    },
    "custom_section": {"flag": True},
}


def hatch_targets() -> dict[str, Any]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text("utf-8"))
    return pyproject["tool"]["hatch"]["build"]["targets"]


def flatten(table: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in table.items():
        if isinstance(value, dict):
            flat.update(flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def merged(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merged(result[key], value)
        else:
            result[key] = value
    return result


@pytest.fixture
def installed_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make ``config_manager`` believe it lives in ``site-packages`` (no repository around)."""
    package_dir = tmp_path / "site-packages" / "ai_intervention_agent"
    package_dir.mkdir(parents=True)
    monkeypatch.setattr(
        config_manager, "__file__", str(package_dir / "config_manager.py")
    )
    return package_dir


def first_run(path: Path, caplog: pytest.LogCaptureFixture) -> tuple[str, list[str]]:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        ConfigManager(str(path))
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    return path.read_text("utf-8"), warnings


def start_with_legacy_file(path: Path) -> ConfigManager:
    with patch.object(config_manager, "find_config_file", return_value=path):
        return ConfigManager()


def test_wheel_force_includes_the_template_into_the_package() -> None:
    wheel = hatch_targets()["wheel"]

    assert wheel["packages"] == ["src/ai_intervention_agent"]
    assert (
        wheel["force-include"]["config.toml.default"]
        == "ai_intervention_agent/config.toml.default"
    )


def test_sdist_carries_the_template_for_wheels_built_from_it() -> None:
    assert "/config.toml.default" in hatch_targets()["sdist"]["include"]


def test_lookup_finds_the_template_in_the_repository_root() -> None:
    assert config_manager.find_default_config_template() == TEMPLATE.resolve()


def test_lookup_finds_the_copy_inside_an_installed_package(
    installed_package: Path,
) -> None:
    shipped = installed_package / "config.toml.default"
    shipped.write_text("[notification]\n", encoding="utf-8")

    assert config_manager.find_default_config_template() == shipped.resolve()


def test_lookup_finds_nothing_when_no_copy_is_shipped(installed_package: Path) -> None:
    assert config_manager.find_default_config_template() is None


def test_a_stray_file_above_an_installed_package_is_not_a_template(
    installed_package: Path,
) -> None:
    (installed_package.parent.parent / "config.toml.default").write_text(
        "[stray]\n", encoding="utf-8"
    )

    assert config_manager.find_default_config_template() is None


def test_first_run_in_a_checkout_copies_the_template_without_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    text, warnings = first_run(tmp_path / "config.toml", caplog)

    assert text == TEMPLATE.read_text("utf-8")
    assert warnings == []


def test_first_run_from_an_installed_package_copies_the_packaged_template(
    installed_package: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    packaged = TEMPLATE.read_text("utf-8") + "\n# packaged copy\n"
    (installed_package / "config.toml.default").write_text(packaged, encoding="utf-8")

    text, warnings = first_run(tmp_path / "config.toml", caplog)

    assert text == packaged
    assert warnings == []


def test_the_copy_is_writable_when_the_packaged_template_is_read_only(
    installed_package: Path, tmp_path: Path
) -> None:
    shipped = installed_package / "config.toml.default"
    shipped.write_text(TEMPLATE.read_text("utf-8"), encoding="utf-8")
    shipped.chmod(0o444)
    created = tmp_path / "config.toml"

    ConfigManager(str(created))

    assert created.stat().st_mode & 0o200


def test_first_run_without_a_template_still_writes_a_working_config_and_warns(
    installed_package: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    text, warnings = first_run(tmp_path / "config.toml", caplog)

    assert tomllib.loads(text)["notification"]["sound_volume"] == 80
    assert [w for w in warnings if "模板文件不存在" in w] != []


def test_first_run_with_a_json_path_does_not_blame_a_missing_template(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    text, warnings = first_run(tmp_path / "config.json", caplog)

    assert "notification" in json.loads(text)
    assert warnings == []


def test_the_template_has_the_built_in_default_values(tmp_path: Path) -> None:
    built_in = ConfigManager(str(tmp_path / "config.json"))._get_default_config()
    template = tomllib.loads(TEMPLATE.read_text("utf-8"))

    assert flatten(template) == flatten(built_in)


def test_a_migrated_legacy_config_keeps_the_template_comments_and_every_user_value(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "config.jsonc"
    legacy.write_text(
        "// written by an old version\n" + json.dumps(LEGACY_CONFIG), encoding="utf-8"
    )
    template_text = TEMPLATE.read_text("utf-8")

    manager = start_with_legacy_file(legacy)

    migrated = tmp_path / "config.toml"
    assert manager.config_file == migrated
    assert (tmp_path / "config.jsonc.bak").exists()
    text = migrated.read_text("utf-8")
    assert tomllib.loads(text) == merged(tomllib.loads(template_text), LEGACY_CONFIG)
    comments = [ln for ln in template_text.split("\n") if ln.lstrip().startswith("#")]
    assert comments
    assert set(comments) <= set(text.split("\n"))
    assert manager.get("notification")["sound_volume"] == 33


def test_the_editor_whitelist_uses_the_same_template_lookup(tmp_path: Path) -> None:
    from ai_intervention_agent.web_ui_routes.system import _resolve_allowed_paths

    shipped = tmp_path / "config.toml.default"
    shipped.write_text("[notification]\n", encoding="utf-8")

    with patch.object(
        config_manager, "find_default_config_template", return_value=shipped
    ):
        assert shipped.resolve() in _resolve_allowed_paths()

    with patch.object(
        config_manager, "find_default_config_template", return_value=None
    ):
        assert [
            p for p in _resolve_allowed_paths() if p.name.endswith(".default")
        ] == []
