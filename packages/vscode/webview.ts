import * as vscode from "vscode";
import * as fs from "fs";
import * as crypto from "crypto";
import { createLogger } from "./logger";
import type { Logger } from "./logger";
import { AppleScriptExecutor } from "./applescript-executor";
import { NotificationCenter } from "./notification-center";
import { NotificationType } from "./notification-models";
import {
  VSCodeApiNotificationProvider,
  MacOSNativeNotificationProvider,
} from "./notification-providers";

const EXT_GITHUB_URL = "https://github.com/XIADENGMA/ai-intervention-agent";

/**
 * 生成符合 CSP3 (`script-src 'nonce-...'`) 推荐熵阈值的 nonce。
 *
 * **不要换回 `Math.random()`。** 历史实现是 62-char alphabet × 32 字符
 * 的字符串，看起来熵很高，但 V8 的 `Math.random` 内部是 xorshift128+
 * (53 bits PRNG state)，输出在 [V8 源码](https://github.com/v8/v8/blob/main/src/numbers/math-random.cc)
 * 已经是公开可分析的 —— 攻击者只要观察少量 nonce 就能预测后续的，
 * 把"unsafe-inline 的兜底防御"打成纸糊（CSP3 §6 安全条款明确禁止
 * 用 non-CSPRNG 生成 nonce）。
 *
 * Node.js 的 `crypto.randomBytes(16)` 走 OS CSPRNG（macOS
 * `getentropy`、Linux `getrandom`、Windows `BCryptGenRandom`），16 字节
 * 即 128 bits 熵，超过 CSP3 推荐的 64 bits 阈值；`base64` 编码后是 24
 * 字符（含两位 `=` padding，浏览器 CSP nonce 比对不挑剔 padding）。
 *
 * 与 [VSCode 官方 webview-sample](https://github.com/microsoft/vscode-extension-samples/blob/main/webview-sample/src/extension.ts) 同步。
 */
function getNonce(): string {
  return crypto.randomBytes(16).toString("base64");
}

function safeReadTextFile(uri: vscode.Uri): string {
  try {
    if (!uri || !uri.fsPath) return "";
    return fs.readFileSync(uri.fsPath, "utf8");
  } catch {
    return "";
  }
}

function safeJsonForInlineScript(value: unknown): string {
  try {
    return JSON.stringify(value).replace(/</g, "\\u003c");
  } catch {
    return "null";
  }
}

function safeStringForInlineScript(value: unknown): string {
  try {
    return JSON.stringify(String(value ?? "")).replace(/</g, "\\u003c");
  } catch {
    return '""';
  }
}

interface WebviewMessage {
  type: string;
  [key: string]: unknown;
}

interface TaskStatsState {
  connected: boolean;
  active: number;
  pending: number;
  total?: number;
}

interface NotificationConfig {
  enabled: boolean;
  macosNativeEnabled: boolean;
}

interface TaskData {
  id: string;
  prompt: string;
}

type VisibilityCallback = (visible: boolean) => void;
type TaskStatsCallback = (stats: TaskStatsState) => void;
type TaskIdsCallback = (ids: string[]) => void;

/**
 * AI交互代理的Webview视图提供器
 *
 * 功能说明：
 * - 提供侧边栏webview视图，展示任务反馈界面
 * - 完全独立实现HTML/CSS/JS，无需iframe
 * - 支持多任务标签页切换和倒计时显示
 * - 实现与本地服务器的轮询通信机制
 */
export class WebviewProvider implements vscode.WebviewViewProvider {
  private _extensionUri: vscode.Uri;
  private _outputChannel: vscode.OutputChannel;
  private _logger: Logger;
  private _appleScriptLogger: Logger;
  private _appleScriptExecutor: AppleScriptExecutor;
  private _notificationLogger: Logger;
  private _notificationCenter: NotificationCenter;
  private _vscodeNotificationProvider: VSCodeApiNotificationProvider;
  private _macosNativeNotificationProvider: MacOSNativeNotificationProvider;
  private _serverUrl: string;
  private _extensionVersion: string;
  private _onVisibilityChanged: VisibilityCallback | null;
  private _onTasksStatsChanged: TaskStatsCallback | null;
  private _onNewTaskIdsFromWebview: TaskIdsCallback | null;
  private _onLanguageChanged: ((lang: string) => void) | null;
  private _view: vscode.WebviewView | null;
  private _disposables: vscode.Disposable[];
  private _lastServerStatus: boolean | null;
  private _hasEverConnected: boolean;
  private _webviewReady: boolean;
  private _webviewReadyTimer: ReturnType<typeof setTimeout> | null;
  private _pendingMessages: WebviewMessage[];
  private _pendingMessageLimit: number;
  private _revealPanelUntilMs: number;
  private _notificationConfig: NotificationConfig | null;
  private _notificationConfigFetchedAt: number;
  private _notificationConfigFetchPromise: Promise<NotificationConfig | null> | null;
  private _cachedServerLang: string | null;
  private _cachedLocales: Record<string, Record<string, unknown>>;
  private _cachedStaticAssets: {
    activityIconSvg: string;
  } | null;
  // R20.13-E：``inlineAllLocalesLiteral`` 是 ``_getHtmlContent`` 每次都要序列化
  // 一次的 ~10 KB JSON。对单个 webview 生命周期内 ``_cachedLocales`` 内容很少
  // 变（只有 ``_preloadResources`` 第一次填充 + 偶尔 fallback 补一两条 entry），
  // 把序列化结果缓存起来配合一个键（locale 名集合 + 内容长度签名）做轻量失效。
  // 命中缓存时 ``_getHtmlContent`` 直接拿 string 拼 HTML，省去 ``JSON.stringify``
  // (~50-100 µs) + ``replace(/</g, ...)`` (~5 µs)。绝对值噪声级，但配合 R20.12-B
  // 的「能不重算就别重算」思路，一致性比 µs 更重要。
  private _cachedInlineAllLocalesJson: string | null;
  private _cachedInlineAllLocalesKey: string | null;
  private _prefetchServerLangPromise: Promise<void> | null;
  private _prefetchServerLangAbortController: AbortController | null;
  private _visibilityBenchmarkSeq: number;
  private _retainContextWhenHidden: boolean;
  private _webviewServerUrl: string;
  // R692 (TODO#6-2)：通知直达任务。webview 隐藏期间派发新任务通知时记录
  // 首个 task_id；用户点击状态栏/通知回到面板（webview 变为可见）时，
  // 在时间窗内把该任务推给前端切换，实现"点通知 → 直达对应任务"。
  private _pendingNotifiedTaskId: string;
  private _pendingNotifiedTaskAtMs: number;

  constructor(
    extensionUri: vscode.Uri,
    outputChannel: vscode.OutputChannel,
    serverUrl = "http://localhost:8080",
    extensionVersion: string = "0.0.0",
    onVisibilityChanged?: VisibilityCallback,
    onTasksStatsChanged?: TaskStatsCallback,
    onNewTaskIdsFromWebview?: TaskIdsCallback,
    onLanguageChanged?: (lang: string) => void,
    retainContextWhenHidden = false,
  ) {
    this._extensionUri = extensionUri;
    this._outputChannel = outputChannel;
    this._logger = createLogger(outputChannel, {
      component: "ext:webview",
      getLevel: () => {
        try {
          const cfg = vscode.workspace.getConfiguration(
            "ai-intervention-agent",
          );
          return cfg.get<string>("logLevel", "info") ?? "info";
        } catch {
          return "info";
        }
      },
    });
    this._appleScriptLogger = this._logger.child("applescript");
    this._appleScriptExecutor = new AppleScriptExecutor({
      logger: this._appleScriptLogger,
    });
    this._notificationLogger = this._logger.child("notify");
    this._notificationCenter = new NotificationCenter({
      logger: this._notificationLogger,
      dedupeWindowMs: 10000,
    });
    this._vscodeNotificationProvider = new VSCodeApiNotificationProvider({
      logger: this._notificationLogger.child("vscode"),
    });
    this._macosNativeNotificationProvider = new MacOSNativeNotificationProvider(
      {
        logger: this._appleScriptLogger,
        executor: this._appleScriptExecutor,
        vscodeApi: vscode,
      },
    );
    this._notificationCenter.registerProvider(
      NotificationType.VSCODE,
      this._vscodeNotificationProvider,
    );
    this._notificationCenter.registerProvider(
      NotificationType.MACOS_NATIVE,
      this._macosNativeNotificationProvider,
    );
    this._serverUrl = serverUrl;
    this._webviewServerUrl = this._normalizeWebviewServerUrl(serverUrl);
    // R20.13-B/F：从 host 端 ``activate`` 一次性传入版本号，免得每次
    // ``_getHtmlContent`` 都掏 ``vscode.extensions.getExtension`` 注册表查表
    // （macOS M1 实测每次 ~1-3 ms，热路径 1-2 次 / 会话）。
    this._extensionVersion =
      typeof extensionVersion === "string" && extensionVersion
        ? extensionVersion
        : "0.0.0";
    this._onVisibilityChanged =
      typeof onVisibilityChanged === "function" ? onVisibilityChanged : null;
    this._onTasksStatsChanged =
      typeof onTasksStatsChanged === "function" ? onTasksStatsChanged : null;
    this._onNewTaskIdsFromWebview =
      typeof onNewTaskIdsFromWebview === "function"
        ? onNewTaskIdsFromWebview
        : null;
    this._onLanguageChanged =
      typeof onLanguageChanged === "function" ? onLanguageChanged : null;
    this._view = null;
    this._disposables = [];
    this._lastServerStatus = null;
    this._hasEverConnected = false;
    this._webviewReady = false;
    this._webviewReadyTimer = null;
    this._pendingMessages = [];
    this._pendingMessageLimit = 50;
    this._revealPanelUntilMs = 0;
    this._pendingNotifiedTaskId = "";
    this._pendingNotifiedTaskAtMs = 0;
    this._notificationConfig = null;
    this._notificationConfigFetchedAt = 0;
    this._notificationConfigFetchPromise = null;
    this._cachedServerLang = null;
    this._cachedLocales = {};
    this._cachedStaticAssets = null;
    this._cachedInlineAllLocalesJson = null;
    this._cachedInlineAllLocalesKey = null;
    this._prefetchServerLangPromise = null;
    this._prefetchServerLangAbortController = null;
    this._visibilityBenchmarkSeq = 0;
    this._retainContextWhenHidden = retainContextWhenHidden === true;
  }

  private _normalizeWebviewServerUrl(serverUrl: string): string {
    const fallback = "http://localhost:8080";
    const raw =
      typeof serverUrl === "string" && serverUrl.trim()
        ? serverUrl.trim()
        : fallback;
    return raw.replace(/\/+$/, "");
  }

  private async _refreshWebviewServerUrl(): Promise<void> {
    const fallback = this._normalizeWebviewServerUrl(this._serverUrl);
    this._webviewServerUrl = fallback;

    // R453: VS Code webviews execute on the user's local UI side even when
    // the extension host is remote. A literal localhost URL in webview JS can
    // therefore point at the wrong machine in Remote SSH / Dev Containers /
    // Codespaces. Keep extension-host fetches on _serverUrl, but forward the
    // browser-facing webview URL through asExternalUri when VS Code can provide
    // one. If forwarding is unavailable, retain the direct URL so desktop-local
    // sessions and older hosts keep working.
    try {
      const forwarded = await vscode.env.asExternalUri(vscode.Uri.parse(fallback));
      const forwardedText = forwarded.toString();
      if (forwardedText) {
        this._webviewServerUrl = this._normalizeWebviewServerUrl(forwardedText);
      }
    } catch {
      this._webviewServerUrl = fallback;
    }
  }

  private async _preloadResources(): Promise<void> {
    // R24.1/R462: critical disk reads 并行化。
    //
    // why
    // - R24.1 pre-fix 是「en locale → await → zh-CN locale → await → svg →
    //   await → lottie → await」纯串行 disk read（每次 ~50-200 µs，
    //   含 ``vscode.workspace.fs.readFile`` 的 IPC overhead）。在
    //   ``resolveWebviewView`` 的 hot path 上累计 ~50 ms（已在 line 426
    //   的注释里量化），是 webview 首屏渲染前**唯一**的同步阻塞点。
    // - critical read 之间**没有任何数据依赖**：locale en 不依赖 zh-CN，
    //   SVG 不依赖 locale。串行只是 historical
    //   accident（早期单文件版本逐步加进来时没有重构）。
    // - R462 后，445KB ``lottie/sprout.json`` 不再由 host 端读取/JSON.parse：
    //   ``_getHtmlContent`` 已经固定内联 null，并把 ``data-no-content-lottie-json-url``
    //   交给 webview-ui 按需 fetch + force-cache。保留 host 预读只会拖慢
    //   resolveWebviewView 的首屏路径，而且解析结果没有消费者。
    // - ``Promise.all`` 把 wall-clock 缩到 ``max(read_a, read_b, read_c)``，
    //   R462 再移除最大的 JSON read/parse，直接降低 cold-open IO 与 CPU。
    // - 二次以后的 ``resolveWebviewView`` 走 ``_cachedLocales[loc]`` /
    //   ``_cachedStaticAssets`` 的 fast-path（line 235 / 264 的 cache
    //   guard），所以 R24.1 主要改善 cold-open / window reload 这种
    //   首屏 critical path 场景。
    //
    // 容错保留：critical 文件保留原有的 ``safeReadTextFile`` ``vscode.workspace.fs``
    // → ``fs.readFileSync`` fallback chain，所以 ``Promise.all`` 中即便
    // 某一个 read fail，``catch`` 内部的兜底会把它降级到同步 fs，整体
    // ``_preloadResources`` 的成功率与 pre-fix 完全一致。
    const decoder = new TextDecoder("utf-8");

    const loadLocale = async (loc: string): Promise<void> => {
      if (this._cachedLocales[loc]) return;
      try {
        const uri = vscode.Uri.joinPath(
          this._extensionUri,
          "locales",
          loc + ".json",
        );
        const bytes = await vscode.workspace.fs.readFile(uri);
        const text = decoder.decode(bytes);
        if (text)
          this._cachedLocales[loc] = JSON.parse(text) as Record<
            string,
            unknown
          >;
      } catch {
        try {
          const text = safeReadTextFile(
            vscode.Uri.joinPath(this._extensionUri, "locales", loc + ".json"),
          );
          if (text)
            this._cachedLocales[loc] = JSON.parse(text) as Record<
              string,
              unknown
            >;
        } catch {
          /* 忽略 */
        }
      }
    };

    const loadStaticAssets = async (): Promise<void> => {
      if (this._cachedStaticAssets) return;
      let svgText = "";
      try {
        const svgBytes = await vscode.workspace.fs.readFile(
          vscode.Uri.joinPath(this._extensionUri, "activity-icon.svg"),
        );
        svgText = decoder.decode(svgBytes);
      } catch {
        svgText = safeReadTextFile(
          vscode.Uri.joinPath(this._extensionUri, "activity-icon.svg"),
        );
      }
      this._cachedStaticAssets = { activityIconSvg: svgText };
    };

    // cr32 §3.2 fix [medium]：补 zh-TW.json 预加载。否则用户系统
    // 语言是 zh-TW / zh-HK / zh-Hant* 时，``normalizeLang`` 已 fold 到
    // ``zh-TW``（feat-zhtw-locale §3.3），但 ``_cachedLocales['zh-TW']``
    // 不存在 → webview-ui.js 的 ``ensureLocaleRegistered`` 找不到 locale
    // → ``_t()`` 静默 fallback 到 en，台湾用户体感是"插件忽略我的语言设置"。
    // 预加载放在并行 ``Promise.all`` 内，~50 µs 额外 IO；如果文件缺失走
    // 同一 ``try { fs.readFile } catch { fs.readFileSync }`` fallback 链。
    await Promise.all([
      loadLocale("en"),
      loadLocale("zh-CN"),
      loadLocale("zh-TW"),
      loadStaticAssets(),
    ]);
  }

  private _abortPrefetchServerLanguage(): void {
    const controller = this._prefetchServerLangAbortController;
    this._prefetchServerLangAbortController = null;
    this._prefetchServerLangPromise = null;
    if (controller && typeof controller.abort === "function") {
      try {
        controller.abort();
      } catch {
        /* noop */
      }
    }
  }

  private _prefetchServerLanguage(): Promise<void> {
    // 缓存短路：已有结果就不再发请求（updateServerUrl 会清空缓存以便重新预取）
    if (this._cachedServerLang) {
      return Promise.resolve();
    }
    // 单飞锁：并发调用共享同一 Promise，避免对 /api/config 发起重复请求
    if (this._prefetchServerLangPromise) {
      return this._prefetchServerLangPromise;
    }
    const requestServerUrl = this._serverUrl;
    const task = (async (): Promise<void> => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      let controller: AbortController | null = null;
      try {
        controller =
          typeof AbortController !== "undefined" ? new AbortController() : null;
        // 超时从 3500ms 收紧到 1000ms：localhost 本应毫秒级，失败即降级
        // 不再重试：失败后前端 checkServerStatus 会通过 langDetected 回传语言
        if (controller) {
          this._prefetchServerLangAbortController = controller;
          const activeController = controller;
          timer = setTimeout(() => {
            try {
              activeController.abort();
            } catch {
              /* noop */
            }
          }, 1000);
        }
        const resp = await fetch(`${requestServerUrl}/api/config`, {
          signal: controller ? controller.signal : undefined,
          headers: { Accept: "application/json" },
        });
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        if (this._serverUrl !== requestServerUrl) {
          return;
        }
        if (resp.ok) {
          const data = (await resp.json()) as Record<string, unknown>;
          if (this._serverUrl !== requestServerUrl) {
            return;
          }
          if (
            data.language &&
            typeof data.language === "string" &&
            data.language !== "auto"
          ) {
            this._cachedServerLang = data.language;
            this._log(
              vscode.l10n.t(
                "[i18n] Server language prefetch succeeded: {0}",
                String(data.language),
              ),
            );
            if (this._onLanguageChanged) {
              try {
                this._onLanguageChanged(data.language as string);
              } catch {
                /* 忽略 */
              }
            }
            return;
          }
          this._log(
            vscode.l10n.t(
              "[i18n] Server returned language=auto or empty, using vscode.env.language",
            ),
          );
          return;
        }
        this._log(
          vscode.l10n.t(
            "[i18n] Server non-200 response: {0}",
            String(resp.status),
          ),
        );
      } catch {
        if (this._serverUrl === requestServerUrl) {
          this._log(
            vscode.l10n.t(
              "[i18n] Language prefetch failed, waiting for front-end langDetected",
            ),
          );
        }
      } finally {
        if (timer) clearTimeout(timer);
        if (this._prefetchServerLangAbortController === controller) {
          this._prefetchServerLangAbortController = null;
        }
      }
    })();
    this._prefetchServerLangPromise = task;
    // 无论成功失败都清单飞锁，允许 updateServerUrl 后重新预取
    task.finally(() => {
      if (this._prefetchServerLangPromise === task) {
        this._prefetchServerLangPromise = null;
      }
    });
    return task;
  }

  _log(message: string): void {
    try {
      if (this._logger && typeof this._logger.info === "function") {
        this._logger.info(String(message));
      }
    } catch {
      // 忽略：日志系统异常不应影响主流程
    }
  }

  private _sendVisibilityBenchmarkProbe(): void {
    try {
      this._visibilityBenchmarkSeq += 1;
      this._sendMessage({
        type: "visibility-benchmark-probe",
        seq: this._visibilityBenchmarkSeq,
        hostSentAtMs: Date.now(),
        retainContextWhenHidden: this._retainContextWhenHidden,
      });
    } catch {
      // Benchmark telemetry must never affect webview restore.
    }
  }

  private _recordVisibilityBenchmark(message: WebviewMessage): void {
    try {
      const hostReceivedAtMs = Date.now();
      const seq =
        typeof message.seq === "number" && Number.isFinite(message.seq)
          ? Math.max(0, Math.floor(message.seq))
          : 0;
      const hostSentAtMs =
        typeof message.hostSentAtMs === "number" &&
        Number.isFinite(message.hostSentAtMs)
          ? message.hostSentAtMs
          : 0;
      const webviewReceivedAtMs =
        typeof message.webviewReceivedAtMs === "number" &&
        Number.isFinite(message.webviewReceivedAtMs)
          ? message.webviewReceivedAtMs
          : 0;
      const webviewPaintedAtMs =
        typeof message.webviewPaintedAtMs === "number" &&
        Number.isFinite(message.webviewPaintedAtMs)
          ? message.webviewPaintedAtMs
          : 0;
      const paintLatencyMs =
        typeof message.paintLatencyMs === "number" &&
        Number.isFinite(message.paintLatencyMs)
          ? message.paintLatencyMs
          : webviewPaintedAtMs && webviewReceivedAtMs
            ? webviewPaintedAtMs - webviewReceivedAtMs
            : null;
      const roundTripMs = hostSentAtMs ? hostReceivedAtMs - hostSentAtMs : null;
      const usedJSHeapSize =
        typeof message.usedJSHeapSize === "number" &&
        Number.isFinite(message.usedJSHeapSize)
          ? Math.max(0, Math.floor(message.usedJSHeapSize))
          : null;
      const totalJSHeapSize =
        typeof message.totalJSHeapSize === "number" &&
        Number.isFinite(message.totalJSHeapSize)
          ? Math.max(0, Math.floor(message.totalJSHeapSize))
          : null;
      const payload = {
        seq,
        retainContextWhenHidden: this._retainContextWhenHidden,
        hostSentAtMs,
        hostReceivedAtMs,
        webviewReceivedAtMs,
        webviewPaintedAtMs,
        roundTripMs,
        paintLatencyMs,
        usedJSHeapSize,
        totalJSHeapSize,
      };

      if (this._logger && typeof this._logger.event === "function") {
        this._logger.event("webview.visibility_benchmark", payload, {
          level: "debug",
        });
      } else if (this._logger && typeof this._logger.debug === "function") {
        this._logger.debug(
          `webview.visibility_benchmark ${JSON.stringify(payload)}`,
        );
      }

      const outputPath =
        typeof process !== "undefined" &&
        process &&
        process.env &&
        process.env.AIIA_WEBVIEW_BENCH_OUTPUT
          ? String(process.env.AIIA_WEBVIEW_BENCH_OUTPUT)
          : "";
      if (outputPath) {
        fs.appendFileSync(outputPath, JSON.stringify(payload) + "\n", "utf8");
      }
    } catch {
      // Benchmark telemetry must stay best-effort.
    }
  }

  dispose(): void {
    try {
      this._webviewReady = false;
      if (this._webviewReadyTimer) {
        clearTimeout(this._webviewReadyTimer);
        this._webviewReadyTimer = null;
      }
    } catch {
      // 忽略
    }
    try {
      this._pendingMessages = [];
    } catch {
      // 忽略
    }
    try {
      this._abortPrefetchServerLanguage();
    } catch {
      // 忽略
    }

    try {
      for (const d of this._disposables) {
        try {
          d.dispose();
        } catch {
          // 忽略
        }
      }
    } finally {
      this._disposables = [];
    }

    try {
      if (this._onVisibilityChanged) {
        this._onVisibilityChanged(false);
      }
    } catch {
      // 忽略
    }

    this._view = null;
    this._lastServerStatus = null;
  }

  async resolveWebviewView(webviewView: vscode.WebviewView): Promise<void> {
    // 只阻塞本地 critical 资源预加载（locales/svg，首次 ~50ms，二次 ~0ms）
    // 服务器语言预取改为 fire-and-forget，避免服务器不可达时首屏最坏 7.5s 空白
    // 语言纠偏有两条备份链路：
    //   1) _getHtmlContent 先用 vscode.env.language 兜底
    //   2) 前端 checkServerStatus 拿到 language 后通过 langDetected 回传
    await Promise.all([this._preloadResources(), this._refreshWebviewServerUrl()]);
    this._prefetchServerLanguage().catch(() => {
      /* 忽略：失败不影响首屏 */
    });
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };

    webviewView.onDidChangeVisibility(() => {
      try {
        if (this._logger && typeof this._logger.event === "function") {
          this._logger.event(
            "webview.visibility",
            { visible: !!webviewView.visible },
            { level: "debug" },
          );
        } else {
          this._log(
            vscode.l10n.t(
              "[event] Webview visibility changed: visible={0}",
              String(!!webviewView.visible),
            ),
          );
        }
      } catch {
        this._log(
          vscode.l10n.t(
            "[event] Webview visibility changed: visible={0}",
            String(!!webviewView.visible),
          ),
        );
      }
      if (this._onVisibilityChanged) {
        this._onVisibilityChanged(!!webviewView.visible);
      }
      if (webviewView.visible) {
        this._sendMessage({ type: "refresh" });
        // BM-5：规避 VSCode issue #113188 的 ghost-rendering 残影。
        // retainContextWhenHidden:true 时，隐藏→显示可能保留过期合成层；
        // 发送 force-repaint 让前端用 rAF 触发 layer 重建清除残影。
        this._sendMessage({ type: "force-repaint" });
        this._sendVisibilityBenchmarkProbe();
        // R692 (TODO#6-2)：隐藏期间有新任务通知 → 回到面板时直达该任务。
        // 时间窗 120s：超过说明用户并非"看到通知立刻回来"，不再抢切换。
        const PENDING_NOTIFY_DEEPLINK_FRESH_MS = 120 * 1000;
        if (
          this._pendingNotifiedTaskId &&
          Date.now() - this._pendingNotifiedTaskAtMs <=
            PENDING_NOTIFY_DEEPLINK_FRESH_MS
        ) {
          this._sendMessage({
            type: "switchToTask",
            taskId: this._pendingNotifiedTaskId,
          });
        }
        this._pendingNotifiedTaskId = "";
        this._pendingNotifiedTaskAtMs = 0;
      }
    });

    webviewView.onDidDispose(() => {
      try {
        if (this._logger && typeof this._logger.event === "function") {
          this._logger.event("webview.disposed", {}, { level: "info" });
        } else {
          this._log(vscode.l10n.t("[event] Webview disposed"));
        }
      } catch {
        this._log(vscode.l10n.t("[event] Webview disposed"));
      }
      if (this._onVisibilityChanged) {
        this._onVisibilityChanged(false);
      }

      try {
        this._webviewReady = false;
        if (this._webviewReadyTimer) {
          clearTimeout(this._webviewReadyTimer);
          this._webviewReadyTimer = null;
        }
        this._abortPrefetchServerLanguage();
      } catch {
        // 忽略
      }

      try {
        for (const d of this._disposables) {
          try {
            d.dispose();
          } catch {
            // 忽略：单个 disposable 失败不应影响其它清理
          }
        }
      } finally {
        this._disposables = [];
      }

      this._view = null;
      this._lastServerStatus = null;
    });

    if (this._onVisibilityChanged) {
      this._onVisibilityChanged(!!webviewView.visible);
    }

    const html = this._getHtmlContent(webviewView.webview);

    webviewView.webview.html = html;

    try {
      const scriptCount = (html.match(/<script\b/gi) || []).length;
      if (this._logger && typeof this._logger.debug === "function") {
        this._logger.debug(
          vscode.l10n.t(
            "Webview HTML script tag count: {0}",
            String(scriptCount),
          ),
        );
      }
      const tickCount = (html.match(/`/g) || []).length;
      if (
        tickCount > 0 &&
        this._logger &&
        typeof this._logger.warn === "function"
      ) {
        this._logger.warn(
          vscode.l10n.t(
            "Webview HTML contains {0} backtick character(s); may cause injection failure (recommend externalizing / runtime generation)",
            String(tickCount),
          ),
        );
      }
    } catch {
      // 忽略：诊断日志失败不应影响 Webview 初始化
    }

    this._webviewReady = false;
    if (this._webviewReadyTimer) {
      clearTimeout(this._webviewReadyTimer);
      this._webviewReadyTimer = null;
    }
    this._webviewReadyTimer = setTimeout(() => {
      if (
        !this._webviewReady &&
        this._logger &&
        typeof this._logger.warn === "function"
      ) {
        try {
          if (typeof this._logger.event === "function") {
            this._logger.event(
              "webview.ready_timeout",
              { timeoutMs: 2500, webviewReady: false },
              {
                level: "warn",
                message: vscode.l10n.t(
                  "Webview not ready: script may not have executed (CSP / injection / HTML structure broken)",
                ),
              },
            );
          } else {
            this._logger.warn(
              vscode.l10n.t(
                "Webview not ready: script may not have executed (CSP / injection / HTML structure broken)",
              ),
            );
          }
        } catch {
          this._logger.warn(
            vscode.l10n.t(
              "Webview not ready: script may not have executed (CSP / injection / HTML structure broken)",
            ),
          );
        }
      }
    }, 2500);

    webviewView.webview.onDidReceiveMessage(
      (message: WebviewMessage) => {
        this._handleMessage(message);
      },
      null,
      this._disposables,
    );

    try {
      if (this._logger && typeof this._logger.debug === "function") {
        this._logger.debug(vscode.l10n.t("Webview ready"));
      }
    } catch {
      // 忽略：日志系统异常不应影响主流程
    }
  }

  updateServerUrl(serverUrl: string): void {
    this._serverUrl = serverUrl;
    this._webviewServerUrl = this._normalizeWebviewServerUrl(serverUrl);
    this._notificationConfig = null;
    this._notificationConfigFetchedAt = 0;
    this._notificationConfigFetchPromise = null;
    this._cachedServerLang = null;
    this._abortPrefetchServerLanguage();
    if (this._view && this._view.webview) {
      try {
        this._webviewReady = false;
        if (this._webviewReadyTimer) {
          clearTimeout(this._webviewReadyTimer);
          this._webviewReadyTimer = null;
        }
        this._pendingMessages = [];
      } catch {
        // 忽略
      }

      const view = this._view;
      // 同 resolveWebviewView：不 await 语言预取，避免切换 serverUrl 时首屏阻塞
      this._prefetchServerLanguage().catch(() => {
        /* 忽略：失败不影响 UI */
      });
      Promise.all([this._preloadResources(), this._refreshWebviewServerUrl()])
        .catch(() => {})
        .finally(() => {
          // R18.2 dispose-race guard：``_preloadResources`` 是 async（通常含
          // 一次 HTTP probe），在它 pending 期间 webview 可能已被 dispose
          // （extension deactivate / 用户折叠侧栏 → onDidDispose 触发）。
          // 若不 short-circuit，stale finally 仍会：
          //   1) 给 disposed view 赋 ``view.webview.html``（VSCode 多半 noop
          //      但偶发抛 'Webview is disposed'，把 finally 转成 unhandled
          //      rejection，污染 Output channel）；
          //   2) 创建一个新的 ``_webviewReadyTimer``，2.5s 后写一条
          //      ``webview.ready_timeout`` warning 日志 —— 但 webview 早已
          //      不存在，这是 false-positive observability 噪声，会让运维
          //      在排查"真" CSP / script 注入失败时被误导。
          // 防御：对比 capture 时的 ``view`` 与当前 ``this._view``：不一致或
          // 已为 null，则 stale finally 不再操作（既不重写 HTML 也不开新
          // timer）。``dispose()`` 已经 ``clearTimeout`` 了之前的 timer，新
          // timer 不再创建即可彻底闭环。
          if (this._view !== view) return;
          if (view.webview)
            view.webview.html = this._getHtmlContent(view.webview);
          this._webviewReadyTimer = setTimeout(() => {
            if (
              !this._webviewReady &&
              this._logger &&
              typeof this._logger.warn === "function"
            ) {
              try {
                if (typeof this._logger.event === "function") {
                  this._logger.event(
                    "webview.ready_timeout",
                    {
                      timeoutMs: 2500,
                      webviewReady: false,
                      reason: "serverUrl_changed",
                    },
                    {
                      level: "warn",
                      message: vscode.l10n.t(
                        "Webview not ready: script may not have executed (CSP / injection / HTML structure broken)",
                      ),
                    },
                  );
                } else {
                  this._logger.warn(
                    vscode.l10n.t(
                      "Webview not ready: script may not have executed (CSP / injection / HTML structure broken)",
                    ),
                  );
                }
              } catch {
                this._logger.warn(
                  vscode.l10n.t(
                    "Webview not ready: script may not have executed (CSP / injection / HTML structure broken)",
                  ),
                );
              }
            }
          }, 2500);
        });
    }
  }

  _handleMessage(message: WebviewMessage): void {
    switch (message.type) {
      case "log":
        try {
          const levelRaw =
            message && message.level ? String(message.level) : "debug";
          const level = levelRaw.toLowerCase();
          const text =
            message && message.message ? String(message.message) : "";
          if (!text) break;

          if (
            level === "error" &&
            this._logger &&
            typeof this._logger.error === "function"
          ) {
            this._logger.error(text);
          } else if (
            (level === "warn" || level === "warning") &&
            this._logger &&
            typeof this._logger.warn === "function"
          ) {
            this._logger.warn(text);
          } else if (
            level === "info" &&
            this._logger &&
            typeof this._logger.info === "function"
          ) {
            this._logger.info(text);
          } else if (this._logger && typeof this._logger.debug === "function") {
            this._logger.debug(text);
          }
        } catch {
          // 忽略：日志系统异常不应影响主流程
        }
        break;
      case "error":
        try {
          if (this._logger && typeof this._logger.error === "function") {
            this._logger.error(String(message.message));
          } else {
            this._log(vscode.l10n.t("[error] {0}", String(message.message)));
          }
        } catch {
          // 忽略：日志系统异常不应影响主流程
        }
        break;
      case "ready":
        this._webviewReady = true;
        if (this._webviewReadyTimer) {
          clearTimeout(this._webviewReadyTimer);
          this._webviewReadyTimer = null;
        }
        try {
          this._flushPendingMessages();
        } catch {
          // 忽略
        }
        try {
          if (this._logger && typeof this._logger.event === "function") {
            this._logger.event(
              "webview.ready",
              { ready: true },
              { level: "info" },
            );
          } else {
            this._log(vscode.l10n.t("Webview script ready"));
          }
        } catch {
          this._log(vscode.l10n.t("Webview script ready"));
        }
        break;
      case "tasksStats":
        try {
          const connected = !!(message && message.connected);
          const active =
            message &&
            typeof message.active === "number" &&
            Number.isFinite(message.active)
              ? Math.max(0, Math.floor(message.active))
              : 0;
          const pending =
            message &&
            typeof message.pending === "number" &&
            Number.isFinite(message.pending)
              ? Math.max(0, Math.floor(message.pending))
              : 0;
          const total =
            message &&
            typeof message.total === "number" &&
            Number.isFinite(message.total)
              ? Math.max(0, Math.floor(message.total))
              : active + pending;

          if (this._onTasksStatsChanged) {
            this._onTasksStatsChanged({ connected, active, pending, total });
          }
        } catch {
          // 忽略：消息处理失败不应影响主流程
        }
        break;
      case "serverStatus":
        try {
          const connected = !!(message && message.connected);
          if (connected !== this._lastServerStatus) {
            const prev = this._lastServerStatus;
            this._lastServerStatus = connected;
            if (connected) {
              this._hasEverConnected = true;
              if (this._logger && typeof this._logger.event === "function") {
                this._logger.event(
                  "webview.server_status",
                  { connected: true, prev: prev === null ? "null" : prev },
                  { level: prev === false ? "info" : "debug" },
                );
              } else {
                this._log(
                  vscode.l10n.t("[event] Webview server status: connected"),
                );
              }
            } else if (this._hasEverConnected) {
              if (this._logger && typeof this._logger.event === "function") {
                this._logger.event(
                  "webview.server_status",
                  { connected: false, prev: prev === null ? "null" : prev },
                  { level: "warn" },
                );
              } else if (
                this._logger &&
                typeof this._logger.warn === "function"
              ) {
                this._logger.warn(
                  vscode.l10n.t("[event] Webview server status: disconnected"),
                );
              } else {
                this._log(
                  vscode.l10n.t("[event] Webview server status: disconnected"),
                );
              }
            } else if (
              this._logger &&
              typeof this._logger.debug === "function"
            ) {
              if (typeof this._logger.event === "function") {
                this._logger.event(
                  "webview.server_status",
                  { connected: false, prev: prev === null ? "null" : prev },
                  { level: "debug" },
                );
              } else {
                this._logger.debug(
                  vscode.l10n.t("[event] Webview server status: disconnected"),
                );
              }
            }
          }
        } catch {
          // 忽略：状态日志失败不应影响主流程
        }
        break;
      case "notify":
        this._handleNotify(message);
        break;
      case "showInfo":
        this._dispatchNotificationEvent({
          title: "AI Intervention Agent",
          message: message && message.message ? String(message.message) : "",
          trigger: "immediate",
          types: [NotificationType.VSCODE],
          metadata: {
            presentation: "statusBar",
            severity: "info",
            timeoutMs: 3000,
          },
          source: "webview",
          dedupeKey:
            message && message.message
              ? `status:${String(message.message).slice(0, 200)}`
              : "",
        });
        break;
      case "requestClipboardText":
        this._handleRequestClipboardText(message);
        break;
      case "openExternal":
        this._handleOpenExternal(message);
        break;
      case "langDetected":
        try {
          const lang =
            message &&
            typeof (message as Record<string, unknown>).language === "string"
              ? String((message as Record<string, unknown>).language)
              : "";
          if (lang && lang !== "auto" && lang !== this._cachedServerLang) {
            this._cachedServerLang = lang;
            this._log(
              vscode.l10n.t(
                "[i18n] Client detected language: {0}",
                String(lang),
              ),
            );
            if (this._onLanguageChanged) {
              try {
                this._onLanguageChanged(lang);
              } catch {
                /* 忽略 */
              }
            }
            // 前端 applyServerLanguage 已通过 i18n.setLang + retranslateAllI18nElements
            // 就地重翻译（覆盖 data-i18n / data-i18n-title / data-i18n-placeholder /
            // data-i18n-version），host 侧不再重设 webview.html，避免一次 HTML 重建闪烁。
          }
        } catch {
          /* 忽略 */
        }
        break;
      case "visibilityBenchmarkResult":
        this._recordVisibilityBenchmark(message);
        break;
      default:
        break;
    }
  }

  _dispatchNotificationEvent(event: Record<string, unknown>): void {
    try {
      if (
        !this._notificationCenter ||
        typeof this._notificationCenter.dispatch !== "function"
      )
        return;
      try {
        this._armRevealPanelOnNextFocus(event);
      } catch {
        // 忽略
      }
      Promise.resolve()
        .then(() => this._notificationCenter.dispatch(event))
        .then((result) => {
          try {
            if (
              !this._notificationLogger ||
              typeof this._notificationLogger.event !== "function"
            )
              return;
            const evt =
              result && result.event
                ? (result.event as unknown as Record<string, unknown>)
                : event;
            const types =
              evt && Array.isArray(evt.types)
                ? (evt.types as unknown[]).map((t) => String(t))
                : [];
            const delivered =
              result && result.delivered ? result.delivered : {};
            const skipped = !!(result && result.skipped);
            const reason = result && result.reason ? String(result.reason) : "";
            const eventId = evt && evt.id ? String(evt.id) : "";
            this._notificationLogger.event(
              "notify.dispatch",
              {
                eventId,
                types,
                skipped,
                reason,
                delivered,
              },
              { level: "debug" },
            );
          } catch {
            // 忽略：日志系统异常不应影响通知流程
          }
        })
        .catch((e: unknown) => {
          try {
            if (
              !this._notificationLogger ||
              typeof this._notificationLogger.event !== "function"
            )
              return;
            const msg = e instanceof Error ? e.message : String(e);
            this._notificationLogger.event(
              "notify.dispatch_failed",
              { error: msg },
              { level: "warn" },
            );
          } catch {
            // 忽略
          }
        });
    } catch {
      // 忽略：通知分发失败不应影响主流程
    }
  }

  _armRevealPanelOnNextFocus(event: Record<string, unknown>): void {
    try {
      const evt =
        event && typeof event === "object"
          ? event
          : ({} as Record<string, unknown>);
      const types =
        evt && Array.isArray(evt.types)
          ? (evt.types as unknown[]).map((t) => String(t))
          : [];
      if (!types.includes(NotificationType.MACOS_NATIVE)) return;

      const md =
        evt && evt.metadata && typeof evt.metadata === "object"
          ? (evt.metadata as Record<string, unknown>)
          : {};
      const isTest = !!(md && md.isTest);
      const kind = md && md.kind ? String(md.kind) : "";
      if (isTest) return;
      if (kind !== "new_tasks") return;

      const focused = !!(
        vscode &&
        vscode.window &&
        vscode.window.state &&
        vscode.window.state.focused
      );
      if (focused) return;

      this._revealPanelUntilMs = Date.now() + 30000;
    } catch {
      // 忽略
    }
  }

  async onWindowFocusChanged(focused: boolean): Promise<void> {
    try {
      if (!focused) return;
      const until =
        typeof this._revealPanelUntilMs === "number"
          ? this._revealPanelUntilMs
          : 0;
      if (!until || Date.now() > until) return;
      this._revealPanelUntilMs = 0;
      await vscode.commands.executeCommand("ai-intervention-agent.openPanel");
    } catch {
      // 忽略
    }
  }

  _handleNotify(message: WebviewMessage): void {
    const event =
      message && message.event
        ? (message.event as Record<string, unknown>)
        : null;
    if (!event) return;
    try {
      if (this._logger && typeof this._logger.debug === "function") {
        const dk = event.dedupeKey ? String(event.dedupeKey) : "";
        const src = event.source ? String(event.source) : "webview";
        this._logger.debug(`_handleNotify: source=${src} dedupeKey=${dk}`);
      }
    } catch {
      /* noop */
    }
    this._dispatchNotificationEvent(event);
    try {
      const md =
        event && event.metadata && typeof event.metadata === "object"
          ? (event.metadata as Record<string, unknown>)
          : {};
      if (
        md.kind === "new_tasks" &&
        Array.isArray(md.taskIds) &&
        this._onNewTaskIdsFromWebview
      ) {
        this._onNewTaskIdsFromWebview(md.taskIds as string[]);
      }
    } catch {
      // 同步失败不应影响通知流程
    }
  }

  _handleRequestClipboardText(message: WebviewMessage): void {
    const requestId =
      message && message.requestId ? String(message.requestId) : "";
    Promise.resolve()
      .then(() => vscode.env.clipboard.readText())
      .then((text) => {
        const clip = text ? String(text) : "";
        if (!clip.trim()) {
          this._sendMessage({
            type: "clipboardText",
            success: false,
            requestId,
            error: vscode.l10n.t("Clipboard is empty; please copy code first."),
          });
          return;
        }

        this._sendMessage({
          type: "clipboardText",
          success: true,
          requestId,
          text: clip,
        });
      })
      .catch((e: unknown) => {
        this._sendMessage({
          type: "clipboardText",
          success: false,
          requestId,
          error: e instanceof Error ? e.message : String(e),
        });
      });
  }

  /**
   * 处理 webview 发来的 openExternal 消息。
   *
   * VS Code webview 出于安全模型禁止 <a target="_blank" href="https://...">
   * 直接 navigate（点击后看似无反应），需要由 host 调
   * `vscode.env.openExternal` 显式打开默认浏览器。
   *
   * 安全约束：
   * - 协议白名单仅放行 http(s) 与 mailto，避免 webview 借此 channel 调起
   *   file:// / vscode:// / command: 等敏感 URI（潜在的本地命令执行/任意
   *   文件读取风险）。
   * - 任何解析失败 / 非法协议 / 缺失字段都静默返回，绝不抛出，避免单条坏
   *   消息影响主消息循环。
   * - 仅记录到 logger（不弹 UI），点击是低频用户行为，不需要打扰用户。
   */
  _handleOpenExternal(message: WebviewMessage): void {
    try {
      const rawUrl = message && (message as Record<string, unknown>).url;
      const url = typeof rawUrl === "string" ? rawUrl.trim() : "";
      if (!url) return;

      if (!/^(?:https?|mailto):/i.test(url)) {
        try {
          if (this._logger && typeof this._logger.warn === "function") {
            this._logger.warn(
              `Refused openExternal for non-http(s)/mailto URL: ${url.slice(0, 120)}`,
            );
          }
        } catch {
          // 忽略：日志失败不影响安全决策
        }
        return;
      }

      let parsed: vscode.Uri;
      try {
        parsed = vscode.Uri.parse(url, true);
      } catch {
        try {
          if (this._logger && typeof this._logger.warn === "function") {
            this._logger.warn(
              `Refused openExternal for unparseable URL: ${url.slice(0, 120)}`,
            );
          }
        } catch {
          // 忽略
        }
        return;
      }

      void Promise.resolve(vscode.env.openExternal(parsed)).catch((e) => {
        try {
          if (this._logger && typeof this._logger.warn === "function") {
            this._logger.warn(
              `vscode.env.openExternal failed: ${e instanceof Error ? e.message : String(e)}`,
            );
          }
        } catch {
          // 忽略
        }
      });
    } catch {
      // 忽略：openExternal 异常不应影响主流程
    }
  }

  _sendMessage(message: WebviewMessage): void {
    if (!this._view || !this._view.webview) return;

    if (!this._webviewReady) {
      try {
        this._pendingMessages.push(message);
        if (this._pendingMessages.length > this._pendingMessageLimit) {
          this._pendingMessages.splice(
            0,
            this._pendingMessages.length - this._pendingMessageLimit,
          );
        }
      } catch {
        // 忽略：缓冲失败不应影响主流程
      }
      return;
    }

    this._postMessage(message);
  }

  _postMessage(message: WebviewMessage): void {
    try {
      if (
        this._view &&
        this._view.webview &&
        typeof this._view.webview.postMessage === "function"
      ) {
        this._view.webview.postMessage(message);
      }
    } catch {
      // 忽略：Webview 通信失败不应影响主流程
    }
  }

  _flushPendingMessages(): void {
    if (!this._webviewReady) return;
    if (!this._pendingMessages || this._pendingMessages.length === 0) return;
    const batch = this._pendingMessages.slice(0);
    this._pendingMessages = [];
    for (const msg of batch) {
      this._postMessage(msg);
    }
  }

  async _fetchNotificationConfig(
    force?: boolean,
  ): Promise<NotificationConfig | null> {
    const now = Date.now();
    if (
      !force &&
      this._notificationConfig &&
      now - this._notificationConfigFetchedAt < 30000
    ) {
      return this._notificationConfig;
    }
    if (this._notificationConfigFetchPromise)
      return this._notificationConfigFetchPromise;

    const requestServerUrl = this._serverUrl;
    let fetchPromise: Promise<NotificationConfig | null> | null = null;
    fetchPromise = (async (): Promise<NotificationConfig | null> => {
      let timeoutId: ReturnType<typeof setTimeout> | null = null;
      try {
        const controller =
          typeof AbortController !== "undefined" ? new AbortController() : null;
        timeoutId = controller
          ? setTimeout(() => {
              try {
                controller.abort();
              } catch {
                /* noop */
              }
            }, 2500)
          : null;
        const resp = await fetch(
          `${requestServerUrl}/api/get-notification-config`,
          {
            signal: controller ? controller.signal : undefined,
            headers: {
              Accept: "application/json",
              "Cache-Control": "no-cache",
            },
          } as RequestInit,
        );
        if (timeoutId) {
          clearTimeout(timeoutId);
          timeoutId = null;
        }
        if (!resp.ok) return this._notificationConfig;
        const data = (await resp.json()) as Record<string, unknown>;
        const config = data.config as Record<string, unknown> | undefined;
        if (this._serverUrl !== requestServerUrl) {
          return this._notificationConfig;
        }
        if (data && data.status === "success" && config) {
          this._notificationConfig = {
            enabled: config.enabled !== false,
            macosNativeEnabled: config.macos_native_enabled !== false,
          };
          this._notificationConfigFetchedAt = Date.now();
        }
        return this._notificationConfig;
      } catch {
        return this._notificationConfig;
      } finally {
        if (timeoutId) {
          clearTimeout(timeoutId);
        }
        if (this._notificationConfigFetchPromise === fetchPromise) {
          this._notificationConfigFetchPromise = null;
        }
      }
    })();
    this._notificationConfigFetchPromise = fetchPromise;
    return fetchPromise;
  }

  async dispatchNewTaskNotification(taskData: TaskData[]): Promise<void> {
    try {
      const items: TaskData[] = [];
      const ids: string[] = [];
      if (Array.isArray(taskData)) {
        for (const item of taskData) {
          if (!item) continue;
          items.push(item);
          const taskId = item.id || "";
          if (taskId) {
            ids.push(taskId);
          }
        }
      }
      if (items.length === 0) return;
      if (ids.length === 0) return;

      try {
        if (this._logger && typeof this._logger.event === "function") {
          this._logger.event(
            "ext.dispatch_entry",
            {
              ids,
              hasCenter: !!this._notificationCenter,
              serverUrl: this._serverUrl ? "set" : "empty",
            },
            { level: "info" },
          );
        }
      } catch {
        /* noop */
      }

      const config = await this._fetchNotificationConfig();
      const settings = config || { enabled: true, macosNativeEnabled: true };

      try {
        if (this._logger && typeof this._logger.event === "function") {
          this._logger.event(
            "ext.dispatch_config",
            {
              enabled: settings.enabled,
              macosNative: settings.macosNativeEnabled,
              configCached: !!config,
            },
            { level: "info" },
          );
        }
      } catch {
        /* noop */
      }

      if (settings.enabled === false) {
        try {
          if (this._logger && typeof this._logger.debug === "function") {
            this._logger.debug("ext.new_task_notify: skipped (enabled=false)");
          }
        } catch {
          /* noop */
        }
        return;
      }

      const SUMMARY_MAX_LEN = 120;
      const firstPrompt = (items[0] && items[0].prompt) || "";
      const cleaned = firstPrompt
        ? firstPrompt
            .replace(/[\r\n]+/g, " ")
            .replace(/\s+/g, " ")
            .trim()
        : "";
      const truncated = cleaned.length > SUMMARY_MAX_LEN;
      const summary = truncated
        ? cleaned.slice(0, SUMMARY_MAX_LEN) + "\u2026"
        : cleaned;
      let msg: string;
      if (summary) {
        msg =
          ids.length === 1
            ? summary
            : summary +
              "\uff08\u5171 " +
              ids.length +
              " \u4e2a\u4efb\u52a1\uff09";
      } else {
        msg =
          ids.length === 1
            ? "\u65b0\u4efb\u52a1\u5df2\u6dfb\u52a0: " + ids[0]
            : "\u6536\u5230 " + ids.length + " \u4e2a\u65b0\u4efb\u52a1";
      }

      const types: string[] = [NotificationType.VSCODE];
      if (settings.macosNativeEnabled) {
        types.push(NotificationType.MACOS_NATIVE);
      }

      try {
        if (this._logger && typeof this._logger.event === "function") {
          this._logger.event(
            "ext.new_task_notify",
            {
              count: ids.length,
              types: types.join(","),
              macosNative: !!settings.macosNativeEnabled,
            },
            { level: "info" },
          );
        }
      } catch {
        /* noop */
      }

      // R692 (TODO#6-2)：记录本轮通知的首个任务，等用户回到面板时直达。
      // 本方法只在 webview 不可见时被 extension 调用（可见时上游跳过派发），
      // 因此这里登记的 pending 深链不会干扰正在面板中操作的用户。
      this._pendingNotifiedTaskId = ids[0] || "";
      this._pendingNotifiedTaskAtMs = Date.now();

      this._dispatchNotificationEvent({
        title: "AI \u4ea4\u4e92\u53cd\u9988",
        message: msg,
        trigger: "immediate",
        types: types,
        metadata: {
          presentation: "statusBar",
          severity: "info",
          timeoutMs: 3000,
          isTest: false,
          kind: "new_tasks",
          taskIds: ids,
          source: "extension",
        },
        source: "extension",
        dedupeKey: "new_tasks:" + ids.join("|"),
      });
    } catch (e: unknown) {
      try {
        if (this._logger && typeof this._logger.warn === "function") {
          this._logger.warn(
            "ext.new_task_notify failed: " +
              (e instanceof Error ? e.message : String(e)),
          );
        }
      } catch {
        /* noop */
      }
    }
  }

  _getHtmlContent(webview: vscode.Webview): string {
    const serverUrl =
      this._webviewServerUrl ||
      this._normalizeWebviewServerUrl(this._serverUrl) ||
      "http://localhost:8080";
    const cspSource = webview.cspSource;
    const markedJsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "marked.min.js"),
    );
    const prismBootstrapUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "prism-bootstrap.js"),
    );
    const prismJsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "prism.min.js"),
    );
    const prismCssUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "prism.min.css"),
    );
    const webviewCssUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "webview.css"),
    );
    const mathjaxScriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "mathjax", "tex-mml-svg.js"),
    );
    const webviewStateUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "webview-state.js"),
    );
    const webviewHelpersUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "webview-helpers.js"),
    );
    const webviewUiUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "webview-ui.js"),
    );
    const activityIconUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "activity-icon.svg"),
    );
    const webviewNotifyCoreUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "webview-notify-core.js"),
    );
    const webviewSettingsUiUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "webview-settings-ui.js"),
    );
    const i18nJsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "i18n.js"),
    );
    // T1 · C10c: @aiia/tri-state-panel 双端共享组件。tri-state-panel.js / -loader.js /
    // -bootstrap.js / .css 是 static/ 源的字节级拷贝，由
    // tests/test_tri_state_panel_parity.py::sha256 守护，禁止手工编辑
    // packages/vscode/ 下这 4 个文件，请改 static/ 并同步拷贝。
    const triStatePanelJsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "tri-state-panel.js"),
    );
    const triStatePanelLoaderUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "tri-state-panel-loader.js"),
    );
    const triStatePanelBootstrapUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "tri-state-panel-bootstrap.js"),
    );
    // R20.13-B/F：从构造器一次性传入的 ``_extensionVersion`` 取值；不再
    // 在 ``_getHtmlContent`` 热路径上做 ``vscode.extensions.getExtension``
    // 注册表查表。``WebviewProvider`` 实例总是由 ``extension.ts::activate``
    // 创建，``EXT_VERSION`` 在 activation 期间已经填好（``context.extension
    // .packageJSON.version``）。
    const extensionVersion = this._extensionVersion;
    const githubUrl = EXT_GITHUB_URL || "";
    const githubUrlDisplay = githubUrl
      ? githubUrl.replace(/^https?:\/\//i, "")
      : "";
    const lottieJsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "lottie.min.js"),
    );
    const noContentLottieJsonUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, "lottie", "sprout.json"),
    );
    const nonce = getNonce();

    const activityIconSvgText =
      this._cachedStaticAssets?.activityIconSvg ||
      safeReadTextFile(
        vscode.Uri.joinPath(this._extensionUri, "activity-icon.svg"),
      );
    const inlineNoContentFallbackSvgLiteral =
      safeStringForInlineScript(activityIconSvgText);
    // Lottie JSON (445KB) 不再内联进 HTML，改由前端通过 data-no-content-lottie-json-url
    // 懒加载（webview-ui.js 里的 loadNoContentLottieData 走 fetch + force-cache 兜底）。
    // 收益：HTML 体积 ~500KB → ~50KB，resolveWebviewView 与 langDetected re-render 更快。
    const inlineNoContentLottieDataLiteral = "null";

    let i18nLang = "en";
    // P9·L5·G1: Pseudo-locale developer switch. When
    // ``ai-intervention-agent.i18n.pseudoLocale`` is true we force
    // ``i18nLang`` to ``pseudo`` and load ``locales/_pseudo/pseudo.json``.
    // Guard with try/catch so a broken workspace settings file never
    // bricks the webview.
    let pseudoLocaleEnabled = false;
    try {
      pseudoLocaleEnabled = Boolean(
        vscode.workspace
          .getConfiguration("ai-intervention-agent")
          .get<boolean>("i18n.pseudoLocale", false),
      );
    } catch {
      pseudoLocaleEnabled = false;
    }

    if (pseudoLocaleEnabled) {
      i18nLang = "pseudo";
    } else if (this._cachedServerLang) {
      i18nLang =
        this._cachedServerLang.toLowerCase().indexOf("zh") === 0
          ? "zh-CN"
          : "en";
    } else {
      try {
        const vsLang = vscode.env.language || "";
        i18nLang = vsLang.toLowerCase().indexOf("zh") === 0 ? "zh-CN" : "en";
      } catch {
        i18nLang = "en";
      }
    }
    let i18nLocaleData: Record<string, unknown> | null =
      this._cachedLocales[i18nLang] || null;
    if (!i18nLocaleData) {
      try {
        const relPath =
          i18nLang === "pseudo"
            ? ["locales", "_pseudo", "pseudo.json"]
            : ["locales", i18nLang + ".json"];
        const localeText = safeReadTextFile(
          vscode.Uri.joinPath(this._extensionUri, ...relPath),
        );
        i18nLocaleData = localeText
          ? (JSON.parse(localeText) as Record<string, unknown>)
          : null;
      } catch {
        /* 忽略 */
      }
    }
    if (!i18nLocaleData) {
      i18nLocaleData = this._cachedLocales["en"] || null;
      if (!i18nLocaleData) {
        try {
          const fallbackText = safeReadTextFile(
            vscode.Uri.joinPath(this._extensionUri, "locales", "en.json"),
          );
          i18nLocaleData = fallbackText
            ? (JSON.parse(fallbackText) as Record<string, unknown>)
            : null;
        } catch {
          /* 忽略 */
        }
      }
      if (i18nLocaleData) i18nLang = "en";
    }
    const allLocales: Record<string, Record<string, unknown>> = {
      ...this._cachedLocales,
    };
    // cr32 §3.2 fix [medium]：把 zh-TW 也加入 fallback 列表。预加载链路
    // (``_preloadResources``) 通常已经把它填入 ``_cachedLocales``，但若
    // ``vscode.workspace.fs`` async + 同步 fs fallback 都失败（典型场景：
    // 文件刚被安装但 readFile 路径还没 settled），这里二次同步兜底，保证
    // ``allLocales['zh-TW']`` 一定可用。否则 zh-TW 用户走 webview-ui 时
    // ``registerLocale`` 拿不到数据 → ``_t()`` 静默 fallback 到 'en'，
    // 体感与 web UI 不一致。
    if (
      !allLocales["en"] ||
      !allLocales["zh-CN"] ||
      !allLocales["zh-TW"]
    ) {
      for (const loc of ["en", "zh-CN", "zh-TW"]) {
        if (allLocales[loc]) continue;
        try {
          const text = safeReadTextFile(
            vscode.Uri.joinPath(this._extensionUri, "locales", loc + ".json"),
          );
          if (text)
            allLocales[loc] = JSON.parse(text) as Record<string, unknown>;
        } catch {
          /* 忽略 */
        }
      }
    }
    // Pseudo locale is only bundled into allLocales when explicitly
    // requested — we never want production sessions to accidentally
    // swap in `[!ẗęśṭ!]` strings just because some cache key collides.
    if (pseudoLocaleEnabled && !allLocales["pseudo"]) {
      try {
        const text = safeReadTextFile(
          vscode.Uri.joinPath(
            this._extensionUri,
            "locales",
            "_pseudo",
            "pseudo.json",
          ),
        );
        if (text)
          allLocales["pseudo"] = JSON.parse(text) as Record<string, unknown>;
      } catch {
        /* 忽略 */
      }
    }
    // R20.13-E：``safeJsonForInlineScript(allLocales)`` 序列化 ~10 KB JSON +
    // ``replace(/</g, '\\u003c')`` 的代价，按 ``_cachedLocales`` 内容签名缓存
    // 结果。键由「locale 名集合（排序、|分隔）+ 各 entry 字典 key 数」组成，
    // 既反映新增 locale（如开了 pseudoLocale 之后），也反映 entry 大小级别的
    // 变化；不靠完整 deep equal，因为 ``_cachedLocales`` 写入路径是 readFile +
    // JSON.parse，正常生命周期内不会原地 mutate。
    const localeNames = Object.keys(allLocales).sort();
    let localeSignature = "";
    for (let i = 0; i < localeNames.length; i += 1) {
      const name = localeNames[i];
      if (i > 0) localeSignature += "|";
      localeSignature += `${name}:${Object.keys(allLocales[name] || {}).length}`;
    }
    let inlineAllLocalesLiteral: string;
    if (
      localeNames.length > 0 &&
      this._cachedInlineAllLocalesKey === localeSignature &&
      this._cachedInlineAllLocalesJson !== null
    ) {
      inlineAllLocalesLiteral = this._cachedInlineAllLocalesJson;
    } else if (localeNames.length === 0) {
      inlineAllLocalesLiteral = "null";
      this._cachedInlineAllLocalesJson = null;
      this._cachedInlineAllLocalesKey = null;
    } else {
      inlineAllLocalesLiteral = safeJsonForInlineScript(allLocales);
      this._cachedInlineAllLocalesJson = inlineAllLocalesLiteral;
      this._cachedInlineAllLocalesKey = localeSignature;
    }
    const inlineI18nLocaleLiteral = i18nLocaleData
      ? safeJsonForInlineScript(i18nLocaleData)
      : "null";
    const inlineI18nLangLiteral = safeStringForInlineScript(i18nLang);
    // Server-side, pre-paint string resolver used only for the first
    // HTML render (before ``i18n.js`` finishes loading and can retranslate
    // via ``translateDOM``). Supports Mustache ``{{name}}`` substitution
    // to mirror the runtime API in ``packages/vscode/i18n.js``, so call
    // sites like ``tl('settings.footer.versionLink', { version })`` produce
    // the same output both pre- and post-hydration.
    const tl = (
      key: string,
      params?: Record<string, string | number>,
    ): string => {
      if (!i18nLocaleData) return key;
      const parts = String(key).split(".");
      let node: unknown = i18nLocaleData;
      for (const p of parts) {
        if (!node || typeof node !== "object") return key;
        node = (node as Record<string, unknown>)[p];
      }
      if (typeof node !== "string") return key;
      if (!params) return node;
      return node.replace(/\{\{(\w+)\}\}/g, (match, name) =>
        Object.prototype.hasOwnProperty.call(params, name)
          ? String(params[name])
          : match,
      );
    };
    // Pseudo locale contains only ASCII+Latin diacritics that Chromium
    // renders fine under any BCP-47 tag; picking ``en-x-pseudo`` keeps
    // accessibility tooling happy (lang must be a valid BCP-47 subtag).
    const htmlLang =
      i18nLang === "pseudo"
        ? "en-x-pseudo"
        : i18nLang === "zh-CN"
          ? "zh-CN"
          : "en";
    // 目前仅支持 en / zh-CN（都 LTR）。显式注入 dir 以保持与 Web UI 的无障碍行为一致，
    // 并与 packages/vscode/i18n.js::langToDir 白名单对齐，未来加 RTL 语言仅需扩同一套逻辑。
    const rtlPrefixes = [
      "ar",
      "fa",
      "he",
      "iw",
      "ps",
      "ur",
      "yi",
      "ug",
      "ckb",
      "ku",
      "dv",
      "sd",
    ];
    const htmlLangLower = htmlLang.toLowerCase();
    const htmlDir = rtlPrefixes.some(
      (p) => htmlLangLower === p || htmlLangLower.startsWith(p + "-"),
    )
      ? "rtl"
      : "ltr";

    return `<!DOCTYPE html>
<html lang="${htmlLang}" dir="${htmlDir}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; connect-src ${serverUrl} ${cspSource} 'self'; style-src ${cspSource}; script-src 'nonce-${nonce}'; img-src data: ${serverUrl} https: ${cspSource}; font-src ${serverUrl} data: ${cspSource}; object-src 'none'; frame-src 'none';">
    <meta id="aiia-config" data-server-url="${serverUrl}" data-csp-nonce="${nonce}" data-lottie-lib-url="${lottieJsUri}" data-no-content-lottie-json-url="${noContentLottieJsonUri}" data-no-content-fallback-svg-url="${activityIconUri}" data-mathjax-script-url="${mathjaxScriptUri}" data-marked-js-url="${markedJsUri}" data-prism-js-url="${prismJsUri}" data-notify-core-js-url="${webviewNotifyCoreUri}" data-settings-ui-js-url="${webviewSettingsUiUri}">
    <script nonce="${nonce}">window.__AIIA_NO_CONTENT_FALLBACK_SVG=${inlineNoContentFallbackSvgLiteral};window.__AIIA_NO_CONTENT_LOTTIE_DATA=${inlineNoContentLottieDataLiteral};window.__AIIA_I18N_LANG=${inlineI18nLangLiteral};window.__AIIA_I18N_LOCALE=${inlineI18nLocaleLiteral};window.__AIIA_I18N_ALL_LOCALES=${inlineAllLocalesLiteral};</script>
    <title>AI Intervention Agent</title>
    <link rel="stylesheet" href="${prismCssUri}">
    <link rel="stylesheet" href="${webviewCssUri}">
</head>
<body>
    <!--
      BM-7：首帧纯 CSS 骨架屏（boot skeleton）
      - HTML 解析到此处即可显示，不依赖脚本执行
      - JS init() 成功后通过切换 class + [hidden] 淡出（CSP 友好，无 inline style）
      - 始终提供 fallback：window.onerror / unhandledrejection 也会隐藏它，
        避免脚本异常导致永久遮盖真实 UI
      - 只是装饰性占位：aria-hidden=true + role=presentation 不吸走焦点/朗读
    -->
    <div id="aiiaBootSkeleton" class="aiia-boot-skeleton" role="presentation" aria-hidden="true">
        <div class="aiia-boot-skeleton__bar aiia-boot-skeleton__bar--title"></div>
        <div class="aiia-boot-skeleton__bar"></div>
        <div class="aiia-boot-skeleton__bar"></div>
        <div class="aiia-boot-skeleton__bar aiia-boot-skeleton__bar--short"></div>
        <div class="aiia-boot-skeleton__spacer"></div>
        <div class="aiia-boot-skeleton__bar aiia-boot-skeleton__bar--button"></div>
    </div>

    <div class="container">
        <div class="tabs-container hidden" id="tasksTabsContainer">
            <div class="status-indicator">
                <div class="breathing-light" id="statusLight" title="${tl("ui.status.serverStatus")}" data-i18n-title="ui.status.serverStatus"></div>
            </div>
            <button class="settings-btn" id="settingsBtn" title="${tl("ui.settingsBtn")}" aria-label="${tl("ui.settingsBtn")}" data-i18n-title="ui.settingsBtn">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                    <circle cx="12" cy="12" r="3"></circle>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82 1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                </svg>
            </button>
        </div>

        <!-- 统一三态面板（T1 · C10c / @aiia/tri-state-panel）
             默认 data-state="ready" → CSS 将整个面板 display:none；通过 URL 调试参数
             ?aiia_tri_state=loading|skeleton|empty|error[&aiia_tri_state_error=network|server_500|timeout|unknown]
             [&aiia_tri_state_empty=default|filtered] 可手动切换到各分支用于 E2E 演示。
             正式消费（loading/empty/error 真实业务驱动）由 C10d / S2 接入 window.AIIA_CONTENT_SM。
             反向闸门（tests/test_runtime_behavior.py::test_pre_reserved_keys_not_yet_consumed）
             依赖以下 13 个 data-i18n 声明 + tl() SSR 文本以标记 VSCode 端消费完成。 -->
        <div
            id="aiia-tri-state-panel"
            class="aiia-tri-state-panel"
            data-state="ready"
            data-error-mode="unknown"
            data-empty-mode="default"
            role="status"
            aria-live="polite"
            aria-busy="false"
        >
            <div class="aiia-tsp-branch" data-tsp-branch="skeleton">
                <span class="aiia-tsp-skeleton-placeholder" aria-hidden="true"></span>
                <span class="aiia-tsp-skeleton-placeholder" aria-hidden="true"></span>
            </div>
            <div class="aiia-tsp-branch" data-tsp-branch="loading">
                <h3 class="aiia-tsp-title" data-i18n="aiia.state.loading.title">${tl("aiia.state.loading.title")}</h3>
                <p class="aiia-tsp-message" data-i18n="aiia.state.loading.message">${tl("aiia.state.loading.message")}</p>
            </div>
            <div class="aiia-tsp-branch" data-tsp-branch="empty">
                <h3 class="aiia-tsp-title" data-i18n="aiia.state.empty.title">${tl("aiia.state.empty.title")}</h3>
                <p class="aiia-tsp-empty-detail" data-tsp-empty-detail="default" data-i18n="aiia.state.empty.message.default">${tl("aiia.state.empty.message.default")}</p>
                <p class="aiia-tsp-empty-detail" data-tsp-empty-detail="filtered" data-i18n="aiia.state.empty.message.filtered">${tl("aiia.state.empty.message.filtered")}</p>
            </div>
            <div class="aiia-tsp-branch" data-tsp-branch="error">
                <h3 class="aiia-tsp-title" data-i18n="aiia.state.error.title">${tl("aiia.state.error.title")}</h3>
                <p class="aiia-tsp-error-detail" data-tsp-error-detail="network" data-i18n="aiia.state.error.message.network">${tl("aiia.state.error.message.network")}</p>
                <p class="aiia-tsp-error-detail" data-tsp-error-detail="server_500" data-i18n="aiia.state.error.message.server_500">${tl("aiia.state.error.message.server_500")}</p>
                <p class="aiia-tsp-error-detail" data-tsp-error-detail="timeout" data-i18n="aiia.state.error.message.timeout">${tl("aiia.state.error.message.timeout")}</p>
                <p class="aiia-tsp-error-detail" data-tsp-error-detail="unknown" data-i18n="aiia.state.error.message.unknown">${tl("aiia.state.error.message.unknown")}</p>
                <div class="aiia-tsp-actions">
                    <button type="button" class="aiia-tsp-action" data-tsp-action="retry" data-i18n="aiia.state.error.action.retry">${tl("aiia.state.error.action.retry")}</button>
                    <button type="button" class="aiia-tsp-action" data-tsp-action="open_log" data-i18n="aiia.state.error.action.open_log">${tl("aiia.state.error.action.open_log")}</button>
                    <button type="button" class="aiia-tsp-action" data-tsp-action="copy_diagnostics" data-i18n="aiia.state.error.action.copy_diagnostics">${tl("aiia.state.error.action.copy_diagnostics")}</button>
                </div>
            </div>
        </div>

        <div class="content" id="mainContent">
            <div class="loading hidden" id="loadingState">
                <div class="spinner"></div>
                <div data-i18n="ui.connecting">${tl("ui.connecting")}</div>
            </div>

            <div class="no-content" id="noContentState">
                <button class="settings-btn no-content-settings-btn" id="settingsBtnNoContent" title="${tl("ui.settingsBtn")}" aria-label="${tl("ui.settingsBtn")}" data-i18n-title="ui.settingsBtn">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                        <circle cx="12" cy="12" r="3"></circle>
                        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82 1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                    </svg>
                </button>
                <div class="no-content-icon" id="hourglass-lottie" aria-hidden="true">\ud83c\udf31</div>
                <div class="title" data-i18n="ui.noContent.title">${tl("ui.noContent.title")}</div>
                <div class="status-indicator-standalone">
                    <div class="breathing-light" id="statusLightStandalone" title="${tl("ui.status.serverStatus")}" data-i18n-title="ui.status.serverStatus"></div>
                    <span id="statusTextStandalone" data-i18n="ui.noContent.connecting">${tl("ui.noContent.connecting")}</span>
                </div>
                <div class="no-content-progress" id="noContentProgress">
                    <div class="no-content-progress-bar"></div>
                </div>
            </div>

            <div class="feedback-form hidden" id="feedbackForm">
                <div class="scrollable-content">
                    <!-- R691（TODO#5 跨端一致性）：任务级 header chip（≤16 字符领域标签），
                         与 web 端 #task-header-chip 同构；无 header_label 时隐藏。 -->
                    <div class="task-header-chip hidden" id="taskHeaderChip" aria-hidden="false"></div>
                    <!-- Loop 工程 P4（与 web 端 #task-loop-context 同构）：活动任务的
                         loop 上下文条。agent 传 loop_id / loop_phase / iteration_label /
                         loop_objective / success_criteria 时显示；由 updateLoopContext
                         控制显隐，textContent 填充（XSS 安全）。 -->
                    <div class="task-loop-context hidden" id="taskLoopContext" role="status">
                        <div class="loop-context-chips">
                            <span class="loop-chip hidden" id="loopChipId" title="${tl("ui.loop.idTitle")}" data-i18n-title="ui.loop.idTitle"></span>
                            <span class="loop-chip hidden" id="loopChipPhase" title="${tl("ui.loop.phaseTitle")}" data-i18n-title="ui.loop.phaseTitle"></span>
                            <span class="loop-chip hidden" id="loopChipIter" title="${tl("ui.loop.iterTitle")}" data-i18n-title="ui.loop.iterTitle"></span>
                        </div>
                        <div class="loop-context-line hidden" id="loopObjectiveLine">
                            <span class="loop-context-label" data-i18n="ui.loop.objectiveLabel">${tl("ui.loop.objectiveLabel")}</span>
                            <span class="loop-context-value" id="loopObjectiveValue"></span>
                        </div>
                        <div class="loop-context-line hidden" id="loopCriteriaLine">
                            <span class="loop-context-label" data-i18n="ui.loop.criteriaLabel">${tl("ui.loop.criteriaLabel")}</span>
                            <span class="loop-context-value" id="loopCriteriaValue"></span>
                        </div>
                        <!-- Loop 视图（与 web 端同构）：历史轮次折叠面板。点击拉取
                             GET /api/loops，按当前 loop_id 渲染已完成轮次时间线。 -->
                        <button type="button" class="loop-history-toggle hidden" id="loopHistoryToggle" aria-expanded="false" aria-controls="loopHistoryList">
                            <svg class="loop-history-caret" width="9" height="9" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                                <polyline points="5 3 11 8 5 13" />
                            </svg>
                            <span data-i18n="ui.loop.historyToggle">${tl("ui.loop.historyToggle")}</span>
                            <span class="loop-history-count" id="loopHistoryCount"></span>
                        </button>
                        <div class="loop-history-list hidden" id="loopHistoryList" role="list"></div>
                    </div>
                    <div class="markdown-content" id="markdownContent"></div>

                    <div class="form-section hidden" id="optionsSection">
                        <div class="form-label" data-i18n="ui.form.optionsLabel">${tl("ui.form.optionsLabel")}</div>
                        <div class="options-container" id="optionsContainer"></div>
                    </div>

                </div>

                <div class="fixed-input-area">
                    <!-- R690（TODO#5 web/插件功能对齐）：倒计时控制行。
                         与 web 端 countdown-extend-btn / countdown-freeze-btn 同构：
                         仅当 active 任务 auto_resubmit_timeout > 0 时显示；
                         +60s 受服务端 extends_max 配额约束（达到上限置灰）。 -->
                    <div class="countdown-controls hidden" id="countdownControls">
                        <button type="button" class="countdown-ctrl-btn" id="countdownExtendBtn" title="${tl("ui.countdown.extendTitle")}" aria-label="${tl("ui.countdown.extendAriaLabel")}" data-i18n-title="ui.countdown.extendTitle">
                            <span data-i18n="ui.countdown.extendLabel">${tl("ui.countdown.extendLabel")}</span>
                        </button>
                        <button type="button" class="countdown-ctrl-btn" id="countdownFreezeBtn" title="${tl("ui.countdown.freezeTitle")}" aria-label="${tl("ui.countdown.freezeAriaLabel")}" data-i18n-title="ui.countdown.freezeTitle">
                            <span data-i18n="ui.countdown.freezeLabel">${tl("ui.countdown.freezeLabel")}</span>
                        </button>
                    </div>
                    <div class="uploaded-images" id="uploadedImages"></div>

                    <!-- R691（TODO#5 跨端一致性）：question_type="yesno" 时替代
                         textarea 的一行 Yes/No 按钮组，点击直接提交字面 yes/no。 -->
                    <div class="yesno-button-group hidden" id="yesnoButtonGroup">
                        <button type="button" class="yesno-btn yesno-btn-yes" id="yesnoYesBtn" data-i18n="ui.form.yesnoYes">${tl("ui.form.yesnoYes")}</button>
                        <button type="button" class="yesno-btn yesno-btn-no" id="yesnoNoBtn" data-i18n="ui.form.yesnoNo">${tl("ui.form.yesnoNo")}</button>
                    </div>

                    <div class="textarea-wrapper">
                        <div class="textarea-resize-handle" id="resizeHandle"></div>
                        <textarea
                            class="feedback-textarea"
                            id="feedbackText"
                            placeholder="${tl("ui.form.placeholder")}"
                            data-i18n-placeholder="ui.form.placeholder"
                        ></textarea>

                        <input type="file" id="imageInput" accept="image/*" multiple class="hidden">

                        <div class="input-buttons">
                            <button type="button" class="insert-code-btn" id="insertCodeBtn" title="${tl("ui.form.insertCode")}" aria-label="${tl("ui.form.insertCode")}" data-i18n-title="ui.form.insertCode">
                                <svg class="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                                    <polyline points="16 18 22 12 16 6"></polyline>
                                    <polyline points="8 6 2 12 8 18"></polyline>
                                    <line x1="14" y1="4" x2="10" y2="20"></line>
                                </svg>
                            </button>
                            <button type="button" class="upload-btn" id="uploadBtn" title="${tl("ui.form.uploadImage")}" aria-label="${tl("ui.form.uploadImage")}" data-i18n-title="ui.form.uploadImage">
                                <svg class="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
                                    <path fill-rule="evenodd" clip-rule="evenodd" d="M3 4.5C3 3.67157 3.67157 3 4.5 3H15.5C16.3284 3 17 3.67157 17 4.5V15.5C17 16.3284 16.3284 17 15.5 17H4.5C3.67157 17 3 16.3284 3 15.5V4.5ZM4.5 4C4.22386 4 4 4.22386 4 4.5V12.2929L6.64645 9.64645C6.84171 9.45118 7.15829 9.45118 7.35355 9.64645L10 12.2929L13.1464 9.14645C13.3417 8.95118 13.6583 8.95118 13.8536 9.14645L16 11.2929V4.5C16 4.22386 15.7761 4 15.5 4H4.5ZM16 12.7071L13.5 10.2071L10.3536 13.3536C10.1583 13.5488 9.84171 13.5488 9.64645 13.3536L7 10.7071L4 13.7071V15.5C4 15.7761 4.22386 16 4.5 16H15.5C15.7761 16 16 15.7761 16 15.5V12.7071ZM7 7.5C7 6.94772 7.44772 6.5 8 6.5C8.55228 6.5 9 6.94772 9 7.5C9 8.05228 8.55228 8.5 8 8.5C7.44772 8.5 7 8.05228 7 7.5Z" fill="currentColor" />
                                </svg>
                            </button>
                            <button type="button" class="submit-btn-embedded" id="submitBtn" title="${tl("ui.form.submit")}" aria-label="${tl("ui.form.submit")}" data-i18n-title="ui.form.submit">
                                <svg class="btn-icon submit-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" aria-hidden="true" focusable="false">
                                    <path d="M19.26 9.77C19.91 9.08 20.92 8.91 21.73 9.32L21.89 9.40L21.94 9.43L22.19 9.63C22.20 9.64 22.22 9.65 22.23 9.66L44.63 30.46C45.05 30.86 45.30 31.42 45.30 32.00C45.30 32.44 45.16 32.86 44.91 33.21C44.90 33.23 44.89 33.24 44.88 33.26L44.66 33.50C44.65 33.52 44.64 33.53 44.63 33.54L22.23 54.34C21.38 55.13 20.05 55.08 19.26 54.23C18.47 53.38 18.52 52.05 19.37 51.26L40.12 32.00L19.37 12.74C19.36 12.73 19.35 12.72 19.34 12.70L19.12 12.46C19.11 12.45 19.10 12.43 19.09 12.42C18.52 11.62 18.57 10.52 19.26 9.77Z" fill="currentColor" />
                                </svg>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

        <div class="toast-host" id="toastHost" aria-live="polite" aria-atomic="true"></div>

    <div class="settings-overlay hidden" id="settingsOverlay">
        <div class="settings-panel" id="settingsPanel" role="dialog" aria-modal="true">
            <div class="settings-header">
                <div class="settings-title" data-i18n="settings.title">${tl("settings.title")}</div>
                <button class="settings-close" id="settingsClose" title="${tl("settings.close")}" aria-label="${tl("settings.close")}" data-i18n-title="settings.close">
                    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                        <path d="M5 5L15 15"></path>
                        <path d="M15 5L5 15"></path>
                    </svg>
                </button>
            </div>
            <div class="settings-body">
                <label class="settings-toggle">
                    <span data-i18n="settings.enabled">${tl("settings.enabled")}</span>
                    <input type="checkbox" id="notifyEnabled">
                </label>
                <label class="settings-toggle">
                    <span data-i18n="settings.macosNative">${tl("settings.macosNative")}</span>
                    <input type="checkbox" id="notifyMacOSNativeEnabled">
                </label>

                <div class="settings-divider"></div>

                <label class="settings-toggle">
                    <span data-i18n="settings.bark.enabled">${tl("settings.bark.enabled")}</span>
                    <input type="checkbox" id="notifyBarkEnabled">
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.bark.url">${tl("settings.bark.url")}</span>
                    <input type="text" id="notifyBarkUrl" placeholder="${tl("settings.bark.urlPlaceholder")}" data-i18n-placeholder="settings.bark.urlPlaceholder">
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.bark.deviceKey">${tl("settings.bark.deviceKey")}</span>
                    <input type="text" id="notifyBarkDeviceKey" placeholder="${tl("settings.bark.deviceKeyPlaceholder")}" data-i18n-placeholder="settings.bark.deviceKeyPlaceholder">
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.bark.icon">${tl("settings.bark.icon")}</span>
                    <input type="text" id="notifyBarkIcon" placeholder="${tl("settings.bark.iconPlaceholder")}" data-i18n-placeholder="settings.bark.iconPlaceholder">
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.bark.action">${tl("settings.bark.action")}</span>
                    <select id="notifyBarkAction">
                        <option value="none" data-i18n="settings.bark.actionNone">${tl("settings.bark.actionNone")}</option>
                        <option value="url" data-i18n="settings.bark.actionUrl">${tl("settings.bark.actionUrl")}</option>
                        <option value="copy" data-i18n="settings.bark.actionCopy">${tl("settings.bark.actionCopy")}</option>
                    </select>
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.bark.urlTemplate">${tl("settings.bark.urlTemplate")}</span>
                    <input type="text" id="notifyBarkUrlTemplate" placeholder="${tl("settings.bark.urlTemplatePlaceholder")}" data-i18n-placeholder="settings.bark.urlTemplatePlaceholder">
                    <span class="settings-field-hint" data-i18n="settings.bark.urlTemplateHint">${tl("settings.bark.urlTemplateHint")}</span>
                </label>
                <div class="settings-field bark-base-url-status" id="settingsBarkBaseUrlStatus" hidden>
                    <span class="settings-label" data-i18n="settings.bark.baseUrlStatusTitle">${tl("settings.bark.baseUrlStatusTitle")}</span>
                    <span class="settings-field-hint" id="settingsBarkBaseUrlMessage"></span>
                    <span class="settings-field-hint" id="settingsBarkBaseUrlSuggestion"></span>
                    <div class="settings-bark-base-url-actions" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px;">
                        <button type="button" class="settings-action secondary" id="settingsBarkBaseUrlCopyBtn" hidden data-i18n="settings.bark.baseUrlCopyLan">${tl("settings.bark.baseUrlCopyLan")}</button>
                        <button type="button" class="settings-action secondary" id="settingsBarkBaseUrlRecheckBtn" data-i18n="settings.bark.baseUrlRecheck">${tl("settings.bark.baseUrlRecheck")}</button>
                    </div>
                </div>

                <div class="settings-divider"></div>

                <div class="settings-section-title" data-i18n="settings.feedback.title">${tl("settings.feedback.title")}</div>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.feedback.countdown">${tl("settings.feedback.countdown")}</span>
                    <input type="number" id="feedbackCountdown" min="0" max="3600" step="10" value="240" style="max-width:100px">
                    <span class="settings-field-hint" data-i18n="settings.feedback.countdownHint">${tl("settings.feedback.countdownHint")}</span>
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.feedback.resubmitPrompt">${tl("settings.feedback.resubmitPrompt")}</span>
                    <!-- maxlength 与 server_config.PROMPT_MAX_LENGTH (100_000) +
                         web 端 templates/web_ui.html#feedback-resubmit-prompt 对齐 (BUG6-跨端).
                         插件先前硬编码 500 让用户在 VSCode 设置面板里输入超过 500
                         字符就被静默截断，导致后端实际接收的 resubmit_prompt 和
                         配置文件持久化的内容长度不一致。 -->
                    <textarea id="feedbackResubmitPrompt" rows="2" maxlength="100000" placeholder="${tl("settings.feedback.resubmitPromptPlaceholder")}" data-i18n-placeholder="settings.feedback.resubmitPromptPlaceholder"></textarea>
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.feedback.promptSuffix">${tl("settings.feedback.promptSuffix")}</span>
                    <!-- 同上：与 PROMPT_MAX_LENGTH = 100_000 对齐 -->
                    <textarea id="feedbackPromptSuffix" rows="2" maxlength="100000" placeholder="${tl("settings.feedback.promptSuffixPlaceholder")}" data-i18n-placeholder="settings.feedback.promptSuffixPlaceholder"></textarea>
                </label>
                <div class="settings-divider"></div>

                <div class="settings-section-title" data-i18n="settings.config.title">${tl("settings.config.title")}</div>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.config.path">${tl("settings.config.path")}</span>
                    <input type="text" id="settingsConfigPath" readonly placeholder="${tl("settings.config.pathPlaceholder")}" data-i18n-placeholder="settings.config.pathPlaceholder">
                </label>

                <div class="settings-divider"></div>

                <div class="settings-actions">
                    <button class="settings-action secondary" id="settingsTestNativeBtn" data-i18n="settings.testNative">${tl("settings.testNative")}</button>
                    <button class="settings-action secondary" id="settingsTestBarkBtn" data-i18n="settings.testBark">${tl("settings.testBark")}</button>
                    <div class="settings-actions-right">
                        <span class="settings-auto-save" title="${tl("settings.autoSaveTooltip")}" data-i18n="settings.autoSave" data-i18n-title="settings.autoSaveTooltip">${tl("settings.autoSave")}</span>
                    </div>
                </div>
                <!-- feat-footer-link-plugin: align with web UI footer.
                     Merge "v1.7.X" text + standalone "GitHub" link into a
                     single clickable anchor "AI Intervention Agent X.Y.Z".
                     Now matches the web .version-link capsule pill style
                     with GitHub octocat icon prefix (currentColor inherits
                     link text color, so dark / light / hc themes all work).
                     data-i18n-version lets i18n.js re-interpolate the
                     extensionVersion on language switch (kept in sync with
                     the pre-paint tl(...) result). Note: backticks are
                     intentionally avoided in this comment because the
                     surrounding TypeScript template literal would otherwise
                     terminate early. -->
                <div class="settings-footer" id="settingsFooter">
                    <a class="settings-footer-link" href="${githubUrl}" target="_blank" rel="noopener noreferrer" data-i18n-title="settings.footer.versionLinkTitle" title="${tl("settings.footer.versionLinkTitle")}">
                        <svg viewBox="0 0 24 24" fill="currentColor" class="github-icon" width="14" height="14" aria-hidden="true" focusable="false">
                            <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/>
                        </svg>
                        <span class="settings-footer-link-text" data-i18n="settings.footer.versionLink" data-i18n-version="${extensionVersion}">${tl("settings.footer.versionLink", { version: extensionVersion })}</span>
                    </a>
                </div>
                <div class="settings-hint" id="settingsHint"></div>
            </div>
        </div>
    </div>

    <!-- Prism.js for code highlighting (no inline scripts; CSP-safe) -->
    <script nonce="${nonce}" src="${prismBootstrapUri}"></script>
    <!-- prism.min.js / marked.min.js 由 webview-ui.js 按需懒加载（首屏更快） -->

        <script nonce="${nonce}" src="${i18nJsUri}"></script>
        <script nonce="${nonce}" src="${webviewStateUri}"></script>
        <script nonce="${nonce}" src="${webviewHelpersUri}"></script>
        <script nonce="${nonce}" src="${webviewUiUri}"></script>
        <script nonce="${nonce}" src="${webviewNotifyCoreUri}"></script>

        <!-- T1 · C10c: @aiia/tri-state-panel via Import Maps
             importmap 必须出现在所有 <script type="module"> 之前（浏览器规范）。
             业务代码通过 bare specifier \`@aiia/tri-state-panel\` 消费，Web UI 与
             VSCode webview 双端书写完全一致——真正的物理文件路径差异只在
             importmap 映射里。CSP 合规：importmap 与 module script 均携带 nonce，
             受 \`script-src 'nonce-...'\` 约束。 -->
        <script type="importmap" nonce="${nonce}">
        {
          "imports": {
            "@aiia/tri-state-panel": "${triStatePanelJsUri}"
          }
        }
        </script>
        <script type="module" nonce="${nonce}" src="${triStatePanelLoaderUri}"></script>
        <script nonce="${nonce}" src="${triStatePanelBootstrapUri}"></script>
</body>
</html>`;
  }
}

module.exports = { WebviewProvider };
