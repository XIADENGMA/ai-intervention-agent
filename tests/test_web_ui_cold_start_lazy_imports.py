"""Cold-start import guards for the Web UI entrypoint.

The Web UI process needs Flask and route definitions early, but it should not
load configuration singletons, Pydantic section models, or the TaskQueue model
graph until a route or startup hook actually needs them. These tests use fresh
subprocesses so ``sys.modules`` reflects a real cold import rather than pytest's
already-warmed module graph.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

HEAVY_WEB_UI_IMPORTS = (
    "ai_intervention_agent.config_manager",
    "ai_intervention_agent.shared_types",
    "ai_intervention_agent.server_config",
    "ai_intervention_agent.task_queue",
    "flask_limiter",
    "pydantic",
)


def _run_probe(code: str) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestWebUiColdStartLazyImports(unittest.TestCase):
    def test_import_web_ui_does_not_load_config_or_pydantic_graph(self) -> None:
        code = f"""
import json
import sys
import ai_intervention_agent.web_ui  # noqa: F401
mods = {HEAVY_WEB_UI_IMPORTS!r}
print(json.dumps({{name: name in sys.modules for name in mods}}, sort_keys=True))
"""
        loaded = _run_probe(code)
        self.assertEqual(
            loaded,
            dict.fromkeys(HEAVY_WEB_UI_IMPORTS, False),
            "import ai_intervention_agent.web_ui must stay free of config_manager, "
            "shared_types/Pydantic, server_config, and task_queue cold-start costs",
        )

    def test_web_ui_get_config_is_lazy_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.toml"
            code = f"""
import json
import os
import sys
os.environ["AI_INTERVENTION_AGENT_CONFIG_FILE"] = {str(cfg_path)!r}
import ai_intervention_agent.web_ui as web_ui
before = "ai_intervention_agent.config_manager" in sys.modules
cfg = web_ui.get_config()
after = "ai_intervention_agent.config_manager" in sys.modules
print(json.dumps({{
    "before": before,
    "after": after,
    "class": cfg.__class__.__name__,
}}, sort_keys=True))
"""
            observed = _run_probe(code)

        self.assertEqual(
            observed,
            {"before": False, "after": True, "class": "ConfigManager"},
        )

    def test_constructing_webui_does_not_load_config_taskqueue_or_limiter(self) -> None:
        code = f"""
import json
import sys
from ai_intervention_agent.web_ui import WebFeedbackUI
WebFeedbackUI(prompt="cold-construction", port=0)
mods = {HEAVY_WEB_UI_IMPORTS!r}
print(json.dumps({{name: name in sys.modules for name in mods}}, sort_keys=True))
"""
        loaded = _run_probe(code)
        self.assertEqual(
            loaded,
            dict.fromkeys(HEAVY_WEB_UI_IMPORTS, False),
            "WebFeedbackUI construction must not eagerly load config_manager, "
            "TaskQueue, Pydantic, or flask_limiter; those are request-time costs",
        )


if __name__ == "__main__":
    unittest.main()
