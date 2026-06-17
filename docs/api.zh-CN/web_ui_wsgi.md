# web_ui_wsgi

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/web_ui_wsgi.md`](../api/web_ui_wsgi.md)

Optional WSGI entrypoint for long-running / reverse-proxied Web UI deployments.

The default local path remains ``WebFeedbackUI.run()``, which uses Flask's
development server for a short-lived desktop workflow. This module exists for
operators who want to run the same Flask app behind Waitress, Gunicorn, uWSGI,
or a reverse proxy.

Important: the task queue is in-process memory. Use one worker process unless a
future release introduces an external queue backend.

## 函数

### `create_app() -> Any`

Return the Web UI Flask app for WSGI servers.

The import is intentionally lazy so ``import ai_intervention_agent.web_ui_wsgi``
stays cheap and side-effect-light. WSGI servers that support factory syntax
should prefer ``--call ai_intervention_agent.web_ui_wsgi:create_app`` or
``'ai_intervention_agent.web_ui_wsgi:create_app()'``.

## 类

### `class _LazyApplication`

WSGI callable that constructs the Flask app on first request.

#### 方法
