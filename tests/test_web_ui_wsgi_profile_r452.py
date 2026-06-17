"""R452 · Optional WSGI / reverse-proxy deployment profile."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WSGI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_wsgi.py"
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"
DEPLOY_EN = REPO_ROOT / "docs" / "deployment.md"
DEPLOY_ZH = REPO_ROOT / "docs" / "deployment.zh-CN.md"


def test_wsgi_module_exists_and_is_lazy() -> None:
    script = (
        "import sys\n"
        "import ai_intervention_agent.web_ui_wsgi as w\n"
        "print('ai_intervention_agent.web_ui' in sys.modules)\n"
        "print(callable(w.application))\n"
        "print(callable(w.create_app))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    lines = result.stdout.strip().splitlines()
    assert lines == ["False", "True", "True"]


def test_wsgi_factory_returns_flask_app() -> None:
    from ai_intervention_agent.web_ui_wsgi import create_app

    app = create_app()
    assert hasattr(app, "route")
    assert hasattr(app, "test_client")


def test_default_run_path_still_uses_flask_dev_server() -> None:
    text = WEB_UI_PY.read_text(encoding="utf-8")
    assert "self.app.run(" in text
    assert "debug=False" in text
    assert "use_reloader=False" in text


def test_wsgi_doc_warns_about_single_worker_and_sse_proxy_headers() -> None:
    for path in (DEPLOY_EN, DEPLOY_ZH):
        text = path.read_text(encoding="utf-8")
        assert "ai_intervention_agent.web_ui_wsgi:create_app" in text
        assert "--workers 1" in text
        assert "proxy_buffering off" in text
        assert "X-Accel-Buffering: no" in text
        assert "Cache-Control: no-cache" in text
        assert "BroadcastChannel" in text


def test_wsgi_module_documents_in_process_queue_boundary() -> None:
    text = WSGI_PY.read_text(encoding="utf-8")
    assert "in-process memory" in text
    assert "Use one worker process" in text
    assert "lazy" in text
