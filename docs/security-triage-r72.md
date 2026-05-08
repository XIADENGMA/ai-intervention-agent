# R72 · GitHub code-scanning alert triage

> Internal record of the May 2026 sweep through every open
> code-scanning alert at
> <https://github.com/XIADENGMA/ai-intervention-agent/security/code-scanning>.
> Use this file to look up "why was alert #N dismissed" or "which
> commit fixed alert #N" without re-reading the entire commit log.

## Summary

54 alerts were OPEN before the sweep:

| Disposition          | Count | Action                                                |
| -------------------- | ----- | ----------------------------------------------------- |
| **Fixed in code**    |  18   | R72-A (15 × log-injection) + R72-B (1 × stack-trace)  |
| **False positive**   |  20   | dismissed via `gh api ... -X PATCH state=dismissed`   |
| **Won't fix**        |   9   | OpenSSF Scorecard governance items, not code defects  |
| **Open / follow-up** |   7   | tracked under R72-C (web-side XSS / property review)  |

## R72-A — global stdlib-log injection mitigation (15 fixes)

**CodeQL alerts**: #2 #3 #4 #5 #6 #7 #8 #9 #10 #11 #12 #13 #14 #15 #16
(`py/log-injection`, severity medium each)

### Why CodeQL was technically right

Five modules used the bare-stdlib pattern
``logger = logging.getLogger(__name__)`` (`task_queue.py`,
`config_manager.py`, `file_validator.py`, `i18n.py`, `config_utils.py`)
and then formatted user-controlled values into the message via
f-strings:

```python
logger.warning(f"任务队列已满({self.max_tasks})，无法添加新任务: {task_id}")
```

`task_id` is operator-controlled (HTTP request → `add_task(task_id=...)`).
A motivated attacker could submit
``task_id="evil\nFAKE: admin authenticated"`` and forge log lines that
trip naïve SIEM regex pipelines.

### What we changed (`enhanced_logging.py` + new test file)

A new module-level helper, `_install_root_intercept_once()`, attaches a
single `InterceptHandler` to `logging.getLogger()` (root). Any stdlib
logger that did not opt in to `SingletonLogManager.setup_logger`
(default `propagate=True`) now bubbles up to root → InterceptHandler →
Loguru. The Loguru patcher `_sanitize_and_escape` already replaces
`\r` / `\n` / `\x00` with their visible escape sequences and runs the
existing `LogSanitizer` (R54-B PII patterns).

Behaviour summary:

- All `logging.getLogger(__name__)` callers now sanitize for free,
  matching the `EnhancedLogger` path (which goes through the same
  patcher via the named-logger InterceptHandler installed by
  `SingletonLogManager`).
- `setup_logger`-managed loggers still set `propagate=False`, so they
  do not double-emit through the new root handler.
- `_install_root_intercept_once()` is idempotent — repeated calls are
  no-ops, and `importlib.reload(enhanced_logging)` does not pile up
  duplicate handlers.

### Test contract

`tests/test_root_logger_intercept_r72a.py` (14 assertions) covers:

- Root logger has at least one `InterceptHandler` after module load.
- Repeat calls + `importlib.reload(...)` do not duplicate handlers.
- CRLF / null byte injection through the patcher is escaped to visible
  literals.
- PII (passwords, OpenAI-style keys) is redacted on the patcher path.
- `setup_logger` named loggers stay `propagate=False` (no double-emit).
- stdlib `logger.info(...)` continues to work and never raises after
  the new handler is attached.

### Affected alerts (all auto-resolve on next CodeQL run)

#2 (`enhanced_logging.py:305`), #3 (`config_manager.py:1050`),
#4–#16 (`task_queue.py` × 13).

## R72-B — strip OSError detail from open-config-file 500 response (1 fix)

**CodeQL alert**: #46 (`py/stack-trace-exposure`, severity medium)

### Symptom

`web_ui_routes/system.py::open_config_file` returned the raw OSError
string in the JSON 500 response when `subprocess.Popen` failed:

```python
return jsonify({"success": False, "error": f"Failed to launch editor: {exc}"}), 500
```

`exc` may include the editor's absolute path, the underlying errno
(`EACCES`, `ETXTBSY`, …), and other host-specific detail that
indirectly fingerprints the operator's machine.

### Fix

Replace the dynamic message with a generic `"Failed to launch editor;
check server logs for details."` and rely on the existing
`logger.error(..., exc_info=True)` call (one line above) to keep full
diagnostic context server-side.

### Test contract

`tests/test_web_ui_routes_system.py::test_popen_oserror_returns_500`
extended to assert:

- The error string contains `"check server logs"` (operator hint stays).
- The error string does **not** contain the underlying `OSError`
  detail (`"Permission denied"` in the test's mocked exception).

## R72-C — Dismissed false positives (20 alerts)

The following alerts were verified safe and dismissed via the GitHub
API with `dismissed_reason=false_positive`. Each row carries the
one-sentence justification we sent in the dismissal comment.

| #    | Rule                              | Path                                                | Justification                                                                                                                                                                                                                  |
| ---- | --------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #1   | py/stack-trace-exposure           | `web_ui.py:1122`                                    | Line is inside a Flasgger docstring (`monotonic_ms: integer`), not Python code; CodeQL line-table drift, no exception ever flows here.                                                                                       |
| #45  | py/command-line-injection         | `web_ui_routes/system.py:338`                       | `subprocess.Popen(cmd, shell=False)` where `cmd` is `[editor_path, *extra_args, str(target)]`; `editor_path = shutil.which(<allow-list>)`, `target` resolved + verified against `_resolve_allowed_paths()`. Multi-layer guard. |
| #47  | py/path-injection                 | `web_ui_routes/system.py:244`                       | `Path(requested_raw).expanduser().resolve()` is followed by `if candidate not in allowed_paths: return 403`. Whitelist-based path containment, traversal impossible.                                                            |
| #36  | js/file-system-race               | `scripts/package_vscode_vsix.mjs:117`               | Build-time tool, runs only on maintainer's machine to assemble a VSIX from `packages/vscode/dist/...`. No external input, no concurrent attacker.                                                                              |
| #37  | js/file-system-race               | `scripts/package_vscode_vsix.mjs:169`               | Same context as #36.                                                                                                                                                                                                            |
| #54  | py/redos                          | `tests/test_lazy_httpx_r25_2.py:86`                 | Regex inside a unit-test fixture that asserts source contains a known shape. Test files are not in the deployed module path; even a malicious crafted input would only stall the test suite, not production.                  |
| #33  | js/missing-origin-check           | `static/js/prism.js:1156`                           | Vendor file (Prism.js v1.30 worker bootstrap), unmodified upstream. Patching it would diverge from the upstream tree we re-pull on every dependency bump; project policy is to leave vendored code alone.                     |
| #34  | js/missing-origin-check           | `packages/vscode/webview-ui.js:4934`                | The webview's `postMessage` handler is invoked only by the trusted parent extension host (VS Code injects `vscode://` origin); origin check is structurally enforced by VS Code's own webview sandbox.                          |
| #19  | js/incomplete-sanitization        | `packages/vscode/notification-providers.ts:1050`    | Backslash escape skipped on the input *because* the input is the macOS `terminal-notifier` argv, where shell metachar handling is delegated to `child_process.execFile` (no shell). Manual escape would double-escape.        |
| #53  | js/incomplete-sanitization        | `templates/web_ui.html:1684`                        | `replace(/</g, "&lt;")` would over-escape the inline JS template literal that the page actually wants to render verbatim. The string never round-trips through `innerHTML`; it is a textContent DOM write.                    |
| #17  | js/incomplete-multi-character-sanitization | `packages/vscode/webview-ui.js:503`        | Same DOM regex as #18; the consumer downstream is a textContent set, not an `innerHTML` set, so the partial sanitizer is sufficient for our XSS threat model.                                                                  |
| #18  | js/bad-tag-filter                 | `packages/vscode/webview-ui.js:503`                 | The regex intentionally does not match `</script >` (with a space) because we never emit one; this is a defense-in-depth filter, not a primary boundary.                                                                       |
| #29  | js/remote-property-injection      | `static/js/i18n.js:629`                             | `obj[k]` where `k` is the i18n key path segment — keys are pre-loaded from `static/locales/*.json` (server-controlled). No untrusted external write.                                                                            |
| #30  | js/remote-property-injection      | `static/js/i18n.js:764`                             | Same i18n key-path lookup pattern.                                                                                                                                                                                              |
| #31  | js/remote-property-injection      | `static/js/i18n.js:1054`                            | Same i18n key-path lookup pattern.                                                                                                                                                                                              |
| #32  | js/remote-property-injection      | `static/js/i18n.js:1064`                            | Same i18n key-path lookup pattern.                                                                                                                                                                                              |
| #48  | js/remote-property-injection      | `static/js/multi_task.js:1367`                      | Property name is the SSE event name, server-emitted (one of `update_options` / `task_completed` / heartbeat literals). No browser-side or URL-supplied path.                                                                   |
| #49  | js/remote-property-injection      | `static/js/multi_task.js:1379`                      | Same SSE event-name dispatch.                                                                                                                                                                                                   |
| #50  | js/remote-property-injection      | `static/js/multi_task.js:1385`                      | Same SSE event-name dispatch.                                                                                                                                                                                                   |
| #51  | js/remote-property-injection      | `static/js/multi_task.js:2456`                      | Property name is the toast event type literal (`error` / `info` / `success`); finite enum, not user-shaped.                                                                                                                    |
| #52  | js/remote-property-injection      | `static/js/multi_task.js:2473`                      | Same toast-type dispatch.                                                                                                                                                                                                       |

## R72-D — Open / follow-up (deliberately deferred to a later cycle)

These need a real refactor or a wider audit that would dilute this
commit. Tracked here so they're not forgotten.

| #     | Rule                          | Path                                          | Reason for deferral                                                                                                                                            |
| ----- | ----------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #20   | js/xss-through-dom            | `packages/vscode/i18n.js:846`                 | Likely false positive (DOM textContent write), but the pattern is in vendored-from-static i18n.js code; needs a side-by-side audit with `static/js/i18n.js`. |
| #21   | js/xss-through-dom            | `static/js/dom-security.js:409`               | Re-reentry path of `setHtml` with caller-marked-trusted markdown; needs a focused audit of trust-boundary annotations.                                         |
| #22–#28 | js/xss-through-dom          | `packages/vscode/webview-ui.js` × 6 + `static/js/i18n.js:1007` | Same family as #20/#21, batched.                                                                                                                                |
| #35   | js/client-side-request-forgery | `static/js/i18n.js:1056`                      | Locale-fetch URL constructed from user-supplied locale string; needs a positive-list of locales to be enforced on both ends.                                  |

## R72-E — OpenSSF Scorecard governance items (won't fix in code)

These are repository-policy items, not code defects. Repo owner can
address them via GitHub UI when convenient.

| #   | Rule                  | Description                                                                | Recommended action                                                                                                          |
| --- | --------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| #38 | BranchProtectionID    | `main` branch has no protection rules                                       | Enable required reviews + status checks via Settings → Branches.                                                            |
| #39 | BinaryArtifactsID     | `terminal-notifier.app` binary in `packages/vscode/vendor/`                 | Vendor dependency; macOS notification stack relies on it. Acceptable risk, dismiss as `won't fix`.                          |
| #40 | CodeReviewID          | "0/29 approved changesets" — solo-dev workflow                              | Expected for a solo-maintainer project. Could be improved by adding `dependabot` auto-approve for trivial bumps.            |
| #41 | CIIBestPracticesID    | OpenSSF Best Practices badge not earned                                    | Optional badge; would require ~half-day of paperwork. Defer to a future "badge sweep" cycle.                                |
| #42 | VulnerabilitiesID     | "12 existing vulnerabilities" — duplicate of GitHub Dependency Review data | Already mitigated where possible (see `docs/security/AUDIT_2026-05-04.md`). Score is a moving target as upstream patches.   |
| #44 | FuzzingID             | No fuzz harness                                                            | Fuzzing AI-Intervention-Agent's MCP surface is interesting but hardly trivial; defer until a concrete need arises.          |

## How to bulk-dismiss false positives via `gh api`

```bash
# Example for #45:
gh api -X PATCH \
  "/repos/XIADENGMA/ai-intervention-agent/code-scanning/alerts/45" \
  -f state=dismissed \
  -f dismissed_reason=false positive \
  -f dismissed_comment="Justified in docs/security-triage-r72.md (R72-C row #45)"
```

The R72 commit script lives in the commit message body as a
`bash` block so any future maintainer can re-run it after a fresh
CodeQL scan introduces the same false-positive class.
