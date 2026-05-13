# Code Review #16 — `v1.6.4` follow-ups, cycle 2

> Scope: 5 commits between `685c133` (CR#15 archived) and `246accc`
> (silent-failure baseline restored), 2026-05-12.
> Themes: completing the env-override → CLI → health-endpoint
> observability loop, landing R185 (Dependabot CVE gate), syncing
> the new entry points to docs/Makefile, and a same-cycle hotfix
> for an R120 baseline regression.

## 1 Commits at a glance

| #   | SHA       | Type         | Lines  | Purpose                                                                                                                                              |
| --- | --------- | ------------ | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `36cdc72` | `:sparkles:` | +400   | `/api/system/health` adds `web_ui_env_overrides` field + 11 guard tests                                                                              |
| 2   | `a37e17d` | `:sparkles:` | +950   | R185 opt-in Dependabot CVE gate (`--check-cve`/`--cve-severity`/`--allow-cve`) + 32 tests + markdownlint cleanup of CHANGELOG R184 region            |
| 3   | `288b7fb` | `:memo:`     | +206   | R185 docs sync: Makefile `release-check-cve` target, `scripts/README.md` index entry, bilingual `docs/release-recovery.{md,zh-CN.md}`, 8 guard tests |
| 4   | `cf2555c` | `:sparkles:` | +448   | CLI `--print-config` flag + 11 guard tests + bilingual README & docs/configuration updates                                                           |
| 5   | `246accc` | `:wrench:`   | +13/-4 | Hotfix: downgrade two `except Exception: pass` in `_print_effective_config` to `logger.debug(...)` to satisfy R120 baseline (5106 passed)            |

Total: ~2.0k lines net (`+2017 / -342` if I subtract the markdownlint
normalization from R184 region in `a37e17d`). Tests added across the
cycle: **62** (11 + 32 + 8 + 11). Final suite: **5106 passed, 2
skipped, 620 subtests**.

## 2 Architectural narrative

This cycle deliberately tightened the **observability loop** opened
by CR#15:

```
config.toml + env vars        →     get_web_ui_config()  →  bound socket
                                       (10s TTL cache)
                                            │
                                            ▼
                                   web_ui.host:port:lang
                                            │
                                            ├─→ /api/system/health   [#1 36cdc72]
                                            │     ↳ web_ui_env_overrides field
                                            │       (K8s probe / curl | jq)
                                            │
                                            └─→ --print-config        [#4 cf2555c]
                                                  ↳ same shape, stdout JSON
                                                    (developer / debug)
```

The user's actual question we're optimising for is _"why is my port
8181 instead of 8080?"_. CR#15 added the env-override CLI surface but
left the user without a way to **introspect** the running answer. This
cycle closes both surfaces (health endpoint for live process, CLI for
next-restart) with intentionally redundant outputs and a shared
trust contract (`network_security` filtered out by
`ConfigManager.get_all()`).

Orthogonally, R185 (Dependabot CVE gate) was landed because it had
been sitting in the working tree across 7+ commits — CR#15 explicitly
flagged that "cohabitation" as a coupled-changes risk. Landing it in
this cycle (commits #2 + #3) eliminated the risk.

## 3 What went well

### 3.1 Helper-function reuse: `_safe_web_ui_env_overrides` / `_print_effective_config`

Both new surfaces share the **same** env-override whitelist logic, but
they don't share code. That's a deliberate trade-off:

- `_safe_web_ui_env_overrides()` lives in `web_ui_routes/system.py` and
  is called inside the `system_health()` handler — strict R53-F
  contract: handler body can't touch `os.environ` directly.
- `_print_effective_config()` lives in `server.py` and can call
  `os.environ.get(...)` directly because it's a CLI dump function, not
  an HTTP handler.

Both functions hardcode the same 3-name whitelist
(`_ENV_WEB_UI_HOST`/`_PORT`/`_LANGUAGE`) sourced from
`service_manager` constants. The whitelist parity is **invariant-
tested** in `tests/test_health_env_overrides.py::
TestSafeWebUiEnvOverridesWhitelisted::
test_dict_keys_match_service_manager_constants`. If a future
contributor adds a new env override to `service_manager` but forgets
either of these two surfaces, the test fails with a specific
"key set mismatch" error. **High-confidence drift detection.**

### 3.2 R185 byte-identity guarantee

`check_tag_push_safety.py --check-cve` defaults to `False` —
`argparse.BooleanOptionalAction` makes `--check-cve` and
`--no-check-cve` both valid CLI verbs. Critically, every existing
`make release-check` call site (CI workflows, contributor docs, even
internal usage) is **byte-identical** post-merge. The R185 entry in
CHANGELOG explicitly calls out this property — and `make release-check`
in the repo still resolves to the exact same command as before.

Future contributors can opt into the CVE gate via the new
`make release-check-cve` shortcut (commit #3 documented this in
`Makefile` + `scripts/README.md` + bilingual recovery docs +
`tests/test_r185_docs_sync.py`).

### 3.3 Same-cycle hotfix (#5)

When `cf2555c` introduced two `except Exception: pass` sites, R120's
silent-failure regression guard caught them in the next full-suite
run. The fix was landed **inside the same cycle** (commit #5) with:

- explanatory commit body that anchors the fix to R107-R119 doctrine,
- inline `logger.debug(...)` calls that double as failure-mode
  documentation,
- a 1-line comment per except explaining **why** the partial-payload
  fallback is safe (per R-series doctrine "every silent except
  documents its rationale"),
- verified `silent_failure_audit.py check` returns to baseline-27
  - same-cycle full-suite (5106 passed).

This is the textbook outcome for a regression: caught by guard, fixed
inside the cycle, doesn't bleed into the next CR.

### 3.4 Bilingual docs lockstep

Every doc change in this cycle landed in **both** `.md` and
`.zh-CN.md` simultaneously:

- `README.md` + `README.zh-CN.md` for the CLI inspection section
- `docs/configuration.md` + `docs/configuration.zh-CN.md` for the
  verification subsection
- `docs/release-recovery.md` + `docs/release-recovery.zh-CN.md` for
  the R185 callout

`tests/test_r185_docs_sync.py::TestReleaseRecoveryBilingualSync` enforces
that both files mention R185 + `--check-cve` + `release-check-cve` —
so if I (or any future contributor) updates only the English version,
pytest fails with a specific localised message.

### 3.5 CHANGELOG depth

Each entry follows the established "what + why + how" pattern with
explicit test-count references. The R185 entry in particular is one
of the longest in the changelog (~22 lines) but every line earns its
place: opt-in default rationale (OWASP/NIST), graceful-degradation
list, 32-test coverage breakdown, `gh` CLI prerequisites.

## 4 What could be improved

### 4.1 F-1 · `--print-config` doesn't expose `mdns` / `feedback` sections

The current dump only includes `web_ui` because that's the section
with env overrides. But users debugging "why doesn't mDNS work?" would
benefit from seeing `mdns.enabled` / `mdns.hostname` too. Two
options:

(a) Expand `--print-config` to include all non-sensitive sections
(`web_ui`, `mdns`, `feedback`, `notification`).
(b) Add a `--print-config <section>` arg variant.

(a) is simpler and consistent with `ConfigManager.get_all()` already
exposing everything except `network_security`. **Recommended for the
next cycle.**

### 4.2 F-2 · R185 `gh api` rate-limit handling not tested

The R185 graceful-degradation list covers "missing gh CLI",
"non-GitHub remote", "Dependabot disabled", but **not** "gh API rate
limit hit". `gh` returns a non-zero exit with a body like
`HTTP 403: API rate limit exceeded` — currently the code path falls
into the JSON-parse-failure branch (which is "pass with log"), so
behaviour is correct, but there's no explicit test for it.

Adding `tests/test_check_tag_push_safety_cve_gate_r185.py::
TestRateLimit::test_gh_rate_limit_passes_with_warning` would document
the exact behavior. **Low priority** since the existing graceful-
degradation pattern already covers it, but worth adding for
documentation value.

### 4.3 F-3 · `--print-config` could expose `config_file_path` for non-loaded configs

When `ConfigManager` falls back to the bundled default `config.toml`
(no user config file found), `config_file_path` is the bundled path
— which is correct, but misleading for "I haven't created
`~/.config/ai-intervention-agent/config.toml` yet" debugging. The
output could additionally include a top-level `using_defaults: bool`
field so users see _"I'm running on built-in defaults"_ at a glance.

Implementation: ~5 lines in `_print_effective_config()`, ~3 test cases.
**Recommended F-3** for the next cycle as part of the
"`--print-config` polish" workstream alongside F-1.

### 4.4 F-4 · Markdownlint normalization should be a one-shot, not riding R185

`a37e17d` rolled in `CHANGELOG.md` markdownlint normalization (`* `
→ `- `, `*emph*` → `_emph_`) that had been sitting in the working
tree for 7+ commits. That made the R185 commit larger than it needed
to be (645 lines of churn that's a no-op for renderers).

Should have been a dedicated `:art: chore(changelog): normalize
markdownlint formatting in v1.6.4 R184 region` commit **before**
landing R185. CR#15 actually called this out as a future
improvement; F-4 is to **enforce** this split via a pre-commit
hook that fails if a single commit changes >100 lines of `CHANGELOG.md`
in a non-`[Unreleased]` region. (The R184 region had been released
already, so the changes were renderer-equivalent edits to historic
sections.)

### 4.5 F-5 · `_print_effective_config` failure-mode test uses subprocess-mock pattern but `service_manager` is a TTL cache

The new `tests/test_server_print_config.py::
TestPrintConfigReflectsEnvOverrides` correctly invalidates
`service_manager._config_cache` in `setUp()` and per-test. That's
the right pattern, but it requires reaching into a private
attribute (`_config_cache`) — a public `service_manager.
invalidate_web_ui_config_cache()` helper would be cleaner.

Implementation: add a 3-line public function in `service_manager.py`,
update the test to use it. **Low priority cleanup**; current test is
correct, just slightly fragile to internal `_config_cache` shape
changes.

## 5 Static contract audit

Re-verified the R-series contracts that this cycle's changes
touch:

| Contract                                                  | Status                            | Evidence                                                                                                                                                     |
| --------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **R53-F** "no config-value passthrough in health handler" | ✅ preserved                      | `system_health()` only calls `_safe_*` helpers; new `_safe_web_ui_env_overrides()` follows pattern                                                           |
| **R120** silent-failure baseline                          | ✅ baseline=27 (was 27 pre-cycle) | commit #5 hotfix returns to baseline                                                                                                                         |
| **R121-A** health payload field whitelist                 | ✅ expanded with type assertions  | `tests/test_web_ui_routes_system.py::TestSystemHealthEndpoint::test_payload_carries_no_sensitive_fields` adds dict[str,str] guard for `web_ui_env_overrides` |
| **R178** docs i18n lockstep                               | ✅ all 3 doc pairs synced         | `tests/test_r185_docs_sync.py::TestReleaseRecoveryBilingualSync` enforces                                                                                    |
| **R19.1** tag-push safety                                 | ✅ unchanged default behaviour    | `--check-cve` default OFF; bytes-identical to pre-R185                                                                                                       |
| **CR#15 F-3** entry-point wiring                          | ✅ unchanged                      | `_cli_main` still the `console_script` target; new `--print-config` flag is parsed _inside_ `main()`                                                         |

## 6 Suggested follow-ups (ordered)

1. **F-1** — `--print-config` includes all non-sensitive sections
   (mdns/feedback/notification). _est. 2h, low-risk_
2. **F-3** — `--print-config` shows `using_defaults: bool`. _est.
   30m, low-risk_
3. **F-5** — public `invalidate_web_ui_config_cache()` helper.
   _est. 15m, cleanup_
4. **F-2** — explicit rate-limit test for R185. _est. 30m,
   documentation_
5. **F-4** — pre-commit hook for "large CHANGELOG diff in
   non-Unreleased region". _est. 1h, governance_

If next cycle picks 1-3 it'd be ~3h of focused work for solid UX
polish; 4-5 are nice-to-have governance improvements.

## 7 Versioning recommendation

Cumulative public-surface changes across CR#15 + CR#16:

- Three new env vars (`AI_INTERVENTION_AGENT_WEB_UI_HOST`/`_PORT`/`_LANGUAGE`)
- Three new CLI flags (`--version` / `--help` / `--print-config`)
- One new health-endpoint field (`web_ui_env_overrides`)
- One new release-check flag family (`--check-cve` / `--cve-severity` /
  `--allow-cve`) + Makefile target (`release-check-cve`)

By SemVer that's clearly **MINOR**, not PATCH. Recommend:

- Bump to `v1.7.0` once this cycle is reviewed and stable.
- v1.7.0 release notes should headline the
  **env-override + CLI + health-endpoint observability triangle** —
  it's the cohesive user-facing improvement of the cycle, not the
  individual flags.

Alternatively, ship the cycle's loop as `v1.6.5` (PATCH) **if** the
project intentionally treats env vars as "non-breaking addition" and
the SemVer reading is "no behaviour change for users who don't touch
the new surfaces". The SemVer spec is ambiguous here — both
interpretations exist in practice.

**Recommendation**: `v1.7.0`. The cumulative surface area genuinely
warrants it, and a MINOR bump signals to users that the observability
story has materially improved.

---

_Authored 2026-05-12. Archive this file when v1.7.0 (or v1.6.5) is
cut, mirroring the CR#15 archival pattern._
