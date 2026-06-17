"""Optional WSGI entrypoint for long-running / reverse-proxied Web UI deployments.

The default local path remains ``WebFeedbackUI.run()``, which uses Flask's
development server for a short-lived desktop workflow. This module exists for
operators who want to run the same Flask app behind Waitress, Gunicorn, uWSGI,
or a reverse proxy.

Important: the task queue is in-process memory. Use one worker process unless a
future release introduces an external queue backend.
"""

from __future__ import annotations

from typing import Any

_app: Any | None = None


def create_app() -> Any:
    """Return the Web UI Flask app for WSGI servers.

    The import is intentionally lazy so ``import ai_intervention_agent.web_ui_wsgi``
    stays cheap and side-effect-light. WSGI servers that support factory syntax
    should prefer ``--call ai_intervention_agent.web_ui_wsgi:create_app`` or
    ``'ai_intervention_agent.web_ui_wsgi:create_app()'``.
    """

    global _app
    if _app is None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        _app = WebFeedbackUI(prompt="", auto_resubmit_timeout=0).app
    return _app


class _LazyApplication:
    """WSGI callable that constructs the Flask app on first request."""

    def __call__(self, environ: Any, start_response: Any) -> Any:
        return create_app()(environ, start_response)


application = _LazyApplication()
