# Security Policy

> English | [简体中文](./SECURITY.zh-CN.md)

## Supported versions

Only the **latest minor** on the `main` branch receives security fixes. Older
minors are end-of-life the moment a new minor is published on PyPI / Open VSX /
VS Code Marketplace.

| Version | Status          |
| ------- | --------------- |
| 1.6.x   | ✅ Supported     |
| < 1.6   | ❌ End-of-life   |

If you need a backport to an older line, open a discussion first — we evaluate
case by case based on CVSS and exposure.

## Reporting a vulnerability

**Do not open a public GitHub issue for security problems.**

Preferred channel (private, triageable, audit-logged):

1. Go to the [Security tab → "Report a vulnerability"][ghsa] on GitHub; this
   opens a private advisory only the maintainers can see.
2. Include: affected component (Web UI / VSCode extension / MCP server /
   AppleScript executor), version, reproduction, and the impact you observed
   (RCE / XSS / secret leak / DoS / etc.).
3. If PoC requires binary blobs or screenshots, attach them inside the private
   advisory — avoid pasting them to public channels.

Fallback channel if GitHub is unavailable: email the maintainer via the address
listed on the GitHub profile `@xiadengma`. Please tag the subject with
`[SECURITY] ai-intervention-agent`.

## Disclosure policy

- Acknowledgement target: within **72 hours**.
- Triage + fix ETA: shared within **7 days** of acknowledgement.
- Coordinated disclosure: a GitHub Security Advisory is published once a fix
  reaches users (PyPI / Marketplace / Open VSX). We credit reporters in the
  advisory unless anonymity is requested.

## Hardening recommendations for non-loopback deployments

The default deployment (`make run` / `uvx ai-intervention-agent`) binds the
Web UI to `127.0.0.1` and only accepts loopback traffic. If you intentionally
bind to a non-loopback address — e.g. via
`AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0` for SSH-remote / LAN access — the
following endpoints become reachable by anyone on the same network and
include user-specific credentials in their responses:

- `GET /api/get-notification-config` — full `notification` config including
  `bark_device_key` (Bark push device token).
- `GET /api/get-feedback-prompts` — your saved feedback prompt library.

These endpoints intentionally **do not** auto-redact at the HTTP boundary so
the built-in Settings panel can round-trip existing values. If you bind
outside loopback you must compensate at another layer:

1. Set `network_security.allowed_networks` in `config.toml` to the smallest
   CIDR you actually trust (e.g. `["192.168.1.0/24"]`). This is a separate,
   stricter ACL than the `*_WEB_UI_HOST` env var and is not overridden by
   it.
2. Prefer `ssh -L 18080:127.0.0.1:18080 user@remote` tunnels over binding
   to `0.0.0.0`. Same UX, zero exposure.
3. For ad-hoc inspection without a UI session, the CLI
   `ai-intervention-agent --print-config` auto-redacts secret-like keys
   (`*_device_key`, `*_token`, `*_secret`, `password`, `*_api_key`, …) so
   you can safely paste its output into chat/issues; the HTTP API
   intentionally does not.

These three layers (bind interface, `network_security.allowed_networks`, SSH
tunnel) are independent — pick whichever matches your threat model. If you
need stricter API-boundary redaction (e.g. you publish a kiosk-style UI),
open a discussion so we can prioritize a per-endpoint redaction policy
without breaking the round-trip Settings flow.

## Out of scope

- Vulnerabilities in direct or transitive dependencies — please report them
  upstream; Dependabot already auto-PRs patch/minor bumps into this repo.
- Issues requiring local shell / filesystem write access the user already has
  (the AppleScript executor is intentionally local-only and gated by macOS
  permissions — see the **AppleScript executor security model** section of
  [`packages/vscode/README.md`](../packages/vscode/README.md) for the full
  safeguard list).
- Social engineering of maintainers.

[ghsa]: https://github.com/xiadengma/ai-intervention-agent/security/advisories/new
