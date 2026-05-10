/**
 * R146 — Settings UI button: trigger system-level notification self-test.
 *
 * Background
 * ----------
 * R141 already shipped ``POST /api/system/notifications/test`` as an
 * **operations / monitoring** endpoint — it dispatches a synthetic
 * ``NotificationEvent`` through the live ``NotificationManager`` config
 * and returns ``event_id`` + the list of providers actually fired,
 * letting callers cross-reference ``GET /api/system/health``'s
 * ``checks.notification.stats`` (R142 per-provider stats / R143
 * ``last_error_class`` / R145 ``success_streak`` + ``failure_streak``)
 * to see whether the notification really reached its destination.
 *
 * Up to R145 the only way to actually call the endpoint was to ``curl``
 * it — fine for ops dashboards, not great for end-users who just want
 * to confirm "did Bark / desktop / sound actually work after I changed
 * the config?". R146 closes that loop with a single button in the
 * **Test functions** subgroup of the settings panel.
 *
 * Design principles
 * -----------------
 * - **Pure presentational module** — no business logic; the heavy
 *   lifting (provider-enable matrix / event dispatch / per-provider
 *   stats) is owned by R141-R145 on the server. This module is a
 *   ~150 LoC fetch wrapper + i18n glue + ARIA-correct status reporter.
 * - **Capture-phase isolation** — like R140 / R144, no global keydown
 *   handlers; we attach exactly one ``click`` listener on the
 *   ``#system-notification-test-btn`` element and nothing else.
 * - **Double-click guard** — ``button.disabled = true`` for the
 *   duration of the fetch; if the user mashes the button mid-flight
 *   we silently drop the duplicate. The R141 endpoint is already
 *   rate-limited at 6/min so even if a deliberate attacker bypassed
 *   ``disabled`` the server would 429 within seconds.
 * - **Graceful degradation** — every error path (network down /
 *   401/403/404/429/500) is mapped to a translatable status string;
 *   the button always re-enables in a ``finally`` block.
 * - **i18n aware** — all user-facing strings go through
 *   ``window.AIIA_I18N.t(key, params)`` with English fallback baked
 *   into the locale files. Provider list is rendered via
 *   ``formatList`` so localized "and" / "、" separators stay correct.
 * - **No global state** — no module-level mutable variables; safe to
 *   ``init()`` more than once (idempotent). The ``window``
 *   re-export exposes only pure helpers + the public ``init`` for
 *   tests / debugging, never internal state.
 * - **Aria-live="polite"** on the status element so screen readers
 *   announce the result without interrupting the user mid-input.
 */

(function () {
  "use strict";

  var BUTTON_ID = "system-notification-test-btn";
  var STATUS_ID = "system-notification-test-status";
  var PROBE_ID = "system-notification-test-probe";
  var ENDPOINT = "/api/system/notifications/test";
  var HEALTH_ENDPOINT = "/api/system/health";
  // Server's Flask-Limiter is 6/min on this route; we add a tiny
  // client-side cooldown to dampen accidental double-tap before the
  // server has a chance to 429.  AbortController on top of that.
  //
  // R151: bumped 600 → 1500. After R147 + R148, the user-visible
  // dispatch path is roughly:
  //   baseline fetch (≤1s) → POST dispatch (variable, often 1-2s)
  //   → probe wait (1.5s) → probe fetch (≤5s)
  //   ≈ 4-8s wall-clock total
  // The previous 600 ms was effectively zero relative to the
  // ``button.disabled = true`` window covering the same path. 1500 ms
  // is the minimum useful budget that survives a settings-panel
  // re-mount (where ``button.disabled`` resets but
  // ``data-last-click-ts`` survives via the DOM attribute round-trip),
  // keeping the cooldown defensive rather than decorative.
  var CLIENT_COOLDOWN_MS = 1500;
  // 60s hard cap on the fetch — well above realistic Bark RTT (~2s)
  // but short enough that a hung connection doesn't keep the button
  // disabled forever.
  var FETCH_TIMEOUT_MS = 60 * 1000;
  // R147: after a successful R141 dispatch, wait this long before
  // probing /api/system/health so the backend's async send
  // (Bark HTTP RTT ~1-2s, web/sound/system are local microsec) has
  // a fair chance to update per-provider stats. 1.5s covers the
  // typical Bark case; if the provider is slower, the probe simply
  // shows a "stale" verdict and the user can re-click.
  var PROBE_DELAY_MS = 1500;
  // 5s hard cap on the health probe — well above realistic /health
  // RTT (~10ms) but short enough that an unhealthy server doesn't
  // strand the user looking at "Probing..." forever.
  var PROBE_TIMEOUT_MS = 5 * 1000;
  // R147: when judging "is this provider stats reflective of the
  // self-test we just dispatched?", we look at last_event_age_seconds.
  // If the last event happened more than 10s ago, the dispatch most
  // likely missed (or got rejected) and the stats we're showing
  // belong to an older event. Empirically tuned: PROBE_DELAY_MS +
  // 5s headroom for slow networks / paused tabs.
  //
  // R148: the threshold is now only the **fallback** (when the
  // baseline snapshot is null / unreachable). With a baseline
  // available, classification is delta-based — see
  // ``_classifyProviderVerdict`` for the exact contract.
  var PROBE_STALE_THRESHOLD_S = 10;
  // R148: tight timeout for the **baseline** snapshot taken right
  // before the dispatch. We must not stall the user-visible
  // dispatch action by more than ~1 second waiting for the
  // baseline; on timeout we fall back to age-only classification
  // (R147 behaviour) without breaking anything.
  var BASELINE_TIMEOUT_MS = 1 * 1000;
  // R148: provider keys the server's per_provider dict is keyed on
  // — see ``_HEALTH_PER_PROVIDER_KEYS`` in
  // ``web_ui_routes/system.py``. We baseline **all four** because
  // we don't know yet which subset the dispatch will actually
  // touch (server inspects config at dispatch time). Locking this
  // tuple in source means a future server-side rename (e.g.
  // adding a new "discord" provider) will fail loud here rather
  // than silently degrading every probe to "stale".
  var ALL_KNOWN_PROVIDERS = ["bark", "web", "sound", "system"];
  // R150 — self-test history trail. Stored client-side in
  // localStorage so it survives reloads; cap at HISTORY_MAX_ENTRIES
  // entries (~200 bytes each → ~1 KiB total, well below the
  // 5–10 MiB localStorage budget every browser ships). Schema
  // versioned (``v: 1``) so a future R151 / R152 schema bump can
  // reject + drop incompatible old payloads instead of crashing.
  // Same competitive class as uptime-kuma / healthchecks.io
  // (a "last 5 self-test results" list under the trigger button).
  var HISTORY_LS_KEY = "aiia.self_test.history.v1";
  var HISTORY_MAX_ENTRIES = 5;
  var HISTORY_TOGGLE_ID = "system-notification-test-history-toggle";
  var HISTORY_LIST_ID = "system-notification-test-history-list";
  // Schema version embedded in every persisted entry. Bumping this
  // forces ``_loadHistory`` to drop every entry whose ``v !== 1`` so
  // a future shape change (extra field / renamed kind / etc.) can't
  // crash the renderer with stale localStorage payloads from an
  // older deploy.
  var HISTORY_SCHEMA_VERSION = 1;

  function _t(key, params) {
    try {
      var i18n = window.AIIA_I18N;
      if (i18n && typeof i18n.t === "function") {
        return i18n.t(key, params);
      }
    } catch (_e) {
      /* fallthrough to literal key */
    }
    return key;
  }

  function _formatProviderList(providers) {
    if (!Array.isArray(providers) || providers.length === 0) return "";
    try {
      var i18n = window.AIIA_I18N;
      if (i18n && typeof i18n.formatList === "function") {
        return i18n.formatList(providers);
      }
    } catch (_e) {
      /* noop */
    }
    return providers.join(", ");
  }

  function _setStatus(node, kind, text) {
    if (!node) return;
    node.textContent = text || "";
    // Use semantic class so CSS can theme success / error / pending
    // without inline styles.  Always reset before writing so back-to-
    // back invocations don't leave stale state.
    node.className = "setting-status-line";
    if (kind === "pending") node.className += " setting-status-pending";
    else if (kind === "success") node.className += " setting-status-success";
    else if (kind === "error") node.className += " setting-status-error";
    else if (kind === "warning") node.className += " setting-status-warning";
  }

  // Map the R141 response shape to a (kind, text) tuple ready to be
  // rendered into the status line.  This is the **only** place that
  // knows about the endpoint's contract; tests lock the full matrix.
  //
  // Note: every i18n key we reach is invoked as a string literal inside
  // ``_t("...")`` so the project's static i18n dead-key analyzer
  // (tests/test_runtime_behavior.py::TestI18nDeadKeys) finds them via
  // grep.  Dynamic dispatch through a key variable would silently leak
  // every key into "dead key" land.
  function _classifyResponse(httpStatus, body) {
    if (httpStatus === 429) {
      return {
        kind: "warning",
        text: _t("settings.systemTestRateLimited"),
      };
    }
    if (httpStatus >= 400 && httpStatus < 500) {
      var clientMsg = (body && (body.message || body.error)) || "";
      return {
        kind: "error",
        text: _t("settings.systemTestFailed", {
          error: String(clientMsg).slice(0, 200),
        }),
      };
    }
    if (httpStatus >= 500) {
      var err = body && body.error;
      if (err === "notification_unavailable") {
        return {
          kind: "error",
          text: _t("settings.systemTestUnavailable"),
        };
      }
      return {
        kind: "error",
        text: _t("settings.systemTestFailed", {
          error: String((body && body.message) || err || httpStatus).slice(
            0,
            200,
          ),
        }),
      };
    }
    if (!body || typeof body !== "object") {
      return {
        kind: "error",
        text: _t("settings.systemTestFailed", { error: "empty response" }),
      };
    }
    if (body.success === true) {
      var providers = Array.isArray(body.providers_dispatched)
        ? body.providers_dispatched
        : [];
      return {
        kind: "success",
        text: _t("settings.systemTestSuccess", {
          count: providers.length,
          providers: _formatProviderList(providers),
          event_id: String(body.event_id || "").slice(0, 64),
        }),
      };
    }
    // 200 + success=false: provider/config disabled.  Server returns
    // a human-readable message in body.message; we surface it as-is
    // because the wording carries the actionable hint
    // ("notification.bark_enabled false" etc).
    var serverMsg = String((body && body.message) || "").trim();
    if (/disabled|enabled=false|notification\./i.test(serverMsg)) {
      return {
        kind: "warning",
        text: _t("settings.systemTestDisabled", {
          reason: serverMsg.slice(0, 200),
        }),
      };
    }
    return {
      kind: "warning",
      text: _t("settings.systemTestNoProviders", {
        reason: serverMsg.slice(0, 200),
      }),
    };
  }

  // R147 / R148: derive a per-provider verdict for the line we render
  // under the main status text.  Pure function over the per-provider
  // stats blob (R142 / R143 / R145 contract) plus an **optional**
  // R148 baseline snapshot.
  //
  // The per-provider stats actually shipped by R142 are:
  //   - attempts / success / failure (counters)
  //   - success_rate / avg_latency_ms (aggregates)
  //   - last_success_age_seconds / last_failure_age_seconds (since-times)
  //   - last_error_present / last_error_class (R143)
  //   - success_streak / failure_streak (R145)
  //
  // R148 — baseline-delta primary path:
  //
  // When ``baselineStats`` is provided (snapshot taken *before* the
  // dispatch), we **delta-compare** the streak counters between
  // baseline and current.  This rules out the "false-success" race
  // where a recent (but unrelated) successful click wrote
  // last_success_at within the stale threshold but the current
  // dispatch hasn't actually completed yet:
  //
  //   - current.success_streak > baseline.success_streak  → "success"
  //   - current.failure_streak > baseline.failure_streak  → "failure"
  //   - neither delta (and last_error_class !== not_registered) → "stale"
  //
  // Both streaks are reset on each event (success → fail_streak=0;
  // failure → succ_streak=0), so a single dispatch always increments
  // exactly one counter.  Comparing ``current > baseline`` is robust to
  // the streak being non-monotonic (success then failure resets succ
  // to 0 in the meantime — but baseline was *also* 0 then, so there's
  // no false positive).
  //
  // R147 — age-only fallback path:
  //
  // When ``baselineStats === null`` (baseline fetch failed / hadn't
  // run yet / null path), we fall back to the original R147 logic:
  // pick freshest of {success_age, failure_age}; > 10s → stale, < 10s
  // + last-was-failure → failure, < 10s + last-was-success → success.
  //
  // Common branches (regardless of baseline availability):
  //   - null stats / last_error_class === "not_registered" → "skipped"
  //   - all defensive fallthroughs                         → "unknown"
  function _classifyProviderVerdict(stats, baselineStats) {
    if (!stats || typeof stats !== "object") {
      return { kind: "skipped", reason: "no_stats" };
    }
    var lastErrorClass = stats.last_error_class || null;
    if (lastErrorClass === "not_registered") {
      return { kind: "skipped", reason: "not_registered" };
    }
    var sa = stats.last_success_age_seconds;
    var fa = stats.last_failure_age_seconds;
    var successAge =
      typeof sa === "number" && isFinite(sa) && sa >= 0 ? sa : null;
    var failureAge =
      typeof fa === "number" && isFinite(fa) && fa >= 0 ? fa : null;
    var failureStreak = parseInt(stats.failure_streak, 10);
    var successStreak = parseInt(stats.success_streak, 10);
    if (!isFinite(failureStreak)) failureStreak = 0;
    if (!isFinite(successStreak)) successStreak = 0;

    // R148 — baseline-delta primary path
    if (baselineStats && typeof baselineStats === "object") {
      var bSucc = parseInt(baselineStats.success_streak, 10);
      var bFail = parseInt(baselineStats.failure_streak, 10);
      if (!isFinite(bSucc)) bSucc = 0;
      if (!isFinite(bFail)) bFail = 0;
      // last_*_age_seconds also flip a tick on each event; for "fresh"
      // age we pick min(success, failure) post-dispatch.
      var deltaSucc = successStreak - bSucc;
      var deltaFail = failureStreak - bFail;
      if (deltaSucc > 0) {
        return {
          kind: "success",
          age: successAge,
          streak: successStreak,
          source: "delta",
        };
      }
      if (deltaFail > 0) {
        return {
          kind: "failure",
          age: failureAge,
          streak: failureStreak,
          errorClass: lastErrorClass || "unknown",
          source: "delta",
        };
      }
      // Neither streak advanced → dispatch hasn't landed (yet).
      return { kind: "stale", age: null, source: "delta" };
    }

    // R147 — age-only fallback path (no baseline available)
    var freshest = null;
    var lastWas = null; // "success" | "failure"
    if (successAge !== null && failureAge !== null) {
      if (failureAge <= successAge) {
        freshest = failureAge;
        lastWas = "failure";
      } else {
        freshest = successAge;
        lastWas = "success";
      }
    } else if (successAge !== null) {
      freshest = successAge;
      lastWas = "success";
    } else if (failureAge !== null) {
      freshest = failureAge;
      lastWas = "failure";
    }
    if (freshest === null || freshest > PROBE_STALE_THRESHOLD_S) {
      return { kind: "stale", age: freshest, source: "age" };
    }
    if (lastWas === "failure") {
      return {
        kind: "failure",
        age: freshest,
        streak: failureStreak,
        errorClass: lastErrorClass || "unknown",
        source: "age",
      };
    }
    if (lastWas === "success") {
      return {
        kind: "success",
        age: freshest,
        streak: successStreak,
        source: "age",
      };
    }
    return { kind: "unknown", age: freshest, source: "age" };
  }

  // R147 / R148: render a per-provider verdict tuple to a localised
  // string fragment.  Each verdict gets its own i18n key so translators
  // can reorder words / use locale-appropriate punctuation.
  //
  // R148 wrinkle: the baseline-delta path can produce verdicts where
  // ``verdict.age`` is null (we know "the streak advanced" but not
  // exactly how recently — the new last_*_at is fresh by definition,
  // but we don't read that field separately).  When age is null we
  // pick a substitute message that simply says "delivered" / "failed"
  // without the seconds suffix, rather than rendering the
  // word "null" into the localised string.  This keeps the i18n
  // contract intact and the screen-reader announcement clean.
  function _renderProviderVerdict(provider, verdict) {
    if (!verdict) return null;
    var providerLabel = String(provider).slice(0, 32);
    if (verdict.kind === "success") {
      var hasSuccessAge =
        typeof verdict.age === "number" && isFinite(verdict.age);
      if (hasSuccessAge) {
        return _t("settings.systemTestProbeProviderSuccess", {
          provider: providerLabel,
          streak: verdict.streak,
          age_seconds: verdict.age.toFixed(1),
        });
      }
      return _t("settings.systemTestProbeProviderSuccessNoAge", {
        provider: providerLabel,
        streak: verdict.streak,
      });
    }
    if (verdict.kind === "failure") {
      return _t("settings.systemTestProbeProviderFailure", {
        provider: providerLabel,
        streak: verdict.streak,
        error_class: String(verdict.errorClass).slice(0, 32),
      });
    }
    if (verdict.kind === "stale") {
      return _t("settings.systemTestProbeProviderStale", {
        provider: providerLabel,
      });
    }
    if (verdict.kind === "skipped") {
      return _t("settings.systemTestProbeProviderSkipped", {
        provider: providerLabel,
        reason: String(verdict.reason || "").slice(0, 32),
      });
    }
    return _t("settings.systemTestProbeProviderUnknown", {
      provider: providerLabel,
    });
  }

  // R147 / R148 shared helper: GET /api/system/health, project
  // per-provider stats for the requested provider keys.  Returns
  // null on any transport / parsing failure so callers treat the
  // probe line as silent fallback (main message stays visible).
  //
  // R148: ``timeoutMs`` argument lets callers tune the per-call
  // budget — the post-dispatch probe still uses PROBE_TIMEOUT_MS
  // (5s, gives slow Bark room), but the **baseline** snapshot
  // taken *before* dispatch uses BASELINE_TIMEOUT_MS (1s, tighter
  // because the user clicked "do something" and we mustn't stall
  // the dispatch waiting for a hung baseline fetch).
  async function _fetchHealthSnapshot(providers, timeoutMs) {
    if (!Array.isArray(providers) || providers.length === 0) return null;
    var t = typeof timeoutMs === "number" && timeoutMs > 0
      ? timeoutMs
      : PROBE_TIMEOUT_MS;
    var controller = null;
    var timeoutId = null;
    try {
      if (typeof AbortController !== "undefined") {
        controller = new AbortController();
        timeoutId = setTimeout(function () {
          try {
            controller.abort();
          } catch (_e) {
            /* noop */
          }
        }, t);
      }
      var resp = await fetch(HEALTH_ENDPOINT, {
        method: "GET",
        credentials: "same-origin",
        signal: controller ? controller.signal : undefined,
      });
      if (!resp.ok) return null;
      var body = await resp.json();
      if (!body || typeof body !== "object") return null;
      // Server contract (R142): /api/system/health returns
      //   { checks: { notification: { per_provider: { bark: {...} | null, ... } } } }
      // — no `.stats` intermediate wrapper.  `per_provider` itself
      // is the dict keyed on NotificationType.value ∈ {bark, web,
      // sound, system}, with each value either the R142 stats blob
      // or `null` (provider not registered / never used).
      var checks = body.checks || {};
      var notif = checks.notification || {};
      var perProvider = notif.per_provider || {};
      var out = {};
      for (var i = 0; i < providers.length; i++) {
        var p = providers[i];
        if (typeof p !== "string") continue;
        out[p] = perProvider[p] || null;
      }
      return out;
    } catch (_err) {
      return null;
    } finally {
      if (timeoutId) {
        try {
          clearTimeout(timeoutId);
        } catch (_e) {
          /* noop */
        }
      }
    }
  }

  // R147 backwards-compat alias — same name kept so external callers
  // / tests don't churn.  Just delegates to the parameterised helper
  // with the probe's longer timeout.
  function _probeHealthForProviders(providers) {
    return _fetchHealthSnapshot(providers, PROBE_TIMEOUT_MS);
  }

  // R147 / R148: orchestrate the post-dispatch probe.  This runs
  // **after** the main status line has already been written, so any
  // failure / null result simply leaves the probe line empty (silent
  // fallback, matching the project's "graceful degradation" pattern
  // from R140 / R146).  The probe line is rendered as separate
  // <span> children joined by " · " so the screen-reader
  // announcement reads like a list, not one giant blob.
  //
  // R148: ``baseline`` is the snapshot of per_provider stats taken
  // *before* the dispatch (or null if that fetch failed). When
  // available, it lets ``_classifyProviderVerdict`` switch from
  // age-only heuristics to delta-based classification — solving the
  // R147 false-success race where a previous successful click left
  // last_success_age within the stale threshold while the current
  // dispatch was still in flight.
  async function _runProbe(providers, probeNode, baseline) {
    if (!probeNode) return;
    if (!Array.isArray(providers) || providers.length === 0) return;
    _setProbe(probeNode, "pending", _t("settings.systemTestProbing"));
    await new Promise(function (r) {
      setTimeout(r, PROBE_DELAY_MS);
    });
    var statsByProvider = await _probeHealthForProviders(providers);
    if (statsByProvider === null) {
      // fail-silent: clear pending text but don't surface an error
      // (main message already says dispatch went out)
      _setProbe(probeNode, "neutral", "");
      return;
    }
    var fragments = [];
    var anyFailure = false;
    var anyStale = false;
    for (var i = 0; i < providers.length; i++) {
      var p = providers[i];
      var baselineForProvider = (baseline && baseline[p]) || null;
      var verdict = _classifyProviderVerdict(
        statsByProvider[p],
        baselineForProvider,
      );
      var line = _renderProviderVerdict(p, verdict);
      if (line) fragments.push(line);
      if (verdict.kind === "failure") anyFailure = true;
      if (verdict.kind === "stale") anyStale = true;
    }
    var probeText = fragments.join(" · ");
    var probeKind = "success";
    if (anyFailure) probeKind = "error";
    else if (anyStale) probeKind = "warning";
    _setProbe(probeNode, probeKind, probeText);
  }

  function _setProbe(node, kind, text) {
    if (!node) return;
    node.textContent = text || "";
    node.className = "setting-status-line";
    if (kind === "pending") node.className += " setting-status-pending";
    else if (kind === "success") node.className += " setting-status-success";
    else if (kind === "warning") node.className += " setting-status-warning";
    else if (kind === "error") node.className += " setting-status-error";
    // "neutral" leaves the base class only (keeps default text
    // colour, no visual highlight); empty strings will collapse the
    // line via the min-height: 0 rule on the empty-text case below.
  }

  // R150: localStorage helpers for the self-test history trail.
  // Defensive against three failure modes:
  //   1. localStorage unavailable (Safari private mode, iframes
  //      that block third-party storage, OAuth-callback contexts,
  //      etc.) → return null and have callers fall through to
  //      "no history" silently.
  //   2. Quota exceeded (e.g. user has 5 MiB of other localStorage
  //      data already) → swallow the setItem error.  The next
  //      successful click will retry, and dropping the entry is
  //      strictly better than a TypeError surfacing to the user.
  //   3. Schema drift across deploys → ``_loadHistory`` filters by
  //      ``v: HISTORY_SCHEMA_VERSION`` so an older version's
  //      payload is silently discarded rather than rendered into
  //      undefined fields.
  function _readStorage() {
    try {
      if (typeof localStorage === "undefined" || !localStorage) return null;
      // Probe write-access early; some sandboxed iframes throw
      // on getItem/setItem rather than returning null.
      var probeKey = "__aiia_probe_r150__";
      localStorage.setItem(probeKey, "1");
      localStorage.removeItem(probeKey);
      return localStorage;
    } catch (_e) {
      return null;
    }
  }

  function _loadHistory() {
    var storage = _readStorage();
    if (!storage) return [];
    try {
      var raw = storage.getItem(HISTORY_LS_KEY);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      var clean = [];
      for (var i = 0; i < parsed.length; i++) {
        var e = parsed[i];
        if (
          e &&
          typeof e === "object" &&
          e.v === HISTORY_SCHEMA_VERSION &&
          typeof e.ts === "number" &&
          isFinite(e.ts) &&
          e.ts > 0
        ) {
          clean.push(e);
        }
        if (clean.length >= HISTORY_MAX_ENTRIES) break;
      }
      return clean;
    } catch (_e) {
      return [];
    }
  }

  function _pushHistory(entry) {
    var storage = _readStorage();
    if (!storage) return;
    if (!entry || typeof entry !== "object") return;
    var providers = Array.isArray(entry.providers) ? entry.providers : [];
    var safeProviders = [];
    for (var i = 0; i < providers.length && i < 16; i++) {
      var p = providers[i];
      if (typeof p === "string") safeProviders.push(p.slice(0, 32));
    }
    var record = {
      v: HISTORY_SCHEMA_VERSION,
      ts: Date.now(),
      verdict_kind: String(entry.verdict_kind || "unknown").slice(0, 16),
      providers: safeProviders,
      source: String(entry.source || "").slice(0, 16),
      event_id: String(entry.event_id || "").slice(0, 64),
    };
    if (entry.error_class) {
      record.error_class = String(entry.error_class).slice(0, 32);
    }
    var existing = _loadHistory();
    var combined = [record].concat(existing).slice(0, HISTORY_MAX_ENTRIES);
    try {
      storage.setItem(HISTORY_LS_KEY, JSON.stringify(combined));
    } catch (_e) {
      /* quota exceeded / private mode — silent drop */
    }
  }

  function _clearHistory() {
    var storage = _readStorage();
    if (!storage) return;
    try {
      storage.removeItem(HISTORY_LS_KEY);
    } catch (_e) {
      /* noop */
    }
  }

  // Bucket the entry's age into "just now / Xs ago / Xm ago / Xh
  // ago / Xd ago" so screen-reader announcements stay short and
  // monitors get rough freshness without exposing sub-second wall
  // time. Future-proof against negative diffs (clock skew /
  // localStorage from a different browser session) by clamping at 0.
  function _formatRelativeTime(ts) {
    var nowMs = Date.now();
    var diffSec = Math.max(0, Math.floor((nowMs - ts) / 1000));
    if (diffSec < 5) return _t("settings.systemTestHistoryAgeJustNow");
    if (diffSec < 60) {
      return _t("settings.systemTestHistoryAgeSeconds", { seconds: diffSec });
    }
    if (diffSec < 3600) {
      return _t("settings.systemTestHistoryAgeMinutes", {
        minutes: Math.floor(diffSec / 60),
      });
    }
    if (diffSec < 86400) {
      return _t("settings.systemTestHistoryAgeHours", {
        hours: Math.floor(diffSec / 3600),
      });
    }
    return _t("settings.systemTestHistoryAgeDays", {
      days: Math.floor(diffSec / 86400),
    });
  }

  // Map verdict.kind ∈ {success, warning, error, pending, unknown}
  // to a localized human label + a CSS suffix used in the entry
  // row's class list.  ``pending`` is never persisted (we only
  // record after the verdict resolves) but is mapped defensively
  // so a future call site that pre-records can't render "undefined".
  function _historyVerdictLabel(kind) {
    if (kind === "success") return _t("settings.systemTestHistoryVerdictSuccess");
    if (kind === "warning") return _t("settings.systemTestHistoryVerdictWarning");
    if (kind === "error") return _t("settings.systemTestHistoryVerdictError");
    return _t("settings.systemTestHistoryVerdictUnknown");
  }

  // Render the history list into ``node`` (a <ul>).  Always reads
  // localStorage live so a foreign tab's update (via the storage
  // event) just calls _renderHistory again and gets fresh data.
  // Uses ``textContent`` exclusively — no innerHTML, no template
  // strings — so persisted strings (event_id, providers) can never
  // become a DOM-XSS surface even if a future rogue script writes
  // attacker-controlled values into localStorage.
  function _renderHistory(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
    var entries = _loadHistory();
    if (entries.length === 0) {
      var empty = document.createElement("li");
      empty.className = "self-test-history-empty";
      empty.textContent = _t("settings.systemTestHistoryEmpty");
      node.appendChild(empty);
      return;
    }
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      var li = document.createElement("li");
      li.className =
        "self-test-history-entry self-test-history-" + e.verdict_kind;
      var when = document.createElement("span");
      when.className = "self-test-history-when";
      when.textContent = _formatRelativeTime(e.ts);
      li.appendChild(when);
      var verdict = document.createElement("span");
      verdict.className = "self-test-history-verdict";
      verdict.textContent = _historyVerdictLabel(e.verdict_kind);
      li.appendChild(verdict);
      if (e.providers && e.providers.length > 0) {
        var prov = document.createElement("span");
        prov.className = "self-test-history-providers";
        prov.textContent = _formatProviderList(e.providers);
        li.appendChild(prov);
      }
      if (e.event_id) {
        var eid = document.createElement("code");
        eid.className = "self-test-history-eventid";
        eid.textContent = e.event_id.slice(0, 8);
        li.appendChild(eid);
      }
      node.appendChild(li);
    }
  }

  // Stamp the last-click time on the button so the cooldown survives
  // any rerender that swaps DOM nodes (defensive vs settings panel
  // re-mounts).  Stored as data attribute, not module variable.
  function _isOnCooldown(button) {
    if (!button) return false;
    var raw = button.getAttribute("data-last-click-ts");
    if (!raw) return false;
    var ts = parseInt(raw, 10);
    if (!isFinite(ts)) return false;
    return Date.now() - ts < CLIENT_COOLDOWN_MS;
  }
  function _stampClick(button) {
    if (!button) return;
    try {
      button.setAttribute("data-last-click-ts", String(Date.now()));
    } catch (_e) {
      /* setAttribute can throw on detached XML node — silently ignore */
    }
  }

  async function triggerSelfTest(button, statusNode, probeNode) {
    if (!button) return;
    if (button.disabled) return;
    if (_isOnCooldown(button)) return;
    _stampClick(button);

    button.disabled = true;
    _setStatus(statusNode, "pending", _t("settings.systemTestSending"));
    // R147: clear any stale probe line from a previous run so the
    // user doesn't see "bark: success" left over from 2 minutes ago.
    if (probeNode) _setProbe(probeNode, "neutral", "");

    // R148: take a baseline snapshot of per_provider stats **before**
    // dispatching, so the post-dispatch probe can delta-compare
    // streak counters and reliably tell "we just delivered" from
    // "an old click delivered, current is still in flight". Tight
    // 1s timeout — if /health is hung we fall back to age-only
    // classification (R147 behaviour) rather than stalling the
    // user-visible dispatch.
    var baseline = null;
    if (probeNode) {
      baseline = await _fetchHealthSnapshot(
        ALL_KNOWN_PROVIDERS,
        BASELINE_TIMEOUT_MS,
      );
    }

    var controller = null;
    var timeoutId = null;
    try {
      if (typeof AbortController !== "undefined") {
        controller = new AbortController();
        timeoutId = setTimeout(function () {
          try {
            controller.abort();
          } catch (_e) {
            /* noop */
          }
        }, FETCH_TIMEOUT_MS);
      }

      var resp = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
        credentials: "same-origin",
        signal: controller ? controller.signal : undefined,
      });
      var body = null;
      try {
        body = await resp.json();
      } catch (_e) {
        body = null;
      }
      var verdict = _classifyResponse(resp.status, body);
      _setStatus(statusNode, verdict.kind, verdict.text);
      // R150 — record this dispatch in the history trail before the
      // probe runs.  We record at "verdict resolved" (success /
      // warning / error) rather than after the probe because the
      // dispatch verdict is the user-facing source-of-truth; the
      // probe is just observability.  If a future R-feature wants
      // to also record the per-provider probe outcomes, that's a
      // separate ``_pushHistory`` call after ``_runProbe`` returns.
      _pushHistory({
        verdict_kind: verdict.kind,
        providers:
          body && Array.isArray(body.providers_dispatched)
            ? body.providers_dispatched
            : [],
        source: "dispatch",
        event_id: body && body.event_id ? body.event_id : "",
      });
      var historyListNode = document.getElementById(HISTORY_LIST_ID);
      if (historyListNode) _renderHistory(historyListNode);
      // R147: only probe when dispatch actually went out (not 4xx /
      // 5xx / config-disabled / no-providers).  Probe runs in the
      // background — we await it to keep button.disabled until probe
      // completes, so a frantic user mashing the button can't overrun
      // a probe-in-flight (matches R146's idempotent contract).
      if (
        verdict.kind === "success" &&
        body &&
        Array.isArray(body.providers_dispatched) &&
        body.providers_dispatched.length > 0
      ) {
        await _runProbe(body.providers_dispatched, probeNode, baseline);
      }
    } catch (err) {
      // AbortError lands here as well — treat as a network-grade
      // failure from the user's POV (they pressed a button and got
      // nothing).  String literal _t() calls so the i18n dead-key
      // analyzer can grep them out.
      var fallbackText;
      if (err && err.name === "AbortError") {
        fallbackText = _t("settings.systemTestFailed", {
          error: "request aborted",
        });
      } else if (err && err.message) {
        fallbackText = _t("settings.systemTestFailed", {
          error: String(err.message).slice(0, 200),
        });
      } else {
        fallbackText = _t("settings.systemTestNetworkError");
      }
      _setStatus(statusNode, "error", fallbackText);
      // R150 — also record the failure in history. We don't have
      // an event_id (server never accepted the request), so we
      // surface the network-level error class instead. Distinct
      // ``source: "network"`` so future analytics can tell
      // dispatch-side failures from provider-side failures.
      _pushHistory({
        verdict_kind: "error",
        providers: [],
        source: "network",
        error_class: err && err.name ? String(err.name) : "NetworkError",
      });
      var historyNetworkListNode = document.getElementById(HISTORY_LIST_ID);
      if (historyNetworkListNode) _renderHistory(historyNetworkListNode);
    } finally {
      if (timeoutId) {
        try {
          clearTimeout(timeoutId);
        } catch (_e) {
          /* noop */
        }
      }
      button.disabled = false;
    }
  }

  function init() {
    var button = document.getElementById(BUTTON_ID);
    var statusNode = document.getElementById(STATUS_ID);
    var probeNode = document.getElementById(PROBE_ID);
    var historyToggle = document.getElementById(HISTORY_TOGGLE_ID);
    var historyList = document.getElementById(HISTORY_LIST_ID);
    if (!button) return null;
    // Idempotent: drop any existing handler before re-binding so a
    // second init() doesn't double-fire.  We use a sentinel attribute
    // because handler identity is captured in closure.
    if (button.getAttribute("data-r146-bound") === "1") {
      return {
        button: button,
        statusNode: statusNode,
        probeNode: probeNode,
        historyToggle: historyToggle,
        historyList: historyList,
      };
    }
    button.addEventListener("click", function () {
      // Defer to microtask queue so click handlers don't await
      // inline (keeps browser responsive on slow mobiles).
      Promise.resolve().then(function () {
        triggerSelfTest(button, statusNode, probeNode);
      });
    });
    button.setAttribute("data-r146-bound", "1");

    // R150 — wire up the history toggle / list.  The toggle is a
    // semantic ``aria-expanded`` button; the list is hidden by
    // default (``[hidden]`` attribute on the <ul>) so the settings
    // panel stays clean for users who don't care about the trail.
    if (historyToggle && historyList) {
      _renderHistory(historyList);
      historyToggle.addEventListener("click", function () {
        var expanded = historyToggle.getAttribute("aria-expanded") === "true";
        var nextExpanded = !expanded;
        historyToggle.setAttribute("aria-expanded", String(nextExpanded));
        if (nextExpanded) {
          historyList.removeAttribute("hidden");
          _renderHistory(historyList);
        } else {
          historyList.setAttribute("hidden", "");
        }
      });
      // Multi-tab sync: another tab clicking the button writes to
      // localStorage and fires a ``storage`` event in this tab.
      if (typeof window !== "undefined" && window.addEventListener) {
        window.addEventListener("storage", function (ev) {
          if (ev && ev.key === HISTORY_LS_KEY) _renderHistory(historyList);
        });
      }
    }

    return {
      button: button,
      statusNode: statusNode,
      probeNode: probeNode,
      historyToggle: historyToggle,
      historyList: historyList,
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AIIA_NOTIFICATION_TEST_BUTTON = {
    BUTTON_ID: BUTTON_ID,
    STATUS_ID: STATUS_ID,
    PROBE_ID: PROBE_ID,
    ENDPOINT: ENDPOINT,
    HEALTH_ENDPOINT: HEALTH_ENDPOINT,
    CLIENT_COOLDOWN_MS: CLIENT_COOLDOWN_MS,
    FETCH_TIMEOUT_MS: FETCH_TIMEOUT_MS,
    PROBE_DELAY_MS: PROBE_DELAY_MS,
    PROBE_TIMEOUT_MS: PROBE_TIMEOUT_MS,
    PROBE_STALE_THRESHOLD_S: PROBE_STALE_THRESHOLD_S,
    BASELINE_TIMEOUT_MS: BASELINE_TIMEOUT_MS,
    ALL_KNOWN_PROVIDERS: ALL_KNOWN_PROVIDERS,
    HISTORY_LS_KEY: HISTORY_LS_KEY,
    HISTORY_MAX_ENTRIES: HISTORY_MAX_ENTRIES,
    HISTORY_TOGGLE_ID: HISTORY_TOGGLE_ID,
    HISTORY_LIST_ID: HISTORY_LIST_ID,
    HISTORY_SCHEMA_VERSION: HISTORY_SCHEMA_VERSION,
    init: init,
    triggerSelfTest: triggerSelfTest,
    _classifyResponse: _classifyResponse,
    _classifyProviderVerdict: _classifyProviderVerdict,
    _renderProviderVerdict: _renderProviderVerdict,
    _fetchHealthSnapshot: _fetchHealthSnapshot,
    _probeHealthForProviders: _probeHealthForProviders,
    _runProbe: _runProbe,
    _setProbe: _setProbe,
    _formatProviderList: _formatProviderList,
    _isOnCooldown: _isOnCooldown,
    _readStorage: _readStorage,
    _loadHistory: _loadHistory,
    _pushHistory: _pushHistory,
    _clearHistory: _clearHistory,
    _renderHistory: _renderHistory,
    _formatRelativeTime: _formatRelativeTime,
    _historyVerdictLabel: _historyVerdictLabel,
  };
})();
