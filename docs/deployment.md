# Deployment Profiles

AI Intervention Agent has two supported Web UI profiles.

## Local Desktop Profile

This is the default. `WebFeedbackUI.run()` keeps using Flask's built-in server
with `debug=False` and `use_reloader=False`. It is optimized for the normal MCP
workflow: start quickly, bind to the configured local/LAN address, serve one
user, then shut down cleanly.

Use this profile for local CLI, `uvx`, VS Code, Cursor, Claude Desktop, and SSH
tunnel workflows.

## WSGI / Reverse Proxy Profile

Use this only when the Web UI is long-running, remotely accessed, supervised by
systemd, or placed behind nginx / Apache / a corporate proxy. Flask's own
deployment docs are explicit that the development server is for local
development, not production, stability, or efficiency.

Install a WSGI server next to the package and point it at the lazy factory.
Waitress is a good Windows / simple-deployment option, and its docs expose
thread and connection tuning knobs. Do not assume SSE health from a normal
request; always verify the stream with `curl -N /api/events` in the target
profile.

```bash
python -m pip install ai-intervention-agent waitress
waitress-serve --listen=127.0.0.1:8080 --threads=8 --call 'ai_intervention_agent.web_ui_wsgi:create_app'
```

On POSIX hosts with long-lived connections or many concurrent SSE clients,
prefer Gunicorn with gevent or an equivalent async worker. Keep a single worker
process because the task queue and SSE bus are currently in-process memory:

```bash
python -m pip install ai-intervention-agent gunicorn gevent
gunicorn 'ai_intervention_agent.web_ui_wsgi:create_app()' \
  --bind 127.0.0.1:8080 \
  --workers 1 \
  --worker-class gevent \
  --worker-connections 100 \
  --timeout 0
```

Do not run multiple worker processes unless a future release introduces an
external task queue backend. Multiple workers would each have their own task
queue and SSE bus, so a task created in one worker could be invisible to a
browser connected to another.

## SSE Proxy Requirements

`/api/events` is a Server-Sent Events stream. Reverse proxies must not buffer it.
The route already emits:

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `X-Accel-Buffering: no`

nginx still needs explicit proxy settings:

```nginx
location /api/events {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
}
```

If you expose the Web UI outside loopback, keep `network_security.allowed_networks`
as narrow as possible and prefer SSH tunnels when feasible. The live settings API
must be able to round-trip existing notification configuration, so it is not a
secret-redacted public API.

## Validation Checklist

Run these before treating a deployment change as healthy:

```bash
curl -i http://127.0.0.1:8080/api/system/health
curl -N http://127.0.0.1:8080/api/events
uv run pytest -q tests/test_web_ui_wsgi_profile_r452.py tests/test_sse_last_event_id_r41.py
```

For browser-heavy sessions, the Web UI shares one EventSource across same-origin
tabs when `BroadcastChannel` is available. This avoids the HTTP/1.x per-browser /
per-domain SSE connection limit documented by MDN, while retaining direct SSE as
the fallback when `BroadcastChannel` is missing.

Reference docs used for this profile: Flask's production deployment guide,
Flask's Gunicorn/gevent deployment pages, Waitress' runner options, and MDN's
Server-Sent Events connection-limit note.
