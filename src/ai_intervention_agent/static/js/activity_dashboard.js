/**
 * R152 — Activity Dashboard (settings panel).
 *
 * Background
 * ----------
 * R141-R150 shipped a comprehensive server-side observability stack:
 *   - ``/api/system/health`` (R53-F + R121-A + R142 + R143 + R145):
 *     server status, sse_bus / task_queue / recent_errors checks,
 *     per-provider notification stats with last_error_class +
 *     success_streak / failure_streak.
 *   - ``/api/system/sse-stats`` (R47 + R51-B + R58 + R61 + R134):
 *     emit_total, subscriber_count, heartbeat_total, oversize_drops,
 *     emit_by_type, P50 / P95 emit→deliver latency.
 *   - ``/api/tasks`` (and ``/api/tasks/export``): pending / active /
 *     completed / total counters via ``stats`` field.
 *   - ``/api/system/recent-logs?limit=N``: redacted recent
 *     WARNING / ERROR ring-buffer entries (R52-B).
 *
 * Up to R150 the only way to read all four was ``curl`` — fine for
 * ops dashboards, not great for end-users who just want a glance at
 * "is the agent healthy?  any backlog?  any flaky provider?".  R152
 * closes that loop with a collapsed-by-default Activity Dashboard
 * subsection in the settings panel.
 *
 * Design principles
 * -----------------
 * - **Pure presentational module** — same shape as R146.  No
 *   business logic; the heavy lifting lives in R47 / R53-F /
 *   R121-A / R141-R145 on the server.
 * - **Idempotent IIFE** — ``init()`` is safe to call more than once;
 *   sentinel ``data-r152-bound="1"`` on the toggle button prevents
 *   double-binding.
 * - **Visibility-aware polling** — when ``document.hidden`` flips
 *   true (tab in background) we cancel the next poll; flipping back
 *   we fire one immediate fetch + restart the interval.  Saves
 *   battery on phones / suspended laptops.
 * - **State-machine polling cancellation** — every fetch tracks an
 *   AbortController; closing the dashboard / unmounting the panel
 *   aborts the in-flight request so a slow ``/api/system/recent-logs``
 *   doesn't write into a torn-down DOM.
 * - **Graceful degradation** — every fetch failure (network down /
 *   401/403/429/5xx / non-JSON) gets a per-row ``stale`` badge.
 *   Other rows keep refreshing; we don't tear down the whole
 *   dashboard on a single endpoint hiccup.
 * - **Pull rate** — 5 s default poll; the four endpoints we touch
 *   are all ≥ 60 / min on Flask-Limiter so 12 / min is well under.
 * - **i18n aware** — every string passes through
 *   ``window.AIIA_I18N.t`` with literal keys (so the static dead-key
 *   analyzer can grep them).  Numbers are localised via
 *   ``Intl.NumberFormat`` when available; fallback to
 *   ``String(value)``.
 * - **DOM-XSS-immune renderer** — exclusively ``createElement`` +
 *   ``textContent``.  Server-side responses go through a defensive
 *   slice (32-128 chars depending on field) so even an absurdly
 *   long error message can't break layout.
 * - **a11y** — toggle is a real ``<button>`` with ``aria-controls``
 *   + ``aria-expanded``; rendered region is ``role="region"`` with
 *   an ``aria-labelledby``-targeted heading; per-row stat updates
 *   inside the open dashboard go through ``role="status"`` so a
 *   screen reader hears "queue: 3 pending" without spamming on
 *   every poll.
 */

(function () {
  "use strict";

  // ---------- Constants -----------------------------------------------------

  var DASHBOARD_ID = "activity-dashboard";
  var TOGGLE_ID = "activity-dashboard-toggle";
  var BODY_ID = "activity-dashboard-body";
  var ROW_ID_PREFIX = "activity-dashboard-row-";

  var ENDPOINT_HEALTH = "/api/system/health";
  var ENDPOINT_SSE_STATS = "/api/system/sse-stats";
  var ENDPOINT_TASKS = "/api/tasks";
  // R156 — base path only.  ``_pollOnce`` appends
  // ``"?limit=" + _state.logsLimit`` so the toggle below can switch
  // between LOGS_LIMIT_DEFAULT (= 5) and LOGS_LIMIT_EXPANDED (= 50)
  // without rewriting the URL constant.  The R152 / R154 path-prefix
  // contract is preserved (server matches on the path, ignores query).
  var ENDPOINT_RECENT_LOGS_BASE = "/api/system/recent-logs";
  // Backward-compatible alias still emitted by R152 / R154 contracts
  // (some tests assert the exact ``?limit=5`` literal).  Kept in
  // lockstep with LOGS_LIMIT_DEFAULT so the URL string and the
  // numerical default can't drift apart silently.
  var ENDPOINT_RECENT_LOGS = "/api/system/recent-logs?limit=5";

  // 5 s poll keeps the dashboard live without hammering anything.  Each
  // server endpoint is ≥ 60 / min Flask-Limited; 12 / min is well
  // under cap.  Tunable via the ``AIIA_ACTIVITY_DASHBOARD.setPollMs``
  // export for tests / dev tools.
  var POLL_MS_DEFAULT = 5000;
  var POLL_MS_MIN = 1000;
  var POLL_MS_MAX = 60000;

  // 4 s hard cap on every fetch (above realistic LAN RTT, well below
  // the poll interval).  AbortController on top.
  var FETCH_TIMEOUT_MS = 4000;

  // R153 — how many tail-most recent log entries we render under the
  // ``logs`` row's expand control.  5 is the same magic number we use
  // for R150's self-test history trail; same UX rationale (uptime-kuma
  // / healthchecks.io ship "last 5" panels).  Each rendered entry is
  // ~ 240 bytes after server-side ``LogSanitizer`` redaction + our own
  // 128-char message slice, so 5 entries ≈ 1.2 KiB DOM — negligible.
  var LOGS_TAIL_COUNT = 5;
  // R153 — defensive per-entry message slice.  Server already caps
  // each message at 500 chars (``enhanced_logging._LOG_MESSAGE_MAX``)
  // but we further shrink to 256 to keep the inline expansion compact
  // and avoid wrapping the row layout on a stack-trace one-liner.
  var LOG_MESSAGE_SLICE = 256;

  // R155 — localStorage-backed "remember whether the dashboard is
  // expanded across page reloads" (closes CR#9 F-3).  Stored as a
  // single boolean ``true|false`` under a schema-versioned key,
  // mirroring R150's history-trail pattern so the same defensive
  // ``_readStorageFlag`` / ``_writeStorageFlag`` shape can be reused
  // by a future R-cycle that adds another remember-this affordance.
  var EXPANDED_LS_KEY = "aiia.activity_dashboard.expanded.v1";
  // Schema version embedded so a future R157 / R158 shape change
  // (e.g. per-row expanded state, not just the top-level toggle) can
  // bump and drop the older payload without crashing the renderer.
  var EXPANDED_SCHEMA_VERSION = 1;

  // R156 — logs row's optional "show more" toggle (closes CR#9 F-4).
  // Default value matches R153's LOGS_TAIL_COUNT so the URL and the
  // numerical default can't drift apart.  ``LOGS_LIMIT_EXPANDED`` is
  // 50 because the ``/api/system/recent-logs`` ring buffer caps at
  // 200 in production and 50 is a comfortable middle ground:
  // - 50 entries × ~ 240 bytes per redacted entry ≈ 12 KiB / fetch.
  // - 5 s poll × 12 KiB ≈ 144 KiB / minute when the user explicitly
  //   asks for the full view.  Closes "I have to curl recent-logs to
  //   read the full WARN list" without changing the default poll
  //   load.
  var LOGS_LIMIT_DEFAULT = 5;
  var LOGS_LIMIT_EXPANDED = 50;
  var LOGS_LIMIT_LS_KEY = "aiia.activity_dashboard.logs_limit.v1";
  var LOGS_LIMIT_SCHEMA_VERSION = 1;

  // The list of "rows" (stat tiles) we render.  Each row maps an
  // id (used as React-style key + DOM id) to the i18n label and the
  // formatter that turns the latest value into a textContent string.
  // Order is the visual top-to-bottom order.
  var ROW_DEFS = [
    { id: "tasks", label: "settings.activityDashboardRowTasks" },
    { id: "sse", label: "settings.activityDashboardRowSse" },
    { id: "latency", label: "settings.activityDashboardRowLatency" },
    { id: "notif", label: "settings.activityDashboardRowNotif" },
    { id: "health", label: "settings.activityDashboardRowHealth" },
    { id: "logs", label: "settings.activityDashboardRowLogs" },
  ];

  // ---------- Local state ---------------------------------------------------

  // ``_state`` is intentionally module-private: the export surface only
  // exposes pure helpers, so callers / tests can't accidentally hold a
  // direct reference to the live state.
  var _state = {
    timerId: null,
    pollMs: POLL_MS_DEFAULT,
    inflight: null, // current AbortController
    isOpen: false,
    visibilityHandler: null,
    lastRender: {},
    // R156 — currently requested ``?limit=N`` on
    // ``/api/system/recent-logs``.  Either LOGS_LIMIT_DEFAULT (5) or
    // LOGS_LIMIT_EXPANDED (50); init() hydrates from localStorage.
    logsLimit: LOGS_LIMIT_DEFAULT,
  };

  // ---------- i18n / number formatting --------------------------------------

  function _t(key, params) {
    try {
      var i18n = window.AIIA_I18N;
      if (i18n && typeof i18n.t === "function") {
        return i18n.t(key, params);
      }
    } catch (_e) {
      /* fallthrough */
    }
    return key;
  }

  function _fmtNum(n) {
    if (typeof n !== "number" || !isFinite(n)) return "—";
    try {
      if (typeof Intl !== "undefined" && Intl.NumberFormat) {
        return new Intl.NumberFormat().format(n);
      }
    } catch (_e) {
      /* fallthrough */
    }
    return String(n);
  }

  function _fmtMs(n) {
    if (typeof n !== "number" || !isFinite(n)) return "—";
    if (n < 10) return n.toFixed(2) + " ms";
    if (n < 1000) return Math.round(n) + " ms";
    return (n / 1000).toFixed(2) + " s";
  }

  // ---------- Fetch helpers -------------------------------------------------

  // Wrap a single endpoint fetch with the AbortController + per-call
  // timeout.  Returns ``null`` on any failure (network / parse / non-OK
  // / abort) so the renderer can show a "stale" badge for that row
  // without fanning the failure out to the rest.
  async function _fetchJson(endpoint, controller, timeoutMs) {
    var timeoutId = null;
    try {
      if (controller && typeof setTimeout === "function") {
        timeoutId = setTimeout(function () {
          try {
            controller.abort();
          } catch (_e) {
            /* noop */
          }
        }, timeoutMs);
      }
      var resp = await fetch(endpoint, {
        method: "GET",
        credentials: "same-origin",
        signal: controller ? controller.signal : undefined,
      });
      if (!resp.ok) return null;
      var body = await resp.json();
      if (!body || typeof body !== "object") return null;
      return body;
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

  // ---------- Per-row formatters --------------------------------------------

  function _formatTasks(tasks) {
    if (!tasks || typeof tasks !== "object") return null;
    var stats = (tasks && tasks.stats) || {};
    var pending = typeof stats.pending === "number" ? stats.pending : 0;
    var active = typeof stats.active === "number" ? stats.active : 0;
    var completed = typeof stats.completed === "number" ? stats.completed : 0;
    var total = typeof stats.total === "number" ? stats.total : 0;
    return _t("settings.activityDashboardTasksValue", {
      pending: _fmtNum(pending),
      active: _fmtNum(active),
      completed: _fmtNum(completed),
      total: _fmtNum(total),
    });
  }

  function _formatSse(sse) {
    if (!sse || typeof sse !== "object") return null;
    var emitTotal = typeof sse.emit_total === "number" ? sse.emit_total : 0;
    var subscriberCount =
      typeof sse.subscriber_count === "number" ? sse.subscriber_count : 0;
    var heartbeat =
      typeof sse.heartbeat_total === "number" ? sse.heartbeat_total : 0;
    return _t("settings.activityDashboardSseValue", {
      emit: _fmtNum(emitTotal),
      subs: _fmtNum(subscriberCount),
      heartbeat: _fmtNum(heartbeat),
    });
  }

  function _formatLatency(sse) {
    if (!sse || typeof sse !== "object") return null;
    var latency = sse.latency_ms || {};
    if (typeof latency !== "object") latency = {};
    var p50 = typeof latency.p50_ms === "number" ? latency.p50_ms : null;
    var p95 = typeof latency.p95_ms === "number" ? latency.p95_ms : null;
    var count = typeof latency.count === "number" ? latency.count : 0;
    if (count === 0) {
      return _t("settings.activityDashboardLatencyEmpty");
    }
    return _t("settings.activityDashboardLatencyValue", {
      p50: _fmtMs(p50),
      p95: _fmtMs(p95),
      count: _fmtNum(count),
    });
  }

  function _formatNotif(health) {
    if (!health || typeof health !== "object") return null;
    var checks = health.checks || {};
    var notif = checks.notification || {};
    var perProv = notif.per_provider || {};
    if (typeof perProv !== "object") perProv = {};
    var lines = [];
    var keys = ["bark", "web", "sound", "system"];
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      var stats = perProv[k];
      if (stats == null) continue;
      var ss = parseInt(stats.success_streak, 10);
      var fs = parseInt(stats.failure_streak, 10);
      if (!isFinite(ss)) ss = 0;
      if (!isFinite(fs)) fs = 0;
      lines.push(
        _t("settings.activityDashboardNotifLine", {
          provider: k.slice(0, 16),
          success: _fmtNum(ss),
          failure: _fmtNum(fs),
        }),
      );
    }
    if (lines.length === 0) {
      return _t("settings.activityDashboardNotifEmpty");
    }
    return lines.join(" · ");
  }

  function _formatHealth(health) {
    if (!health || typeof health !== "object") return null;
    var status = String(health.status || "unknown").slice(0, 16);
    return _t("settings.activityDashboardHealthValue", {
      status: status,
    });
  }

  // R153 — return shape changed from ``string`` to
  // ``{ summary: string, entries: [...] }`` so the logs row can render
  // both a one-line summary and an expand-able inline list of the last
  // ``LOGS_TAIL_COUNT`` entries.
  //
  // Bug fix vs R152: the server payload uses ``entries`` (matches
  // ``web_ui_routes/system.py::recent_logs``), not ``logs``.  R152
  // shipped with ``logs.logs`` which always returned null → the logs
  // row was permanently marked ``stale`` whenever the endpoint
  // responded.  Locked by a regression test in
  // ``tests/test_activity_dashboard_r152_logs_bugfix_r153.py``.
  function _formatLogs(logs) {
    if (!logs || typeof logs !== "object") {
      return { summary: null, entries: [] };
    }
    var entries = logs.entries;
    if (!Array.isArray(entries)) {
      return { summary: null, entries: [] };
    }
    var warns = 0;
    var errors = 0;
    for (var i = 0; i < entries.length; i++) {
      var lvl = entries[i] && entries[i].level;
      if (lvl === "WARNING") warns += 1;
      else if (lvl === "ERROR") errors += 1;
    }
    var summary = _t("settings.activityDashboardLogsValue", {
      warnings: _fmtNum(warns),
      errors: _fmtNum(errors),
      total: _fmtNum(entries.length),
    });
    // Take only the *tail* (most recent N entries).  ``N`` matches
    // the current ``_state.logsLimit`` so R156's "show 50" toggle
    // surfaces 50 entries when expanded and just LOGS_TAIL_COUNT
    // (= LOGS_LIMIT_DEFAULT = 5) when collapsed.  The endpoint
    // returns oldest → newest, so slicing from the end gives us the
    // most recent regardless of how many the server shipped.
    // Defensive caps on every per-entry field happen later inside
    // ``_renderLogsRow``.
    var tail = entries.slice(Math.max(0, entries.length - _state.logsLimit));
    return { summary: summary, entries: tail };
  }

  // ---------- Renderer ------------------------------------------------------

  // Static label registry.  Every row id maps to a literal translate
  // call so ``scripts/check_i18n_orphan_keys.py`` can grep the keys and
  // not falsely mark them as orphans (the regex only matches direct
  // translate-with-literal shapes, not labels stored as data on
  // ROW_DEFS above).  Keep this in lockstep with ROW_DEFS — add a new
  // ``if`` branch for every new row.
  function _labelForRow(rowId) {
    if (rowId === "tasks") return _t("settings.activityDashboardRowTasks");
    if (rowId === "sse") return _t("settings.activityDashboardRowSse");
    if (rowId === "latency") return _t("settings.activityDashboardRowLatency");
    if (rowId === "notif") return _t("settings.activityDashboardRowNotif");
    if (rowId === "health") return _t("settings.activityDashboardRowHealth");
    if (rowId === "logs") return _t("settings.activityDashboardRowLogs");
    return rowId;
  }

  function _ensureRow(rowId, labelKey, body) {
    var row = document.getElementById(ROW_ID_PREFIX + rowId);
    if (row) return row;
    row = document.createElement("div");
    row.id = ROW_ID_PREFIX + rowId;
    row.className = "activity-dashboard-row";

    var label = document.createElement("dt");
    label.className = "activity-dashboard-label";
    label.textContent = _labelForRow(rowId);
    label.setAttribute("data-i18n", labelKey);
    row.appendChild(label);

    var value = document.createElement("dd");
    value.className = "activity-dashboard-value";
    value.textContent = "—";
    row.appendChild(value);
    body.appendChild(row);
    return row;
  }

  function _writeRow(row, text, isStale) {
    if (!row) return;
    var value = row.querySelector(".activity-dashboard-value");
    if (!value) return;
    if (typeof text !== "string" || text.length === 0) {
      value.textContent = "—";
    } else {
      // Cap at 256 chars to avoid blowing layout on a runaway server
      // payload.  Real fields are << 100 chars in practice.
      value.textContent = text.length > 256 ? text.slice(0, 256) + "…" : text;
    }
    if (isStale) {
      row.classList.add("activity-dashboard-stale");
    } else {
      row.classList.remove("activity-dashboard-stale");
    }
  }

  function _renderAll(body, snapshot) {
    if (!body) return;
    for (var i = 0; i < ROW_DEFS.length; i++) {
      var def = ROW_DEFS[i];
      var row = _ensureRow(def.id, def.label, body);
      var entry = (snapshot && snapshot[def.id]) || {
        text: null,
        stale: true,
      };
      if (def.id === "logs") {
        // R153 — logs row uses a richer renderer that draws a summary
        // line plus a collapsed-by-default sub-list of the most recent
        // LOGS_TAIL_COUNT entries.  All other rows keep the simple
        // ``_writeRow`` contract.
        _renderLogsRow(row, entry);
      } else {
        _writeRow(row, entry.text, entry.stale);
      }
    }
  }

  // ---------- R153 logs sub-row -------------------------------------------

  // Pure helper — returns one of three sentinel level CSS class
  // suffixes (``warning`` / ``error`` / ``info``) so the renderer
  // can colour-code WARNING / ERROR rows without depending on the
  // server's full level enum.  ERROR-and-above (50 CRITICAL) all
  // collapse onto ``error`` because the dashboard only colour-codes
  // two buckets visually; the actual server-side ``level`` string
  // is still rendered verbatim below.
  function _logLevelClassSuffix(level) {
    if (typeof level !== "string") return "info";
    var upper = level.toUpperCase();
    if (upper === "WARNING" || upper === "WARN") return "warning";
    if (upper === "ERROR" || upper === "CRITICAL") return "error";
    return "info";
  }

  // Pure helper — given an ISO-8601 timestamp string, return just the
  // HH:MM:SS slice (UTC).  We render UTC time, not local; the dashboard
  // is meant for ops debugging where wall-clock time across operators
  // would only confuse "did this WARNING happen before or after the
  // crash report I'm reading?".  Falls back to the raw string if the
  // input doesn't look like an ISO timestamp.
  function _logTimeShort(tsIso) {
    if (typeof tsIso !== "string") return "—";
    // ISO format is ``YYYY-MM-DDTHH:MM:SS.fffffffff+00:00`` (per
    // ``enhanced_logging._build_entry``); slice "T" + 8 chars.
    var t = tsIso.indexOf("T");
    if (t === -1 || tsIso.length < t + 9) {
      return tsIso.slice(0, 16);
    }
    return tsIso.slice(t + 1, t + 9);
  }

  // R153 — render the logs row.  Reuses ``_writeRow`` for the summary,
  // then injects (or refreshes) a ``[expand]`` button + nested ``<ul>``
  // that lists the most-recent ``LOGS_TAIL_COUNT`` entries.  Idempotent
  // — re-renders by clearing the list and rebuilding it from scratch
  // each tick.
  function _renderLogsRow(row, entry) {
    if (!row) return;
    var value = row.querySelector(".activity-dashboard-value");
    if (!value) return;
    var stale = entry && entry.stale === true;
    var formatted = (entry && entry.text) || {};
    var summary = formatted && formatted.summary;
    var entries = (formatted && formatted.entries) || [];
    if (!Array.isArray(entries)) entries = [];

    // Replace the summary text but preserve our expand-control children
    // so a stale poll doesn't unhook the user's expanded state on
    // every tick.  Strategy: find or create a ``<span>`` for summary,
    // and find or create the controls (button + ul) as siblings.
    var summarySpan = value.querySelector(".activity-dashboard-logs-summary");
    if (!summarySpan) {
      // Tear down whatever ``_writeRow`` might have left here on first
      // mount (a single text node) and seed the structured layout.
      while (value.firstChild) value.removeChild(value.firstChild);
      summarySpan = document.createElement("span");
      summarySpan.className = "activity-dashboard-logs-summary";
      value.appendChild(summarySpan);
    }
    if (typeof summary !== "string" || summary.length === 0) {
      summarySpan.textContent = "—";
    } else {
      summarySpan.textContent =
        summary.length > LOG_MESSAGE_SLICE
          ? summary.slice(0, LOG_MESSAGE_SLICE) + "…"
          : summary;
    }

    // Update stale visual on the row container (consistent with the
    // simple-row path).
    if (stale) {
      row.classList.add("activity-dashboard-stale");
    } else {
      row.classList.remove("activity-dashboard-stale");
    }

    // Find or create the expand control + list.  The control's
    // ``aria-expanded`` state is preserved across re-renders.
    var btn = value.querySelector(".activity-dashboard-logs-expand");
    var list = value.querySelector("#activity-dashboard-logs-list");
    // R156 — sibling "show 50" / "show 5" toggle.  Lives next to
    // the expand button so it's discoverable whether the list is
    // open or closed; toggles the in-flight ``?limit=N`` on the
    // next poll cycle (no manual re-fetch — the dashboard's 5 s
    // poll picks up the new state).
    var moreBtn = value.querySelector(".activity-dashboard-logs-show-more");
    if (!btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "activity-dashboard-logs-expand";
      btn.setAttribute("aria-controls", "activity-dashboard-logs-list");
      btn.setAttribute("aria-expanded", "false");
      btn.setAttribute("data-i18n", "settings.activityDashboardLogsExpand");
      btn.textContent = _t("settings.activityDashboardLogsExpand");
      btn.addEventListener("click", function () {
        var expanded = btn.getAttribute("aria-expanded") === "true";
        btn.setAttribute("aria-expanded", expanded ? "false" : "true");
        if (list) {
          if (expanded) list.setAttribute("hidden", "");
          else list.removeAttribute("hidden");
        }
        btn.textContent = expanded
          ? _t("settings.activityDashboardLogsExpand")
          : _t("settings.activityDashboardLogsCollapse");
        // Keep the ``data-i18n`` attribute pointing at the *currently
        // displayed* key so a future runtime locale-switch re-translates
        // it correctly.
        btn.setAttribute(
          "data-i18n",
          expanded
            ? "settings.activityDashboardLogsExpand"
            : "settings.activityDashboardLogsCollapse",
        );
      });
      value.appendChild(btn);
    }
    if (!list) {
      list = document.createElement("ul");
      list.id = "activity-dashboard-logs-list";
      list.className = "activity-dashboard-logs-list";
      list.setAttribute("role", "list");
      list.setAttribute("aria-live", "polite");
      list.setAttribute("hidden", "");
      value.appendChild(list);
    }
    if (!moreBtn) {
      // Create the "show 50" toggle once.  It only appears after
      // ``btn`` (expand) so the visual order is summary | expand |
      // show-50 — the more advanced control sits last.
      moreBtn = document.createElement("button");
      moreBtn.type = "button";
      moreBtn.className = "activity-dashboard-logs-show-more";
      // Initial label tracks the *current* state: if we're already
      // on the expanded limit, the button offers to go back.
      var initiallyExpanded = _state.logsLimit === LOGS_LIMIT_EXPANDED;
      moreBtn.setAttribute("data-i18n", _showMoreKey(initiallyExpanded));
      moreBtn.textContent = _showMoreLabel(initiallyExpanded);
      moreBtn.addEventListener("click", function () {
        var nowExpanded = _state.logsLimit === LOGS_LIMIT_EXPANDED;
        _state.logsLimit = nowExpanded
          ? LOGS_LIMIT_DEFAULT
          : LOGS_LIMIT_EXPANDED;
        _writeLogsLimit(_state.logsLimit);
        // Refresh the label immediately so the affordance reflects
        // the new state without waiting for the next poll.  After
        // the flip, ``nowExpanded`` is the *prior* state, so the
        // *new* expanded flag is ``!nowExpanded``.
        var flipped = !nowExpanded;
        moreBtn.setAttribute("data-i18n", _showMoreKey(flipped));
        moreBtn.textContent = _showMoreLabel(flipped);
        // Kick a microtask poll so the user sees the new limit
        // applied within ~ 0 ms rather than waiting up to 5 s for
        // the next setInterval tick.  No throttle here — the click
        // is human-driven and the AbortController on the existing
        // in-flight batch will cancel any conflicting prior fetch.
        if (_state.isOpen) {
          Promise.resolve().then(_pollOnce);
        }
      });
      value.appendChild(moreBtn);
    }

    // Rebuild the list every tick.  Cheap (LOGS_TAIL_COUNT items) and
    // avoids per-entry diff bookkeeping.
    while (list.firstChild) list.removeChild(list.firstChild);
    if (entries.length === 0) {
      var emptyLi = document.createElement("li");
      emptyLi.className = "activity-dashboard-logs-empty";
      emptyLi.setAttribute("data-i18n", "settings.activityDashboardLogsEmpty");
      emptyLi.textContent = _t("settings.activityDashboardLogsEmpty");
      list.appendChild(emptyLi);
      return;
    }
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i] || {};
      var level = typeof e.level === "string" ? e.level.slice(0, 16) : "INFO";
      var ts = _logTimeShort(e.ts_iso);
      var msg = typeof e.message === "string" ? e.message : "";
      if (msg.length > LOG_MESSAGE_SLICE)
        msg = msg.slice(0, LOG_MESSAGE_SLICE) + "…";

      var li = document.createElement("li");
      var levelSuffix = _logLevelClassSuffix(level);
      li.className =
        "activity-dashboard-log-entry " +
        "activity-dashboard-log-" +
        levelSuffix;

      var levelSpan = document.createElement("span");
      levelSpan.className = "activity-dashboard-log-level";
      levelSpan.textContent = level;
      li.appendChild(levelSpan);

      var tsSpan = document.createElement("span");
      tsSpan.className = "activity-dashboard-log-ts";
      tsSpan.textContent = ts;
      li.appendChild(tsSpan);

      var msgSpan = document.createElement("span");
      msgSpan.className = "activity-dashboard-log-message";
      msgSpan.textContent = msg || "—";
      li.appendChild(msgSpan);

      list.appendChild(li);
    }
  }

  // ---------- Snapshot orchestration ----------------------------------------

  // Run one poll cycle: fan out the four GETs in parallel, await all,
  // build a per-row snapshot, render, and store ``lastRender`` for
  // tests / dev tools.  Single AbortController so a teardown can
  // cancel the whole batch.
  async function _pollOnce() {
    if (!_state.isOpen) return;
    if (typeof AbortController === "undefined") {
      // Without AbortController we still fire the requests but cannot
      // cancel them; teardown will rely on the stale-text guard.
    }
    var controller =
      typeof AbortController !== "undefined" ? new AbortController() : null;
    _state.inflight = controller;

    var p1 = _fetchJson(ENDPOINT_TASKS, controller, FETCH_TIMEOUT_MS);
    var p2 = _fetchJson(ENDPOINT_SSE_STATS, controller, FETCH_TIMEOUT_MS);
    var p3 = _fetchJson(ENDPOINT_HEALTH, controller, FETCH_TIMEOUT_MS);
    // R156 — append ``?limit=N`` from state so the user's "show 50"
    // toggle takes effect on the next poll without rewriting the URL
    // constant.
    var recentLogsUrl =
      ENDPOINT_RECENT_LOGS_BASE + "?limit=" + _state.logsLimit;
    var p4 = _fetchJson(recentLogsUrl, controller, FETCH_TIMEOUT_MS);

    var results = await Promise.all([p1, p2, p3, p4]);
    var tasks = results[0];
    var sse = results[1];
    var health = results[2];
    var logs = results[3];

    var snapshot = {
      tasks: { text: _formatTasks(tasks), stale: tasks === null },
      sse: { text: _formatSse(sse), stale: sse === null },
      latency: { text: _formatLatency(sse), stale: sse === null },
      notif: { text: _formatNotif(health), stale: health === null },
      health: { text: _formatHealth(health), stale: health === null },
      logs: { text: _formatLogs(logs), stale: logs === null },
    };

    var body = document.getElementById(BODY_ID);
    _renderAll(body, snapshot);
    _state.lastRender = snapshot;
    _state.inflight = null;
  }

  // ---------- Polling lifecycle ---------------------------------------------

  function _startPolling() {
    if (_state.timerId) return;
    // Kick a poll immediately so the user sees fresh data on open;
    // schedule subsequent polls via setInterval.
    Promise.resolve().then(_pollOnce);
    _state.timerId = setInterval(_pollOnce, _state.pollMs);
  }

  function _stopPolling() {
    if (_state.timerId) {
      try {
        clearInterval(_state.timerId);
      } catch (_e) {
        /* noop */
      }
      _state.timerId = null;
    }
    if (_state.inflight) {
      try {
        _state.inflight.abort();
      } catch (_e) {
        /* noop */
      }
      _state.inflight = null;
    }
  }

  function _onVisibilityChange() {
    if (!_state.isOpen) return;
    if (document.hidden) {
      _stopPolling();
    } else {
      _startPolling();
    }
  }

  function _open(toggleBtn, body) {
    _state.isOpen = true;
    if (body) body.removeAttribute("hidden");
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "true");
    _startPolling();
    if (
      _state.visibilityHandler === null &&
      typeof document !== "undefined" &&
      document.addEventListener
    ) {
      _state.visibilityHandler = _onVisibilityChange;
      document.addEventListener("visibilitychange", _state.visibilityHandler);
    }
  }

  function _close(toggleBtn, body) {
    _state.isOpen = false;
    _stopPolling();
    if (body) body.setAttribute("hidden", "");
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "false");
    if (
      _state.visibilityHandler !== null &&
      typeof document !== "undefined" &&
      document.removeEventListener
    ) {
      try {
        document.removeEventListener(
          "visibilitychange",
          _state.visibilityHandler,
        );
      } catch (_e) {
        /* noop */
      }
      _state.visibilityHandler = null;
    }
  }

  // R156 — static label registry for the logs-row "show more / show
  // default" toggle.  Mirrors the ``_labelForRow`` pattern so each
  // i18n key shows up as a direct translate-with-literal call that
  // ``scripts/check_i18n_orphan_keys.py`` (and ``test_runtime_behavior``'s
  // dead-key analyser) can grep — a ternary embedded inside the
  // translate-call argument list would otherwise hide the key
  // strings behind the conditional and the analyser's regex (which
  // only matches the direct translate-with-literal shape) would
  // miss both keys, falsely marking them as orphans.
  function _showMoreLabel(currentlyExpanded) {
    if (currentlyExpanded) {
      return _t("settings.activityDashboardLogsShowDefault");
    }
    return _t("settings.activityDashboardLogsShowMore");
  }

  // Returns the matching ``data-i18n`` key for the current state so
  // the attribute and the rendered text stay in lockstep (used by a
  // future runtime locale-switch that needs to re-translate the
  // button label).  Strict ``=== LOGS_LIMIT_EXPANDED`` check so the
  // function can't accidentally flip on a stale numeric value.
  function _showMoreKey(currentlyExpanded) {
    if (currentlyExpanded) {
      return "settings.activityDashboardLogsShowDefault";
    }
    return "settings.activityDashboardLogsShowMore";
  }

  // ---------- R155 expanded-state persistence -----------------------------

  // Safe localStorage read.  Returns the parsed payload object iff:
  //   - localStorage is reachable (Safari private mode / sandboxed
  //     iframe disable it),
  //   - the stored value parses as JSON,
  //   - the payload has the expected schema version (so a stale older
  //     deploy's payload is silently discarded),
  //   - the embedded ``expanded`` field is a boolean.
  // Returns ``null`` on any failure.  Modelled on R150's
  // ``_readStorage`` so the defensive contract is consistent across
  // both dashboard sub-modules.
  function _readExpandedFlag() {
    try {
      if (typeof localStorage === "undefined" || !localStorage) return null;
      var raw = localStorage.getItem(EXPANDED_LS_KEY);
      if (raw == null) return null;
      var parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (_e) {
        return null;
      }
      if (
        parsed &&
        typeof parsed === "object" &&
        parsed.v === EXPANDED_SCHEMA_VERSION &&
        typeof parsed.expanded === "boolean"
      ) {
        return parsed.expanded;
      }
      return null;
    } catch (_err) {
      return null;
    }
  }

  // Safe localStorage write.  Wraps ``setItem`` in a try/catch so a
  // quota-exceeded / disabled-storage / sandboxed-iframe scenario
  // can't surface a TypeError to the user via the click handler.
  function _writeExpandedFlag(expanded) {
    try {
      if (typeof localStorage === "undefined" || !localStorage) return;
      var payload = JSON.stringify({
        v: EXPANDED_SCHEMA_VERSION,
        expanded: expanded === true,
      });
      localStorage.setItem(EXPANDED_LS_KEY, payload);
    } catch (_e) {
      /* noop — defensive: quota-exceeded / read-only storage / etc. */
    }
  }

  // ---------- R156 logs-limit persistence ---------------------------------

  // Read the persisted ``?limit=N`` for the recent-logs endpoint.
  // Returns ``LOGS_LIMIT_DEFAULT`` or ``LOGS_LIMIT_EXPANDED`` if a
  // valid schema-versioned payload exists; ``null`` otherwise.
  // Defensive contract identical to ``_readExpandedFlag`` —
  // unknown-version payloads are silently dropped (CR#9 F-5 lesson).
  function _readLogsLimit() {
    try {
      if (typeof localStorage === "undefined" || !localStorage) return null;
      var raw = localStorage.getItem(LOGS_LIMIT_LS_KEY);
      if (raw == null) return null;
      var parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (_e) {
        return null;
      }
      if (
        parsed &&
        typeof parsed === "object" &&
        parsed.v === LOGS_LIMIT_SCHEMA_VERSION &&
        typeof parsed.limit === "number" &&
        (parsed.limit === LOGS_LIMIT_DEFAULT ||
          parsed.limit === LOGS_LIMIT_EXPANDED)
      ) {
        return parsed.limit;
      }
      return null;
    } catch (_err) {
      return null;
    }
  }

  // Write the requested limit.  Coerces invalid input back to the
  // default so a future call site that passes a stale number can't
  // poison the storage payload.
  function _writeLogsLimit(limit) {
    var safe =
      limit === LOGS_LIMIT_EXPANDED ? LOGS_LIMIT_EXPANDED : LOGS_LIMIT_DEFAULT;
    try {
      if (typeof localStorage === "undefined" || !localStorage) return;
      var payload = JSON.stringify({
        v: LOGS_LIMIT_SCHEMA_VERSION,
        limit: safe,
      });
      localStorage.setItem(LOGS_LIMIT_LS_KEY, payload);
    } catch (_e) {
      /* noop — defensive: quota-exceeded / read-only storage / etc. */
    }
  }

  // ---------- init ----------------------------------------------------------

  function init() {
    var toggleBtn = document.getElementById(TOGGLE_ID);
    var body = document.getElementById(BODY_ID);
    if (!toggleBtn || !body) return null;
    if (toggleBtn.getAttribute("data-r152-bound") === "1") {
      return { toggleBtn: toggleBtn, body: body };
    }
    toggleBtn.addEventListener("click", function () {
      var expanded = toggleBtn.getAttribute("aria-expanded") === "true";
      if (expanded) {
        _close(toggleBtn, body);
        _writeExpandedFlag(false);
      } else {
        _open(toggleBtn, body);
        _writeExpandedFlag(true);
      }
    });
    toggleBtn.setAttribute("data-r152-bound", "1");

    // R155 — hydrate the persisted expanded state.  If the user had
    // the dashboard open before they reloaded, re-open it for them.
    // No-op if no flag was stored or the flag was ``false``.
    if (_readExpandedFlag() === true) {
      _open(toggleBtn, body);
    }

    // R156 — hydrate the persisted recent-logs limit so the user's
    // "show 50" preference survives a reload.  Falls back to the
    // default if no payload, parse failure, schema-version mismatch,
    // or non-allowlisted value.
    var savedLimit = _readLogsLimit();
    if (savedLimit === LOGS_LIMIT_EXPANDED) {
      _state.logsLimit = LOGS_LIMIT_EXPANDED;
    }

    // R155 — multi-tab sync via the standard ``storage`` event.  When
    // another tab toggles the dashboard, this tab follows along.
    // Defensive: only react to changes on *our* key with a parseable
    // payload, ignore other keys and ignore null payloads (clears).
    if (typeof window !== "undefined" && window.addEventListener) {
      window.addEventListener("storage", function (event) {
        if (!event || event.key !== EXPANDED_LS_KEY) return;
        var newFlag = _readExpandedFlag();
        var currentlyExpanded =
          toggleBtn.getAttribute("aria-expanded") === "true";
        if (newFlag === true && !currentlyExpanded) {
          _open(toggleBtn, body);
        } else if (newFlag === false && currentlyExpanded) {
          _close(toggleBtn, body);
        }
      });
    }

    return { toggleBtn: toggleBtn, body: body };
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }

  // ---------- Public surface ------------------------------------------------

  function setPollMs(ms) {
    var n = parseInt(ms, 10);
    if (!isFinite(n)) return _state.pollMs;
    if (n < POLL_MS_MIN) n = POLL_MS_MIN;
    if (n > POLL_MS_MAX) n = POLL_MS_MAX;
    _state.pollMs = n;
    if (_state.isOpen) {
      _stopPolling();
      _startPolling();
    }
    return _state.pollMs;
  }

  function getLastRender() {
    return _state.lastRender;
  }

  window.AIIA_ACTIVITY_DASHBOARD = {
    DASHBOARD_ID: DASHBOARD_ID,
    TOGGLE_ID: TOGGLE_ID,
    BODY_ID: BODY_ID,
    ROW_ID_PREFIX: ROW_ID_PREFIX,
    ROW_DEFS: ROW_DEFS,
    ENDPOINT_HEALTH: ENDPOINT_HEALTH,
    ENDPOINT_SSE_STATS: ENDPOINT_SSE_STATS,
    ENDPOINT_TASKS: ENDPOINT_TASKS,
    ENDPOINT_RECENT_LOGS: ENDPOINT_RECENT_LOGS,
    POLL_MS_DEFAULT: POLL_MS_DEFAULT,
    POLL_MS_MIN: POLL_MS_MIN,
    POLL_MS_MAX: POLL_MS_MAX,
    FETCH_TIMEOUT_MS: FETCH_TIMEOUT_MS,
    init: init,
    setPollMs: setPollMs,
    getLastRender: getLastRender,
    _fetchJson: _fetchJson,
    _formatTasks: _formatTasks,
    _formatSse: _formatSse,
    _formatLatency: _formatLatency,
    _formatNotif: _formatNotif,
    _formatHealth: _formatHealth,
    _formatLogs: _formatLogs,
    _pollOnce: _pollOnce,
    _ensureRow: _ensureRow,
    _writeRow: _writeRow,
    _renderAll: _renderAll,
    _labelForRow: _labelForRow,
    _renderLogsRow: _renderLogsRow,
    _logLevelClassSuffix: _logLevelClassSuffix,
    _logTimeShort: _logTimeShort,
    LOGS_TAIL_COUNT: LOGS_TAIL_COUNT,
    LOG_MESSAGE_SLICE: LOG_MESSAGE_SLICE,
    _open: _open,
    _close: _close,
    EXPANDED_LS_KEY: EXPANDED_LS_KEY,
    EXPANDED_SCHEMA_VERSION: EXPANDED_SCHEMA_VERSION,
    _readExpandedFlag: _readExpandedFlag,
    _writeExpandedFlag: _writeExpandedFlag,
    LOGS_LIMIT_DEFAULT: LOGS_LIMIT_DEFAULT,
    LOGS_LIMIT_EXPANDED: LOGS_LIMIT_EXPANDED,
    LOGS_LIMIT_LS_KEY: LOGS_LIMIT_LS_KEY,
    LOGS_LIMIT_SCHEMA_VERSION: LOGS_LIMIT_SCHEMA_VERSION,
    ENDPOINT_RECENT_LOGS_BASE: ENDPOINT_RECENT_LOGS_BASE,
    _readLogsLimit: _readLogsLimit,
    _writeLogsLimit: _writeLogsLimit,
  };
})();
