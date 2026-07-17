/**
 * AI Intervention Agent - 主应用脚本
 *
 * 功能模块：
 *   - Lottie 动画配置和初始化
 *   - Markdown 渲染和代码高亮
 *   - 页面状态管理（无内容页面/内容页面切换）
 *   - 内容轮询逻辑
 *   - 表单处理和提交
 *   - 通知管理器
 *   - 设置管理器
 *   - 图片上传处理
 *   - 应用初始化
 *
 * 依赖：
 *   - mathjax-loader.js: MathJax 懒加载
 *   - multi_task.js: 多任务管理
 *   - theme.js: 主题管理
 *   - dom-security.js: DOM 安全工具
 *   - validation-utils.js: 验证工具
 *   - marked.js: Markdown 解析
 *   - prism.min.js: 代码高亮（R27.1：从 prism.js 切换到 upstream minified 版本）
 *   - lottie.min.js: 动画库
 */

// ==================================================================
// 访问地址兼容性处理（0.0.0.0 -> 127.0.0.1）
// ==================================================================
//
// 背景：
// - 0.0.0.0 是服务端“监听所有网卡”的绑定地址，适合服务端 bind，但不适合作为浏览器访问地址。
// - 部分浏览器/环境下，访问 http://0.0.0.0:PORT 可能出现异常（如权限异常、请求失败、Failed to fetch）。
//
// 处理策略：
// - 若检测到当前页面 hostname 为 0.0.0.0，则自动切换为 127.0.0.1（保持端口/路径/查询参数不变）
// - 使用 location.replace 避免污染历史记录
(function redirectZeroHostToLoopback() {
  try {
    const url = new URL(window.location.href);
    if (url.hostname === "0.0.0.0") {
      url.hostname = "127.0.0.1";
      console.warn(
        `Detected 0.0.0.0 host; auto-redirecting to ${url.origin} (avoids browser compatibility issues).`,
      );
      window.location.replace(url.toString());
    }
  } catch (e) {
    // 忽略：不影响主流程
  }
})();

// ==================================================================
// 全局错误兜底：捕获未处理的 JS 异常和 Promise 拒绝
// ==================================================================
window.addEventListener("error", function (event) {
  console.error("[global error]", event.error || event.message);
});
window.addEventListener("unhandledrejection", function (event) {
  console.error("[unhandled rejection]", event.reason);
});

// ==================================================================
// 带超时的 fetch 包装（防止网络异常时无限等待）
//
// 与朴素 `fetch(url, { signal })` 的差异：
// - timeoutMs > 0 时自动添加超时信号；
// - 调用方可以继续通过 options.signal 提供"外部取消"（例如页面卸载、用户
//   手动取消）；外部信号和超时信号通过 AbortSignal.any（或兜底手写 merge）
//   合并，**任何一方触发都会终止请求**，而不会像以前那样静默丢弃 caller signal。
//
// 浏览器兼容：
// - AbortSignal.timeout() 和 AbortSignal.any() 在 Chrome 116+ / Firefox 124+ /
//   Safari 17.4+ 已广泛可用；本函数对两者都做了 feature detect，缺失时用
//   AbortController + addEventListener 手写 fallback。
// - 极旧/受限宿主如果连 AbortController 也没有，就保留原 options 发起 fetch；
//   此时无法合成 timeout，但不能因为缺少取消 API 而阻断请求本身。
// ==================================================================
function fetchWithTimeout(url, options, timeoutMs) {
  var userSignal = options && options.signal;
  var hasTimeout = typeof timeoutMs === "number" && timeoutMs > 0;

  if (!hasTimeout) {
    return fetch(url, options);
  }

  var hasAbortAny =
    typeof AbortSignal !== "undefined" && typeof AbortSignal.any === "function";
  var hasAbortTimeout =
    typeof AbortSignal !== "undefined" &&
    typeof AbortSignal.timeout === "function";

  if (hasAbortTimeout && (!userSignal || hasAbortAny)) {
    var timeoutSignal = AbortSignal.timeout(timeoutMs);
    var mergedSignal = userSignal
      ? AbortSignal.any([userSignal, timeoutSignal])
      : timeoutSignal;
    var mergedNative = Object.assign({}, options || {}, {
      signal: mergedSignal,
    });
    return fetch(url, mergedNative);
  }

  if (typeof AbortController === "undefined") {
    return fetch(url, options);
  }

  var controller = new AbortController();
  var timer = setTimeout(function () {
    controller.abort();
  }, timeoutMs);

  function onUserAbort() {
    controller.abort();
  }
  if (userSignal) {
    if (userSignal.aborted) {
      controller.abort();
    } else {
      userSignal.addEventListener("abort", onUserAbort, { once: true });
    }
  }

  var mergedFallback = Object.assign({}, options || {}, {
    signal: controller.signal,
  });
  return fetch(url, mergedFallback).finally(function () {
    clearTimeout(timer);
    if (userSignal) {
      userSignal.removeEventListener("abort", onUserAbort);
    }
  });
}

// 主题管理器已在 theme.js 中定义和初始化
// 此处不再重复定义，避免 CSP nonce 和重复声明问题

let config = null;

function t(key, params) {
  try {
    if (window.AIIA_I18N && typeof window.AIIA_I18N.t === "function") {
      return window.AIIA_I18N.t(key, params);
    }
  } catch (_e) {
    /* noop */
  }
  return key;
}

// ==================================================================
// marked.js 安全配置（禁用原生 HTML 渲染）
// ==================================================================
//
// 背景：
// - marked 默认允许 Markdown 中的原生 HTML（如 <style> / <iframe> / <script> 等）
// - 即使有 CSP，原生 HTML 注入仍可能造成 UI 欺骗/样式污染（防御纵深不足）
// - 这里选择“直接禁用 HTML token 的渲染”，让原生 HTML 在渲染结果中被丢弃
//
// 影响：
// - Markdown 内嵌的原生 HTML 不再生效（常规 Markdown 语法不受影响）
//
if (typeof window.__aiiaMarkedSecurityConfigured === "undefined") {
  window.__aiiaMarkedSecurityConfigured = false;
}

function configureMarkedSecurity() {
  if (window.__aiiaMarkedSecurityConfigured) return;
  if (typeof marked === "undefined" || !marked) return;

  try {
    if (typeof marked.use === "function") {
      marked.use({
        renderer: {
          // token: { type: 'html', text: '...' }
          html() {
            return "";
          },
        },
      });
    }

    if (typeof marked.setOptions === "function") {
      // 可复现/可预测输出：禁用 email 混淆与标题 id 生成（避免不必要的 DOM 变化）
      marked.setOptions({ mangle: false, headerIds: false });
    }

    window.__aiiaMarkedSecurityConfigured = true;
  } catch (e) {
    console.warn("marked security config failed (ignored):", e);
  }
}

configureMarkedSecurity();

// ==================================================================
// Lottie 嫩芽动画配置
// ==================================================================
//
// 功能说明：
//   在"无有效内容"页面显示循环播放的嫩芽生长动画，
//   向用户传达"等待中/正在生长"的视觉隐喻。
//
// 动画来源：
//   /static/lottie/sprout.json
//
// 主题适配：
//   - 浅色模式：原色（深色线条）
//   - 深色模式：通过 CSS filter: invert(1) 反转为白色线条
//   - 叶子颜色因 invert 也会变化（可接受的视觉效果）
//
// 降级处理：
//   若 Lottie 库加载失败，显示内置 SVG/CSS 备用图标
// ==================================================================

// Lottie 动画实例引用（用于后续控制如暂停/销毁）
let hourglassAnimation = null;
let _lottieLoadPromise = null;
let _hourglassObserver = null;
let _hourglassDelayTimer = null;
let _hourglassFallbackRemovalTimer = null;
let _hourglassIdleCallbackId = null;
let _hourglassLoadHandler = null;
let _hourglassThemeTimer = null;
let _hourglassLifecycleToken = 0;
let _hourglassLifecycleDisposed = false;
let _hourglassLifecycleHandlersInstalled = false;

function _isHourglassLifecycleActive(container, token) {
  if (_hourglassLifecycleDisposed) return false;
  if (token !== _hourglassLifecycleToken) return false;
  if (typeof document !== "undefined" && document.hidden) return false;
  if (!container) return false;
  try {
    if (container.isConnected === false) return false;
  } catch (_e) {
    // 忽略
  }
  try {
    if (
      document.body &&
      typeof document.body.contains === "function" &&
      !document.body.contains(container)
    ) {
      return false;
    }
  } catch (_e) {
    // 忽略
  }
  return true;
}

function _disconnectHourglassObserver() {
  try {
    if (_hourglassObserver) _hourglassObserver.disconnect();
  } catch (_e) {
    // 忽略
  }
  _hourglassObserver = null;
}

function _clearHourglassLifecycleTimers() {
  try {
    if (_hourglassDelayTimer) clearTimeout(_hourglassDelayTimer);
  } catch (_e) {
    // 忽略
  }
  _hourglassDelayTimer = null;

  try {
    if (_hourglassFallbackRemovalTimer) {
      clearTimeout(_hourglassFallbackRemovalTimer);
    }
  } catch (_e) {
    // 忽略
  }
  _hourglassFallbackRemovalTimer = null;

  try {
    if (
      _hourglassIdleCallbackId !== null &&
      typeof window.cancelIdleCallback === "function"
    ) {
      window.cancelIdleCallback(_hourglassIdleCallbackId);
    }
  } catch (_e) {
    // 忽略
  }
  _hourglassIdleCallbackId = null;

  try {
    if (_hourglassLoadHandler) {
      window.removeEventListener("load", _hourglassLoadHandler);
    }
  } catch (_e) {
    // 忽略
  }
  _hourglassLoadHandler = null;

  try {
    if (_hourglassThemeTimer) clearTimeout(_hourglassThemeTimer);
  } catch (_e) {
    // 忽略
  }
  _hourglassThemeTimer = null;
}

function destroyHourglassAnimation() {
  try {
    if (hourglassAnimation) hourglassAnimation.destroy();
  } catch (_e) {
    // 忽略
  }
  hourglassAnimation = null;
}

function disposeHourglassAnimationLifecycle() {
  _hourglassLifecycleDisposed = true;
  _hourglassLifecycleToken += 1;
  _disconnectHourglassObserver();
  _clearHourglassLifecycleTimers();
  destroyHourglassAnimation();
}

function installHourglassAnimationLifecycleHandlers() {
  if (_hourglassLifecycleHandlersInstalled) return;
  _hourglassLifecycleHandlersInstalled = true;

  try {
    window.addEventListener("pagehide", function () {
      disposeHourglassAnimationLifecycle();
    });
  } catch (_e) {
    // 忽略
  }

  try {
    window.addEventListener("pageshow", function (event) {
      if (!event || !event.persisted) return;
      if (typeof document !== "undefined" && document.hidden) return;
      initHourglassAnimation();
    });
  } catch (_e) {
    // 忽略
  }

  try {
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        disposeHourglassAnimationLifecycle();
      } else {
        initHourglassAnimation();
      }
    });
  } catch (_e) {
    // 忽略
  }
}

/**
 * 渲染“嫩芽”动画的 SVG/CSS 降级版本
 *
 * 设计目标：
 * - 不依赖外部资源（JSON/网络/库）
 * - 纯 SVG + CSS 动画，可在 Lottie 加载失败时仍提供动态反馈
 * - 颜色由容器的 filter/invert 统一控制（对齐 updateLottieAnimationColor）
 */
function renderSproutFallback(container) {
  if (!container) return;
  try {
    // 清空容器（避免和 Lottie 的 SVG 叠加）
    container.textContent = "";
    container.innerHTML = `
      <svg
        width="48"
        height="48"
        viewBox="0 0 48 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
        style="display:block; width:48px; height:48px;"
      >
        <style>
          @keyframes sproutGrow {
            0%   { transform: translateY(6px) scale(0.86); opacity: 0.65; }
            50%  { transform: translateY(0px) scale(1);    opacity: 1; }
            100% { transform: translateY(6px) scale(0.86); opacity: 0.65; }
          }
          @keyframes leafWiggle {
            0%,100% { transform: rotate(-6deg); }
            50%     { transform: rotate(6deg); }
          }
          .sprout-root { transform-origin: 24px 42px; animation: sproutGrow 1.6s ease-in-out infinite; }
          .leaf-left  { transform-origin: 18px 18px; animation: leafWiggle 1.6s ease-in-out infinite; }
          .leaf-right { transform-origin: 30px 18px; animation: leafWiggle 1.6s ease-in-out infinite reverse; }
        </style>
        <g class="sprout-root">
          <path d="M24 42V20" stroke="#111" stroke-width="3" stroke-linecap="round"/>
          <path class="leaf-left" d="M24 22C19 22 15 19 14 15C18 15 22 17 24 20" stroke="#111" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
          <path class="leaf-right" d="M24 22C29 22 33 19 34 15C30 15 26 17 24 20" stroke="#111" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M18 44C20 40 28 40 30 44" stroke="#111" stroke-width="3" stroke-linecap="round"/>
        </g>
      </svg>
    `;
  } catch (e) {
    // 最后兜底：极端情况下显示文本提示，避免再退化为 emoji
    container.textContent = t("status.waiting");
  }
}

function _ensureLottieLoaded() {
  if (typeof lottie !== "undefined") return Promise.resolve(true);
  if (_lottieLoadPromise) return _lottieLoadPromise;
  _lottieLoadPromise = new Promise((resolve) => {
    const script = document.createElement("script");
    script.src =
      window.AIIA_LOTTIE_JS_URL || "/static/js/lottie.min.js";
    script.onload = () => resolve(typeof lottie !== "undefined");
    script.onerror = () => {
      _lottieLoadPromise = null;
      resolve(false);
    };
    document.head.appendChild(script);
  });
  return _lottieLoadPromise;
}

function _createLottieAnimation(container, token) {
  if (!_isHourglassLifecycleActive(container, token)) return null;
  try {
    destroyHourglassAnimation();
    hourglassAnimation = lottie.loadAnimation({
      container,
      renderer: "svg",
      loop: true,
      autoplay: true,
      path: "/static/lottie/sprout.json",
      rendererSettings: { preserveAspectRatio: "xMidYMid meet" },
    });
    hourglassAnimation.addEventListener("DOMLoaded", () => {
      if (!_isHourglassLifecycleActive(container, token)) return;
      updateLottieAnimationColor();
    });
    hourglassAnimation.addEventListener("error", () => {
      if (!_isHourglassLifecycleActive(container, token)) return;
      renderSproutFallback(container);
      container.style.opacity = "1";
    });
    console.debug("Sprout animation initialized (lazy load)");
    return hourglassAnimation;
  } catch (error) {
    console.error("Lottie animation init failed:", error);
    if (_isHourglassLifecycleActive(container, token)) {
      renderSproutFallback(container);
      container.style.opacity = "1";
    }
    return null;
  }
}

/**
 * 初始化嫩芽生长 Lottie 动画
 *
 * 策略（R696）：lottie.min.js 已随首屏 ``<script defer>`` 预加载（见
 * web_ui.html），本函数直接创建 Lottie 动画——空态从第一帧起就是
 * Lottie，不再先渲染 SVG 降级动画再热切换（旧流程的可见跳变即由
 * 该切换引起）。仅两种情形回退到零依赖 SVG：
 *   1. 用户开启 prefers-reduced-motion（保持静态、尊重系统偏好）；
 *   2. lottie 运行时加载失败（离线/CDN 故障，走 AIIA_LOTTIE_JS_URL
 *      动态加载兜底后仍失败）。
 */
function initHourglassAnimation() {
  installHourglassAnimationLifecycleHandlers();

  if (typeof document !== "undefined" && document.hidden) return;

  const container = document.getElementById("hourglass-lottie");
  if (!container) return;

  _hourglassLifecycleDisposed = false;
  if (hourglassAnimation) {
    updateLottieAnimationColor();
    return;
  }

  _disconnectHourglassObserver();
  _clearHourglassLifecycleTimers();
  const token = _hourglassLifecycleToken + 1;
  _hourglassLifecycleToken = token;

  const prefersReducedMotion =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReducedMotion) {
    renderSproutFallback(container);
    return;
  }

  _ensureLottieLoaded().then((ok) => {
    if (!_isHourglassLifecycleActive(container, token)) return;
    if (!ok) {
      renderSproutFallback(container);
      return;
    }
    _createLottieAnimation(container, token);
    updateLottieAnimationColor();
  });
}

/**
 * 根据当前主题更新 Lottie 动画的线条颜色
 *
 * 实现方式：
 *   使用 CSS filter: invert(1) 反转颜色，而非修改 SVG 内部属性。
 *   这种方式更简单可靠，且能在主题切换时即时生效。
 *
 * 效果：
 *   - invert(0) / none：保持原色
 *   - invert(1)：将所有颜色反转（黑→白，白→黑）
 */
function updateLottieAnimationColor() {
  const container = document.getElementById("hourglass-lottie");
  if (!container) return;

  // 获取当前主题状态
  const isLightTheme =
    document.documentElement.getAttribute("data-theme") === "light";

  // 应用 CSS filter 实现颜色切换
  if (isLightTheme) {
    // 浅色模式：保持原色（深色线条在浅色背景上清晰可见）
    container.style.filter = "none";
  } else {
    // 深色模式：反转颜色（深色线条变为白色，在深色背景上清晰可见）
    container.style.filter = "invert(1)";
  }

}

// 监听主题变化事件（由 ThemeManager 在 theme.js 中派发）
// 用于在用户切换主题时即时更新 Lottie 动画颜色
window.addEventListener("theme-changed", (event) => {
  // 延迟 50ms 执行，确保 DOM data-theme 属性已更新
  try {
    if (_hourglassThemeTimer) clearTimeout(_hourglassThemeTimer);
  } catch (_e) {
    // 忽略
  }
  _hourglassThemeTimer = setTimeout(() => {
    _hourglassThemeTimer = null;
    if (!_hourglassLifecycleDisposed) {
      updateLottieAnimationColor();
    }
  }, 50);
});

// 高性能markdown渲染函数
// isMarkdown: 是否为 Markdown 源文本（需要 marked.js 解析）
function renderMarkdownContent(element, content, isMarkdown = false) {
  // R687 (TODO#1 渲染抽搐修复，与 multi_task.js::updateDescriptionDisplay
  // 同构)：SSE auto-refresh 路径可能以相同内容重入 loadConfig →
  // renderMarkdownContent。内容未变化时幂等短路，避免 innerHTML 重建 +
  // MathJax 重排造成的闪烁与选区丢失。dataset 兜底：测试桩元素可能没有
  // dataset 属性。
  const renderedDataset = element && element.dataset ? element.dataset : null;
  if (
    renderedDataset &&
    content &&
    renderedDataset.renderedContent === content &&
    element.childNodes &&
    element.childNodes.length > 0
  ) {
    return;
  }
  // 使用requestAnimationFrame优化渲染时机
  _scheduleNextFrame(() => {
    if (content) {
      let htmlContent = content;

      // 如果是 Markdown 文本，先用 marked.js 解析
      if (isMarkdown && typeof marked !== "undefined") {
        try {
          htmlContent = marked.parse(content);
        } catch (e) {
          console.warn("marked.js parse failed:", e);
        }
      }

      // 批量DOM操作优化
      const fragment = document.createDocumentFragment();
      const tempDiv = document.createElement("div");
      tempDiv.innerHTML = htmlContent;

      // 移动所有子节点到fragment
      while (tempDiv.firstChild) {
        fragment.appendChild(tempDiv.firstChild);
      }

      // 一次性更新DOM
      element.innerHTML = "";
      element.appendChild(fragment);
      // R687：渲染成功后记录签名，供幂等短路比较
      if (renderedDataset) {
        renderedDataset.renderedContent = content;
      }

      // 处理代码块，添加复制按钮
      processCodeBlocks(element);

      // 处理删除线语法
      processStrikethrough(element);

      /**
       * 按需加载并渲染 MathJax 数学公式
       *
       * 加载策略：
       *   1. 首先检测内容中是否包含数学公式（$...$, $$...$$, \(...\), \[...\]）
       *   2. 如果有数学公式，触发 MathJax 懒加载（约 1.17MB）
       *   3. MathJax 加载完成后，通过 startup.ready 回调自动渲染待处理元素
       *
       * 回退机制：
       *   如果 loadMathJaxIfNeeded 未定义（理论上不会发生），
       *   回退到直接检查 MathJax 对象并调用 typesetPromise
       */
      const textContent = element.textContent || "";
      if (window.loadMathJaxIfNeeded) {
        window.loadMathJaxIfNeeded(element, textContent);
      } else if (window.MathJax && window.MathJax.typesetPromise) {
        // 回退：如果 MathJax 已加载但 loadMathJaxIfNeeded 不可用，直接渲染
        window.MathJax.typesetPromise([element]).catch((err) => {
          console.warn("MathJax render failed:", err);
        });
      }
    } else {
      element.textContent = t("page.loading");
    }
  });
}

// 处理代码块，添加复制按钮和语言标识
function processCodeBlocks(container) {
  const codeBlocks = container.querySelectorAll("pre");

  const codeBlockCount =
    codeBlocks && Number.isFinite(codeBlocks.length) ? codeBlocks.length : 0;
  for (let codeBlockIndex = 0; codeBlockIndex < codeBlockCount; codeBlockIndex += 1) {
    const pre = codeBlocks[codeBlockIndex];
    if (!pre) continue;
    // 检查是否已经被处理过
    if (
      pre.parentElement &&
      pre.parentElement.classList.contains("code-block-container")
    ) {
      continue;
    }

    // 创建代码块容器
    const codeContainer = document.createElement("div");
    codeContainer.className = "code-block-container";

    // 将 pre 元素包装在容器中
    pre.parentNode.insertBefore(codeContainer, pre);
    codeContainer.appendChild(pre);

    // 检测语言类型
    const codeElement = pre.querySelector("code");
    let language = "text";
    if (codeElement && codeElement.className) {
      const langMatch = codeElement.className.match(/language-(\w+)/);
      if (langMatch) {
        language = langMatch[1];
      }
    }

    // 创建工具栏
    const toolbar = document.createElement("div");
    toolbar.className = "code-toolbar";

    // 添加语言标识
    if (language !== "text") {
      const langLabel = document.createElement("span");
      langLabel.className = "language-label";
      langLabel.textContent = language.toUpperCase();
      toolbar.appendChild(langLabel);
    }

    // 使用安全的复制按钮创建方法
    const copyButton = DOMSecurity.createCopyButton(pre.textContent || "");

    toolbar.appendChild(copyButton);

    // 将工具栏添加到容器中
    codeContainer.appendChild(toolbar);
  }
}

const COPY_BUTTON_RESTORE_DELAY_MS = 2000;
const COPY_BUTTON_ORIGINAL_HTML_PROP = "__aiiaCopyOriginalHTML";
const COPY_BUTTON_RESTORE_TIMER_PROP = "__aiiaCopyRestoreTimer";

function _clearCopyButtonRestoreTimer(button) {
  if (!button) return;
  const timerId = button[COPY_BUTTON_RESTORE_TIMER_PROP];
  if (timerId !== undefined && timerId !== null) {
    clearTimeout(timerId);
    button[COPY_BUTTON_RESTORE_TIMER_PROP] = null;
  }
}

function _beginCopyButtonTransientFeedback(button) {
  _clearCopyButtonRestoreTimer(button);
  if (
    !Object.prototype.hasOwnProperty.call(button, COPY_BUTTON_ORIGINAL_HTML_PROP)
  ) {
    button[COPY_BUTTON_ORIGINAL_HTML_PROP] = button.innerHTML;
  }
}

function _restoreCopyButtonBaseline(button) {
  button.innerHTML = button[COPY_BUTTON_ORIGINAL_HTML_PROP] || "";
  button.classList.remove("copied");
  button.classList.remove("error");
}

function _scheduleCopyButtonRestore(button, restoreCallback) {
  const timerId = setTimeout(() => {
    if (button[COPY_BUTTON_RESTORE_TIMER_PROP] !== timerId) {
      return;
    }
    try {
      restoreCallback();
    } finally {
      button[COPY_BUTTON_RESTORE_TIMER_PROP] = null;
      delete button[COPY_BUTTON_ORIGINAL_HTML_PROP];
    }
  }, COPY_BUTTON_RESTORE_DELAY_MS);
  button[COPY_BUTTON_RESTORE_TIMER_PROP] = timerId;
}

// 复制代码到剪贴板
async function copyCodeToClipboard(preElement, button) {
  // R285 / cycle-26 t26-2 (R268/R279/R280 entry-side 第四轮):
  // preElement 与 button 是 caller (event handler) 传入的引用。点击瞬间
  // 它们一定存在，但 await navigator.clipboard 之后可能：
  // (a) preElement 因 markdown re-render (SSE auto-refresh) 被替换 → stale
  // (b) button 因父 message bubble unmount → DOM detached
  // 旧实现直接 ``button.innerHTML = ...`` 抛 TypeError → catch 路径再次
  // ``button.innerHTML = errorIconSvg + ...`` 也抛 → 整个 setTimeout
  // restore 链断裂，console error 无法被用户感知。
  // R285 修复: 入口先 null/connected check，await 后访问也判 isConnected,
  // best-effort UI feedback 缺失 silently skip。
  const checkIconSvg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M13.7803 4.21967C14.0732 4.51256 14.0732 4.98744 13.7803 5.28033L6.78033 12.2803C6.48744 12.5732 6.01256 12.5732 5.71967 12.2803L2.21967 8.78033C1.92678 8.48744 1.92678 8.01256 2.21967 7.71967C2.51256 7.42678 2.98744 7.42678 3.28033 7.71967L6.25 10.6893L12.7197 4.21967C13.0126 3.92678 13.4874 3.92678 13.7803 4.21967Z"/></svg>';
  const errorIconSvg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M4.21967 4.21967C4.51256 3.92678 4.98744 3.92678 5.28033 4.21967L8 6.93934L10.7197 4.21967C11.0126 3.92678 11.4874 3.92678 11.7803 4.21967C12.0732 4.51256 12.0732 4.98744 11.7803 5.28033L9.06066 8L11.7803 10.7197C12.0732 11.0126 12.0732 11.4874 11.7803 11.7803C11.4874 12.0732 11.0126 12.0732 10.7197 11.7803L8 9.06066L5.28033 11.7803C4.98744 12.0732 4.51256 12.0732 4.21967 11.7803C3.92678 11.4874 3.92678 11.0126 4.21967 10.7197L6.93934 8L4.21967 5.28033C3.92678 4.98744 3.92678 4.51256 4.21967 4.21967Z"/></svg>';

  // R285 entry-side guard
  if (!preElement || !button) {
    console.warn("copyCodeToClipboard: preElement/button missing — abort");
    return;
  }

  try {
    const codeElement = preElement.querySelector("code");
    const textToCopy = codeElement
      ? codeElement.textContent
      : preElement.textContent;

    await navigator.clipboard.writeText(textToCopy);

    // R285: button 可能在 await 期间 detach (DOM re-render)，
    // isConnected 检查比直接访问 innerHTML 安全
    if (!button.isConnected) {
      console.debug(
        "copyCodeToClipboard: button detached after copy success — skip UI",
      );
      return;
    }
    _beginCopyButtonTransientFeedback(button);
    // AIIA-XSS-SAFE: checkIconSvg 是开发者手写 SVG 字面量；t('status.copied')
    // 走 locales/*.json 静态 key 且无参数。详见 docs/i18n.md § Security。
    button.innerHTML = checkIconSvg + t("status.copied");
    button.classList.remove("error");
    button.classList.add("copied");

    _scheduleCopyButtonRestore(button, () => {
      if (button.isConnected) {
        _restoreCopyButtonBaseline(button);
      }
    });
  } catch (err) {
    console.error("Copy failed:", err);

    // R285: catch 路径同样需要 isConnected check —— err 可能就是因为
    // button DOM detach 导致 (虽然多数 err 来自 navigator.clipboard)
    if (!button.isConnected) {
      console.debug(
        "copyCodeToClipboard: button detached during copy failure — skip UI",
      );
      return;
    }
    _beginCopyButtonTransientFeedback(button);
    // AIIA-XSS-SAFE: errorIconSvg 是开发者手写 SVG 字面量；t('status.copyFailed')
    // 走 locales/*.json 静态 key 且无参数。与 line 561 success 路径同源安全。
    button.innerHTML = errorIconSvg + t("status.copyFailed");
    button.classList.remove("copied");
    button.classList.add("error");

    _scheduleCopyButtonRestore(button, () => {
      if (button.isConnected) {
        _restoreCopyButtonBaseline(button);
      }
    });
  }
}

// 处理删除线语法 ~~text~~
function processStrikethrough(container) {
  // 获取所有文本节点，但排除代码块
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode: function (node) {
      // 排除代码块、pre、script 等标签内的文本
      const parent = node.parentElement;
      if (
        parent &&
        (parent.tagName === "CODE" ||
          parent.tagName === "PRE" ||
          parent.tagName === "SCRIPT" ||
          parent.tagName === "STYLE" ||
          parent.closest("pre, code, script, style"))
      ) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) {
    textNodes.push(node);
  }

  // 处理每个文本节点（使用 DOM API 避免 innerHTML 注入风险）
  for (let textNodeIndex = 0; textNodeIndex < textNodes.length; textNodeIndex += 1) {
    const textNode = textNodes[textNodeIndex];
    const text = textNode.textContent;
    const strikethroughRegex = /~~([^~\n]+?)~~/g;

    if (!strikethroughRegex.test(text)) continue;

    const parts = text.split(/~~([^~\n]+?)~~/);
    if (parts.length <= 1) continue;

    const fragment = document.createDocumentFragment();
    for (let i = 0; i < parts.length; i++) {
      if (i % 2 === 0) {
        if (parts[i]) fragment.appendChild(document.createTextNode(parts[i]));
      } else {
        const del = document.createElement("del");
        del.textContent = parts[i];
        fragment.appendChild(del);
      }
    }

    textNode.parentNode.replaceChild(fragment, textNode);
  }
}

// 加载配置
async function loadConfig() {
  try {
    const response = await fetchWithTimeout("/api/config", undefined, 10000);
    config = await response.json();

    // 检查是否有有效内容
    if (!config.has_content) {
      showNoContentPage();
      // 不再显示动态状态消息，只保留HTML中的固定文本
      return;
    }

    // 显示正常内容页面
    showContentPage();

    // 页面首次加载不发送通知，只在内容变化时通知

    // R285 / cycle-26 t26-2 (R268/R279/R280 entry-side 第四轮):
    // loadConfig 在 await fetch 之后访问 DOM 节点。loadConfig 可能在
    // SSE auto-refresh 路径多次重入；如果 #description 节点被 multi-task
    // 切换 / 错误 fallback 替换，``renderMarkdownContent(null, ...)`` 会
    // 抛 TypeError 被 catch 翻成 user-visible "Config load failed"——但
    // 配置实际加载成功了，UI 渲染失败误报为"加载失败"。null check 兜底
    // 让用户看到正确状态 (silently skip render + console.warn 留 trace)。
    const descriptionElement = document.getElementById("description");
    if (descriptionElement) {
      renderMarkdownContent(
        descriptionElement,
        config.prompt_html || config.prompt,
      );
    } else {
      console.warn(
        "loadConfig: #description not in DOM (SSE reload + multi-task " +
          "switch concurrent?) — skipping prompt render",
      );
    }

    if (config.predefined_options && config.predefined_options.length > 0) {
      const optionsContainer = document.getElementById("options-container");
      const separator = document.getElementById("separator");

      // R285: 同上，options-container / separator 任一缺失即跳过 options
      // 渲染，不报"加载失败"。
      if (!optionsContainer || !separator) {
        console.warn(
          "loadConfig: #options-container or #separator missing — " +
            "skipping options render",
        );
      } else {
        const optionDefaults = Array.isArray(config.predefined_options_defaults)
          ? config.predefined_options_defaults
          : [];
        const predefinedOptionCount = config.predefined_options.length;
        for (let index = 0; index < predefinedOptionCount; index += 1) {
          if (!(index in config.predefined_options)) continue;
          const option = config.predefined_options[index];
          const optionDiv = document.createElement("div");
          optionDiv.className = "option-item";

          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.id = `option-${index}`;
          checkbox.value = option;
          checkbox.checked = optionDefaults[index] === true;

          const label = document.createElement("label");
          label.htmlFor = `option-${index}`;
          label.textContent = option;

          optionDiv.appendChild(checkbox);
          optionDiv.appendChild(label);
          if (checkbox.checked) {
            optionDiv.classList.add("selected");
          }
          optionsContainer.appendChild(optionDiv);
        }

        optionsContainer.style.display = "block";
        separator.style.display = "block";
      }
    }
  } catch (error) {
    console.error("Config load failed:", error);
    showStatus(t("status.loadFailed"), "error");
    throw error; // 重新抛出错误，让调用者知道加载失败
  }
}

function setElementDisplayById(id, display) {
  const element = document.getElementById(id);
  if (!element) {
    console.warn(`Page state update skipped: #${id} not in DOM`);
    return false;
  }
  element.style.display = display;
  return true;
}

// 显示无内容页面
function showNoContentPage() {
  setElementDisplayById("content-container", "none");
  setElementDisplayById("no-content-container", "flex");

  // 添加无内容模式的CSS类，启用特殊布局
  document.body.classList.add("no-content-mode");

  // 隐藏任务标签栏（无内容时不需要显示）
  const taskTabsContainer = document.getElementById("task-tabs-container");
  if (taskTabsContainer) {
    taskTabsContainer.classList.add("hidden");
  }

  // 显示关闭按钮，让用户可以关闭服务
  if (config) {
    setElementDisplayById("no-content-buttons", "block");
  }
}

// 显示内容页面
function showContentPage() {
  setElementDisplayById("content-container", "block");
  setElementDisplayById("no-content-container", "none");

  // 移除无内容模式的CSS类，恢复正常布局
  document.body.classList.remove("no-content-mode");

  // 任务标签栏的显示由 multi_task.js 的 renderTaskTabs() 控制
  // 这里不需要手动显示，等待 renderTaskTabs() 根据任务数量决定

  enableSubmitButton();
}

// R229 / R234 / Cycle 13-14: 全部 3 个元素 (submit-btn, insert-code-btn,
// feedback-text) 的禁用视觉降级统一下沉到 CSS :disabled。
//
// R229 修了 #submit-btn / #insert-code-btn——它们的启用规则用了
// !important，inline non-important 永远输，所以加 CSS :disabled 接管。
// 当时 feedback-text 没改是因为它的 CSS 没用 !important, inline 真能生效,
// 但走 inline 的代价是: 两套 hex 配色全是 dark-theme 值
// (#2c2c2e / #8e8e93 / rgba(255,255,255,0.03) / #f5f5f7), 浅色主题切到时
// textarea 的禁用视觉是错的 (深色背景显示在浅色页面上, 字体颜色对比度反
// 转)。R234 把 textarea 也下沉到 CSS, 浅+深两套主题正确, 同时这里 JS 只
// 剩 disabled 属性切换, 三个元素同模式同纪律。
function disableSubmitButton() {
  const submitBtn = document.getElementById("submit-btn");
  const insertBtn = document.getElementById("insert-code-btn");
  const feedbackText = document.getElementById("feedback-text");

  if (submitBtn) submitBtn.disabled = true;
  if (insertBtn) insertBtn.disabled = true;
  if (feedbackText) feedbackText.disabled = true;
}

function enableSubmitButton() {
  const submitBtn = document.getElementById("submit-btn");
  const insertBtn = document.getElementById("insert-code-btn");
  const feedbackText = document.getElementById("feedback-text");

  if (submitBtn) submitBtn.disabled = false;
  if (insertBtn) insertBtn.disabled = false;
  if (feedbackText) feedbackText.disabled = false;
}

// 显示状态消息
//
// R214 / Cycle 10 · F-notif-fallback-1: type 'warning' 也走 content-page
// toast，否则 notification-manager 的 showFallbackNotification (R214 后
// 用 'warning' 类型) 在 content page 上完全 silent —— 用户看不到任何视
// 觉反馈，浏览器拒绝通知权限时只能 console.debug。修前: 仅 'success' /
// 'error' 在 content page 可见; 修后: 'success' / 'warning' / 'error'
// 都可见 ('info' 仍 silent 以维持 R214 之前的 INFO 噪声水位)。
const _statusDismissTimers = Object.create(null);
const _statusDismissGenerations = Object.create(null);

function _clearStatusDismissTimer(statusElementId) {
  const timerId = _statusDismissTimers[statusElementId];
  if (timerId !== undefined && timerId !== null) {
    clearTimeout(timerId);
    _statusDismissTimers[statusElementId] = null;
  }
}

function showStatus(message, type) {
  const noContentContainer = document.getElementById("no-content-container");
  const isNoContentPage =
    noContentContainer && noContentContainer.style.display === "flex";

  if (!isNoContentPage && type !== "error") {
    // R214: success / warning 走 toast (warning 是降级通知的合理 level);
    // info 维持 silent (大量内部状态变化用 info，不该到处 toast)。
    if (type === "success" || type === "warning") {
      _showToast(message);
    }
    return;
  }

  const statusElementId = isNoContentPage
    ? "no-content-status-message"
    : "status-message";
  const statusElement = document.getElementById(statusElementId);

  if (!statusElement) return;

  _clearStatusDismissTimer(statusElementId);
  const statusGeneration =
    (_statusDismissGenerations[statusElementId] || 0) + 1;
  _statusDismissGenerations[statusElementId] = statusGeneration;

  statusElement.textContent = message;
  statusElement.className = `status-message status-${type}`;
  statusElement.style.display = "block";

  // R214: warning 自动消失 5s (介于 success 3s 与 error 10s 之间)。
  const autoDismissMs =
    type === "success"
      ? 3000
      : type === "warning"
        ? 5000
        : type === "error"
          ? 10000
          : 0;
  if (autoDismissMs > 0) {
    const dismissTimerId = setTimeout(() => {
      if (
        _statusDismissGenerations[statusElementId] !== statusGeneration ||
        _statusDismissTimers[statusElementId] !== dismissTimerId
      ) {
        return;
      }
      statusElement.style.display = "none";
      _statusDismissTimers[statusElementId] = null;
      _statusDismissGenerations[statusElementId] = statusGeneration + 1;
    }, autoDismissMs);
    _statusDismissTimers[statusElementId] = dismissTimerId;
  }
}

function _scheduleNextFrame(callback) {
  if (typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(callback);
    return;
  }
  setTimeout(callback, 16);
}

function _removeElement(element) {
  if (!element) return;
  if (typeof element.remove === "function") {
    element.remove();
    return;
  }
  if (element.parentNode) {
    element.parentNode.removeChild(element);
  }
}

let _toastHideTimerId = null;
let _toastGeneration = 0;

function _showToast(message) {
  let toast = document.getElementById("_aiia-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "_aiia-toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    Object.assign(toast.style, {
      position: "fixed",
      top: "1rem",
      left: "50%",
      transform: "translateX(-50%) translateY(-120%)",
      padding: "0.6rem 1.2rem",
      borderRadius: "10px",
      fontSize: "0.9rem",
      fontWeight: "500",
      color: "var(--text-primary)",
      background: "var(--bg-tertiary)",
      boxShadow: "0 4px 16px var(--shadow-color)",
      border: "1px solid var(--border-color)",
      zIndex: "9999",
      transition: "transform 0.3s ease, opacity 0.3s ease",
      opacity: "0",
      pointerEvents: "none",
      whiteSpace: "nowrap",
    });
    document.body.appendChild(toast);
  }
  if (_toastHideTimerId !== null) {
    clearTimeout(_toastHideTimerId);
    _toastHideTimerId = null;
  }

  const toastGeneration = (_toastGeneration += 1);
  let hideTimerId = null;
  toast.textContent = message;
  _scheduleNextFrame(() => {
    if (toastGeneration !== _toastGeneration || _toastHideTimerId !== hideTimerId) {
      return;
    }
    toast.style.transform = "translateX(-50%) translateY(0)";
    toast.style.opacity = "1";
  });
  hideTimerId = setTimeout(() => {
    if (toastGeneration !== _toastGeneration || _toastHideTimerId !== hideTimerId) {
      return;
    }
    toast.style.transform = "translateX(-50%) translateY(-120%)";
    toast.style.opacity = "0";
    _toastHideTimerId = null;
    _toastGeneration += 1;
  }, 1800);
  _toastHideTimerId = hideTimerId;
}

// 插入代码功能 - 与GUI版本逻辑完全一致
async function insertCodeFromClipboard() {
  // iOS/Safari/HTTP 等环境可能无法使用 navigator.clipboard.readText()
  // 因此这里采用“优先读取剪贴板 -> 失败则弹出粘贴输入框”的策略
  let finished = false;
  let fallbackTimer = null;

  const finish = () => {
    finished = true;
    if (fallbackTimer) {
      clearTimeout(fallbackTimer);
      fallbackTimer = null;
    }
  };

  fallbackTimer = setTimeout(() => {
    if (finished) return;
    finish();
    openCodePasteModal(new Error("ClipboardReadTimeout"));
  }, 1500);

  try {
    if (
      !navigator.clipboard ||
      typeof navigator.clipboard.readText !== "function"
    ) {
      finish();
      openCodePasteModal();
      return;
    }

    const text = await navigator.clipboard.readText();
    if (finished) return;
    finish();

    if (!text || !text.trim()) {
      openCodePasteModal(new Error("ClipboardEmpty"));
      return;
    }

    insertCodeBlockIntoFeedbackTextarea(text);
    showStatus(t("status.codeInserted"), "success");
  } catch (error) {
    if (finished) return;
    finish();
    console.error("Clipboard read failed:", error);
    openCodePasteModal(error);
  }
}

function buildMarkdownCodeFence(text, lang = "") {
  const normalizedText = String(text || "").replace(/\r\n?/g, "\n");
  if (!normalizedText.trim()) return null;

  const backtickRuns = normalizedText.match(/`+/g) || [];
  let longestRun = 0;
  const backtickRunCount = backtickRuns.length;
  for (let index = 0; index < backtickRunCount; index += 1) {
    if (!(index in backtickRuns)) continue;
    const runLength = backtickRuns[index].length;
    if (runLength > longestRun) longestRun = runLength;
  }
  const fence = "`".repeat(Math.max(3, longestRun + 1));
  const fenceHead = lang ? `${fence}${lang}` : fence;
  const codeBody = normalizedText.endsWith("\n")
    ? normalizedText
    : `${normalizedText}\n`;

  return `${fenceHead}\n${codeBody}${fence}\n`;
}

function insertCodeBlockIntoFeedbackTextarea(text) {
  const textarea = document.getElementById("feedback-text");
  if (!textarea) return;

  const codeBlockBody = buildMarkdownCodeFence(text);
  if (!codeBlockBody) return;

  const cursorPos = textarea.selectionStart || 0;
  const currentText = textarea.value || "";
  const textBefore = currentText.substring(0, cursorPos);
  const textAfter = currentText.substring(cursorPos);
  const needsLeadingNewline = cursorPos > 0 && !textBefore.endsWith("\n");
  const needsTrailingNewline =
    textAfter.length > 0 && !textAfter.startsWith("\n");
  const codeBlock = `${needsLeadingNewline ? "\n" : ""}${codeBlockBody}${needsTrailingNewline ? "\n" : ""}`;

  // 插入代码块
  textarea.value = textBefore + codeBlock + textAfter;

  // 将光标移动到代码块末尾（与GUI版本一致）
  const newCursorPos = textBefore.length + codeBlock.length;
  textarea.setSelectionRange(newCursorPos, newCursorPos);
  textarea.focus();
}

function getClipboardFailureHint(error) {
  // 针对常见失败原因给出更明确的提示（尤其是 iOS/HTTP/权限）
  try {
    if (!window.isSecureContext) {
      return t("status.clipboardHttp");
    }

    const name = error && error.name ? String(error.name) : "";
    if (name === "NotAllowedError") {
      return t("status.clipboardDenied");
    }
    if (name === "NotFoundError") {
      return t("status.clipboardEmpty");
    }
    if (name === "Error" && error && error.message === "ClipboardReadTimeout") {
      return t("status.clipboardTimeout");
    }
    if (name === "Error" && error && error.message === "ClipboardEmpty") {
      return t("status.clipboardNoText");
    }
  } catch (e) {
    // 忽略：解析失败时走兜底提示文案
  }
  return t("status.clipboardDefault");
}

// cycle-22 / cr51 follow-up #1：与 image-modal R263a / settings-panel 同套
// capture-activeElement 模式 — 模态打开前 snapshot 真正触发它的元素，
// 关闭时回归。比 hardcode 回 ``#feedback-text`` 更鲁棒的场景：
//   1. 用户从 quick-phrases 面板 paste 触发剪贴板降级，关闭后焦点应回
//      到 quick-phrases 按钮，而非跳走打断 quick-phrases 流；
//   2. 多 task tab 场景下 ``#feedback-text`` 可能并非当前 active task 的
//      textarea（旧 hardcode 会跳到 cached 的第一个 textarea ID）；
//   3. ``#feedback-text`` 元素本身可能在 SSE 重渲染后被替换，``getElementById``
//      返回旧引用 → focus 失败 silent fail。
// 仍保留 fallback 到 ``#feedback-text``，对齐升级前的语义。
let _codePasteModalPreviouslyFocusedElement = null;
let _codePasteModalKeydownWired = false;
let _codePasteModalFocusTimerId = null;
let _codePasteModalFocusGeneration = 0;

function _isCodePasteModalOpen(panel) {
  return !!(
    panel &&
    panel.classList &&
    typeof panel.classList.contains === "function" &&
    panel.classList.contains("show")
  );
}

function installCodePasteModalKeydownHandler() {
  if (_codePasteModalKeydownWired) return;
  document.addEventListener("keydown", handleCodePasteModalKeydown);
  _codePasteModalKeydownWired = true;
}

function removeCodePasteModalKeydownHandler() {
  if (!_codePasteModalKeydownWired) return;
  document.removeEventListener("keydown", handleCodePasteModalKeydown);
  _codePasteModalKeydownWired = false;
}

function clearCodePasteModalFocusTimer() {
  _codePasteModalFocusGeneration += 1;
  if (_codePasteModalFocusTimerId === null) return;
  try {
    clearTimeout(_codePasteModalFocusTimerId);
  } catch (_e) {
    // 忽略：受限宿主下 clearTimeout 可能不可用
  }
  _codePasteModalFocusTimerId = null;
}

function focusCodePasteModalTextarea(textarea, panel) {
  if (!textarea || typeof textarea.focus !== "function") return false;
  if (!_isCodePasteModalOpen(panel)) return false;

  try {
    if (
      typeof document.contains === "function" &&
      (!document.contains(panel) || !document.contains(textarea))
    ) {
      return false;
    }
    if (typeof panel.contains === "function" && !panel.contains(textarea)) {
      return false;
    }
  } catch (_e) {
    return false;
  }

  try {
    textarea.focus({ preventScroll: true });
    return true;
  } catch (_e) {
    try {
      textarea.focus();
      return true;
    } catch (_e2) {
      return false;
    }
  }
}

function focusCodePasteModalRestoreTarget(element) {
  if (!element || typeof element.focus !== "function") return false;
  try {
    element.focus({ preventScroll: true });
    return true;
  } catch (_e) {
    try {
      element.focus();
      return true;
    } catch (_e2) {
      return false;
    }
  }
}

function scheduleCodePasteModalTextareaFocus(textarea, panel) {
  clearCodePasteModalFocusTimer();
  const focusGeneration = _codePasteModalFocusGeneration + 1;
  _codePasteModalFocusGeneration = focusGeneration;
  let focusTimerId = null;
  focusTimerId = setTimeout(() => {
    if (
      focusGeneration !== _codePasteModalFocusGeneration ||
      focusTimerId !== _codePasteModalFocusTimerId
    ) {
      return;
    }
    _codePasteModalFocusTimerId = null;
    focusCodePasteModalTextarea(textarea, panel);
  }, 0);
  _codePasteModalFocusTimerId = focusTimerId;
}

function openCodePasteModal(error) {
  const panel = document.getElementById("code-paste-panel");
  const textarea = document.getElementById("code-paste-textarea");
  const hint = document.getElementById("code-paste-hint");

  if (!panel || !textarea) {
    showStatus(t("status.clipboardFailed"), "error");
    return;
  }

  const wasAlreadyOpen = _isCodePasteModalOpen(panel);
  if (!wasAlreadyOpen) {
    _codePasteModalPreviouslyFocusedElement = document.activeElement;
  }

  if (hint) {
    hint.textContent = getClipboardFailureHint(error);
  }

  textarea.value = "";
  panel.classList.remove("hidden");
  panel.classList.add("show");

  _setContainerSiblingsInert(panel, true);

  // iOS 上需要在用户手势链路内尽快 focus，才能弹出键盘与“粘贴”菜单
  scheduleCodePasteModalTextareaFocus(textarea, panel);

  // ESC 关闭（对齐图片模态框行为）
  installCodePasteModalKeydownHandler();
}

function closeCodePasteModal() {
  const panel = document.getElementById("code-paste-panel");
  const textarea = document.getElementById("code-paste-textarea");
  clearCodePasteModalFocusTimer();
  if (!panel) {
    removeCodePasteModalKeydownHandler();
    _codePasteModalPreviouslyFocusedElement = null;
    return;
  }

  panel.classList.remove("show");
  panel.classList.add("hidden");

  _setContainerSiblingsInert(panel, false);

  if (textarea) {
    textarea.value = "";
  }

  removeCodePasteModalKeydownHandler();

  const prev = _codePasteModalPreviouslyFocusedElement;
  _codePasteModalPreviouslyFocusedElement = null;
  if (prev && document.contains(prev) && focusCodePasteModalRestoreTarget(prev)) {
    return;
  }
  const feedbackTextarea = document.getElementById("feedback-text");
  focusCodePasteModalRestoreTarget(feedbackTextarea);
}

/**
 * R244 / Cycle 16 · F-cycle16-modal-self-inert: open dialogs live INSIDE
 * `.container` (HTML L713 + L976), so the naive R240 implementation
 * (which set inert on the container itself) propagated inert to the
 * dialog and silently broke modal interaction — clicks/focus inside the
 * dialog were blocked because the dialog inherited the parent's inert
 * state from the DOM cascade. The bug was undetected for 4 cycles
 * because R240's test was Pattern B (static grep), not Pattern A
 * (runtime DOM behavior).
 *
 * Correct pattern: iterate `.container > *`, set `inert` on every direct
 * child EXCEPT the open dialog. The dialog stays interactive; everything
 * else in `.container` (header, main content, footer, image-modal, the
 * other dialog) becomes inert. The .container itself is NOT inert, so
 * inert does NOT propagate through it to the open dialog's subtree.
 *
 * This matches the recommended HTML5 modal pattern for non-`<dialog>`
 * implementations: https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Global_attributes/inert
 *
 * @param {HTMLElement} openModalEl - the dialog that should stay interactive
 * @param {boolean} value - true to inert siblings, false to clear
 */
function _setContainerSiblingsInert(openModalEl, value) {
  const container = document.querySelector(".container");
  if (!container) return;
  for (const child of container.children) {
    if (child === openModalEl) continue;
    _safelySetInert(child, value);
  }
}

function _safelySetInert(el, value) {
  if (!el) return;
  try {
    el.inert = value;
  } catch (_e) {
    if (value) {
      el.setAttribute("inert", "");
    } else {
      el.removeAttribute("inert");
    }
  }
}

function _modalFocusTrap(panel, event) {
  if (event.key !== "Tab" || !panel) return;
  const focusables = panel.querySelectorAll(
    'button:not([disabled]),[href],input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
  );
  let first = null;
  let last = null;
  const focusableCount =
    focusables && Number.isFinite(focusables.length) ? focusables.length : 0;
  for (let i = 0; i < focusableCount; i += 1) {
    const el = focusables[i];
    if (!el || el.offsetParent === null || el.hasAttribute("aria-hidden")) {
      continue;
    }
    if (!first) first = el;
    last = el;
  }
  if (!first || !last) return;
  const active = document.activeElement;
  if (event.shiftKey && active === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

function handleCodePasteModalKeydown(event) {
  if (event.key === "Escape") {
    closeCodePasteModal();
    return;
  }
  const panel = document.getElementById("code-paste-panel");
  _modalFocusTrap(panel, event);
}

// 首次加载时缓存 submit 按钮的原始 innerHTML（含 SVG + data-i18n span），
// 之后 finally 用它还原，避免 innerHTML 里硬编码中文（i18n / CI gate 要求）。
let SUBMIT_BTN_ORIGINAL_HTML = null;

function captureSubmitBtnOriginalHTML() {
  if (SUBMIT_BTN_ORIGINAL_HTML !== null) return;
  const btn = document.getElementById("submit-btn");
  if (btn) SUBMIT_BTN_ORIGINAL_HTML = btn.innerHTML;
}

function isSubmitTargetStillCurrent(taskId) {
  if (!taskId) return !window.activeTaskId;
  return window.activeTaskId === taskId;
}

function clearSubmittedTaskLocalState(taskId) {
  if (!taskId) return;
  if (typeof taskTextareaContents !== "undefined") {
    delete taskTextareaContents[taskId];
  }
  if (typeof taskOptionsStates !== "undefined") {
    delete taskOptionsStates[taskId];
  }
  if (typeof taskImages !== "undefined") {
    delete taskImages[taskId];
  }
}

// R289 / cycle-27: 错误消息精细化。把 fetch + DOM 操作的 catch error 分类
// 成 5 个 i18n key，让用户看到"该重试 / 该刷新 / 该联系运维"而非笼统的
// "网络错误"。
//
// 分类规则按 error.name + error.message 字符串特征：
//   - AbortError                       → 请求超时（fetchWithTimeout AbortSignal）
//   - TypeError "Failed to fetch"      → 网络不可达（CORS / DNS / offline）
//   - SyntaxError                      → JSON 解析失败（5xx 返回 HTML / 服务器异常）
//   - TypeError (其他)                  → DOM 访问异常 (stale ref 等)
//   - 其他                              → 通用 networkError 兜底
//
// 通过 ``window._classifyFetchError`` 暴露，让 multi_task.js / settings-manager.js
// 等其他模块也能复用同一套分类逻辑，避免 "网络错误" 重新散落到全代码库。
function _classifyFetchError(error) {
  if (!error) return "status.networkError";
  const name = error.name || "";
  const msg = String(error.message || "").toLowerCase();
  if (name === "AbortError") {
    return "status.requestTimeout";
  }
  if (
    name === "TypeError" &&
    (msg.includes("failed to fetch") ||
      msg.includes("networkerror") ||
      msg.includes("load failed"))
  ) {
    return "status.networkOffline";
  }
  if (name === "SyntaxError") {
    return "status.serverResponseInvalid";
  }
  if (name === "TypeError") {
    return "status.uiRenderingError";
  }
  return "status.networkError";
}
window._classifyFetchError = _classifyFetchError;

// R294 / cycle-28: HTTP response-level 分类 helper（补 R289 _classifyFetchError
// 不覆盖的 response.ok==false 分支）。fetch() 默认 4xx/5xx 不抛 → 当前
// "else { showStatus(result.message || t(status.submitFailed)) }" 把所有 HTTP
// 错误都笼统显示后端 error 字段，但：
//   - 401/403：用户应"重新登录"，不是看后端 message
//   - 5xx (502/503/504)：用户应"稍后重试"，不该看到栈跟踪
//   - 其他：保留后端 message 给上下文
//
// _classifyHttpResponse(response, defaultMsg) 返回:
//   - null  → 调用方按既有逻辑（一般是显示 backend message + defaultMsg 兜底）
//   - 字符串 → i18n key (e.g. "status.unauthorized")
//
// 调用方典型用法:
//   const key = _classifyHttpResponse(response);
//   if (key) showStatus(t(key), "error");
//   else showStatus(result.message || t("status.submitFailed"), "error");
function _classifyHttpResponse(response) {
  if (!response || typeof response.status !== "number") return null;
  const status = response.status;
  if (status === 401 || status === 403) {
    return "status.unauthorized";
  }
  // R301 / cycle-30: 5xx 子分类 — 给 502/503/504 三类常见 reverse-proxy
  // 错误码各自专属 i18n key,因为它们的语义和 user action 都不同：
  //   - 502 (Bad Gateway): nginx/反代收到上游异常响应,通常上游 crash/启动中
  //   - 503 (Service Unavailable): 上游主动返回 unavailable,通常 overload/maintenance
  //   - 504 (Gateway Timeout): 上游处理超时,通常上游 hang/slow query
  //   - 500/501/505+: fallback 到通用 status.serviceUnavailable
  // 给用户一个可执行的暗示("稍后重试" vs "联系运维"),而不是看 backend stack trace。
  if (status === 502) {
    return "status.badGateway";
  }
  if (status === 503) {
    return "status.serviceOverloaded";
  }
  if (status === 504) {
    return "status.gatewayTimeout";
  }
  if (status >= 500 && status < 600) {
    return "status.serviceUnavailable";
  }
  return null;
}
window._classifyHttpResponse = _classifyHttpResponse;

// 提交反馈
async function submitFeedback() {
  captureSubmitBtnOriginalHTML();
  let submitTargetTaskId = null;
  // R280 / cycle-25 entry-side null guard (R268/R279 同 class)：submitFeedback
  // 可由 Ctrl/Cmd+Enter 键盘快捷键触发（line 1527 keyboard handler），即使
  // submit-btn DOM 不在视图（任务切换动画中 / 新 SSE 推送替换了页面）。
  // 旧实现直接 ``getElementById("feedback-text").value.trim()`` 会抛
  // ``TypeError: Cannot read properties of null (reading 'value')``，被 catch
  // 翻译成 user-visible "网络错误"——**误导用户排查网络问题，实际是 DOM
  // stale**。R280 修复：feedback-text 不在 DOM → 视作"用户当前不在反馈视图"
  // 早返回，不污染网络错误 toast；feedback-text 在 DOM 但 trim() 失败属于
  // 字段实际问题，让原 catch 处理。
  const feedbackTextEl = document.getElementById("feedback-text");
  if (!feedbackTextEl) {
    console.warn(
      "submitFeedback: feedback-text not in DOM (likely keyboard shortcut " +
        "triggered during task switch / SSE replace) — silently aborting",
    );
    return;
  }
  const feedbackText = feedbackTextEl.value.trim();
  const selectedOptions = [];

  // 【修复】直接从 DOM 获取选中的预定义选项
  // 不再依赖 config.predefined_options，因为在多任务模式下切换任务时 config 可能未同步更新
  const optionsContainer = document.getElementById("options-container");
  if (optionsContainer) {
    const checkboxes = optionsContainer.querySelectorAll(
      'input[type="checkbox"]:checked',
    );
    const checkboxCount =
      checkboxes && Number.isFinite(checkboxes.length) ? checkboxes.length : 0;
    for (let checkboxIndex = 0; checkboxIndex < checkboxCount; checkboxIndex += 1) {
      const checkbox = checkboxes[checkboxIndex];
      if (!checkbox) continue;
      // 使用 checkbox 的 value 属性获取选项文本
      if (checkbox.value) {
        selectedOptions.push(checkbox.value);
      }
    }
  }

  if (
    !feedbackText &&
    selectedOptions.length === 0 &&
    selectedImages.length === 0
  ) {
    // 如果没有任何输入，显示错误信息
    showStatus(t("status.submitEmpty"), "error");
    return;
  }

  try {
    // R280 / cycle-25: submit-btn 也可能在 entry 时 stale (Ctrl+Enter 键盘
    // 触发 + 任务切换并发场景)。null check 兜底——不存在时仍继续 fetch (
    // 反馈不能因为 UI loading state 缺失就丢失)，UI loading state 是
    // best-effort，silently 跳过即可。
    const submitBtn = document.getElementById("submit-btn");
    if (submitBtn) {
      submitBtn.disabled = true;
      // AIIA-XSS-SAFE: t('status.submitting') 是静态 key 且无参数，不携带用户可控数据。
      submitBtn.innerHTML = t("status.submitting");
    }

    // 使用 FormData 上传文件，避免 base64 编码
    const formData = new FormData();
    formData.append("feedback_text", feedbackText);
    formData.append("selected_options", JSON.stringify(selectedOptions));

    // 添加图片文件（直接使用原始文件，不需要base64）
    const selectedImageCount =
      selectedImages && Number.isFinite(selectedImages.length)
        ? selectedImages.length
        : 0;
    for (let imageIndex = 0; imageIndex < selectedImageCount; imageIndex += 1) {
      if (!(imageIndex in selectedImages)) continue;
      const img = selectedImages[imageIndex];
      if (img.file) {
        formData.append(`image_${imageIndex}`, img.file);
      }
    }

    // 获取当前活动任务ID（由 multi_task.js 管理）
    submitTargetTaskId = window.activeTaskId;

    // 优先使用多任务提交端点（如果有活动任务）
    const submitUrl = submitTargetTaskId
      ? `/api/tasks/${submitTargetTaskId}/submit`
      : "/api/submit";
    console.debug(`Using submit endpoint: ${submitUrl}`);

    const response = await fetchWithTimeout(
      submitUrl,
      {
        method: "POST",
        body: formData,
      },
      30000,
    );

    const result = await response.json();

    if (response.ok) {
      showStatus(result.message, "success");

      // 反馈提交成功，不需要通知（用户要求）

      if (isSubmitTargetStillCurrent(submitTargetTaskId)) {
        // R280 / cycle-25: 清空表单。await 期间 DOM 可能被 multi-task 切换
        // 替换，再 ``getElementById("feedback-text").value = ""`` 会抛
        // TypeError 污染 success path。null check 兜底——DOM 已切走时无需
        // 清空（新视图自己负责状态）。
        const fbTextEl = document.getElementById("feedback-text");
        if (fbTextEl) {
          fbTextEl.value = "";
        }
        const allCheckboxes = document.querySelectorAll('input[type="checkbox"]');
        const allCheckboxCount =
          allCheckboxes && Number.isFinite(allCheckboxes.length)
            ? allCheckboxes.length
            : 0;
        for (
          let checkboxIndex = 0;
          checkboxIndex < allCheckboxCount;
          checkboxIndex += 1
        ) {
          const checkbox = allCheckboxes[checkboxIndex];
          if (checkbox) {
            checkbox.checked = false;
          }
        }
        clearAllImages();
      } else {
        console.debug(
          "submitFeedback: submitted task changed before success cleanup; " +
            "preserving current form state",
        );
      }

      // 清理该任务的缓存（如果是多任务模式）
      clearSubmittedTaskLocalState(submitTargetTaskId);

      // 立即刷新任务列表（由 multi_task.js 处理页面状态切换）
      if (typeof refreshTasksList === "function") {
        console.debug("Invoking refreshTasksList to refresh task list...");
        await refreshTasksList();
      } else {
        // 兼容旧模式：如果没有多任务支持，显示无内容页面
        if (config) {
          config.has_content = false;
          console.debug("Feedback submitted; local state updated to empty");
        }
        showNoContentPage();
      }
    } else {
      // R294 / cycle-28: HTTP 4xx/5xx 不进 catch (fetch 默认不 throw)。
      // 优先按 status 分类 (401/403 → unauthorized, 5xx → serviceUnavailable)，
      // 回退到 backend message + submitFailed 兜底。
      const httpKey = _classifyHttpResponse(response);
      if (httpKey) {
        showStatus(t(httpKey), "error");
      } else {
        showStatus(result.message || t("status.submitFailed"), "error");
      }
    }
  } catch (error) {
    console.error("Submit failed:", error);
    // R289 / cycle-27: 通用 "网络错误" 在 stale DOM / 5xx / timeout / response
    // parse 失败等场景都会被显示，误导用户重试网络。改为按 error.name
    // 分类成更具体的 i18n key，让用户知道是该重试、该刷新、还是该联系运维。
    showStatus(t(_classifyFetchError(error)), "error");
  } finally {
    // R268 / cycle-22 fix: submit 期间任务可能 auto-resubmit timeout →
    // showNoContentPage 把 #submit-btn 从 DOM 移除；或 SSE 重渲染替换
    // 节点 → 旧 getElementById 引用作废。原实现 `submitBtn.disabled =
    // false` 不做 null check，submit-btn 不存在时抛 TypeError 污染
    // finally 块，吞掉原 error 信息（catch 块 console.error 已记录但
    // finally 抛错会覆盖 user-visible status.networkError toast）。
    //
    // 修复：null check 兜底 — submit-btn 已经不在 DOM 时（用户已被切
    // 走 / 任务已 timeout），UI 状态无需 reset，silently 跳过 finally
    // body 即可。
    const submitBtn = document.getElementById("submit-btn");
    if (submitBtn) {
      // R700 修复：提交按钮是跨任务共享的单例 DOM。旧实现仅在
      // isSubmitTargetStillCurrent 时才还原——如果 await 期间发生了
      // 任务切换（提交成功后自动激活下一个任务是常态路径！），守卫
      // 判 false，按钮就永远停留在「提交中…」+ disabled 状态，表现为
      // "提交按钮一直错误显示提交中"。共享按钮的还原对任何任务都
      // 安全（新任务视图本来就需要一个可用的提交按钮），故无条件还原。
      submitBtn.disabled = false;
      // 还原为首次渲染时的 innerHTML（含 SVG + <span data-i18n>），然后重新翻译。
      if (SUBMIT_BTN_ORIGINAL_HTML !== null) {
        submitBtn.innerHTML = SUBMIT_BTN_ORIGINAL_HTML;
        if (
          window.AIIA_I18N &&
          typeof window.AIIA_I18N.translateDOM === "function"
        ) {
          window.AIIA_I18N.translateDOM(submitBtn);
        }
      }
    }
  }
}

// 关闭界面 - 简化版本，统一刷新逻辑
async function closeInterface() {
  try {
    showStatus(t("status.closingWebUI"), "info");

    // 停止轮询
    stopContentPolling();

    const response = await fetchWithTimeout(
      "/api/close",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      },
      10000,
    );

    const result = await response.json();
    if (response.ok) {
      showStatus(t("status.closedRefreshing"), "success");
    } else {
      showStatus(t("status.closeFailed"), "error");
    }
  } catch (error) {
    console.error("Close UI failed:", error);
    showStatus(t("status.closeUIFailed"), "error");
  }

  // 无论成功还是失败，都在2秒后刷新页面
  setTimeout(() => {
    refreshPageSafely();
  }, 2000);
}

// 安全刷新页面函数
function refreshPageSafely() {
  console.debug("Reloading page…");
  try {
    window.location.reload();
  } catch (reloadError) {
    console.error("Page reload failed:", reloadError);
    // 如果刷新失败，尝试跳转到根路径
    try {
      window.location.href = window.location.origin;
    } catch (redirectError) {
      console.error("Page redirect failed:", redirectError);
      // 最后的备选方案：跳转到空白页
      try {
        window.location.href = "about:blank";
      } catch (blankError) {
        console.error("All page navigation failed:", blankError);
      }
    }
  }
}

// R129：``stopContentPolling`` 是历史遗留 API 的"安全空实现"——
//   - 内容轮询已迁移到 ``multi_task.js`` 的任务轮询；
//   - ``closeInterface()`` 仍然在调用本函数，删除会引入 ReferenceError。
//
// 因此保留 no-op 函数本体作为"调用合约稳定层"，但把
// pre-R129 的两段超长 banner 注释（"内容轮询-已停用"+"updatePageContent
// 已删除"）合并成这条 5 行说明，避免 30+ 行的"墓碑"持续干扰阅读。
function stopContentPolling() {
  console.debug("[app.js] stopContentPolling called, but polling is disabled");
}

// NotificationManager 已拆分到 notification-manager.js
// 全局实例 notificationManager 由该文件创建

// SettingsManager 已拆分到 settings-manager.js
// 全局实例 settingsManager 由该文件创建

// ========== 图片处理功能已拆分到 image-upload.js ==========
// 全局函数及变量由该文件创建，包括：
//   selectedImages, initializeImageFeatures(), startPeriodicCleanup(),
//   clearAllImages(), removeImage(), openImageModal(), handleFileUpload() 等

// 移动设备检测
function isMobileDevice() {
  return (
    /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
      navigator.userAgent,
    ) ||
    (navigator.maxTouchPoints &&
      navigator.maxTouchPoints > 2 &&
      /MacIntel/.test(navigator.platform))
  );
}

// 平台检测和快捷键设置
function detectPlatform() {
  const platform = navigator.platform.toLowerCase();
  const userAgent = navigator.userAgent.toLowerCase();

  if (platform.includes("mac") || userAgent.includes("mac")) {
    return "mac";
  } else if (platform.includes("win") || userAgent.includes("win")) {
    return "windows";
  } else if (platform.includes("linux") || userAgent.includes("linux")) {
    return "linux";
  }
  return "windows"; // 默认为Windows
}

function getShortcutText(platform) {
  // 从 i18n 表里复用 settings.shortcut*，去掉结尾的冒号后拼装。
  const strip = (s) => String(s).replace(/[:：]\s*$/, "");
  const submit = strip(t("settings.shortcutSubmit"));
  const insertCode = strip(t("settings.shortcutInsertCode"));
  const pasteImage = strip(t("settings.shortcutPasteImage"));
  const uploadImage = strip(t("settings.shortcutUploadImage"));
  const clearImage = strip(t("settings.shortcutClearImage"));

  const lines =
    platform === "mac"
      ? [
          `⌘+Enter  ${submit}`,
          `⌥+C      ${insertCode}`,
          `⌘+V      ${pasteImage}`,
          `⌘+U      ${uploadImage}`,
          `Delete   ${clearImage}`,
        ]
      : [
          `Ctrl+Enter ${submit}`,
          `Alt+C      ${insertCode}`,
          `Ctrl+V     ${pasteImage}`,
          `Ctrl+U     ${uploadImage}`,
          `Delete     ${clearImage}`,
        ];
  return lines.join("\n");
}

function initializeShortcutTooltip() {
  // 桌面设备显示快捷键信息
  if (!isMobileDevice()) {
    const platform = detectPlatform();
    updateShortcutDisplay(platform);
    console.debug(
      `Desktop platform detected: ${platform}, shortcut hints applied`,
    );
  } else {
    console.debug("Mobile device detected, shortcut hints hidden");
  }
}

function setShortcutText(id, shortcut) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = shortcut;
  }
}

function updateShortcutDisplay(platform) {
  const isMac = platform === "mac";
  const ctrlOrCmd = isMac ? "Cmd" : "Ctrl";
  const altOrOption = isMac ? "Option" : "Alt";

  setShortcutText("shortcut-submit", `${ctrlOrCmd}+Enter`);
  setShortcutText("shortcut-code", `${altOrOption}+C`);
  setShortcutText("shortcut-paste", `${ctrlOrCmd}+V`);
  setShortcutText("shortcut-upload", `${ctrlOrCmd}+U`);
  setShortcutText("shortcut-delete", "Delete");
}

function _isElementEventWired(element, wireFlag) {
  if (!element || !wireFlag) return false;
  if (element.dataset) {
    return element.dataset[wireFlag] === "true";
  }
  return element[`__${wireFlag}`] === true;
}

function _markElementEventWired(element, wireFlag) {
  if (!element || !wireFlag) return;
  if (element.dataset) {
    element.dataset[wireFlag] = "true";
    return;
  }
  element[`__${wireFlag}`] = true;
}

function bindOptionalClick(id, handler, options) {
  const opts = options || {};
  const wireFlag = opts.wireFlag || "aiiaAppClickWired";
  const logMissing = opts.logMissing !== false;
  const element = document.getElementById(id);
  if (!element || typeof element.addEventListener !== "function") {
    if (logMissing) {
      console.debug(`App button binding skipped: #${id} unavailable`);
    }
    return false;
  }
  if (_isElementEventWired(element, wireFlag)) {
    return true;
  }

  element.addEventListener("click", handler);
  _markElementEventWired(element, wireFlag);
  return true;
}

function handleCodePasteInsertClick() {
  const textarea = document.getElementById("code-paste-textarea");
  const text = textarea ? textarea.value || "" : "";
  if (!text.trim()) {
    showStatus(t("status.enterCode"), "error");
    return false;
  }
  insertCodeBlockIntoFeedbackTextarea(text);
  closeCodePasteModal();
  return true;
}

function handleCodePasteBackdropClick(e) {
  const codePastePanel = document.getElementById("code-paste-panel");
  if (e.target === codePastePanel) {
    closeCodePasteModal();
  }
}

function bindCodePasteModalControls() {
  bindOptionalClick("code-paste-close-btn", closeCodePasteModal, {
    wireFlag: "aiiaCodePasteCloseClickWired",
    logMissing: false,
  });
  bindOptionalClick("code-paste-cancel-btn", closeCodePasteModal, {
    wireFlag: "aiiaCodePasteCancelClickWired",
    logMissing: false,
  });
  bindOptionalClick("code-paste-insert-btn", handleCodePasteInsertClick, {
    wireFlag: "aiiaCodePasteInsertClickWired",
    logMissing: false,
  });
  bindOptionalClick("code-paste-panel", handleCodePasteBackdropClick, {
    wireFlag: "aiiaCodePasteBackdropClickWired",
    logMissing: false,
  });
}

async function testNotification() {
  try {
    await notificationManager.sendNotification(
      t("status.testNotifyTitle"),
      t("status.testNotifyBody"),
      {
        tag: "test-notification",
        requireInteraction: false,
      },
    );
    showStatus(t("status.testNotifySent"), "success");
  } catch (error) {
    console.error("Test notification failed:", error);
    showStatus(t("status.testNotifyFailed"), "error");
  }
}

function handleGlobalKeydown(event) {
  const isMac = detectPlatform() === "mac";
  const ctrlOrCmd = isMac ? event.metaKey : event.ctrlKey;
  const altOrOption = isMac ? event.altKey : event.altKey;

  if (ctrlOrCmd && event.key === "Enter") {
    event.preventDefault();
    submitFeedback();
  } else if (altOrOption && event.key === "c") {
    event.preventDefault();
    insertCodeFromClipboard();
  } else if (ctrlOrCmd && event.key === "v") {
    // Ctrl/Cmd+V 粘贴图片 - 浏览器默认处理，我们只在paste事件中处理
    console.debug(`Shortcut: ${isMac ? "Cmd" : "Ctrl"}+V paste`);
  } else if (ctrlOrCmd && event.key === "u") {
    event.preventDefault();
    const uploadBtn = document.getElementById("upload-image-btn");
    if (uploadBtn && typeof uploadBtn.click === "function") {
      uploadBtn.click();
      console.debug(`Shortcut: ${isMac ? "Cmd" : "Ctrl"}+U upload image`);
    } else {
      console.debug("Shortcut upload skipped: upload button unavailable");
    }
  } else if (event.key === "Delete" && selectedImages.length > 0) {
    event.preventDefault();
    clearAllImages();
    console.debug("Shortcut: Delete clear all images");
  } else if (ctrlOrCmd && event.shiftKey && event.key === "N") {
    // Ctrl+Shift+N 测试通知
    event.preventDefault();
    testNotification();
    console.debug(
      `Shortcut: ${isMac ? "Cmd" : "Ctrl"}+Shift+N test notification`,
    );
  }
}

let _globalKeydownHandlerWired = false;

function installGlobalKeydownHandler() {
  if (_globalKeydownHandlerWired) return;
  document.addEventListener("keydown", handleGlobalKeydown);
  _globalKeydownHandlerWired = true;
}

var AUDIO_UNLOCK_EVENTS = ["click", "keydown", "touchstart"];
let _audioUnlockListenersWired = false;

function removeAudioUnlockListeners() {
  if (!_audioUnlockListenersWired) return;
  for (var i = 0; i < AUDIO_UNLOCK_EVENTS.length; i++) {
    document.removeEventListener(
      AUDIO_UNLOCK_EVENTS[i],
      enableAudioOnFirstInteraction,
    );
  }
  _audioUnlockListenersWired = false;
}

function enableAudioOnFirstInteraction() {
  removeAudioUnlockListeners();
  if (
    notificationManager.audioContext &&
    notificationManager.audioContext.state === "suspended"
  ) {
    notificationManager.audioContext
      .resume()
      .then(() => {
        console.debug("Audio context enabled");
      })
      .catch((error) => {
        console.warn("Enable audio context failed:", error);
      });
  }
}

function installAudioUnlockListeners() {
  if (_audioUnlockListenersWired) return;
  for (var i = 0; i < AUDIO_UNLOCK_EVENTS.length; i++) {
    document.addEventListener(
      AUDIO_UNLOCK_EVENTS[i],
      enableAudioOnFirstInteraction,
    );
  }
  _audioUnlockListenersWired = true;
}

// 事件监听器 - 兼容 DOM 已加载完成的情况
function initializeApp() {
  // 初始化 Lottie 沙漏动画
  initHourglassAnimation();

  loadConfig()
    .then(() => {
      // 配置加载完成
      console.debug("Config loaded");
      console.debug("Current config:", {
        has_content: config.has_content,
        persistent: config.persistent,
        prompt_length: config.prompt ? config.prompt.length : 0,
      });

      // R129：本路径只调用 ``initMultiTaskSupport``——legacy 的
      // ``app.js`` 内容轮询已迁移到 ``multi_task.js``；保留 catch
      // 兜底是为了配置加载失败时仍能初始化任务面板（用 setTimeout
      // 给浏览器留出 console.error 渲染窗口，让用户先看到错误再看
      // 到面板，避免错误瞬间被覆盖）。
      if (typeof initMultiTaskSupport === "function") {
        initMultiTaskSupport();
      }
    })
    .catch((error) => {
      console.error("Config load failed:", error);
      setTimeout(() => {
        console.debug("Config load failed, delayed multi-task init…");
        if (typeof initMultiTaskSupport === "function") {
          initMultiTaskSupport();
        }
      }, 3000);
    });

  // 初始化图片功能
  initializeImageFeatures();

  // 启动 URL 对象定期清理
  startPeriodicCleanup();

  // 初始化快捷键提示
  initializeShortcutTooltip();

  // 初始化设置管理器并在其配置就绪后再启动通知管理器
  settingsManager
    .init()
    .then(() => {
      settingsManager.applySettings({ syncBackend: false });
      return notificationManager.init();
    })
    .then(() => {
      console.debug("Notification manager initialized");
    })
    .catch((error) => {
      console.warn("Settings or notification manager init failed:", error);
    });

  // 按钮事件
  bindOptionalClick("insert-code-btn", insertCodeFromClipboard, {
    wireFlag: "aiiaInsertCodeClickWired",
  });
  bindOptionalClick("submit-btn", submitFeedback, {
    wireFlag: "aiiaSubmitClickWired",
  });
  bindOptionalClick("close-btn", closeInterface, {
    wireFlag: "aiiaCloseClickWired",
  });

  // 代码粘贴模态框按钮事件
  bindCodePasteModalControls();

  // 键盘快捷键 - 支持跨平台。页面级长生命周期 listener，由 R338 invariant
  // 通过稳定 handler 名审计；它不是 modal 临时 listener，不需要 remove。
  installGlobalKeydownHandler();

  // 用户首次交互时启用音频上下文
  //
  // 为什么要在 click/keydown/touchstart 上都挂监听：
  //   Chrome 的 Autoplay Policy 会让 AudioContext 初始化时停留在 'suspended'
  //   状态，直到用户产生「user gesture」才能 resume()。三类事件覆盖了桌面
  //   点击、键盘操作、移动端触屏的全部首次交互路径。
  //
  // 为什么需要互卸载（P7-Step-23）：
  //   如果只用 { once: true }，第一个触发的事件会自动移除「自己」，但另外
  //   两个监听依然挂在 document 上。用户整个会话期间它们都不会再触发——只
  //   是白白占用事件分发开销、并阻止 document 的监听器集合被 GC 回收。
  //   改为统一的 "when any fires, remove all three" 之后，document 的事件
  //   分发开销在首次交互后立即归零。
  installAudioUnlockListeners();
}

// 兼容 DOM 已加载和未加载两种情况
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeApp);
} else {
  // DOM 已加载完成，立即执行
  initializeApp();
}
