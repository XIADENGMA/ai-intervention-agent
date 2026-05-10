/**
 * R140 — Feedback 提交模式切换（Ctrl+Enter vs Enter）
 *
 * 背景
 * ----
 * 既有 ``app.js`` 的 keydown handler 把 ``Ctrl/Cmd+Enter`` 硬编码为
 * 提交快捷键，纯键盘党 + 短文本反馈用户在 Slack / Discord / Notion /
 * Telegram 等 IM 工具里用 Enter 提交是默认习惯，每次切回本应用都得
 * "记住"用 Ctrl+Enter，认知负担非零。R140 给用户一个偏好开关：
 *
 *   - ``ctrl_enter``（默认，与现状一致）：``Ctrl/Cmd+Enter`` 提交，
 *     ``Enter`` 换行；
 *   - ``enter``：``Enter`` 提交，``Shift+Enter`` 换行（IM 模式）。
 *     ``Ctrl/Cmd+Enter`` 仍然能提交（保留熟悉路径）。
 *
 * 设计原则
 * --------
 * - **纯前端 localStorage**——与 R137 / R138 / R139 同款架构，不上服
 *   务端 ``user_settings``，避免「设置同步」这条新轴的复杂度。submit
 *   mode 是纯客户端 UX 偏好，多设备不同步是合理边界。
 * - **不替换既有 keydown handler**——R140 在 ``#feedback-text``
 *   textarea 上挂独立 capture-phase listener，``ctrl_enter`` 模式下
 *   不拦截让既有 ``document.addEventListener("keydown", ...)`` 处理；
 *   ``enter`` 模式下 ``preventDefault`` 阻止 textarea 默认换行 + 调
 *   ``#submit-btn.click()`` 触发提交，不直接访问 ``submitFeedback``
 *   函数引用避免硬耦合。
 * - **IME composition 安全**——按 ``event.isComposing`` /
 *   ``keyCode === 229`` 双重判断，让中日韩输入法 / emoji picker 用
 *   户在选词阶段按 Enter 不会误提交（IME 选词 Enter 是确认候选，
 *   不是提交反馈）。
 * - **schema_version envelope** + ``aiia.submitMode.v1`` 命名约定，
 *   与 R130 / R137 / R138 / R139 一致。
 * - **graceful failure**——localStorage 不可用 / corrupt 时静默
 *   fallback 到 ``DEFAULT_MODE``，主路径不挂。
 */

(function () {
  "use strict";

  const STORAGE_KEY = "aiia.submitMode.v1";
  const SCHEMA_VERSION = 1;
  const DEFAULT_MODE = "ctrl_enter";
  const VALID_MODES = ["ctrl_enter", "enter"];
  const TARGET_ID = "feedback-text";
  const SUBMIT_BTN_ID = "submit-btn";

  function _isStorageAvailable() {
    try {
      const probe = "__aiia_submit_mode_probe__";
      localStorage.setItem(probe, "1");
      localStorage.removeItem(probe);
      return true;
    } catch (_e) {
      return false;
    }
  }

  function getMode() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return DEFAULT_MODE;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return DEFAULT_MODE;
      if (parsed.schema_version !== SCHEMA_VERSION) return DEFAULT_MODE;
      const mode = parsed.mode;
      if (VALID_MODES.indexOf(mode) === -1) return DEFAULT_MODE;
      return mode;
    } catch (_e) {
      return DEFAULT_MODE;
    }
  }

  function setMode(mode) {
    if (VALID_MODES.indexOf(mode) === -1) return false;
    if (!_isStorageAvailable()) return false;
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          schema_version: SCHEMA_VERSION,
          mode: mode,
          saved_at: Date.now(),
        }),
      );
      return true;
    } catch (_e) {
      return false;
    }
  }

  // 判断当前 keydown 事件是否应当触发提交（``enter`` 模式下）。
  // 边界：
  //   - Shift+Enter / Alt+Enter / Ctrl+Enter / Cmd+Enter：让既有
  //     handler 路径处理（单 Enter 模式不拦截这些组合键）；
  //   - IME composition 中：选词 Enter 是确认候选，不应当触发提交；
  //   - 其他键：non-Enter 一律不命中。
  function _shouldSubmitOnEnter(event) {
    if (!event) return false;
    if (event.key !== "Enter") return false;
    if (event.shiftKey) return false;
    if (event.altKey) return false;
    if (event.ctrlKey || event.metaKey) return false;
    if (event.isComposing) return false;
    // keyCode 229 是浏览器对 IME composition 的 fallback 标志
    // （event.isComposing 在某些老浏览器 / 边缘 IME 上不可靠）
    if (event.keyCode === 229) return false;
    return true;
  }

  function _triggerSubmit() {
    const btn = document.getElementById(SUBMIT_BTN_ID);
    if (!btn) return false;
    if (btn.disabled) return false;
    btn.click();
    return true;
  }

  function setupKeydownInterceptor(textarea) {
    if (!textarea) return null;
    const handler = function (event) {
      if (getMode() !== "enter") return;
      if (!_shouldSubmitOnEnter(event)) return;
      event.preventDefault();
      _triggerSubmit();
    };
    // capture phase 让本拦截器先于 document-level keydown 跑，确保
    // ``preventDefault`` 在浏览器 newline 默认行为发生前生效。
    textarea.addEventListener("keydown", handler, true);
    return { textarea: textarea, handler: handler };
  }

  // 设置面板里的 <select id="feedback-submit-mode-select"> 切换 mode
  // 后立即写盘，无需重新加载页面（既有 listener 走 getMode()
  // 实时读，不缓存模块状态）。
  function setupSelectListener() {
    const select = document.getElementById("feedback-submit-mode-select");
    if (!select) return null;
    select.value = getMode();
    select.addEventListener("change", function () {
      const next = select.value;
      if (VALID_MODES.indexOf(next) === -1) return;
      setMode(next);
    });
    return select;
  }

  function init() {
    const textarea = document.getElementById(TARGET_ID);
    const interceptor = setupKeydownInterceptor(textarea);
    const select = setupSelectListener();
    return { interceptor: interceptor, select: select };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AIIA_FEEDBACK_SUBMIT_MODE = {
    STORAGE_KEY: STORAGE_KEY,
    SCHEMA_VERSION: SCHEMA_VERSION,
    DEFAULT_MODE: DEFAULT_MODE,
    VALID_MODES: VALID_MODES,
    TARGET_ID: TARGET_ID,
    SUBMIT_BTN_ID: SUBMIT_BTN_ID,
    getMode: getMode,
    setMode: setMode,
    _shouldSubmitOnEnter: _shouldSubmitOnEnter,
    _triggerSubmit: _triggerSubmit,
    _isStorageAvailable: _isStorageAvailable,
    setupKeydownInterceptor: setupKeydownInterceptor,
    setupSelectListener: setupSelectListener,
    init: init,
  };
})();
