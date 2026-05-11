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
