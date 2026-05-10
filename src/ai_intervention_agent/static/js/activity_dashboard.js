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

  function _formatLogs(logs) {
    if (!logs || typeof logs !== "object") return null;
    var entries = logs.logs;
    if (!Array.isArray(entries)) return null;
    var warns = 0;
    var errors = 0;
    for (var i = 0; i < entries.length; i++) {
      var lvl = entries[i] && entries[i].level;
      if (lvl === "WARNING") warns += 1;
      else if (lvl === "ERROR") errors += 1;
    }
    return _t("settings.activityDashboardLogsValue", {
      warnings: _fmtNum(warns),
      errors: _fmtNum(errors),
      total: _fmtNum(entries.length),
    });
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
    if (rowId === "latency")
      return _t("settings.activityDashboardRowLatency");
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
      _writeRow(row, entry.text, entry.stale);
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
    var p4 = _fetchJson(ENDPOINT_RECENT_LOGS, controller, FETCH_TIMEOUT_MS);

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
      if (expanded) _close(toggleBtn, body);
      else _open(toggleBtn, body);
    });
    toggleBtn.setAttribute("data-r152-bound", "1");
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
    _open: _open,
    _close: _close,
  };
})();
