/**
 * R137 — Feedback textarea 高度持久化
 *
 * 背景
 * ----
 * ``.feedback-textarea`` 已经支持 CSS ``resize: vertical``，用户可以拖拽
 * 调整高度。但每次刷新 / 新会话后高度都会重置回 ``min-height: 180px``
 * 默认值——熟练用户每次都得手动调一遍，是低频但持续的小痛点。
 * ``mcp-feedback-enhanced`` v2.4.3 把 "Input Height Memory" 列入版本
 * highlight 是因为这是「键盘党 + 长输入用户」体感差异最大的一项。
 *
 * 设计原则
 * --------
 * - ``localStorage`` 持久化，per-domain（loopback http://127.0.0.1:8888 共
 *   享一份），不引入服务端状态。
 * - schema_version envelope 与 R130 quick_phrases 同款，让未来 v2 可
 *   以加 migrator 而不破坏 v1 用户。
 * - clamp 到 ``[MIN_HEIGHT_PX, MAX_HEIGHT_PX]`` 防止用户误拖到极端值
 *   （0 / 全屏）导致 UX 异常。
 * - 优先 ``ResizeObserver``（现代浏览器），fallback ``mouseup``（旧
 *   浏览器、Touch 设备）。
 * - 写盘 debounce 150ms，避免拖动过程中高频 setItem 占 main thread。
 * - localStorage 失败（private browsing / quota）静默跳过，不影响主
 *   功能。
 */

(function () {
  "use strict";

  const STORAGE_KEY = "aiia.feedbackTextareaHeight.v1";
  const SCHEMA_VERSION = 1;
  const MIN_HEIGHT_PX = 100;
  const MAX_HEIGHT_PX = 800;
  const DEBOUNCE_MS = 150;
  const TARGET_ID = "feedback-text";
  let activeResizeBinding = null;

  function _clamp(value) {
    return Math.max(MIN_HEIGHT_PX, Math.min(MAX_HEIGHT_PX, value));
  }

  function readPersistedHeight() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      if (parsed.schema_version !== SCHEMA_VERSION) return null;
      const height = parsed.height_px;
      if (typeof height !== "number" || !Number.isFinite(height)) return null;
      return _clamp(height);
    } catch (_e) {
      return null;
    }
  }

  function persistHeight(height) {
    if (typeof height !== "number" || !Number.isFinite(height)) {
      return false;
    }
    try {
      const clamped = _clamp(height);
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          schema_version: SCHEMA_VERSION,
          height_px: clamped,
          saved_at: Date.now(),
        }),
      );
      return true;
    } catch (_e) {
      return false;
    }
  }

  function applyPersistedHeight(textarea) {
    if (!textarea) return false;
    const persisted = readPersistedHeight();
    if (persisted === null) return false;
    textarea.style.height = persisted + "px";
    return true;
  }

  function disconnectActiveResizeBinding() {
    if (!activeResizeBinding) return;
    if (activeResizeBinding.timeoutId) clearTimeout(activeResizeBinding.timeoutId);
    if (
      activeResizeBinding.observer &&
      typeof activeResizeBinding.observer.disconnect === "function"
    ) {
      activeResizeBinding.observer.disconnect();
    }
    if (activeResizeBinding.mode === "mouseup_fallback") {
      const textarea = activeResizeBinding.textarea;
      if (textarea && typeof textarea.removeEventListener === "function") {
        textarea.removeEventListener("mouseup", activeResizeBinding.handler);
        textarea.removeEventListener("touchend", activeResizeBinding.handler);
      }
    }
    activeResizeBinding = null;
  }

  function setupResizeObserver(textarea) {
    if (!textarea) return null;
    if (activeResizeBinding && activeResizeBinding.textarea === textarea) {
      return activeResizeBinding;
    }
    disconnectActiveResizeBinding();

    const binding = {
      textarea: textarea,
      observer: null,
      handler: null,
      timeoutId: null,
    };
    const handler = function () {
      if (binding.timeoutId) {
        clearTimeout(binding.timeoutId);
      }
      binding.timeoutId = setTimeout(function () {
        const h = textarea.offsetHeight;
        if (h >= MIN_HEIGHT_PX && h <= MAX_HEIGHT_PX) {
          persistHeight(h);
        }
        binding.timeoutId = null;
      }, DEBOUNCE_MS);
    };
    binding.handler = handler;

    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(handler);
      ro.observe(textarea);
      binding.observer = ro;
      binding.mode = "resize_observer";
      activeResizeBinding = binding;
      return binding;
    }
    textarea.addEventListener("mouseup", handler);
    textarea.addEventListener("touchend", handler);
    binding.mode = "mouseup_fallback";
    activeResizeBinding = binding;
    return binding;
  }

  function init() {
    const textarea = document.getElementById(TARGET_ID);
    if (!textarea) return null;
    applyPersistedHeight(textarea);
    return setupResizeObserver(textarea);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AIIA_FEEDBACK_TEXTAREA_HEIGHT = {
    STORAGE_KEY: STORAGE_KEY,
    SCHEMA_VERSION: SCHEMA_VERSION,
    MIN_HEIGHT_PX: MIN_HEIGHT_PX,
    MAX_HEIGHT_PX: MAX_HEIGHT_PX,
    DEBOUNCE_MS: DEBOUNCE_MS,
    TARGET_ID: TARGET_ID,
    readPersistedHeight: readPersistedHeight,
    persistHeight: persistHeight,
    applyPersistedHeight: applyPersistedHeight,
    setupResizeObserver: setupResizeObserver,
    init: init,
  };
})();
