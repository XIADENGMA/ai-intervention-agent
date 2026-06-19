/**
 * R248 / mining-8 Track A — iOS Safari "Add to Home Screen" 提示
 *
 * 背景
 * ----
 * R247 (mining-7 Track A) 在 Chrome/Edge/Brave/Samsung Internet
 * 等支持 ``beforeinstallprompt`` 事件的浏览器上为 PWA 安装提供了
 * 显式按钮 —— 但 **iOS Safari**（包括 iPad / iPhone）至今**不**
 * 实现 ``beforeinstallprompt``。iOS 用户想把 web 应用安装为桌面
 * 应用必须走 **Share → Add to Home Screen** 流程，而这个入口对
 * 大多数用户来说**完全不可发现**。
 *
 * R248 在符合条件的 iOS Safari 环境检测出来后，弹一个**底部一次
 * 性 banner** 引导用户找到 Share 菜单的 Add to Home Screen 选项。
 * banner 是非阻塞、可永久 dismiss 的，确保不会变成噪声。
 *
 * 触发条件（全部满足才显示）
 * --------------------------
 * - **iOS UA**：``iPhone|iPad|iPod`` in ``navigator.userAgent``
 *   或 iPad Pro 11+ 的 ``navigator.platform === 'MacIntel' &&
 *   navigator.maxTouchPoints > 1``（"desktop class Safari" 默认
 *   返回 macOS UA，需要靠 maxTouchPoints 区分）
 * - **Safari**：UA 含 ``Safari`` 且**不**含 ``CriOS|FxiOS|EdgiOS``
 *   （这些是 Chrome / Firefox / Edge for iOS，它们用 WebKit 但
 *   不能调用 Add to Home Screen）
 * - **非 standalone**：``window.navigator.standalone !== true``
 *   且 ``window.matchMedia('(display-mode: standalone)').matches``
 *   不为 true（已安装就不再提示）
 * - **未 dismiss**：localStorage ``aiia.iosA2hsDismissed.v1`` 不
 *   存在或 ≥ 永久 dismiss 时间戳
 *
 * 设计原则
 * --------
 * - **永久 dismiss**：与 R247 PWA install 按钮 30 天 dismiss
 *   不同，iOS A2HS 是一次性引导（用户已经知道流程了），dismiss
 *   后**永久**不再显示（除非用户主动 clear localStorage）。
 * - **零侵入既有 UI**：用 ``position: fixed`` bottom banner，不
 *   占据 layout 空间；shadow + backdrop 让它视觉上独立于 web_ui
 *   主体。
 * - **i18n + a11y**：banner 用 ``role="dialog"`` + ``aria-label
 *   ledby``；图标 SVG 标注 ``aria-hidden``；按钮全 i18n-key 驱动。
 * - **不阻断主流程**：banner 只显示一次，关掉后用户继续正常使
 *   用；不出现在主任务流之间。
 */

(function () {
  "use strict";

  const STORAGE_KEY = "aiia.iosA2hsDismissed.v1";
  const BANNER_ID = "ios-a2hs-hint-banner";
  const DISMISS_BTN_ID = "ios-a2hs-hint-dismiss";
  const SHOW_DELAY_MS = 1500; // 页面 ready 1.5s 后才弹（避开首屏渲染高峰）

  function _isStorageAvailable() {
    try {
      const probe = "__aiia_ios_a2hs_probe__";
      localStorage.setItem(probe, "1");
      localStorage.removeItem(probe);
      return true;
    } catch (_e) {
      return false;
    }
  }

  function _isDismissed() {
    if (!_isStorageAvailable()) return false;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return false;
      const parsed = JSON.parse(raw);
      return typeof parsed === "object" && parsed && parsed.dismissed === true;
    } catch (_e) {
      return false;
    }
  }

  function _setDismissed() {
    if (!_isStorageAvailable()) return;
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          dismissed: true,
          dismissed_at: Date.now(),
          schema_version: 1,
        }),
      );
    } catch (_e) {
      // silent — quota 满 / cookie 禁用等 fallback to no-persistence
    }
  }

  function _isIosSafari() {
    const ua = (navigator.userAgent || "").toLowerCase();
    const platform = navigator.platform || "";
    const maxTouch = navigator.maxTouchPoints || 0;
    const isIosUa = /iphone|ipad|ipod/.test(ua);
    const isIpadDesktopMode =
      platform === "MacIntel" && maxTouch > 1 && !/iphone|ipad|ipod/.test(ua);
    const isIos = isIosUa || isIpadDesktopMode;
    if (!isIos) return false;
    // 排除 iOS 上的 Chrome / Firefox / Edge（都用 WebKit 但不能调 A2HS）
    const isInAppBrowser = /crios|fxios|edgios|opios/.test(ua);
    if (isInAppBrowser) return false;
    return /safari/.test(ua);
  }

  function _isAlreadyStandalone() {
    if (window.navigator && window.navigator.standalone === true) return true;
    try {
      if (
        window.matchMedia &&
        window.matchMedia("(display-mode: standalone)").matches
      ) {
        return true;
      }
    } catch (_e) {
      // matchMedia 不可用 fallback
    }
    return false;
  }

  function _getI18nApis() {
    const apis = [];
    try {
      if (
        window.AIIA_I18N &&
        typeof window.AIIA_I18N.t === "function"
      ) {
        apis.push(window.AIIA_I18N);
      }
    } catch (_e) {
      // i18n namespace unavailable — try legacy fallback below
    }
    try {
      if (
        window.i18n &&
        typeof window.i18n.t === "function" &&
        apis.indexOf(window.i18n) === -1
      ) {
        apis.push(window.i18n);
      }
    } catch (_e) {
      // legacy i18n namespace unavailable
    }
    return apis;
  }

  function _resolveLabel(key, fallback) {
    try {
      const apis = _getI18nApis();
      for (let i = 0; i < apis.length; i += 1) {
        const v = apis[i].t(key);
        if (typeof v === "string" && v && v !== key) return v;
      }
    } catch (_e) {
      // i18n 未就绪 fallback
    }
    return fallback;
  }

  function _nextFrame(callback) {
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

  function _buildBanner() {
    const banner = document.createElement("div");
    banner.id = BANNER_ID;
    banner.className = "ios-a2hs-banner";
    banner.setAttribute("role", "dialog");
    banner.setAttribute("aria-modal", "false");
    banner.setAttribute("aria-labelledby", "ios-a2hs-title");

    // 图标 + 文案区
    const content = document.createElement("div");
    content.className = "ios-a2hs-banner__content";

    const icon = document.createElement("div");
    icon.className = "ios-a2hs-banner__icon";
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" ' +
      'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M8 12h8M12 8v8M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"/></svg>';

    const text = document.createElement("div");
    text.className = "ios-a2hs-banner__text";

    const title = document.createElement("div");
    title.id = "ios-a2hs-title";
    title.className = "ios-a2hs-banner__title";
    title.textContent = _resolveLabel(
      "page.iosA2hs.title",
      "Install as iOS app",
    );

    const desc = document.createElement("div");
    desc.className = "ios-a2hs-banner__desc";
    desc.textContent = _resolveLabel(
      "page.iosA2hs.desc",
      "Tap Share, then Add to Home Screen",
    );

    text.appendChild(title);
    text.appendChild(desc);

    content.appendChild(icon);
    content.appendChild(text);

    // dismiss 叉
    const dismissBtn = document.createElement("button");
    dismissBtn.id = DISMISS_BTN_ID;
    dismissBtn.type = "button";
    dismissBtn.className = "ios-a2hs-banner__dismiss";
    dismissBtn.setAttribute(
      "aria-label",
      _resolveLabel("page.iosA2hs.dismissAriaLabel", "Dismiss this hint"),
    );
    dismissBtn.setAttribute(
      "title",
      _resolveLabel("page.iosA2hs.dismissTitle", "Dismiss"),
    );
    dismissBtn.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" ' +
      'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true">' +
      '<line x1="18" y1="6" x2="6" y2="18"/>' +
      '<line x1="6" y1="6" x2="18" y2="18"/></svg>';
    dismissBtn.addEventListener("click", () => {
      _setDismissed();
      _removeElement(banner);
    });

    banner.appendChild(content);
    banner.appendChild(dismissBtn);

    return banner;
  }

  function _maybeShow() {
    if (_isDismissed()) return;
    if (_isAlreadyStandalone()) return;
    if (!_isIosSafari()) return;

    setTimeout(() => {
      // 二次检查 — 防止 dismiss 与 show 之间的 race（用户在
      // SHOW_DELAY_MS 期间手动改了 localStorage / 切换 standalone）
      if (_isDismissed() || _isAlreadyStandalone()) return;
      const existing = document.getElementById(BANNER_ID);
      if (existing) return;
      const banner = _buildBanner();
      document.body.appendChild(banner);
      // 上滑入场动画
      _nextFrame(() => {
        banner.classList.add("ios-a2hs-banner--visible");
      });
    }, SHOW_DELAY_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _maybeShow);
  } else {
    _maybeShow();
  }

  // 暴露测试 hook
  if (typeof window !== "undefined") {
    window.__iosA2hsInternal = {
      _isIosSafari,
      _isAlreadyStandalone,
      _isDismissed,
      _setDismissed,
      _getI18nApis,
      _resolveLabel,
      _buildBanner,
      _nextFrame,
      _removeElement,
      STORAGE_KEY,
      BANNER_ID,
    };
  }
})();
