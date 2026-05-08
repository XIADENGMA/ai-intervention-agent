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

let _lottieLoadPromise = null;

function _ensureLottieLoaded() {
  if (typeof lottie !== "undefined") return Promise.resolve(true);
  if (_lottieLoadPromise) return _lottieLoadPromise;
  _lottieLoadPromise = new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = "/static/js/lottie.min.js";
    script.onload = () => resolve(typeof lottie !== "undefined");
    script.onerror = () => {
      _lottieLoadPromise = null;
      resolve(false);
    };
    document.head.appendChild(script);
  });
  return _lottieLoadPromise;
}

_ensureLottieLoaded();

function _createLottieAnimation(container) {
  try {
    if (hourglassAnimation) hourglassAnimation.destroy();
    hourglassAnimation = lottie.loadAnimation({
      container,
      renderer: "svg",
      loop: true,
      autoplay: true,
      path: "/static/lottie/sprout.json",
      rendererSettings: { preserveAspectRatio: "xMidYMid meet" },
    });
    hourglassAnimation.addEventListener("DOMLoaded", () =>
      updateLottieAnimationColor(),
    );
    hourglassAnimation.addEventListener("error", () => {
      renderSproutFallback(container);
      container.style.opacity = "1";
    });
    console.log("Sprout animation initialized (lazy load)");
  } catch (error) {
    console.error("Lottie animation init failed:", error);
    renderSproutFallback(container);
    container.style.opacity = "1";
  }
}

/**
 * 初始化嫩芽生长 Lottie 动画
 *
 * 策略：app.js 加载时即开始预取 lottie.min.js（见上方 _ensureLottieLoaded()）。
 * 调用本函数时先等待一个短窗口（200ms），若 Lottie 在窗口内就绪则直接渲染，
 * 跳过 SVG 占位，消除视觉闪烁；若超时则显示 SVG 占位并在 Lottie 就绪后
 * 以 crossfade 过渡替换。
 */
function initHourglassAnimation() {
  const container = document.getElementById("hourglass-lottie");
  if (!container) return;

  if (typeof lottie !== "undefined") {
    _createLottieAnimation(container);
    return;
  }

  let settled = false;
  const timer = setTimeout(() => {
    if (settled) return;
    renderSproutFallback(container);
  }, 200);

  _ensureLottieLoaded().then((ok) => {
    settled = true;
    clearTimeout(timer);
    if (ok) {
      const fallbackSvgs = Array.from(container.querySelectorAll("svg"));
      if (fallbackSvgs.length) {
        container.style.opacity = "0";
        container.style.transition = "opacity .25s ease";
      }
      _createLottieAnimation(container);
      if (fallbackSvgs.length && hourglassAnimation) {
        var removeFallback = () => {
          fallbackSvgs.forEach((s) => {
            if (s.parentNode) s.remove();
          });
        };
        hourglassAnimation.addEventListener("DOMLoaded", () => {
          removeFallback();
          requestAnimationFrame(() => {
            container.style.opacity = "1";
          });
        });
        setTimeout(() => {
          removeFallback();
          container.style.opacity = "1";
        }, 2000);
      }
    } else {
      if (!container.innerHTML.trim()) renderSproutFallback(container);
    }
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
  setTimeout(updateLottieAnimationColor, 50);
});

// 高性能markdown渲染函数
// isMarkdown: 是否为 Markdown 源文本（需要 marked.js 解析）
function renderMarkdownContent(element, content, isMarkdown = false) {
  // 使用requestAnimationFrame优化渲染时机
  requestAnimationFrame(() => {
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

  codeBlocks.forEach((pre) => {
    // 检查是否已经被处理过
    if (
      pre.parentElement &&
      pre.parentElement.classList.contains("code-block-container")
    ) {
      return;
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
  });
}

// 复制代码到剪贴板
async function copyCodeToClipboard(preElement, button) {
  // Claude 官方风格图标
  const checkIconSvg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M13.7803 4.21967C14.0732 4.51256 14.0732 4.98744 13.7803 5.28033L6.78033 12.2803C6.48744 12.5732 6.01256 12.5732 5.71967 12.2803L2.21967 8.78033C1.92678 8.48744 1.92678 8.01256 2.21967 7.71967C2.51256 7.42678 2.98744 7.42678 3.28033 7.71967L6.25 10.6893L12.7197 4.21967C13.0126 3.92678 13.4874 3.92678 13.7803 4.21967Z"/></svg>';
  const errorIconSvg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M4.21967 4.21967C4.51256 3.92678 4.98744 3.92678 5.28033 4.21967L8 6.93934L10.7197 4.21967C11.0126 3.92678 11.4874 3.92678 11.7803 4.21967C12.0732 4.51256 12.0732 4.98744 11.7803 5.28033L9.06066 8L11.7803 10.7197C12.0732 11.0126 12.0732 11.4874 11.7803 11.7803C11.4874 12.0732 11.0126 12.0732 10.7197 11.7803L8 9.06066L5.28033 11.7803C4.98744 12.0732 4.51256 12.0732 4.21967 11.7803C3.92678 11.4874 3.92678 11.0126 4.21967 10.7197L6.93934 8L4.21967 5.28033C3.92678 4.98744 3.92678 4.51256 4.21967 4.21967Z"/></svg>';

  try {
    const codeElement = preElement.querySelector("code");
    const textToCopy = codeElement
      ? codeElement.textContent
      : preElement.textContent;

    await navigator.clipboard.writeText(textToCopy);

    // 更新按钮状态
    const originalHTML = button.innerHTML;
    // AIIA-XSS-SAFE: checkIconSvg 是开发者手写 SVG 字面量；t('status.copied')
    // 走 locales/*.json 静态 key 且无参数。详见 docs/i18n.md § Security。
    button.innerHTML = checkIconSvg + t("status.copied");
    button.classList.add("copied");

    // 2秒后恢复原状
    setTimeout(() => {
      button.innerHTML = originalHTML;
      button.classList.remove("copied");
    }, 2000);
  } catch (err) {
    console.error("Copy failed:", err);

    // 显示错误状态
    const originalHTML = button.innerHTML;
    // AIIA-XSS-SAFE: errorIconSvg 是开发者手写 SVG 字面量；t('status.copyFailed')
    // 走静态 key 且无参数。
    button.innerHTML = errorIconSvg + t("status.copyFailed");
    button.classList.add("error");

    setTimeout(() => {
      button.innerHTML = originalHTML;
      button.classList.remove("error");
    }, 2000);
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
  textNodes.forEach((textNode) => {
    const text = textNode.textContent;
    const strikethroughRegex = /~~([^~\n]+?)~~/g;

    if (!strikethroughRegex.test(text)) return;

    const parts = text.split(/~~([^~\n]+?)~~/);
    if (parts.length <= 1) return;

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
  });
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

    // 更新描述 - 使用高性能渲染函数
    const descriptionElement = document.getElementById("description");
    renderMarkdownContent(
      descriptionElement,
      config.prompt_html || config.prompt,
    );

    // 加载预定义选项
    if (config.predefined_options && config.predefined_options.length > 0) {
      const optionsContainer = document.getElementById("options-container");
      const separator = document.getElementById("separator");

      config.predefined_options.forEach((option, index) => {
        const optionDiv = document.createElement("div");
        optionDiv.className = "option-item";

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.id = `option-${index}`;
        checkbox.value = option;

        const label = document.createElement("label");
        label.htmlFor = `option-${index}`;
        label.textContent = option;

        optionDiv.appendChild(checkbox);
        optionDiv.appendChild(label);
        optionsContainer.appendChild(optionDiv);
      });

      optionsContainer.style.display = "block";
      separator.style.display = "block";
    }
  } catch (error) {
    console.error("Config load failed:", error);
    showStatus(t("status.loadFailed"), "error");
    throw error; // 重新抛出错误，让调用者知道加载失败
  }
}

// 显示无内容页面
function showNoContentPage() {
  document.getElementById("content-container").style.display = "none";
  document.getElementById("no-content-container").style.display = "flex";

  // 添加无内容模式的CSS类，启用特殊布局
  document.body.classList.add("no-content-mode");

  // 隐藏任务标签栏（无内容时不需要显示）
  const taskTabsContainer = document.getElementById("task-tabs-container");
  if (taskTabsContainer) {
    taskTabsContainer.classList.add("hidden");
  }

  // 显示关闭按钮，让用户可以关闭服务
  if (config) {
    document.getElementById("no-content-buttons").style.display = "block";
  }
}

// 显示内容页面
function showContentPage() {
  document.getElementById("content-container").style.display = "block";
  document.getElementById("no-content-container").style.display = "none";

  // 移除无内容模式的CSS类，恢复正常布局
  document.body.classList.remove("no-content-mode");

  // 任务标签栏的显示由 multi_task.js 的 renderTaskTabs() 控制
  // 这里不需要手动显示，等待 renderTaskTabs() 根据任务数量决定

  enableSubmitButton();
}

// 禁用提交按钮
function disableSubmitButton() {
  const submitBtn = document.getElementById("submit-btn");
  const insertBtn = document.getElementById("insert-code-btn");
  const feedbackText = document.getElementById("feedback-text");

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.style.backgroundColor = "#3a3a3c";
    submitBtn.style.color = "#8e8e93";
    submitBtn.style.cursor = "not-allowed";
  }
  if (insertBtn) {
    insertBtn.disabled = true;
    insertBtn.style.backgroundColor = "#3a3a3c";
    insertBtn.style.color = "#8e8e93";
    insertBtn.style.cursor = "not-allowed";
  }
  if (feedbackText) {
    feedbackText.disabled = true;
    feedbackText.style.backgroundColor = "#2c2c2e";
    feedbackText.style.color = "#8e8e93";
    feedbackText.style.cursor = "not-allowed";
  }
}

// 启用提交按钮
function enableSubmitButton() {
  const submitBtn = document.getElementById("submit-btn");
  const insertBtn = document.getElementById("insert-code-btn");
  const feedbackText = document.getElementById("feedback-text");

  if (submitBtn) {
    submitBtn.disabled = false;
    submitBtn.style.backgroundColor = "#0a84ff";
    submitBtn.style.color = "#ffffff";
    submitBtn.style.cursor = "pointer";
  }
  if (insertBtn) {
    insertBtn.disabled = false;
    insertBtn.style.backgroundColor = "#48484a";
    insertBtn.style.color = "#ffffff";
    insertBtn.style.cursor = "pointer";
  }
  if (feedbackText) {
    feedbackText.disabled = false;
    feedbackText.style.backgroundColor = "rgba(255, 255, 255, 0.03)";
    feedbackText.style.color = "#f5f5f7";
    feedbackText.style.cursor = "text";
  }
}

// 显示状态消息
function showStatus(message, type) {
  const noContentContainer = document.getElementById("no-content-container");
  const isNoContentPage =
    noContentContainer && noContentContainer.style.display === "flex";

  if (!isNoContentPage && type !== "error") {
    if (type === "success") {
      _showToast(message);
    }
    return;
  }

  const statusElement = isNoContentPage
    ? document.getElementById("no-content-status-message")
    : document.getElementById("status-message");

  if (!statusElement) return;

  statusElement.textContent = message;
  statusElement.className = `status-message status-${type}`;
  statusElement.style.display = "block";

  const autoDismissMs =
    type === "success" ? 3000 : type === "error" ? 10000 : 0;
  if (autoDismissMs > 0) {
    setTimeout(() => {
      statusElement.style.display = "none";
    }, autoDismissMs);
  }
}

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
  toast.textContent = message;
  requestAnimationFrame(() => {
    toast.style.transform = "translateX(-50%) translateY(0)";
    toast.style.opacity = "1";
  });
  setTimeout(() => {
    toast.style.transform = "translateX(-50%) translateY(-120%)";
    toast.style.opacity = "0";
  }, 1800);
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
  const longestRun = backtickRuns.reduce(
    (max, run) => Math.max(max, run.length),
    0,
  );
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

function openCodePasteModal(error) {
  const panel = document.getElementById("code-paste-panel");
  const textarea = document.getElementById("code-paste-textarea");
  const hint = document.getElementById("code-paste-hint");

  if (!panel || !textarea) {
    showStatus(t("status.clipboardFailed"), "error");
    return;
  }

  if (hint) {
    hint.textContent = getClipboardFailureHint(error);
  }

  textarea.value = "";
  panel.classList.remove("hidden");
  panel.classList.add("show");

  // iOS 上需要在用户手势链路内尽快 focus，才能弹出键盘与“粘贴”菜单
  setTimeout(() => {
    try {
      textarea.focus();
    } catch (e) {
      // 忽略：部分浏览器/设备上 focus 可能失败
    }
  }, 0);

  // ESC 关闭（对齐图片模态框行为）
  document.addEventListener("keydown", handleCodePasteModalKeydown);
}

function closeCodePasteModal() {
  const panel = document.getElementById("code-paste-panel");
  const textarea = document.getElementById("code-paste-textarea");
  if (!panel) return;

  panel.classList.remove("show");
  panel.classList.add("hidden");

  if (textarea) {
    textarea.value = "";
  }

  document.removeEventListener("keydown", handleCodePasteModalKeydown);

  const feedbackTextarea = document.getElementById("feedback-text");
  if (feedbackTextarea) feedbackTextarea.focus();
}

function handleCodePasteModalKeydown(event) {
  if (event.key === "Escape") {
    closeCodePasteModal();
  }
}

// 首次加载时缓存 submit 按钮的原始 innerHTML（含 SVG + data-i18n span），
// 之后 finally 用它还原，避免 innerHTML 里硬编码中文（i18n / CI gate 要求）。
let SUBMIT_BTN_ORIGINAL_HTML = null;

function captureSubmitBtnOriginalHTML() {
  if (SUBMIT_BTN_ORIGINAL_HTML !== null) return;
  const btn = document.getElementById("submit-btn");
  if (btn) SUBMIT_BTN_ORIGINAL_HTML = btn.innerHTML;
}

// 提交反馈
async function submitFeedback() {
  captureSubmitBtnOriginalHTML();
  const feedbackText = document.getElementById("feedback-text").value.trim();
  const selectedOptions = [];

  // 【修复】直接从 DOM 获取选中的预定义选项
  // 不再依赖 config.predefined_options，因为在多任务模式下切换任务时 config 可能未同步更新
  const optionsContainer = document.getElementById("options-container");
  if (optionsContainer) {
    const checkboxes = optionsContainer.querySelectorAll(
      'input[type="checkbox"]:checked',
    );
    checkboxes.forEach((checkbox) => {
      // 使用 checkbox 的 value 属性获取选项文本
      if (checkbox.value) {
        selectedOptions.push(checkbox.value);
      }
    });
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
    const submitBtn = document.getElementById("submit-btn");
    submitBtn.disabled = true;
    // AIIA-XSS-SAFE: t('status.submitting') 是静态 key 且无参数，不携带用户可控数据。
    submitBtn.innerHTML = t("status.submitting");

    // 使用 FormData 上传文件，避免 base64 编码
    const formData = new FormData();
    formData.append("feedback_text", feedbackText);
    formData.append("selected_options", JSON.stringify(selectedOptions));

    // 添加图片文件（直接使用原始文件，不需要base64）
    selectedImages.forEach((img, index) => {
      if (img.file) {
        formData.append(`image_${index}`, img.file);
      }
    });

    // 获取当前活动任务ID（由 multi_task.js 管理）
    const currentTaskId = window.activeTaskId;

    // 优先使用多任务提交端点（如果有活动任务）
    const submitUrl = currentTaskId
      ? `/api/tasks/${currentTaskId}/submit`
      : "/api/submit";
    console.log(`Using submit endpoint: ${submitUrl}`);

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

      // 清空表单
      document.getElementById("feedback-text").value = "";
      // 取消选中所有复选框
      document
        .querySelectorAll('input[type="checkbox"]')
        .forEach((cb) => (cb.checked = false));
      // 清除所有图片
      clearAllImages();

      // 清理该任务的缓存（如果是多任务模式）
      if (currentTaskId) {
        if (typeof taskTextareaContents !== "undefined") {
          delete taskTextareaContents[currentTaskId];
        }
        if (typeof taskOptionsStates !== "undefined") {
          delete taskOptionsStates[currentTaskId];
        }
        if (typeof taskImages !== "undefined") {
          delete taskImages[currentTaskId];
        }
      }

      // 立即刷新任务列表（由 multi_task.js 处理页面状态切换）
      if (typeof refreshTasksList === "function") {
        console.log("Invoking refreshTasksList to refresh task list...");
        await refreshTasksList();
      } else {
        // 兼容旧模式：如果没有多任务支持，显示无内容页面
        if (config) {
          config.has_content = false;
          console.log("Feedback submitted; local state updated to empty");
        }
        showNoContentPage();
      }
    } else {
      showStatus(result.message || t("status.submitFailed"), "error");
    }
  } catch (error) {
    console.error("Submit failed:", error);
    showStatus(t("status.networkError"), "error");
  } finally {
    const submitBtn = document.getElementById("submit-btn");
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
  console.log("Reloading page…");
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

// ==================================================================
// 内容轮询 - 已停用
// ==================================================================
//
// 说明：
//   内容轮询功能已完全由 multi_task.js 的任务轮询接管。
//   此处仅保留空实现，防止被其他代码调用时报错。
//
// 历史原因：
//   原设计中 app.js 负责轮询 /api/config 检测内容变化，
//   但与 multi_task.js 的 /api/tasks 轮询存在冲突，
//   导致 textarea 内容被意外清空。
//
// 解决方案：
//   1. 停用 app.js 轮询，由 multi_task.js 统一管理
//   2. multi_task.js 实现了实时保存机制
// ==================================================================

/**
 * 停止内容轮询（空实现）
 *
 * 保留此函数是因为 closeInterface() 会调用它。
 * 实际轮询由 multi_task.js 的 stopTasksPolling() 管理。
 */
function stopContentPolling() {
  // 轮询已停用，此函数不执行任何操作
  console.log("[app.js] stopContentPolling called, but polling is disabled");
}

// updatePageContent() 已删除
// 页面内容更新现在完全由 multi_task.js 的以下函数处理：
//   - loadTaskDetails(): 加载任务详情
//   - updateDescriptionDisplay(): 更新描述区域
//   - updateOptionsDisplay(): 更新选项区域

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
    console.log(
      `Desktop platform detected: ${platform}, shortcut hints applied`,
    );
  } else {
    console.log("Mobile device detected, shortcut hints hidden");
  }
}

function updateShortcutDisplay(platform) {
  const isMac = platform === "mac";
  const ctrlOrCmd = isMac ? "Cmd" : "Ctrl";
  const altOrOption = isMac ? "Option" : "Alt";

  // 更新各个快捷键显示
  const shortcuts = {
    "shortcut-submit": `${ctrlOrCmd}+Enter`,
    "shortcut-code": `${altOrOption}+C`,
    "shortcut-paste": `${ctrlOrCmd}+V`,
    "shortcut-upload": `${ctrlOrCmd}+U`,
    "shortcut-delete": "Delete",
  };

  Object.entries(shortcuts).forEach(([id, shortcut]) => {
    const element = document.getElementById(id);
    if (element) {
      element.textContent = shortcut;
    }
  });
}

// 事件监听器 - 兼容 DOM 已加载完成的情况
function initializeApp() {
  // 初始化 Lottie 沙漏动画
  initHourglassAnimation();

  loadConfig()
    .then(() => {
      // 配置加载完成
      console.log("Config loaded");
      console.log("Current config:", {
        has_content: config.has_content,
        persistent: config.persistent,
        prompt_length: config.prompt ? config.prompt.length : 0,
      });

      // 【优化】停用 app.js 内容轮询，使用 multi_task.js 的任务轮询统一管理
      // 原因：两个轮询系统会导致 textarea 内容被意外清空
      // startContentPolling() // 已停用

      // 初始化多任务支持（内含任务轮询）
      if (typeof initMultiTaskSupport === "function") {
        initMultiTaskSupport();
      }
    })
    .catch((error) => {
      console.error("Config load failed:", error);
      // 即使配置加载失败，也尝试初始化多任务支持
      setTimeout(() => {
        console.log("Config load failed, delayed multi-task init…");
        // startContentPolling() // 已停用

        // 初始化多任务支持（内含任务轮询）
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
      console.log("Notification manager initialized");
    })
    .catch((error) => {
      console.warn("Settings or notification manager init failed:", error);
    });

  // 按钮事件
  document
    .getElementById("insert-code-btn")
    .addEventListener("click", insertCodeFromClipboard);
  document
    .getElementById("submit-btn")
    .addEventListener("click", submitFeedback);
  document
    .getElementById("close-btn")
    .addEventListener("click", closeInterface);

  // 代码粘贴模态框按钮事件
  const codePasteCloseBtn = document.getElementById("code-paste-close-btn");
  const codePasteCancelBtn = document.getElementById("code-paste-cancel-btn");
  const codePasteInsertBtn = document.getElementById("code-paste-insert-btn");
  const codePastePanel = document.getElementById("code-paste-panel");

  if (codePasteCloseBtn) {
    codePasteCloseBtn.addEventListener("click", closeCodePasteModal);
  }
  if (codePasteCancelBtn) {
    codePasteCancelBtn.addEventListener("click", closeCodePasteModal);
  }
  if (codePasteInsertBtn) {
    codePasteInsertBtn.addEventListener("click", () => {
      const textarea = document.getElementById("code-paste-textarea");
      const text = textarea ? textarea.value || "" : "";
      if (!text.trim()) {
        showStatus(t("status.enterCode"), "error");
        return;
      }
      insertCodeBlockIntoFeedbackTextarea(text);
      closeCodePasteModal();
    });
  }
  if (codePastePanel) {
    codePastePanel.addEventListener("click", function (e) {
      if (e.target === codePastePanel) {
        closeCodePasteModal();
      }
    });
  }

  // 键盘快捷键 - 支持跨平台
  document.addEventListener("keydown", (event) => {
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
      console.log(`Shortcut: ${isMac ? "Cmd" : "Ctrl"}+V paste`);
    } else if (ctrlOrCmd && event.key === "u") {
      event.preventDefault();
      document.getElementById("upload-image-btn").click();
      console.log(`Shortcut: ${isMac ? "Cmd" : "Ctrl"}+U upload image`);
    } else if (event.key === "Delete" && selectedImages.length > 0) {
      event.preventDefault();
      clearAllImages();
      console.log("Shortcut: Delete clear all images");
    } else if (ctrlOrCmd && event.shiftKey && event.key === "N") {
      // Ctrl+Shift+N 测试通知
      event.preventDefault();
      testNotification();
      console.log(
        `Shortcut: ${isMac ? "Cmd" : "Ctrl"}+Shift+N test notification`,
      );
    }
  });

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
  var AUDIO_UNLOCK_EVENTS = ["click", "keydown", "touchstart"];
  function enableAudioOnFirstInteraction() {
    for (var i = 0; i < AUDIO_UNLOCK_EVENTS.length; i++) {
      document.removeEventListener(
        AUDIO_UNLOCK_EVENTS[i],
        enableAudioOnFirstInteraction,
      );
    }
    if (
      notificationManager.audioContext &&
      notificationManager.audioContext.state === "suspended"
    ) {
      notificationManager.audioContext
        .resume()
        .then(() => {
          console.log("Audio context enabled");
        })
        .catch((error) => {
          console.warn("Enable audio context failed:", error);
        });
    }
  }

  for (var i = 0; i < AUDIO_UNLOCK_EVENTS.length; i++) {
    document.addEventListener(
      AUDIO_UNLOCK_EVENTS[i],
      enableAudioOnFirstInteraction,
    );
  }

  // 测试通知功能
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
}

// 兼容 DOM 已加载和未加载两种情况
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeApp);
} else {
  // DOM 已加载完成，立即执行
  initializeApp();
}
