"""R457 predefined option defaults must reach every frontend path."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def test_vscode_task_detail_fallback_carries_predefined_option_defaults() -> None:
    src = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    assert "t.predefined_options_defaults" in src
    assert "predefined_options_defaults: predefinedDefaults" in src


def test_vscode_first_render_uses_backend_defaults_after_local_state() -> None:
    src = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    saved_idx = src.index("const savedState = config.task_id")
    same_task_idx = src.index("} else if (isSameTask)", saved_idx)
    defaults_idx = src.index(
        "} else if (Array.isArray(config.predefined_options_defaults))", same_task_idx
    )
    push_idx = src.index(
        "if (checked === true) savedSelections.push(index)", defaults_idx
    )

    assert saved_idx < same_task_idx < defaults_idx < push_idx


def test_legacy_single_task_app_uses_backend_defaults_only_for_true() -> None:
    src = APP_JS.read_text(encoding="utf-8")

    assert "Array.isArray(config.predefined_options_defaults)" in src
    assert "checkbox.checked = optionDefaults[index] === true" in src
    assert 'optionDiv.classList.add("selected")' in src
