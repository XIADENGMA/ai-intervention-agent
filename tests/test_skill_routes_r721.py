"""R721 · ``GET /api/skills`` — data source of the feedback box's ``/`` picker.

The route is deliberately thin (configuration in, catalogue out), so these tests
pin the contract the two front ends rely on: the response shape, that the
configured directories are honoured, that neither absolute paths nor file
bodies leak, and that failures degrade to a generic error instead of a stack
trace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent import skill_catalog
from ai_intervention_agent.i18n import msg
from ai_intervention_agent.web_ui_routes import skills as skills_route


@pytest.fixture(scope="module")
def client():
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ui = WebFeedbackUI(prompt="skills route", task_id="skills-route-r721", port=19231)
    ui.app.config["TESTING"] = True
    ui.limiter.enabled = False
    return ui.app.test_client()


@pytest.fixture(autouse=True)
def _fresh_cache():
    skill_catalog.invalidate_cache()
    yield
    skill_catalog.invalidate_cache()


class _FakeConfig:
    def __init__(self, section: dict[str, Any]):
        self.section = section
        self.requested: list[str] = []

    def get_section(self, name: str) -> dict[str, Any]:
        self.requested.append(name)
        return self.section


def use_config(monkeypatch: pytest.MonkeyPatch, section: dict[str, Any]) -> _FakeConfig:
    fake = _FakeConfig(section)
    monkeypatch.setattr(skills_route, "get_config", lambda: fake)
    return fake


def make_skill(root: Path, folder: str, front: str, body: str = "BODY\n") -> None:
    path = root / folder / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")


def test_lists_skills_from_the_configured_directories(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "skills"
    make_skill(root, "alpha", "name: alpha\ndescription: First skill")
    make_skill(
        root, "beta", 'name: "Beta 显示名"\ndescription: "Second;触发名:beta-skill"'
    )
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "ship.md").write_text(
        "---\ndescription: Ship it\n---\nGo\n", encoding="utf-8"
    )
    fake = use_config(monkeypatch, {"skill_dirs": [str(root), str(commands)]})

    response = client.get("/api/skills")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["truncated"] is False
    assert fake.requested == ["feedback"]
    rows = {row["insert"]: row for row in payload["skills"]}
    assert set(rows) == {"alpha", "beta-skill", "ship"}
    assert rows["alpha"] == {
        "name": "alpha",
        "insert": "alpha",
        "description": "First skill",
        "kind": "skill",
        "source": rows["alpha"]["source"],
    }
    assert rows["beta-skill"]["name"] == "Beta 显示名"
    assert rows["ship"]["kind"] == "command"
    assert [row["insert"] for row in payload["skills"]] == [
        "alpha",
        "beta-skill",
        "ship",
    ]


def test_response_never_contains_absolute_paths_or_file_bodies(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "private-location" / "skills"
    make_skill(root, "s", "name: s\ndescription: public", "TOP-SECRET-BODY\n")
    use_config(monkeypatch, {"skill_dirs": [str(root)]})

    response = client.get("/api/skills")
    text = response.get_data(as_text=True)

    assert "public" in text
    assert "TOP-SECRET-BODY" not in text
    assert str(tmp_path) not in text
    assert response.get_json()["skills"][0]["source"] == "private-location/skills"


def test_empty_setting_returns_an_empty_list(client, monkeypatch: pytest.MonkeyPatch):
    use_config(monkeypatch, {"skill_dirs": []})
    payload = client.get("/api/skills").get_json()
    assert payload == {"status": "success", "skills": [], "truncated": False}


def test_missing_setting_falls_back_to_the_auto_locations(
    client, monkeypatch: pytest.MonkeyPatch
):
    use_config(monkeypatch, {})
    seen: list[Any] = []
    real = skill_catalog.get_catalog

    def spy(configured: Any = None, **kwargs: Any):
        seen.append(configured)
        return real(configured, **kwargs)

    monkeypatch.setattr(skills_route, "get_catalog", spy)

    response = client.get("/api/skills")

    assert response.status_code == 200
    assert seen == [None]
    assert skill_catalog.normalize_skill_dirs(seen[0]) == ["auto"]


def test_scan_failure_returns_a_generic_error(client, monkeypatch: pytest.MonkeyPatch):
    use_config(monkeypatch, {"skill_dirs": ["auto"]})

    def boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("/Users/secret/path exploded")

    monkeypatch.setattr(skills_route, "get_catalog", boom)

    response = client.get("/api/skills")

    assert response.status_code == 500
    payload = response.get_json()
    assert payload == {"status": "error", "message": msg("feedback.serverError")}
    assert "secret" not in response.get_data(as_text=True)


def test_config_failure_returns_a_generic_error(
    client, monkeypatch: pytest.MonkeyPatch
):
    def boom():
        raise RuntimeError("config store unavailable")

    monkeypatch.setattr(skills_route, "get_config", boom)

    response = client.get("/api/skills")

    assert response.status_code == 500
    assert response.get_json()["status"] == "error"
    assert "unavailable" not in response.get_data(as_text=True)


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_only_get_is_allowed(client, method: str):
    assert getattr(client, method)("/api/skills").status_code == 405


def test_route_is_registered_through_the_mixin_matrix():
    from ai_intervention_agent import web_ui_routes
    from ai_intervention_agent.web_ui import WebFeedbackUI

    assert "SkillRoutesMixin" in web_ui_routes.__all__
    assert issubclass(WebFeedbackUI, web_ui_routes.SkillRoutesMixin)
    assert hasattr(web_ui_routes.SkillRoutesMixin, "_setup_skill_routes")
