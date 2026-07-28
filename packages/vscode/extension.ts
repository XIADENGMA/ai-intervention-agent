import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as http from "http";
import * as https from "https";
import { WebviewProvider } from "./webview";
import { createLogger } from "./logger";

import type { I18nKey } from "./i18n-keys";

const DEFAULT_SERVER_URL = "http://localhost:8080";
let EXT_VERSION = "0.0.0";
try {
  EXT_VERSION = require("./package.json").version || EXT_VERSION;
} catch {
  try {
    const _pkgPath = require("path").resolve(__dirname, "..", "package.json");
    EXT_VERSION = require(_pkgPath).version || EXT_VERSION;
  } catch {

  }
}

let _cachedBuildId: string | null = null;

function getBuildId(): string {
  if (_cachedBuildId !== null) return _cachedBuildId;
  const stamp = "__BUILD_SHA__";
  if (!stamp.startsWith("__")) {
    _cachedBuildId = stamp;
    return stamp;
  }
  let isDevTree = false;
  try {
    isDevTree = fs.existsSync(path.join(__dirname, "..", "..", ".git"));
  } catch {
    isDevTree = false;
  }
  if (!isDevTree) {
    _cachedBuildId = "dev";
    return "dev";
  }
  try {
    const out: string = require("child_process")
      .execSync("git rev-parse --short HEAD", {
        encoding: "utf8",
        timeout: 2000,
        cwd: __dirname,
        stdio: ["ignore", "pipe", "ignore"],
      })
      .trim();
    const value = out || "dev";
    _cachedBuildId = value;
    return value;
  } catch {
    _cachedBuildId = "dev";
    return "dev";
  }
}

let deactivateHook: (() => void) | null = null;

function normalizeServerUrl(input: unknown): string {
  try {
    const raw = (input ?? "").toString().trim();
    if (!raw) return DEFAULT_SERVER_URL;

    const withScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw)
      ? raw
      : `http://${raw}`;
    const u = new URL(withScheme);
    const protocol = String(u.protocol || "").toLowerCase();
    if (protocol !== "http:" && protocol !== "https:")
      return DEFAULT_SERVER_URL;
    const host = String(u.hostname || "").toLowerCase();
    if (host === "0.0.0.0" || host === "::") {
      const port = u.port ? `:${u.port}` : "";
      return `${protocol}//localhost${port}`;
    }
    return u.origin;
  } catch {
    return DEFAULT_SERVER_URL;
  }
}

function getConfiguredServerUrl(): string {
  const cfg = vscode.workspace.getConfiguration("ai-intervention-agent");
  return normalizeServerUrl(cfg.get<string>("serverUrl", DEFAULT_SERVER_URL));
}

function getRetainWebviewContextWhenHidden(): boolean {
  const cfg = vscode.workspace.getConfiguration("ai-intervention-agent");
  return cfg.get<boolean>("webview.retainContextWhenHidden", false) === true;
}

interface StatusBarState {
  connected?: boolean | null;
  active?: number;
  pending?: number;
}

interface TaskData {
  id: string;
  prompt: string;
}

async function loadHostLocale(
  localesDir: string,
  loc: string,
  hostLocales: Record<string, Record<string, unknown>>,
): Promise<void> {
  try {
    const raw = await fs.promises.readFile(
      path.join(localesDir, `${loc}.json`),
      "utf8",
    );
    if (raw) hostLocales[loc] = JSON.parse(raw) as Record<string, unknown>;
  } catch {

  }
}

async function activate(context: vscode.ExtensionContext): Promise<void> {
  let outputChannel: vscode.OutputChannel;
  try {
    outputChannel = vscode.window.createOutputChannel("AI Intervention Agent", {
      log: true,
    });
  } catch {
    outputChannel = vscode.window.createOutputChannel("AI Intervention Agent");
  }

  const logger = createLogger(outputChannel, {
    component: "ext",
    getLevel: () => {
      try {
        const cfg = vscode.workspace.getConfiguration("ai-intervention-agent");
        return cfg.get<string>("logLevel", "info") ?? "info";
      } catch {
        return "info";
      }
    },
  });
  let serverUrl = getConfiguredServerUrl();
  const retainWebviewContextWhenHidden = getRetainWebviewContextWhenHidden();

  try {
    EXT_VERSION = context.extension.packageJSON.version || EXT_VERSION;
  } catch {

  }

  try {
    const cfg = vscode.workspace.getConfiguration("ai-intervention-agent");
    const logLevel = cfg.get<string>("logLevel", "info");
    logger.event(
      "ext.activate",
      {
        version: EXT_VERSION,
        buildId: getBuildId(),
        serverUrl,
        logLevel,
        retainWebviewContextWhenHidden,
      },
      { level: "info" },
    );
  } catch {
    logger.event(
      "ext.activate",
      {
        version: EXT_VERSION,
        buildId: getBuildId(),
        serverUrl,
        retainWebviewContextWhenHidden,
      },
      { level: "info" },
    );
  }

  const hostLocales: Record<string, Record<string, unknown>> = {};
  let hostLang = "en";
  try {
    const localesDir = path.join(context.extensionPath, "locales");
    const localeReads: Promise<void>[] = [];
    for (const loc of ["en", "zh-CN"]) {
      localeReads.push(loadHostLocale(localesDir, loc, hostLocales));
    }
    await Promise.all(localeReads);
    try {
      const vsLang = vscode.env.language || "";
      hostLang = vsLang.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
    } catch {

    }
  } catch {

  }

  const hostT = (key: I18nKey): string => {
    try {
      const dict = hostLocales[hostLang] || hostLocales["en"];
      if (!dict) return key;
      const parts = key.split(".");
      let node: unknown = dict;
      for (const p of parts) {
        if (node === null || node === undefined || typeof node !== "object")
          return key;
        node = (node as Record<string, unknown>)[p];
      }
      return typeof node === "string" ? node : key;
    } catch {
      return key;
    }
  };

  const statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100,
  );
  statusBar.command = "ai-intervention-agent.openPanel";
  statusBar.tooltip = `AI Intervention Agent\nserverUrl: ${serverUrl}\n${hostT("statusBar.language")}: ${hostLang}\n${hostT("statusBar.clickToOpen")}\n${hostT("statusBar.openSettings")}`;
  statusBar.text = "$(sparkle-filled) --";
  statusBar.hide();
  let statusBarShown = false;

  const setStatusBarShown = (shouldShow: boolean): void => {
    const next = !!shouldShow;
    if (next === statusBarShown) return;
    statusBarShown = next;
    if (next) {
      statusBar.show();
    } else {
      statusBar.hide();
    }
  };

  let lastConnected: boolean | null = null;
  let lastActive: number | null = null;
  let lastPending: number | null = null;
  let lastPollAtMs = 0;
  let lastPollDurationMs: number | null = null;
  let lastPollHttpStatus: number | null = null;
  let lastPollErrorName = "";
  let lastPollError = "";

  let extKnownTaskIds = new Set<string>();
  let extTaskTrackingInitialized = false;

  const formatTotalCount = (n: unknown): string => {
    const num =
      typeof n === "number" && Number.isFinite(n)
        ? Math.max(0, Math.floor(n))
        : 0;
    return num > 99 ? "99+" : String(num);
  };

  const buildStatusBarTooltip = ({
    connected,
    active,
    pending,
  }: StatusBarState = {}): string => {
    try {
      const statusText =
        connected === true
          ? hostT("statusBar.connected")
          : connected === false
            ? hostT("statusBar.disconnected")
            : hostT("statusBar.unknown");
      const a =
        typeof active === "number" && Number.isFinite(active) ? active : 0;
      const p =
        typeof pending === "number" && Number.isFinite(pending) ? pending : 0;
      const total = a + p;

      const lines: string[] = [];
      lines.push(`AI Intervention Agent（${statusText}）`);
      if (connected === true) {
        lines.push(
          `${hostT("statusBar.tasks")}：Active ${a}  Pending ${p}  Total ${total}`,
        );
      } else {
        lines.push(`${hostT("statusBar.tasks")}：--`);
      }

      lines.push(`${hostT("statusBar.language")}: ${hostLang}`);

      if (connected === false || connected === null) {
        lines.push(`serverUrl: ${serverUrl}`);
      }
      if ((connected === false || connected === null) && lastPollError) {
        const name = lastPollErrorName ? `${lastPollErrorName}: ` : "";
        lines.push(`${hostT("statusBar.reason")}：${name}${lastPollError}`);
      }

      return lines.join("\n");
    } catch {
      return `AI Intervention Agent\nserverUrl: ${serverUrl}`;
    }
  };

  const applyStatusBarPresentation = ({
    connected,
    active,
    pending,
  }: StatusBarState = {}): void => {
    try {
      const a =
        typeof active === "number" && Number.isFinite(active) ? active : 0;
      const p =
        typeof pending === "number" && Number.isFinite(pending) ? pending : 0;
      const total = a + p;

      if (connected === true) {
        statusBar.text = `$(sparkle-filled) ${formatTotalCount(total)}`;
      } else if (connected === false) {
        statusBar.text = vscode.l10n.t("$(sparkle-filled) Offline");
      } else {
        statusBar.text = "$(sparkle-filled) --";
      }

      statusBar.tooltip = buildStatusBarTooltip({
        connected,
        active: a,
        pending: p,
      });
      try {
        statusBar.accessibilityInformation = {
          label:
            connected === true
              ? vscode.l10n.t(
                  "AI Intervention Agent connected, {0} task(s) total",
                  String(total),
                )
              : connected === false
                ? vscode.l10n.t("AI Intervention Agent not connected")
                : vscode.l10n.t("AI Intervention Agent status unknown"),
          role: "status",
        };
      } catch {

      }
    } catch {

    }
  };

  const updateStatusBarVisibility = (): void => {
    setStatusBarShown(true);
  };

  updateStatusBarVisibility();

  let statusPollDisposed = false;
  let statusPollAbortController: AbortController | null = null;

  const abortStatusPollRequest = (): void => {
    if (
      statusPollAbortController &&
      typeof statusPollAbortController.abort === "function"
    ) {
      try {
        statusPollAbortController.abort();
      } catch {

      }
    }
    statusPollAbortController = null;
  };

  const updateStatusBar = async (): Promise<boolean | null> => {
    if (typeof fetch !== "function") {
      lastPollAtMs = Date.now();
      lastPollDurationMs = null;
      lastPollHttpStatus = null;
      lastPollErrorName = "NoFetch";
      lastPollError = vscode.l10n.t(
        "No fetch available in current runtime; cannot probe server status",
      );
      applyStatusBarPresentation({ connected: null, active: 0, pending: 0 });
      setStatusBarShown(true);
      return null;
    }

    const requestServerUrl = serverUrl;
    const isStaleStatusPoll = (): boolean =>
      statusPollDisposed || serverUrl !== requestServerUrl;
    const controller =
      typeof AbortController !== "undefined" ? new AbortController() : null;
    if (controller) {
      statusPollAbortController = controller;
    }
    const timeoutId = controller
      ? setTimeout(() => {
          try {
            controller.abort();
          } catch {

          }
        }, 1500)
      : null;

    const requestId = `status_${Date.now().toString(16)}_${Math.random().toString(16).slice(2, 8)}`;
    const startedAt = Date.now();
    const prevConnected = lastConnected;
    const prevActive = lastActive;
    const prevPending = lastPending;

    try {
      const resp = await fetch(`${requestServerUrl}/api/tasks`, {
        signal: controller ? controller.signal : undefined,
        headers: { Accept: "application/json", "Cache-Control": "no-cache" },
      } as RequestInit);

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const data = (await resp.json()) as Record<string, unknown>;
      const stats =
        data && data.stats && typeof data.stats === "object"
          ? (data.stats as Record<string, unknown>)
          : {};
      const active =
        stats && typeof stats.active === "number" ? stats.active : 0;
      const pending =
        stats && typeof stats.pending === "number" ? stats.pending : 0;
      const connected = !!(data && data.success);
      const durationMs = Date.now() - startedAt;
      if (isStaleStatusPoll()) {
        logger.event(
          "server.poll.stale",
          { requestId, serverUrlChanged: serverUrl !== requestServerUrl },
          { level: "debug" },
        );
        return null;
      }
      const changed =
        connected !== prevConnected ||
        active !== prevActive ||
        pending !== prevPending;
      lastPollAtMs = Date.now();
      lastPollDurationMs = durationMs;
      lastPollHttpStatus = resp.status;
      lastPollErrorName = "";
      lastPollError = "";

      if (changed) {
        lastConnected = connected;
        lastActive = active;
        lastPending = pending;

        applyStatusBarPresentation({ connected, active, pending });

        const level =
          connected === false && prevConnected === true
            ? "warn"
            : connected === true && prevConnected === false
              ? "info"
              : "debug";
        logger.event(
          "server.poll",
          {
            requestId,
            ok: true,
            httpStatus: resp.status,
            connected,
            active,
            pending,
            durationMs,
          },
          { level },
        );
      }
      if (!changed && statusBarShown) {
        applyStatusBarPresentation({ connected, active, pending });
      }
      updateStatusBarVisibility();

      if (connected && data && Array.isArray(data.tasks)) {
        try {
          const currentIds = new Set<string>();
          const newTaskData: TaskData[] = [];
          const newTaskIds: string[] = [];
          for (const t of data.tasks as Array<Record<string, unknown>>) {
            if (!t || !t.task_id) continue;
            const taskId = String(t.task_id);
            currentIds.add(taskId);
            if (extTaskTrackingInitialized && !extKnownTaskIds.has(taskId)) {
              newTaskData.push({ id: taskId, prompt: String(t.prompt || "") });
              newTaskIds.push(taskId);
            }
          }
          if (newTaskData.length > 0 && extTaskTrackingInitialized) {
            if (
              provider &&
              typeof (provider as unknown as Record<string, unknown>)
                .dispatchNewTaskNotification === "function"
            ) {
              if (isViewVisible) {
                logger.event(
                  "ext.skip_dispatch_webview_visible",
                  { ids: newTaskIds },
                  { level: "debug" },
                );
              } else {
                logger.event(
                  "ext.dispatch_new_task",
                  { ids: newTaskIds, viewVisible: false },
                  { level: "info" },
                );
                (
                  provider as unknown as {
                    dispatchNewTaskNotification: (tasks: TaskData[]) => void;
                  }
                ).dispatchNewTaskNotification(newTaskData);
              }
            }
          }
          extKnownTaskIds = currentIds;
          if (!extTaskTrackingInitialized && connected) {
            extTaskTrackingInitialized = true;
            logger.event(
              "ext.tracking_initialized",
              { knownCount: currentIds.size },
              { level: "info" },
            );
          }
        } catch {

        }
      }

      return connected;
    } catch (e: unknown) {
      if (isStaleStatusPoll()) {
        return null;
      }
      const durationMs = Date.now() - startedAt;
      const errName = e instanceof Error ? e.name : "";
      const errMsg = e instanceof Error ? e.message : String(e);
      lastPollAtMs = Date.now();
      lastPollDurationMs = durationMs;
      lastPollHttpStatus = null;
      lastPollErrorName = errName;
      lastPollError = errMsg;

      if (lastConnected !== false) {
        lastConnected = false;
        lastActive = null;
        lastPending = null;
      }
      applyStatusBarPresentation({ connected: false, active: 0, pending: 0 });

      const level =
        prevConnected === true
          ? "warn"
          : prevConnected === false
            ? "debug"
            : "debug";
      logger.event(
        "server.poll",
        {
          requestId,
          ok: false,
          connected: false,
          durationMs,
          errorName: errName,
          error: errMsg,
        },
        { level },
      );

      updateStatusBarVisibility();
      return false;
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
      if (statusPollAbortController === controller) {
        statusPollAbortController = null;
      }
    }
  };

  const STATUS_POLL_FAST_MS = 3000;
  const STATUS_POLL_SLOW_MS = 15000;
  const STATUS_POLL_SSE_FALLBACK_MS = 60000;
  const STATUS_POLL_MAX_MS = 60000;
  const WEBVIEW_STATS_FRESH_MS = 5000;
  let statusPollTimer: ReturnType<typeof setTimeout> | null = null;
  let statusPollBackoffMs = STATUS_POLL_FAST_MS;
  let statusPollInFlight = false;
  let isViewVisible = true;
  let isWindowFocused = vscode.window.state.focused;
  let lastWebviewStatsAtMs = 0;

  let _sseReq: http.ClientRequest | null = null;
  let _sseConnected = false;
  let _sseReconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let _sseReconnectDelay = 1000;
  let _sseDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  let _lastEventId: string | null = null;

  const _connectSSE = (): void => {
    if (statusPollDisposed) return;
    _disconnectSSE();

    let sseUrl = `${serverUrl}/api/events`;
    if (_lastEventId) {
      const sep = sseUrl.indexOf("?") >= 0 ? "&" : "?";
      sseUrl += `${sep}last_event_id=${encodeURIComponent(_lastEventId)}`;
    }
    const parsed = (() => {
      try {
        return new URL(sseUrl);
      } catch {
        return null;
      }
    })();
    if (!parsed) return;

    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (_lastEventId) {
      headers["Last-Event-ID"] = _lastEventId;
    }

    const httpMod = parsed.protocol === "https:" ? https : http;
    const req = httpMod.get(sseUrl, { headers }, (res) => {
      if (_sseReq !== req) {
        res.resume();
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        _handleSSEError();
        return;
      }

      _sseConnected = true;
      _sseReconnectDelay = 1000;
      logger.event("sse.connected", {}, { level: "debug" });

      let buffer = "";
      let pendingId: string | null = null;
      let pendingType: string | null = null;
      let pendingDataLines: string[] = [];

      const flushPendingEvent = (): void => {
        if (
          pendingDataLines.length === 0 &&
          pendingType === null &&
          pendingId === null
        ) {
          return;
        }

        const dataStr = pendingDataLines.join("\n");
        const evType = pendingType || "message";

        if (pendingId !== null && pendingId !== "") {
          const parsedId = Number(pendingId);
          if (Number.isFinite(parsedId) && parsedId > 0) {
            _lastEventId = String(parsedId);
          }
        }

        if (evType === "gap_warning") {

          logger.event("sse.gap_warning", { dataStr }, { level: "warn" });
          if (_sseDebounceTimer) clearTimeout(_sseDebounceTimer);
          _sseDebounceTimer = setTimeout(() => {
            _sseDebounceTimer = null;
            scheduleStatusPoll(0);
          }, 0);
          pendingId = null;
          pendingType = null;
          pendingDataLines = [];
          return;
        }

        if (evType === "config_changed") {

          logger.event("sse.config_changed", { dataStr }, { level: "info" });
          let hint = "AI Intervention Agent: configuration file changed.";
          try {
            const detail = JSON.parse(dataStr);
            if (detail && typeof detail.hint === "string" && detail.hint) {
              hint = detail.hint;
            }
          } catch {

          }
          try {

            vscode.window.setStatusBarMessage(`$(sync) ${hint}`, 6000);
          } catch {

          }
          pendingId = null;
          pendingType = null;
          pendingDataLines = [];
          return;
        }

        if (evType === "heartbeat") {

          logger.event("sse.heartbeat", { dataStr }, { level: "debug" });
          pendingId = null;
          pendingType = null;
          pendingDataLines = [];
          return;
        }

        if (evType !== "task_changed" && evType !== "message") {

          logger.event(
            "sse.unknown_event",
            { evType, dataStr },
            { level: "debug" },
          );
          pendingId = null;
          pendingType = null;
          pendingDataLines = [];
          return;
        }

        try {
          const ev = JSON.parse(dataStr);
          if (ev && ev.new_status) {
            logger.event(
              "sse.task_changed",
              { taskId: ev.task_id, status: ev.new_status },
              { level: "debug" },
            );

            const optStats =
              ev.stats && typeof ev.stats === "object"
                ? (ev.stats as Record<string, unknown>)
                : null;
            if (optStats) {
              const optActive =
                typeof optStats.active === "number" ? optStats.active : 0;
              const optPending =
                typeof optStats.pending === "number" ? optStats.pending : 0;
              if (lastConnected !== false) {
                lastActive = optActive;
                lastPending = optPending;
                applyStatusBarPresentation({
                  connected: true,
                  active: optActive,
                  pending: optPending,
                });
              }
            }
            if (_sseDebounceTimer) clearTimeout(_sseDebounceTimer);
            _sseDebounceTimer = setTimeout(() => {
              _sseDebounceTimer = null;
              scheduleStatusPoll(0);
            }, 80);
          }
        } catch {

        }
        pendingId = null;
        pendingType = null;
        pendingDataLines = [];
      };

      res.setEncoding("utf8");
      res.on("data", (chunk: string) => {
        if (_sseReq !== req) return;
        buffer += chunk;
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line === "") {

            flushPendingEvent();
            continue;
          }
          if (line.startsWith(":")) {

            continue;
          }
          if (line.startsWith("id:")) {
            pendingId = line.slice(3).replace(/^\s+/, "");
            continue;
          }
          if (line.startsWith("event:")) {
            pendingType = line.slice(6).replace(/^\s+/, "");
            continue;
          }
          if (line.startsWith("data:")) {

            pendingDataLines.push(line.slice(5).replace(/^\s/, ""));
            continue;
          }

        }
      });
      res.on("end", () => {
        if (_sseReq === req) _handleSSEError();
      });
      res.on("error", () => {
        if (_sseReq === req) _handleSSEError();
      });
    });

    req.on("error", () => {
      if (_sseReq === req) _handleSSEError();
    });
    _sseReq = req;
  };

  const _handleSSEError = (): void => {
    _sseConnected = false;
    if (_sseReq) {
      try {
        _sseReq.destroy();
      } catch {

      }
      _sseReq = null;
    }
    if (statusPollDisposed) return;
    logger.event(
      "sse.disconnected",
      { reconnectIn: _sseReconnectDelay },
      { level: "debug" },
    );
    if (_sseReconnectTimer) clearTimeout(_sseReconnectTimer);
    _sseReconnectTimer = setTimeout(() => {
      _sseReconnectTimer = null;
      if (!statusPollDisposed) _connectSSE();
    }, _sseReconnectDelay);
    _sseReconnectDelay = Math.min(30000, _sseReconnectDelay * 2);
  };

  const _disconnectSSE = (): void => {
    if (_sseReconnectTimer) {
      clearTimeout(_sseReconnectTimer);
      _sseReconnectTimer = null;
    }
    if (_sseDebounceTimer) {
      clearTimeout(_sseDebounceTimer);
      _sseDebounceTimer = null;
    }
    if (_sseReq) {
      try {
        _sseReq.destroy();
      } catch {

      }
      _sseReq = null;
    }
    _sseConnected = false;
  };

  const isWebviewStatsFresh = (): boolean =>
    isViewVisible &&
    lastWebviewStatsAtMs > 0 &&
    Date.now() - lastWebviewStatsAtMs < WEBVIEW_STATS_FRESH_MS;

  const computeBaseDelayMs = (): number => {
    if (_sseConnected) return STATUS_POLL_SSE_FALLBACK_MS;
    if (isWebviewStatsFresh()) return STATUS_POLL_SLOW_MS;
    if (isViewVisible && isWindowFocused) return STATUS_POLL_FAST_MS;
    if (isWindowFocused) return STATUS_POLL_FAST_MS * 2;
    return STATUS_POLL_SLOW_MS;
  };
  const computeNextDelayMs = (): number => {
    const base = computeBaseDelayMs();
    if (lastConnected === false) {
      return Math.min(STATUS_POLL_MAX_MS, Math.max(base, statusPollBackoffMs));
    }
    return base;
  };

  const scheduleStatusPoll = (delayMs: number): void => {
    if (statusPollDisposed) return;
    if (statusPollTimer) {
      clearTimeout(statusPollTimer);
      statusPollTimer = null;
    }
    statusPollTimer = setTimeout(runStatusPoll, Math.max(0, delayMs));
  };

  const runStatusPoll = async (): Promise<void> => {
    if (statusPollDisposed) return;
    if (statusPollInFlight) {
      scheduleStatusPoll(computeNextDelayMs());
      return;
    }
    statusPollInFlight = true;
    try {
      const connected = await updateStatusBar();
      if (connected === true) {
        statusPollBackoffMs = STATUS_POLL_FAST_MS;
        if (!_sseConnected && !_sseReq) _connectSSE();
      } else if (connected === false) {
        statusPollBackoffMs = Math.min(
          STATUS_POLL_MAX_MS,
          Math.round(statusPollBackoffMs * 1.7),
        );
      }
    } finally {
      statusPollInFlight = false;
      if (!statusPollDisposed) {
        scheduleStatusPoll(computeNextDelayMs());
      }
    }
  };

  const provider = new WebviewProvider(
    context.extensionUri,
    outputChannel,
    serverUrl,
    EXT_VERSION,
    (visible: boolean) => {
      isViewVisible = !!visible;
      updateStatusBarVisibility();
      scheduleStatusPoll(0);
    },
    ({ connected, active, pending }: StatusBarState = {}) => {
      lastWebviewStatsAtMs = Date.now();
      const c = connected === true;
      const a =
        typeof active === "number" && Number.isFinite(active)
          ? Math.max(0, Math.floor(active))
          : 0;
      const p =
        typeof pending === "number" && Number.isFinite(pending)
          ? Math.max(0, Math.floor(pending))
          : 0;

      const changed =
        c !== lastConnected || a !== lastActive || p !== lastPending;
      if (changed) {
        lastConnected = c;
        lastActive = a;
        lastPending = p;
        applyStatusBarPresentation({ connected: c, active: a, pending: p });
      } else if (statusBarShown) {
        applyStatusBarPresentation({ connected: c, active: a, pending: p });
      }

      if (c) {
        statusPollBackoffMs = STATUS_POLL_FAST_MS;
      } else {
        statusPollBackoffMs = Math.min(
          STATUS_POLL_MAX_MS,
          Math.round(statusPollBackoffMs * 1.7),
        );
      }
    },
    (taskIds: string[]) => {
      if (!Array.isArray(taskIds)) return;
      for (const id of taskIds) {
        if (id) extKnownTaskIds.add(String(id));
      }
    },
    (lang: string) => {
      if (!lang || lang === "auto") return;
      const normalized = lang.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
      if (normalized !== hostLang) {
        hostLang = normalized;
        logger.event(
          "i18n.hostLangChanged",
          { lang: hostLang },
          { level: "info" },
        );
        applyStatusBarPresentation({
          connected: lastConnected,
          active: lastActive ?? undefined,
          pending: lastPending ?? undefined,
        });
      }
    },
    retainWebviewContextWhenHidden,
  );
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      "aiInterventionAgent.feedbackView",
      provider,
      {
        webviewOptions: {

          retainContextWhenHidden: retainWebviewContextWhenHidden,
        },
      },
    ),
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (!e.affectsConfiguration("ai-intervention-agent.serverUrl")) return;

      const next = getConfiguredServerUrl();
      if (!next || next === serverUrl) return;

      const prev = serverUrl;
      serverUrl = next;
      abortStatusPollRequest();
      logger.event(
        "config.update",
        { key: "serverUrl", prev, next: serverUrl },
        { level: "info" },
      );

      lastConnected = null;
      lastActive = null;
      lastPending = null;
      statusPollBackoffMs = STATUS_POLL_FAST_MS;
      extKnownTaskIds = new Set<string>();
      extTaskTrackingInitialized = false;
      _lastEventId = null;
      statusBar.tooltip = `AI Intervention Agent\nserverUrl: ${serverUrl}\n${hostT("statusBar.language")}: ${hostLang}\n${hostT("statusBar.clickToOpen")}\n${hostT("statusBar.openSettings")}`;
      _connectSSE();
      scheduleStatusPoll(0);

      if (
        provider &&
        typeof (
          provider as unknown as { updateServerUrl?: (url: string) => void }
        ).updateServerUrl === "function"
      ) {
        (
          provider as unknown as { updateServerUrl: (url: string) => void }
        ).updateServerUrl(serverUrl);
      }
    }),
  );

  context.subscriptions.push(
    vscode.window.onDidChangeWindowState((state) => {
      isWindowFocused = !!state.focused;
      scheduleStatusPoll(
        isWindowFocused && isViewVisible ? 0 : computeNextDelayMs(),
      );
      try {
        if (
          provider &&
          typeof (
            provider as unknown as {
              onWindowFocusChanged?: (focused: boolean) => void;
            }
          ).onWindowFocusChanged === "function"
        ) {
          (
            provider as unknown as {
              onWindowFocusChanged: (focused: boolean) => void;
            }
          ).onWindowFocusChanged(isWindowFocused);
        }
      } catch {

      }
    }),
  );

  _connectSSE();
  scheduleStatusPoll(0);

  const openPanelDisposable = vscode.commands.registerCommand(
    "ai-intervention-agent.openPanel",
    async function () {
      await vscode.commands.executeCommand(
        "workbench.view.extension.aiInterventionAgent",
      );
      try {
        await vscode.commands.executeCommand(
          "aiInterventionAgent.feedbackView.focus",
        );
      } catch {

      }
    },
  );

  const openSettingsDisposable = vscode.commands.registerCommand(
    "ai-intervention-agent.openSettings",
    async function () {
      try {
        await vscode.commands.executeCommand(
          "workbench.action.openSettings",
          "ai-intervention-agent.serverUrl",
        );
      } catch {
        await vscode.commands.executeCommand(
          "workbench.action.openSettingsJson",
        );
      }
    },
  );

  context.subscriptions.push(openPanelDisposable);
  context.subscriptions.push(openSettingsDisposable);
  context.subscriptions.push(outputChannel);
  context.subscriptions.push(statusBar);

  const cleanup = (): void => {
    try {
      statusPollDisposed = true;
      abortStatusPollRequest();
      _disconnectSSE();
      if (statusPollTimer) {
        clearTimeout(statusPollTimer);
        statusPollTimer = null;
      }
      try {
        if (
          provider &&
          typeof (provider as unknown as { dispose?: () => void }).dispose ===
            "function"
        ) {
          (provider as unknown as { dispose: () => void }).dispose();
        }
      } catch {

      }
    } catch {

    }
  };
  deactivateHook = cleanup;
  context.subscriptions.push({ dispose: cleanup });
}

function deactivate(): void {
  try {
    if (deactivateHook && typeof deactivateHook === "function") {
      deactivateHook();
    }
  } catch {

  } finally {
    deactivateHook = null;
  }
}

module.exports = {
  activate,
  deactivate,
};
