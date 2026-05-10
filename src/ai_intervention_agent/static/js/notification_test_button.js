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
  var CLIENT_COOLDOWN_MS = 600;
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
  var PROBE_STALE_THRESHOLD_S = 10;

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

  // R147: derive a per-provider verdict for the line we render
  // under the main status text.  Pure function over the per-provider
  // stats blob (R142 / R143 / R145 contract).
  //
  // The per-provider stats actually shipped by R142 are:
  //   - attempts / success / failure (counters)
  //   - success_rate / avg_latency_ms (aggregates)
  //   - last_success_age_seconds / last_failure_age_seconds (since-times)
  //   - last_error_present / last_error_class (R143)
  //   - success_streak / failure_streak (R145)
  //
  // We pick the **most recent** of {success_age, failure_age} as the
  // "last event age", because what the user pressed the button for
  // was "did anything fire just now?" — not specifically a success.
  //
  // Decision tree (verdict.kind):
  //   - null stats / last_error_class === "not_registered"  → "skipped"
  //   - both ages null / freshest age > stale threshold     → "stale"
  //   - last event was a failure (failure_age <= success_age, OR
  //     success_age is null)                                → "failure"
  //     with streak = failure_streak, errorClass = last_error_class
  //   - last event was a success (the converse)             → "success"
  //     with streak = success_streak
  //   - both ages 0 / both streaks 0 (defensive)            → "unknown"
  function _classifyProviderVerdict(stats) {
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
    // freshest = whichever is smaller (most recent)
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
      return { kind: "stale", age: freshest };
    }
    var failureStreak = parseInt(stats.failure_streak, 10);
    var successStreak = parseInt(stats.success_streak, 10);
    if (lastWas === "failure") {
      return {
        kind: "failure",
        age: freshest,
        streak: isFinite(failureStreak) ? failureStreak : 0,
        errorClass: lastErrorClass || "unknown",
      };
    }
    if (lastWas === "success") {
      return {
        kind: "success",
        age: freshest,
        streak: isFinite(successStreak) ? successStreak : 0,
      };
    }
    return { kind: "unknown", age: freshest };
  }

  // R147: render a per-provider verdict tuple to a localised string
  // fragment.  Each verdict gets its own i18n key so translators can
  // reorder words / use locale-appropriate punctuation.
  function _renderProviderVerdict(provider, verdict) {
    if (!verdict) return null;
    var providerLabel = String(provider).slice(0, 32);
    if (verdict.kind === "success") {
      return _t("settings.systemTestProbeProviderSuccess", {
        provider: providerLabel,
        streak: verdict.streak,
        age_seconds: verdict.age.toFixed(1),
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

  // R147: fetch /api/system/health and project per-provider stats
  // for the providers we just dispatched. Returns null on any
  // transport / parsing failure (caller treats null as "skip the
  // probe line" — main success message stays visible, no scary
  // error overlap).
  async function _probeHealthForProviders(providers) {
    if (!Array.isArray(providers) || providers.length === 0) return null;
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
        }, PROBE_TIMEOUT_MS);
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

  // R147: orchestrate the post-dispatch probe.  This runs **after**
  // the main status line has already been written, so any failure /
  // null result simply leaves the probe line empty (silent fallback,
  // matching the project's "graceful degradation" pattern from R140
  // / R146).  The probe line is rendered as separate <span> children
  // joined by " · " so the screen-reader announcement reads like
  // a list, not one giant blob.
  async function _runProbe(providers, probeNode) {
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
      var verdict = _classifyProviderVerdict(statsByProvider[p]);
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
        await _runProbe(body.providers_dispatched, probeNode);
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
    if (!button) return null;
    // Idempotent: drop any existing handler before re-binding so a
    // second init() doesn't double-fire.  We use a sentinel attribute
    // because handler identity is captured in closure.
    if (button.getAttribute("data-r146-bound") === "1") {
      return { button: button, statusNode: statusNode, probeNode: probeNode };
    }
    button.addEventListener("click", function () {
      // Defer to microtask queue so click handlers don't await
      // inline (keeps browser responsive on slow mobiles).
      Promise.resolve().then(function () {
        triggerSelfTest(button, statusNode, probeNode);
      });
    });
    button.setAttribute("data-r146-bound", "1");
    return { button: button, statusNode: statusNode, probeNode: probeNode };
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
    init: init,
    triggerSelfTest: triggerSelfTest,
    _classifyResponse: _classifyResponse,
    _classifyProviderVerdict: _classifyProviderVerdict,
    _renderProviderVerdict: _renderProviderVerdict,
    _probeHealthForProviders: _probeHealthForProviders,
    _runProbe: _runProbe,
    _setProbe: _setProbe,
    _formatProviderList: _formatProviderList,
    _isOnCooldown: _isOnCooldown,
  };
})();
