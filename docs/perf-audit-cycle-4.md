# Performance Audit Cycle 4

Date: 2026-06-21

This round continues the optimization audit after the trusted-host/dependency
audit batch. The goal was to find non-duplicate opportunities that are
testable, edge-case aware, and backed by local plus external evidence.

## Evidence Gathered

Local evidence:

- `scripts/perf_e2e_bench.py` already measures cold import, Web UI
  construction/setup, socket readiness, HTML render, and API round trips while
  capturing environment metadata.
- `scripts/perf_gate.py` already compares benchmark output against a baseline
  with percent and absolute noise floors.
- `.github/workflows/vscode.yml` runs VS Code lint, test, and package for
  extension changes.
- `.github/workflows/release.yml` built the release VSIX with package-only
  `npm run vscode:package`; that artifact is the one later published to VS Code
  Marketplace and Open VSX.
- `packages/vscode/webview.ts` kept local resource roots tight and already used
  `asWebviewUri` for extension assets, but webview-side API fetches used the
  configured `serverUrl` directly in CSP/meta.
- `tests/test_tool_annotations.py` already locks MCP tool annotations:
  `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=false`, and
  `openWorldHint=true`.
- VSIX packed-size and heavy-asset budgets already exist in
  `scripts/package_vscode_vsix.mjs`, `tests/test_vscode_vsix_size_budget.py`,
  and `tests/test_vscode_heavy_asset_budget_r452.py`.

External evidence:

- `/tmp/smart-search-evidence/aiia-optimization-next/02-vscode-webview-exa.json`
  contains VS Code official documentation text: webviews are resource-heavy,
  `webview.html` replacement resets script state, local resources should use
  `asWebviewUri`, `localResourceRoots` restricts local filesystem access, and
  direct `localhost` from webview content is not reliable for Remote
  Development / Codespaces. VS Code recommends message passing when possible
  and `vscode.env.asExternalUri` as a workaround for webview access to local
  HTTP servers.
- `/tmp/smart-search-evidence/aiia-optimization-next/06-context7-flask-docs.json`
  contains Flask official snippets for `stream_with_context()` and `send_file`
  cache defaults. Current SSE/static asset work already has focused local
  coverage, so these did not become new implementation rows.
- `/tmp/smart-search-evidence/aiia-optimization-next/04-mcp-search.json`
  surfaced official MCP security/tool-annotation sources, but the local code
  already implements and tests the relevant annotation contract.
- `/tmp/smart-search-evidence/aiia-optimization-next/09-npm-pretest-lifecycle.json`
  contains npm official documentation: `npm test` runs `pretest`, then `test`,
  then `posttest`. That matters because the VS Code workspace `pretest` already
  runs compile and lint before `vscode-test`.

## Shipped Changes

### 1. Release VSIX Gate Parity

The release build now validates the extension before uploading the VSIX artifact:

- `sudo apt-get update && sudo apt-get install -y xvfb`
- `xvfb-run -a npm run vscode:check`

This keeps the published VSIX on the same lint/test/package surface as the
dedicated VS Code workflow while preserving the existing artifact upload and
publish jobs. The release workflow intentionally does not run a separate
`npm run vscode:lint` step: `npm run vscode:check` reaches the workspace
`npm test`, and npm runs that workspace's `pretest` first; the `pretest` script
already runs `npm run compile && npm run lint`.

Guard:

- `tests/test_release_workflow_vscode_gate_parity_r453.py`

Verification run:

```bash
uv run pytest tests/test_release_workflow_vscode_gate_parity_r453.py -q
```

### 2. Remote-Safe Webview Server URL

The extension now separates two URL concerns:

- Extension-host paths keep using direct `serverUrl` for status polling and SSE.
- Webview/browser paths use cached `_webviewServerUrl`, refreshed through
  `vscode.env.asExternalUri(vscode.Uri.parse(...))` when VS Code can provide a
  forwarded URL.

Fallback behavior is explicit: if forwarding fails or is unavailable, the
webview keeps the direct normalized URL so local desktop sessions remain
functional. The URL is normalized without a trailing slash because frontend
modules build endpoints with `SERVER_URL + "/api/..."`.

Guards:

- `tests/test_vscode_webview_remote_server_url_r453.py`
- `packages/vscode/test/extension.test.js`

Verification run:

```bash
uv run pytest tests/test_vscode_webview_remote_server_url_r453.py -q
npm -w ai-intervention-agent run lint
```

### 3. Machine-Aware Perf Report Wrapper

`scripts/perf_report.py` now composes the existing benchmark and gate into one
JSON report. It records:

- command and schema version
- benchmark metadata and environment
- benchmark summaries
- benchmark errors
- optional baseline verdict
- exit policy

Numeric regressions are report-only by default. They become process-failing only
with `--fail-on-regression`, intended for comparable hardware. Benchmark errors
still fail because they prove the measurement itself is broken.

Guard:

- `tests/test_perf_report_r453.py`

Verification run:

```bash
uv run pytest tests/test_perf_report_r453.py -q
uv run python scripts/perf_report.py --help
```

Example local report:

```bash
uv run python scripts/perf_report.py --quick --output /tmp/aiia-perf-report.json
```

## Explicit Non-Changes

- SSE bus hot paths were not changed. The repository already has SSE stats,
  history, cache, and cross-process performance tests plus docs. A new change
  there would need a measured regression or a missing invariant, not just a
  general desire to optimize.
- MCP tool annotations were not changed because the local implementation and
  tests already match the relevant best-practice contract.
- VSIX packed-size limits were not changed because packed-size and known
  heavy-asset budgets are already guarded. The next meaningful step would be
  product-level optionalization of offline assets, not another threshold test.
- Cross-hardware CI median performance hard gates were not added. The existing
  comments in `perf_e2e_bench.py` correctly identify this as noisy across
  GitHub-hosted runners. Cycle 4 instead adds machine-aware reporting and an
  explicit opt-in hard-fail mode.

## Remaining Follow-Ups

- Consider a future host-mediated message-passing API for webview data access if
  Remote/Codespaces usage becomes a primary product target. `asExternalUri` is
  the lower-risk compatibility improvement; message passing is a larger
  architecture change.
- Consider scheduled/local-maintainer perf report artifacts for trend review,
  using stable hardware and `--fail-on-regression` only after enough samples
  establish noise bounds.
- If release duration becomes a problem after adding VS Code tests, split the
  release build into a reusable validated-VSIX artifact from the dedicated
  workflow instead of weakening validation.

## Issue Workflow

Plan:

- `plan/2026-06-21_02-47-28-aiia-optimization-audit-round-2.md`

Issue CSV:

- `issues/2026-06-21_02-47-28-aiia-optimization-audit-round-2.csv`
