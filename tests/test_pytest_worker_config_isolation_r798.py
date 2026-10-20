"""R798: every pytest process owns the config file its tests reset and write.

``tests/conftest.py`` points ``AI_INTERVENTION_AGENT_CONFIG_FILE`` at a temp directory
the process created, and resets that file before each test, but only while the path
is inside the process's *own* temp directory (``_is_managed_tmp_config``).  Under
pytest-xdist the master process imports ``conftest`` first and exports its path; the
workers used to take that inherited value for an explicit choice (``setdefault``), so
the reset was a no-op in every worker and all workers shared one ``config.toml`` in
the master's directory.  A test that writes the config in one worker (rotating the
API token, editing the notification settings) then leaked into whatever another
worker was reading at that moment: ``aiia_token_age_seconds`` showed up in the
Prometheus payload that two other tests scan for the word ``token``, and those tests
failed in the full run, a few seconds after a sweep had rotated the token in a third
worker.  CI runs ``pytest -n 4 --dist=loadfile``.

The subprocess tests start a fresh interpreter, export a path the way the xdist master
does, import the real ``tests.conftest`` and read back what it decided.  The in-process
tests check the process they run in, in whatever mode the suite runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import tests.conftest as conftest_module

REPO_ROOT = Path(__file__).resolve().parent.parent

PROBE = """
import json
import os

import tests.conftest as c

path = c._active_config_path()
print(json.dumps({
    "env": os.environ[c._CONFIG_ENV],
    "own_dir": c._TEST_TMP_DIR.name,
    "managed": c._is_managed_tmp_config(path),
}))
"""


def _probe(inherited: str | None) -> dict[str, Any]:
    """What a new pytest process decides when it inherits ``inherited``."""
    env = dict(os.environ)
    env.pop(conftest_module._CONFIG_ENV, None)
    if inherited is not None:
        env[conftest_module._CONFIG_ENV] = inherited
    done = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stderr == "", done.stderr
    return json.loads(done.stdout)


def _same_dir(a: str, b: str) -> bool:
    return Path(a).resolve() == Path(b).resolve()


class TestAProcessDoesNotAdoptAnotherSessionsConfig:
    """The path a xdist master exported is not an explicit choice."""

    def test_master_path_is_replaced_by_the_workers_own(self, tmp_path: Path) -> None:
        master = tmp_path / "ai-intervention-agent-pytest-abcd1234" / "config.toml"
        result = _probe(str(master))
        assert result["managed"] is True
        assert _same_dir(Path(result["env"]).parent.as_posix(), result["own_dir"])
        assert not _same_dir(Path(result["env"]).parent.as_posix(), str(master.parent))

    def test_a_path_below_another_session_dir_is_replaced_too(
        self, tmp_path: Path
    ) -> None:
        nested = tmp_path / "ai-intervention-agent-pytest-wxyz_890" / "sub" / "c.toml"
        result = _probe(str(nested))
        assert result["managed"] is True
        assert _same_dir(Path(result["env"]).parent.as_posix(), result["own_dir"])

    def test_nothing_exported_gives_the_process_its_own(self) -> None:
        result = _probe(None)
        assert result["managed"] is True
        assert _same_dir(Path(result["env"]).parent.as_posix(), result["own_dir"])

    def test_an_empty_value_is_not_a_path(self) -> None:
        result = _probe("")
        assert result["managed"] is True
        assert _same_dir(Path(result["env"]).parent.as_posix(), result["own_dir"])


class TestAnExplicitChoiceIsStillRespected:
    """Pointing the suite at a config file of your own keeps working."""

    @pytest.mark.parametrize(
        "directory",
        [
            "my-config",
            "ai-intervention-agent-pytest-demo",  # not the 8 random characters
            "ai-intervention-agent-pytest-ABCD1234",  # tempfile never writes capitals
            "ai-intervention-agent-pytest-abcd12345",  # nine characters
            "xai-intervention-agent-pytest-abcd1234",  # a different directory name
        ],
    )
    def test_the_path_is_kept_and_nothing_is_reset(
        self, tmp_path: Path, directory: str
    ) -> None:
        chosen = tmp_path / directory / "config.toml"
        result = _probe(str(chosen))
        assert result["env"] == str(chosen)
        assert result["managed"] is False


class TestThisProcessResetsItsOwnConfig:
    """The process the tests run in (one of the xdist workers in CI)."""

    @staticmethod
    def _skip_when_the_suite_was_pointed_elsewhere() -> None:
        raw = os.environ.get(conftest_module._CONFIG_ENV, "")
        if not conftest_module._is_path_in_a_pytest_session_dir(raw):
            pytest.skip("AI_INTERVENTION_AGENT_CONFIG_FILE was set explicitly")

    def test_the_config_path_is_inside_this_process_temp_dir(self) -> None:
        self._skip_when_the_suite_was_pointed_elsewhere()
        path = conftest_module._active_config_path()
        assert conftest_module._is_managed_tmp_config(path), path

    def test_the_reset_really_restores_the_template(self) -> None:
        self._skip_when_the_suite_was_pointed_elsewhere()
        path = conftest_module._active_config_path()
        template = conftest_module._default_config_template().read_bytes()
        path.write_text("[network_security]\napi_token = 'x'\n", encoding="utf-8")
        conftest_module._reset_config_file_to_default(path)
        assert path.read_bytes() == template
