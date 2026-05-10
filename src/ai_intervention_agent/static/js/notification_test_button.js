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
  var ENDPOINT = "/api/system/notifications/test";
  // Server's Flask-Limiter is 6/min on this route; we add a tiny
  // client-side cooldown to dampen accidental double-tap before the
  // server has a chance to 429.  AbortController on top of that.
  var CLIENT_COOLDOWN_MS = 600;
  // 60s hard cap on the fetch — well above realistic Bark RTT (~2s)
  // but short enough that a hung connection doesn't keep the button
  // disabled forever.
  var FETCH_TIMEOUT_MS = 60 * 1000;

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

  async function triggerSelfTest(button, statusNode) {
    if (!button) return;
    if (button.disabled) return;
    if (_isOnCooldown(button)) return;
    _stampClick(button);

    button.disabled = true;
    _setStatus(statusNode, "pending", _t("settings.systemTestSending"));

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
    if (!button) return null;
    // Idempotent: drop any existing handler before re-binding so a
    // second init() doesn't double-fire.  We use a sentinel attribute
    // because handler identity is captured in closure.
    if (button.getAttribute("data-r146-bound") === "1") {
      return { button: button, statusNode: statusNode };
    }
    button.addEventListener("click", function () {
      // Defer to microtask queue so click handlers don't await
      // inline (keeps browser responsive on slow mobiles).
      Promise.resolve().then(function () {
        triggerSelfTest(button, statusNode);
      });
    });
    button.setAttribute("data-r146-bound", "1");
    return { button: button, statusNode: statusNode };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AIIA_NOTIFICATION_TEST_BUTTON = {
    BUTTON_ID: BUTTON_ID,
    STATUS_ID: STATUS_ID,
    ENDPOINT: ENDPOINT,
    CLIENT_COOLDOWN_MS: CLIENT_COOLDOWN_MS,
    FETCH_TIMEOUT_MS: FETCH_TIMEOUT_MS,
    init: init,
    triggerSelfTest: triggerSelfTest,
    _classifyResponse: _classifyResponse,
    _formatProviderList: _formatProviderList,
    _isOnCooldown: _isOnCooldown,
  };
})();
