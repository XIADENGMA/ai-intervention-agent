"""Optional WSGI entrypoint for long-running / reverse-proxied Web UI deployments.

The default local path remains ``WebFeedbackUI.run()``, which uses Flask's
development server for a short-lived desktop workflow. This module exists for
operators who want to run the same Flask app behind Waitress, Gunicorn, uWSGI,
or a reverse proxy.

Important: the task queue is in-process memory. Use one worker process unless a
future release introduces an external queue backend.

The app is built with the settings the MCP server hands the Web UI it starts as
command-line arguments (``network_security.bind_interface``, ``web_ui.port``,
``web_ui.external_base_url``, ``mdns.hostname`` and
``network_security.trusted_hosts``), read once when the app is first built: the
``Host`` names the Web UI accepts are made from them.
"""

from __future__ import annotations

import threading
from typing import Any

_app: Any | None = None
_app_lock = threading.Lock()


def _web_ui_arguments() -> dict[str, Any]:
    """The address settings of ``WebFeedbackUI``, read as the MCP server reads them.

    ``service_manager.get_web_ui_config()`` is what builds the command line of the
    Web UI process the MCP server starts, environment overrides included, so the
    two profiles accept the same ``Host`` names.  An unreadable configuration must
    not keep a supervised server from starting: the app then starts on the
    defaults (loopback and the default mDNS name), which refuse any other name.
    """
    from ai_intervention_agent.service_manager import get_web_ui_config

    try:
        config, _auto_resubmit_timeout = get_web_ui_config()
    except ValueError as exc:
        from ai_intervention_agent.enhanced_logging import EnhancedLogger

        EnhancedLogger(__name__).warning(
            f"读取 Web UI 配置失败，WSGI 应用按默认值启动"
            f"（只接受回环地址和默认的 mDNS 名称作为 Host）: {exc}"
        )
        return {}
    return {
        "host": config.host,
        "port": config.port,
        "external_base_url": config.external_base_url,
        "mdns_hostname": config.mdns_hostname,
        "trusted_hosts": list(config.trusted_hosts),
    }


def create_app() -> Any:
    """Return the Web UI Flask app for WSGI servers.

    The import is intentionally lazy so ``import ai_intervention_agent.web_ui_wsgi``
    stays cheap and side-effect-light. WSGI servers that support factory syntax
    should prefer ``--call ai_intervention_agent.web_ui_wsgi:create_app`` or
    ``'ai_intervention_agent.web_ui_wsgi:create_app()'``.

    The app is built once, under a lock: threads that make their first request
    together share one app instead of each building their own.
    """

    global _app
    if _app is None:
        with _app_lock:
            if _app is None:
                from ai_intervention_agent.web_ui import WebFeedbackUI

                _app = WebFeedbackUI(
                    prompt="", auto_resubmit_timeout=0, **_web_ui_arguments()
                ).app
    return _app


class _LazyApplication:
    """WSGI callable that constructs the Flask app on first request."""

    def __call__(self, environ: Any, start_response: Any) -> Any:
        return create_app()(environ, start_response)


application = _LazyApplication()
