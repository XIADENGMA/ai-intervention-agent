(function () {
  "use strict";

  const STORAGE_KEY = "aiia.feedbackOptionsHeight.v1";
  const PIN_STORAGE_KEY = "aiia.feedbackOptionsPinned.v1";
  const SCHEMA_VERSION = 1;
  const MIN_HEIGHT_PX = 96;
  const MAX_STORED_HEIGHT_PX = 4000;
  const ARROW_STEP_PX = 24;
  const PAGE_STEP_PX = 96;
  const VIEWPORT_MAX_PERCENT = 70;
  const RESERVE_MARGIN_PX = 16;
  const HEIGHT_VAR = "--aiia-options-height";
  const RESERVE_VAR = "--aiia-options-reserve";
  const LIST_ID = "options-container";
  const HANDLE_ID = "options-resize-handle";
  const DOCK_ID = "options-dock";
  const PIN_BUTTON_ID = "options-pin-btn";
  const UNPINNED_CLASS = "is-unpinned";
  let activeBinding = null;

  function finiteNumberOrNull(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function clampHeight(value, min, max) {
    const n = finiteNumberOrNull(value);
    if (n === null) return null;
    const minValue = finiteNumberOrNull(min);
    const maxValue = finiteNumberOrNull(max);
    const lo = minValue === null ? MIN_HEIGHT_PX : Math.max(0, minValue);
    const hi = maxValue === null ? Math.max(n, lo) : Math.max(maxValue, lo);
    return Math.round(Math.min(Math.max(n, lo), hi));
  }

  function normalizeStoredHeight(value) {
    const n = finiteNumberOrNull(value);
    if (n === null || n < MIN_HEIGHT_PX) return null;
    return Math.round(Math.min(n, MAX_STORED_HEIGHT_PX));
  }

  function resolveKey(key, shiftKey, current, min, max) {
    const unhandled = { handled: false, height: null };
    const now = finiteNumberOrNull(current);
    if (now === null) return unhandled;
    const arrowStep = shiftKey ? PAGE_STEP_PX : ARROW_STEP_PX;
    switch (key) {
      case "ArrowUp":
        return { handled: true, height: clampHeight(now + arrowStep, min, max) };
      case "ArrowDown":
        return { handled: true, height: clampHeight(now - arrowStep, min, max) };
      case "PageUp":
        return { handled: true, height: clampHeight(now + PAGE_STEP_PX, min, max) };
      case "PageDown":
        return { handled: true, height: clampHeight(now - PAGE_STEP_PX, min, max) };
      case "Home":
        return { handled: true, height: clampHeight(0, min, max) };
      case "End":
        return { handled: true, height: clampHeight(Number.MAX_SAFE_INTEGER, min, max) };
      case "Enter":
        return { handled: true, height: null };
      default:
        return unhandled;
    }
  }

  function readPersistedHeight() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      if (parsed.schema_version !== SCHEMA_VERSION) return null;
      return normalizeStoredHeight(parsed.height_px);
    } catch (_e) {
      return null;
    }
  }

  function persistHeight(height) {
    try {
      if (height === null) {
        localStorage.removeItem(STORAGE_KEY);
        return true;
      }
      const stored = normalizeStoredHeight(height);
      if (stored === null) return false;
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          schema_version: SCHEMA_VERSION,
          height_px: stored,
          saved_at: Date.now(),
        }),
      );
      return true;
    } catch (_e) {
      return false;
    }
  }

  // Only "unpinned" is stored: pinned is the default, so a reader who pins again leaves nothing behind.
  function readPersistedPinned() {
    try {
      const raw = localStorage.getItem(PIN_STORAGE_KEY);
      if (!raw) return true;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return true;
      if (parsed.schema_version !== SCHEMA_VERSION) return true;
      return parsed.pinned !== false;
    } catch (_e) {
      return true;
    }
  }

  function persistPinned(pinned) {
    try {
      if (pinned !== false) {
        localStorage.removeItem(PIN_STORAGE_KEY);
        return true;
      }
      localStorage.setItem(
        PIN_STORAGE_KEY,
        JSON.stringify({
          schema_version: SCHEMA_VERSION,
          pinned: false,
          saved_at: Date.now(),
        }),
      );
      return true;
    } catch (_e) {
      return false;
    }
  }

  function disconnectActiveBinding() {
    if (!activeBinding) return;
    const binding = activeBinding;
    activeBinding = null;
    binding.destroy();
  }

  function init() {
    disconnectActiveBinding();
    const list = document.getElementById(LIST_ID);
    const handle = document.getElementById(HANDLE_ID);
    const root = document.documentElement;
    if (!list || !handle || !root) return null;
    const dock = document.getElementById(DOCK_ID);
    const pinButton = document.getElementById(PIN_BUTTON_ID);
    // A button without its tray (or a tray without its button) cannot be pinned or unpinned: leave both alone.
    const pinnable = !!(dock && pinButton);

    let pinned = pinnable ? readPersistedPinned() : true;
    let manualHeight = readPersistedHeight();
    let drag = null;
    let observer = null;

    const currentHeight = () => Math.round(list.getBoundingClientRect().height);
    const heightBounds = () => {
      const naturalHeight = list.offsetHeight - list.clientHeight + list.scrollHeight;
      const viewportMax = Math.floor(((window.innerHeight || 0) * VIEWPORT_MAX_PERCENT) / 100);
      return {
        min: MIN_HEIGHT_PX,
        max: Math.max(MIN_HEIGHT_PX, Math.min(naturalHeight, viewportMax)),
      };
    };
    const sync = () => {
      const bounds = heightBounds();
      const now = clampHeight(currentHeight(), bounds.min, bounds.max);
      handle.setAttribute("aria-valuemin", String(bounds.min));
      handle.setAttribute("aria-valuemax", String(bounds.max));
      handle.setAttribute("aria-valuenow", String(now === null ? bounds.min : now));
      const shown = list.offsetHeight;
      // An unpinned list is part of the message, so nothing has to be kept clear of it.
      const covered = pinned && shown > 0 ? shown + RESERVE_MARGIN_PX : 0;
      root.style.setProperty(RESERVE_VAR, covered + "px");
    };
    const applyPinned = (next) => {
      pinned = next;
      if (pinnable) {
        dock.classList.toggle(UNPINNED_CLASS, !next);
        pinButton.setAttribute("aria-pressed", next ? "true" : "false");
      }
      sync();
    };
    const onPinClick = () => {
      applyPinned(!pinned);
      persistPinned(pinned);
    };
    const writeHeight = (height) => {
      manualHeight = height;
      if (height === null) {
        root.style.removeProperty(HEIGHT_VAR);
      } else {
        root.style.setProperty(HEIGHT_VAR, height + "px");
      }
    };
    const resizeTo = (height) => {
      const before = list.getBoundingClientRect();
      writeHeight(height);
      const after = list.getBoundingClientRect();
      const shift = Math.round(after.height - before.height + (after.top - before.top));
      if (shift !== 0 && typeof window.scrollBy === "function") {
        window.scrollBy(0, shift);
      }
    };
    const endDrag = (e) => {
      if (!drag || (e && e.pointerId !== drag.pointerId)) return;
      const finished = drag;
      drag = null;
      handle.classList.remove("is-dragging");
      try {
        handle.releasePointerCapture(finished.pointerId);
      } catch (_err) {
        void _err;
      }
      if (Math.abs(currentHeight() - finished.startHeight) < 1) {
        writeHeight(finished.startValue);
      }
      sync();
      persistHeight(manualHeight);
    };
    const onPointerDown = (e) => {
      if (typeof e.button === "number" && e.button !== 0) return;
      const bounds = heightBounds();
      drag = {
        pointerId: e.pointerId,
        startY: e.clientY,
        startHeight: currentHeight(),
        startValue: manualHeight,
        min: bounds.min,
        max: bounds.max,
      };
      handle.classList.add("is-dragging");
      try {
        handle.setPointerCapture(e.pointerId);
      } catch (_err) {
        void _err;
      }
      e.preventDefault();
    };
    const onPointerMove = (e) => {
      if (!drag || e.pointerId !== drag.pointerId) return;
      const next = clampHeight(drag.startHeight + (drag.startY - e.clientY), drag.min, drag.max);
      if (next !== null) resizeTo(next);
    };
    const onKeyDown = (e) => {
      const bounds = heightBounds();
      const result = resolveKey(e.key, !!e.shiftKey, currentHeight(), bounds.min, bounds.max);
      if (!result.handled) return;
      e.preventDefault();
      const before = currentHeight();
      const previous = manualHeight;
      resizeTo(result.height);
      if (result.height !== null && Math.abs(currentHeight() - before) < 1) {
        // The key moved nothing (the list is at a limit, or shorter than the minimum): do not remember its height.
        writeHeight(previous);
        sync();
        return;
      }
      sync();
      persistHeight(manualHeight);
    };
    const onDoubleClick = (e) => {
      e.preventDefault();
      resizeTo(null);
      sync();
      persistHeight(manualHeight);
    };

    writeHeight(manualHeight);
    applyPinned(pinned);
    if (pinnable) pinButton.addEventListener("click", onPinClick);
    handle.addEventListener("pointerdown", onPointerDown);
    handle.addEventListener("pointermove", onPointerMove);
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);
    handle.addEventListener("lostpointercapture", endDrag);
    handle.addEventListener("keydown", onKeyDown);
    handle.addEventListener("dblclick", onDoubleClick);
    handle.addEventListener("focus", sync);
    window.addEventListener("resize", sync);
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(sync);
      observer.observe(list);
    }

    const binding = {
      handle: handle,
      pinButton: pinnable ? pinButton : null,
      observer: observer,
      destroy: function () {
        if (pinnable) pinButton.removeEventListener("click", onPinClick);
        handle.removeEventListener("pointerdown", onPointerDown);
        handle.removeEventListener("pointermove", onPointerMove);
        handle.removeEventListener("pointerup", endDrag);
        handle.removeEventListener("pointercancel", endDrag);
        handle.removeEventListener("lostpointercapture", endDrag);
        handle.removeEventListener("keydown", onKeyDown);
        handle.removeEventListener("dblclick", onDoubleClick);
        handle.removeEventListener("focus", sync);
        window.removeEventListener("resize", sync);
        if (observer && typeof observer.disconnect === "function") {
          observer.disconnect();
        }
        observer = null;
        drag = null;
      },
    };
    activeBinding = binding;
    return binding;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AIIA_FEEDBACK_OPTIONS_DOCK = {
    STORAGE_KEY: STORAGE_KEY,
    PIN_STORAGE_KEY: PIN_STORAGE_KEY,
    SCHEMA_VERSION: SCHEMA_VERSION,
    MIN_HEIGHT_PX: MIN_HEIGHT_PX,
    MAX_STORED_HEIGHT_PX: MAX_STORED_HEIGHT_PX,
    HEIGHT_VAR: HEIGHT_VAR,
    RESERVE_VAR: RESERVE_VAR,
    clampHeight: clampHeight,
    normalizeStoredHeight: normalizeStoredHeight,
    resolveKey: resolveKey,
    readPersistedHeight: readPersistedHeight,
    persistHeight: persistHeight,
    readPersistedPinned: readPersistedPinned,
    persistPinned: persistPinned,
    init: init,
  };
})();
