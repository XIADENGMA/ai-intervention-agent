"""R791 — one unusable value in ``config.toml`` must not take the whole section, or the server, down.

``ConfigManager._validate_section`` validated a section as a whole.  When a single value
could not be read — a boolean written as ``""``, ``"maybe"``, ``"enabled"``, a list — pydantic
rejected the whole section and ``get_section`` handed back the *raw* dict: no coercion and no
clamping for any of the other keys either.  ``NotificationConfig.from_config_file`` trusts
``get_section`` ("already coerced and clamped") and builds a strict model from it, so the
raw dict made the constructor raise, ``NotificationManager()`` raised ``NotificationError``
while the module was being imported, and ``server_feedback`` only catches ``ImportError``:

* ``import ai_intervention_agent.server`` failed, and so did the real stdio MCP server — the
  client reported a server that never came up;
* ``ai-intervention-agent --print-config`` printed a traceback;
* the Web UI answered ``/api/system/health`` with 503.

Integer settings never behaved like that (``_clamp_int`` returns the field's default for
anything it cannot read), and ``[network_security]`` validates key by key with its own
fallbacks.  Now the section does as well: a key whose value cannot be read falls back to its
default — with a warning that names the key and never prints the value — and every other key
is coerced and clamped as usual.  ``inf`` (TOML ``inf``) was the same kind of failure for
integer settings: ``int(float("inf"))`` raises ``OverflowError``, which the clamping
validators did not catch.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.notification_manager import NotificationConfig
from ai_intervention_agent.shared_types import SECTION_MODELS

CONFIG_LOGGER = "ai_intervention_agent.config_manager"

# What a hand edit (or a JSON config with ``null``) can leave where a boolean belongs.
UNREADABLE_BOOLEANS: list[Any] = ["maybe", "", "enabled", [], {}, [1], None]

NOT_A_NUMBER_OF_ANY_KIND: list[float] = [float("inf"), float("-inf"), float("nan")]


def _fields_annotated(kind: type) -> list[tuple[str, str]]:
    return [
        (section, name)
        for section, model in SECTION_MODELS.items()
        for name, info in model.model_fields.items()
        if info.annotation is kind
    ]


BOOLEAN_FIELDS = _fields_annotated(bool)
INTEGER_FIELDS = _fields_annotated(int)


def _default(section: str, field: str) -> Any:
    return SECTION_MODELS[section]().model_dump()[field]


BOOLEAN_IDS = [f"{section}.{name}" for section, name in BOOLEAN_FIELDS]
INTEGER_IDS = [f"{section}.{name}" for section, name in INTEGER_FIELDS]


# ---------------------------------------------------------------------------
# The section
# ---------------------------------------------------------------------------
class TestAValueNobodyCanReadFallsBackToItsDefault:
    def test_the_ratchet_sees_the_booleans_and_integers(self) -> None:
        """If a refactor changed how fields are annotated the parametrized tests below
        would silently collect nothing."""
        assert ("notification", "bark_enabled") in BOOLEAN_FIELDS
        assert ("notification", "mobile_vibrate") in BOOLEAN_FIELDS
        assert len(BOOLEAN_FIELDS) >= 12
        assert ("notification", "retry_count") in INTEGER_FIELDS
        assert ("web_ui", "port") in INTEGER_FIELDS
        assert len(INTEGER_FIELDS) >= 8

    @pytest.mark.parametrize(("section", "field"), BOOLEAN_FIELDS, ids=BOOLEAN_IDS)
    @pytest.mark.parametrize("bad", UNREADABLE_BOOLEANS, ids=repr)
    def test_an_unreadable_boolean_becomes_its_default(
        self, section: str, field: str, bad: Any
    ) -> None:
        result = ConfigManager._validate_section(section, {field: bad})
        assert result[field] is _default(section, field)

    @pytest.mark.parametrize(("section", "field"), INTEGER_FIELDS, ids=INTEGER_IDS)
    @pytest.mark.parametrize("bad", NOT_A_NUMBER_OF_ANY_KIND, ids=repr)
    def test_inf_and_nan_become_the_default_of_an_integer_setting(
        self, section: str, field: str, bad: float
    ) -> None:
        result = ConfigManager._validate_section(section, {field: bad})
        assert result[field] == _default(section, field)

    def test_the_rest_of_the_section_is_still_coerced_and_clamped(self) -> None:
        """Before: the whole raw dict came back — ``250`` stayed ``250``, ``"7"`` stayed a string."""
        result = ConfigManager._validate_section(
            "notification",
            {
                "mobile_vibrate": "maybe",
                "sound_volume": 250,
                "retry_count": "7",
                "enabled": "off",
                "web_icon": 5,
                "bark_timeout": "abc",
            },
        )
        assert result["mobile_vibrate"] is True  # the default
        assert result["sound_volume"] == 100  # clamped
        assert result["retry_count"] == 7  # coerced
        assert result["enabled"] is False  # "off" is a boolean
        assert result["web_icon"] == "5"
        assert result["bark_timeout"] == 10  # unreadable number: default

    def test_every_unreadable_key_falls_back_on_its_own(self) -> None:
        result = ConfigManager._validate_section(
            "notification",
            {
                "enabled": "perhaps",
                "web_enabled": [],
                "sound_enabled": "",
                "bark_enabled": {},
                "sound_volume": 30,
            },
        )
        defaults = SECTION_MODELS["notification"]().model_dump()
        for key in ("enabled", "web_enabled", "sound_enabled", "bark_enabled"):
            assert result[key] is defaults[key]
        assert result["sound_volume"] == 30

    def test_keys_the_model_does_not_know_are_kept(self) -> None:
        result = ConfigManager._validate_section(
            "notification", {"legacy_key": [1, 2], "bark_enabled": ""}
        )
        assert result["legacy_key"] == [1, 2]
        assert result["bark_enabled"] is False

    def test_the_caller_dict_is_not_modified(self) -> None:
        raw: dict[str, Any] = {"bark_enabled": "", "sound_volume": 20}
        ConfigManager._validate_section("notification", raw)
        assert raw == {"bark_enabled": "", "sound_volume": 20}

    def test_a_list_setting_that_is_not_a_list_falls_back_too(self) -> None:
        """The ``[network_security]`` lists are typed ``list[str]``."""
        result = ConfigManager._validate_section(
            "network_security", {"allowed_networks": "oops", "blocked_ips": 5}
        )
        defaults = SECTION_MODELS["network_security"]().model_dump()
        assert result["allowed_networks"] == defaults["allowed_networks"]
        assert result["blocked_ips"] == defaults["blocked_ips"]

    def test_a_section_that_is_fine_comes_back_validated_and_silent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger=CONFIG_LOGGER):
            result = ConfigManager._validate_section(
                "notification", {"sound_volume": "40", "enabled": "yes"}
            )
        assert result["sound_volume"] == 40
        assert result["enabled"] is True
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


class TestTheWarning:
    def test_it_names_the_keys_and_the_section(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=CONFIG_LOGGER):
            ConfigManager._validate_section(
                "notification", {"mobile_vibrate": "maybe", "bark_enabled": ""}
            )
        warnings = [
            r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert "notification" in warnings[0]
        assert "mobile_vibrate" in warnings[0]
        assert "bark_enabled" in warnings[0]

    def test_it_never_prints_the_value(self, caplog: pytest.LogCaptureFixture) -> None:
        """Config values can be secrets (``bark_device_key`` sits next to ``bark_enabled``)."""
        secret = "sk-this-must-not-reach-the-log"
        with caplog.at_level(logging.DEBUG, logger=CONFIG_LOGGER):
            ConfigManager._validate_section(
                "notification", {"bark_enabled": secret, "bark_device_key": secret}
            )
        assert secret not in caplog.text


# ---------------------------------------------------------------------------
# The consumers
# ---------------------------------------------------------------------------
def _config_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


class TestTheConsumersGetUsableValues:
    def test_get_section_validates_the_rest_of_the_section(
        self, tmp_path: Path
    ) -> None:
        manager = ConfigManager(
            str(
                _config_file(
                    tmp_path, '[notification]\nbark_enabled = ""\nsound_volume = 20\n'
                )
            )
        )
        section = manager.get_section("notification")
        assert section["bark_enabled"] is False
        assert section["sound_volume"] == 20

    def test_the_notification_config_builds_from_a_file_with_a_bad_boolean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This is the call that raised while ``notification_manager`` was being imported."""
        manager = ConfigManager(
            str(
                _config_file(
                    tmp_path,
                    '[notification]\nbark_enabled = ""\nmobile_vibrate = "maybe"\n'
                    "sound_volume = 20\nretry_count = 7\n",
                )
            )
        )
        monkeypatch.setattr(
            "ai_intervention_agent.notification_manager.get_config", lambda: manager
        )
        config = NotificationConfig.from_config_file()
        assert config.bark_enabled is False
        assert config.mobile_vibrate is True
        assert config.sound_volume == pytest.approx(0.2)
        assert config.retry_count == 7

    def test_a_number_that_is_infinite_does_not_break_the_notification_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = ConfigManager(
            str(
                _config_file(
                    tmp_path, "[notification]\nretry_count = inf\nbark_timeout = inf\n"
                )
            )
        )
        monkeypatch.setattr(
            "ai_intervention_agent.notification_manager.get_config", lambda: manager
        )
        config = NotificationConfig.from_config_file()
        assert config.retry_count == 3
        assert config.bark_timeout == 10


# ---------------------------------------------------------------------------
# The real thing: a process that imports the server
# ---------------------------------------------------------------------------
IMPORT_THE_SERVER = (
    "import ai_intervention_agent.server; "
    "from ai_intervention_agent import server_feedback; "
    "print('IMPORTED notification_available=%s' % server_feedback.NOTIFICATION_AVAILABLE)"
)


@pytest.mark.parametrize("literal", ['""', '"maybe"', "[]", '"enabled"'])
def test_the_server_module_imports_with_an_unreadable_notification_boolean(
    tmp_path: Path, literal: str
) -> None:
    """Before: ``NotificationError`` at import, which ``server_feedback`` (it only catches
    ``ImportError``) let through — the MCP server never started."""
    config = _config_file(tmp_path, f"[notification]\nbark_enabled = {literal}\n")
    env = {
        **os.environ,
        "AI_INTERVENTION_AGENT_CONFIG_FILE": str(config),
        "HOME": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.run(
        [sys.executable, "-c", IMPORT_THE_SERVER],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert "IMPORTED notification_available=True" in proc.stdout


def test_the_server_module_imports_with_an_infinite_retry_count(tmp_path: Path) -> None:
    config = _config_file(tmp_path, "[notification]\nretry_count = inf\n")
    env = {
        **os.environ,
        "AI_INTERVENTION_AGENT_CONFIG_FILE": str(config),
        "HOME": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.run(
        [sys.executable, "-c", IMPORT_THE_SERVER],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert "IMPORTED notification_available=True" in proc.stdout
