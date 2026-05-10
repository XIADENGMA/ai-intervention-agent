/**
 * Keyboard Shortcut Cheatsheet Overlay (R144)
 *
 * @description
 *   按 `?` (Shift+/) 弹出全屏覆盖的快捷键提示浮层，把项目里现有的
 *   keyboard shortcut（R131d Alt+1..9 插入 Quick Phrase chip、R140 提
 *   交模式 Ctrl+Enter / Enter / Shift+Enter）显式 discoverability 化。
 *
 *   触发约束（重要）：
 *     - 只在「**任何 input/textarea/contenteditable 都不 focus**」的状态下
 *       才拦截 ``?``——textarea 里输入 ``?`` 仍然是字符。这与 GitHub /
 *       GitLab 的 ``?`` cheatsheet 同款语义，不打扰键盘党正常输入。
 *     - 浮层打开后：
 *       * Esc 关闭
 *       * 点击半透明遮罩（不点卡片本身）关闭
 *       * 卡片内点击不冒泡到遮罩（避免误关）
 *
 *   竞品对齐：
 *     - mcp-feedback-enhanced：Ctrl+I focus textarea（discoverability 不强）
 *     - cunzhi：未做
 *     - GitHub / GitLab / Linear：``?`` cheatsheet 是行业默认范式
 *
 *   设计原则：
 *     1. **零新依赖** — 纯原生 DOM + addEventListener，与 R131d / R140 一致。
 *     2. **零 innerHTML** — 全部用 createElement + textContent，CSP / XSS 安全。
 *     3. **i18n 全覆盖** — 所有可见文案走 ``window.AIIA_I18N.t``，对未加载
 *        的情况兜底英文 fallback（i18n hook 见 ``_t``）。
 *     4. **失败优雅** — i18n 模块、target 元素都没探到时，初始化 silent skip，
 *        不污染既有用户操作。
 *     5. **单一职责** — 不动 textarea / 不动其他 keydown listener；只在
 *        ``document`` capture-phase 加一个 ``?`` 拦截器。
 *
 *   不存 localStorage：浮层是无状态 UI，每次按 ``?`` 都重新渲染从内置静态
 *   shortcut 列表。后续若要加"用户已看过 N 次"hint，再扩 schema。
 */

(function () {
  "use strict";

  // ============================================================================
  // 常量
  // ============================================================================

  /**
   * 浮层 DOM 的 id —— 为了让 CSS / 测试 / 其他模块能 query。
   * 命名前缀 ``aiia-`` 避免和 app.js / settings-manager.js 冲突。
   */
  var OVERLAY_ID = "aiia-keyboard-shortcut-help-overlay";

  /**
   * 触发 cheatsheet 的按键。``?`` 是 ``Shift+/``，浏览器 + 操作系统
   * 通用、与 textarea 输入字符不冲突（仅在 textarea 不 focus 时拦截）。
   */
  var TRIGGER_KEY = "?";

  /**
   * Shortcut 静态列表 —— 每条 ``{ keys: string[], i18nKey: string,
   * fallback: string }``。``keys`` 是要在面板里显示的按键序列（多键
   * 用 ``+`` 渲染），``i18nKey`` 是 ``window.AIIA_I18N.t`` 的查找键，
   * ``fallback`` 是英文兜底（避开 CJK 触发 i18n CI 守卫）。
   *
   * 顺序按"频率 × 学习曲线"排：常用 + 简单的在前。
   */
  var SHORTCUTS = [
    {
      keys: ["?"],
      i18nKey: "shortcuts.showHelp",
      fallback: "Show this cheatsheet",
    },
    {
      keys: ["Esc"],
      i18nKey: "shortcuts.closeModal",
      fallback: "Close this cheatsheet",
    },
    {
      keys: ["Alt", "1-9"],
      i18nKey: "shortcuts.quickPhrase",
      fallback: "Insert Quick Phrase chip 1..9 (R131d)",
    },
    {
      keys: ["Ctrl", "Enter"],
      i18nKey: "shortcuts.submitCtrlEnter",
      fallback: "Submit feedback (default mode)",
    },
    {
      keys: ["Enter"],
      i18nKey: "shortcuts.submitEnter",
      fallback: "Submit (when Enter mode is selected)",
    },
    {
      keys: ["Shift", "Enter"],
      i18nKey: "shortcuts.newline",
      fallback: "Insert newline (when Enter mode is selected)",
    },
  ];

  // ============================================================================
  // 工具：i18n 查询 + 兜底
  // ============================================================================

  /**
   * 调 ``window.AIIA_I18N.t(key)`` 取本地化字符串；i18n 不可用 / key
   * 缺失（返回的是 key 自身）→ 用 fallback。i18n 静态分析器期望
   * literal ``"shortcuts.xxx"`` 出现在源码中，所以本函数被调用时必须
   * 显式写 literal key，不能用变量替代。
   */
  function _t(key, fallback) {
    try {
      var i18n = window.AIIA_I18N;
      if (i18n && typeof i18n.t === "function") {
        var v = i18n.t(key);
        if (typeof v === "string" && v.length > 0 && v !== key) {
          return v;
        }
      }
    } catch (_e) {
      // i18n 模块炸了 —— 不打断面板，走 fallback
    }
    return fallback;
  }

  /**
   * 直接对应 SHORTCUTS 表里 6 个 i18n key 的查询函数 —— 每条都把
   * literal key 写出来给静态分析器看到。新增 shortcut 时同步加一条。
   */
  function _resolveShortcutLabel(i18nKey, fallback) {
    if (i18nKey === "shortcuts.showHelp") {
      return _t("shortcuts.showHelp", fallback);
    }
    if (i18nKey === "shortcuts.closeModal") {
      return _t("shortcuts.closeModal", fallback);
    }
    if (i18nKey === "shortcuts.quickPhrase") {
      return _t("shortcuts.quickPhrase", fallback);
    }
    if (i18nKey === "shortcuts.submitCtrlEnter") {
      return _t("shortcuts.submitCtrlEnter", fallback);
    }
    if (i18nKey === "shortcuts.submitEnter") {
      return _t("shortcuts.submitEnter", fallback);
    }
    if (i18nKey === "shortcuts.newline") {
      return _t("shortcuts.newline", fallback);
    }
    return fallback;
  }

  // ============================================================================
  // DOM 渲染
  // ============================================================================

  function _renderShortcutRow(shortcut) {
    var row = document.createElement("div");
    row.className = "aiia-kshelp-row";

    var keysDiv = document.createElement("div");
    keysDiv.className = "aiia-kshelp-keys";
    for (var i = 0; i < shortcut.keys.length; i++) {
      if (i > 0) {
        var plus = document.createElement("span");
        plus.className = "aiia-kshelp-plus";
        plus.textContent = "+";
        keysDiv.appendChild(plus);
      }
      var kbd = document.createElement("kbd");
      kbd.className = "aiia-kshelp-key";
      kbd.textContent = shortcut.keys[i];
      keysDiv.appendChild(kbd);
    }

    var label = document.createElement("div");
    label.className = "aiia-kshelp-label";
    label.textContent = _resolveShortcutLabel(
      shortcut.i18nKey,
      shortcut.fallback,
    );

    row.appendChild(keysDiv);
    row.appendChild(label);
    return row;
  }

  function _buildOverlayDom() {
    var overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.className = "aiia-kshelp-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute(
      "aria-label",
      _t("shortcuts.helpTitle", "Keyboard shortcuts"),
    );

    var card = document.createElement("div");
    card.className = "aiia-kshelp-card";
    card.tabIndex = -1;

    var title = document.createElement("h2");
    title.className = "aiia-kshelp-title";
    title.textContent = _t("shortcuts.helpTitle", "Keyboard shortcuts");
    card.appendChild(title);

    var subtitle = document.createElement("p");
    subtitle.className = "aiia-kshelp-subtitle";
    subtitle.textContent = _t(
      "shortcuts.helpSubtitle",
      "Press ? anywhere outside an input to open this panel",
    );
    card.appendChild(subtitle);

    var rows = document.createElement("div");
    rows.className = "aiia-kshelp-rows";
    for (var i = 0; i < SHORTCUTS.length; i++) {
      rows.appendChild(_renderShortcutRow(SHORTCUTS[i]));
    }
    card.appendChild(rows);

    var hint = document.createElement("p");
    hint.className = "aiia-kshelp-hint";
    hint.textContent = _t(
      "shortcuts.helpEscHint",
      "Press Esc or click outside to close",
    );
    card.appendChild(hint);

    // 卡片内点击不冒泡到 overlay（防误关）
    card.addEventListener("click", function (ev) {
      ev.stopPropagation();
    });
    overlay.appendChild(card);

    // 点击半透明遮罩（不在卡片内）→ 关闭
    overlay.addEventListener("click", function () {
      hideOverlay();
    });

    return overlay;
  }

  // ============================================================================
  // 公开 API
  // ============================================================================

  /**
   * 显示 cheatsheet。idempotent：若已经显示，不重复挂 DOM。
   */
  function showOverlay() {
    var existing = document.getElementById(OVERLAY_ID);
    if (existing) {
      return;
    }
    var overlay = _buildOverlayDom();
    document.body.appendChild(overlay);
    // 把 focus 移到卡片，方便屏幕阅读器读出 dialog 内容
    var card = overlay.querySelector(".aiia-kshelp-card");
    if (card && typeof card.focus === "function") {
      try {
        card.focus({ preventScroll: true });
      } catch (_e) {
        // 老浏览器不支持 focus options，忽略
      }
    }
  }

  /**
   * 隐藏并从 DOM 移除 cheatsheet。idempotent。
   */
  function hideOverlay() {
    var overlay = document.getElementById(OVERLAY_ID);
    if (overlay && overlay.parentNode) {
      overlay.parentNode.removeChild(overlay);
    }
  }

  function isOverlayOpen() {
    return Boolean(document.getElementById(OVERLAY_ID));
  }

  // ============================================================================
  // 触发条件判定 —— 只在文本输入元素不 focus 时拦截 ?
  // ============================================================================

  /**
   * 当前 active element 是不是文本输入元素？
   * input/textarea/select/contenteditable 都视为「打字中」，不拦截 ?。
   */
  function _isTypingTarget(el) {
    if (!el) {
      return false;
    }
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") {
      return true;
    }
    // contenteditable
    if (
      el.isContentEditable ||
      el.getAttribute("contenteditable") === "true" ||
      el.getAttribute("contenteditable") === ""
    ) {
      return true;
    }
    return false;
  }

  function _shouldTriggerHelp(event) {
    // ``?`` = Shift+/，event.key 浏览器原生就是 "?"。但 Firefox 老版本
    // 在某些键盘布局下可能触发 "?" 时 shiftKey=false（极端 corner）—— 走
    // event.key 字符串判定最稳。
    if (event.key !== TRIGGER_KEY) {
      return false;
    }
    // 修饰键过滤：Ctrl/Cmd+? 浏览器不一定能产出 "?" 但容错检查；本快捷键
    // 不接受额外修饰，避免和 Ctrl+Shift+/ 这类系统快捷键冲突
    if (event.ctrlKey || event.metaKey || event.altKey) {
      return false;
    }
    // typing 状态不拦截
    if (_isTypingTarget(document.activeElement)) {
      return false;
    }
    return true;
  }

  // ============================================================================
  // 全局键盘 listener
  // ============================================================================

  function _onKeydown(event) {
    // overlay 打开状态下：Esc 关闭；其他键不拦
    if (isOverlayOpen()) {
      if (event.key === "Escape" || event.key === "Esc") {
        event.preventDefault();
        hideOverlay();
      }
      return;
    }
    if (_shouldTriggerHelp(event)) {
      event.preventDefault();
      showOverlay();
    }
  }

  function init() {
    // 用 capture phase：让本拦截器先于其他 keydown handler 拿到事件，
    // 确保在 textarea 失焦后任意位置都能响应 ?；与 R140 同款架构。
    document.addEventListener("keydown", _onKeydown, true);
  }

  // ============================================================================
  // 暴露给 unit test / 其他模块 + 启动
  // ============================================================================

  window.AIIA_KEYBOARD_SHORTCUT_HELP = {
    showOverlay: showOverlay,
    hideOverlay: hideOverlay,
    isOverlayOpen: isOverlayOpen,
    OVERLAY_ID: OVERLAY_ID,
    TRIGGER_KEY: TRIGGER_KEY,
    SHORTCUTS: SHORTCUTS,
    _shouldTriggerHelp: _shouldTriggerHelp,
    _isTypingTarget: _isTypingTarget,
  };

  // DOM ready 时挂 listener；defer script 已经在 DOMContentLoaded 之后
  // 才执行，但额外 if 检查兜底
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
