(function () {

  let vscode = null;
  try {
    vscode =
      typeof globalThis !== "undefined" &&
      globalThis &&
      globalThis.__AIIA_VSCODE_API
        ? globalThis.__AIIA_VSCODE_API
        : null;
  } catch (e) {
    vscode = null;
  }
  if (!vscode) {
    try {
      vscode = acquireVsCodeApi();
    } catch (e) {
      vscode = null;
    }
  }

  const cfgEl =
    typeof document !== "undefined"
      ? document.getElementById("aiia-config")
      : null;
  const SERVER_URL =
    cfgEl && cfgEl.getAttribute("data-server-url")
      ? String(cfgEl.getAttribute("data-server-url"))
      : "";

  function postMessage(message) {
    try {
      if (vscode && typeof vscode.postMessage === "function") {
        vscode.postMessage(message);
        return true;
      }
    } catch (e) {

    }
    return false;
  }

  function postNotificationEvent(event) {
    postMessage({ type: "notify", event: event || {} });
  }

  function postStatusInfo(message, options) {
    postNotificationEvent({
      title: "AI Intervention Agent",
      message: String(message || ""),
      trigger: "immediate",
      types: ["vscode"],
      metadata: Object.assign(
        { presentation: "statusBar", severity: "info", timeoutMs: 3000 },
        options || {},
      ),
      source: "webview-settings-ui",
      dedupeKey: message ? "status:" + String(message).slice(0, 200) : "",
    });
  }

  (function ensureI18nReady() {
    try {
      var i18n =
        (typeof globalThis !== "undefined" && globalThis.AIIA_I18N) ||
        (typeof window !== "undefined" && window.AIIA_I18N);
      if (!i18n || typeof i18n.registerLocale !== "function") return;
      var langs =
        typeof i18n.getAvailableLangs === "function"
          ? i18n.getAvailableLangs()
          : [];
      if (langs.length > 0) return;
      var allLocales =
        (typeof window !== "undefined" && window.__AIIA_I18N_ALL_LOCALES) ||
        null;
      if (allLocales && typeof allLocales === "object") {
        var keys = Object.keys(allLocales);
        for (var i = 0; i < keys.length; i++) {
          if (allLocales[keys[i]] && typeof allLocales[keys[i]] === "object") {
            i18n.registerLocale(keys[i], allLocales[keys[i]]);
          }
        }
      }
      var loc =
        (typeof window !== "undefined" && window.__AIIA_I18N_LOCALE) || null;
      var lang =
        (typeof window !== "undefined" && window.__AIIA_I18N_LANG) || "";
      if (loc && typeof loc === "object" && lang) {
        i18n.registerLocale(String(lang), loc);
        if (typeof i18n.setLang === "function") i18n.setLang(String(lang));
      }
    } catch (e) {

    }
  })();

  function t(key, params) {
    try {
      var i18n =
        (typeof globalThis !== "undefined" && globalThis.AIIA_I18N) ||
        (typeof window !== "undefined" && window.AIIA_I18N);
      if (i18n && typeof i18n.t === "function") return i18n.t(key, params);
    } catch (e) {

    }
    return key;
  }

  function retranslateSettingsPanel() {
    var panel = document.getElementById("settingsPanel");
    if (!panel) return;
    var els = panel.querySelectorAll("[data-i18n]");
    for (var i = 0; i < els.length; i++) {
      var key = els[i].getAttribute("data-i18n");
      if (!key) continue;
      var ver = els[i].getAttribute("data-i18n-version");
      var val = ver ? t(key, { version: ver }) : t(key);
      if (val && val !== key) els[i].textContent = val;
    }
    var titles = panel.querySelectorAll("[data-i18n-title]");
    for (var j = 0; j < titles.length; j++) {
      var tKey = titles[j].getAttribute("data-i18n-title");
      if (!tKey) continue;
      var tVal = t(tKey);
      if (tVal && tVal !== tKey) {
        titles[j].setAttribute("title", tVal);
        if (titles[j].hasAttribute("aria-label"))
          titles[j].setAttribute("aria-label", tVal);
      }
    }
    var phs = panel.querySelectorAll("[data-i18n-placeholder]");
    for (var k = 0; k < phs.length; k++) {
      var phKey = phs[k].getAttribute("data-i18n-placeholder");
      if (!phKey) continue;
      var phVal = t(phKey);
      if (phVal && phVal !== phKey) phs[k].setAttribute("placeholder", phVal);
    }
  }
  try {
    globalThis.__AIIA_retranslateSettingsPanel = retranslateSettingsPanel;
  } catch (e) {

  }

  function rerenderSettingsDynamicText() {
    if (typeof rerenderBarkBaseUrlStatus === "function") {
      rerenderBarkBaseUrlStatus();
    }
  }
  try {
    globalThis.__AIIA_rerenderSettingsDynamicText = rerenderSettingsDynamicText;
  } catch (e) {

  }

  function getNotifyCore() {
    try {
      return globalThis && globalThis.AIIAWebviewNotifyCore
        ? globalThis.AIIAWebviewNotifyCore
        : null;
    } catch (e) {
      try {
        return window && window.AIIAWebviewNotifyCore
          ? window.AIIAWebviewNotifyCore
          : null;
      } catch (_) {
        return null;
      }
    }
  }

  function computeHash(settings) {
    try {
      return JSON.stringify(settings || {});
    } catch (e) {
      return String(Date.now());
    }
  }

  const SETTINGS_AUTO_REFRESH_MS = 2000;
  let settingsAutoRefreshTimer = null;
  let settingsDirty = false;
  let settingsEditEpoch = 0;
  let settingsRemoteChangedWhileDirty = false;
  let isPopulatingSettingsForm = false;
  let lastNotificationSettingsHash = "";
  let settingsHintClearTimer = null;
  let lastBarkBaseUrlStatus = null;
  let rerenderBarkBaseUrlStatus = null;

  const SETTINGS_AUTO_SAVE_DEBOUNCE_MS = 500;
  const SETTINGS_AUTO_SAVE_TIMEOUT_MS = 3500;
  let settingsAutoSaveTimer = null;
  let settingsAutoSaveAbortController = null;
  let settingsAutoSaveInFlight = false;
  let settingsAutoSavePending = false;
  let settingsAutoSaveFlushWhenClosed = false;
  let feedbackConfigSavePromise = null;
  let pendingFeedbackConfigUpdates = null;
  let feedbackConfigEditEpoch = 0;
  const FEEDBACK_CONFIG_SAVE_DEBOUNCE_MS = 800;
  let feedbackConfigDebounceTimer = null;
  let pendingDebouncedFeedbackConfigUpdates = null;

  // What had focus when the dialog opened, to give it back when it closes.
  let settingsOpener = null;
  // The parts of the page made inert while the dialog is open (only those this code changed).
  let settingsInertElements = [];
  // The countdown the server holds, to put back when what was typed is not a number.
  let lastFeedbackCountdown = 240;

  const SETTINGS_FOCUSABLE_SELECTOR =
    'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])';
  const FEEDBACK_COUNTDOWN_MIN = 10;
  const FEEDBACK_COUNTDOWN_MAX = 3600;

  let uiInitialized = false;

  function setSettingsHint(message, isError, autoClearMs) {
    const text = message ? String(message).trim() : "";

    if (text) {
      const toast =
        typeof globalThis !== "undefined" && globalThis.__AIIA_showToast;
      if (toast) {
        toast(text, {
          kind: isError ? "error" : "success",
          timeoutMs: isError ? 4000 : autoClearMs || 1400,
          dedupeKey:
            "settings:" + (isError ? "err:" : "ok:") + text.slice(0, 40),
        });
        return;
      }
    }

    const hint = document.getElementById("settingsHint");
    if (!hint) return;
    hint.textContent = text;

    hint.classList.toggle("aiia-error", !!isError);
    hint.classList.toggle("aiia-has-message", !!text);

    if (settingsHintClearTimer) {
      clearTimeout(settingsHintClearTimer);
      settingsHintClearTimer = null;
    }
    if (!isError && text && autoClearMs && autoClearMs > 0) {
      settingsHintClearTimer = setTimeout(() => {
        try {
          const overlay = document.getElementById("settingsOverlay");

          if (!overlay || overlay.classList.contains("hidden")) return;
          setSettingsHint("", false);
        } catch (e) {

        }
      }, autoClearMs);
    }
  }

  function isSettingsOverlayOpen() {
    const overlay = document.getElementById("settingsOverlay");
    return !!(overlay && !overlay.classList.contains("hidden"));
  }

  function setBarkDeviceKeyRevealed(revealed) {
    const input = document.getElementById("notifyBarkDeviceKey");
    const toggle = document.getElementById("settingsBarkDeviceKeyToggleBtn");
    if (input) input.type = revealed ? "text" : "password";
    if (!toggle) return;
    const key = revealed
      ? "settings.bark.deviceKeyHide"
      : "settings.bark.deviceKeyShow";
    const label = revealed
      ? t("settings.bark.deviceKeyHide")
      : t("settings.bark.deviceKeyShow");
    toggle.setAttribute("data-state", revealed ? "shown" : "hidden");
    toggle.setAttribute("data-i18n-title", key);
    if (label && label !== key) {
      toggle.setAttribute("title", label);
      toggle.setAttribute("aria-label", label);
    }
  }

  function syncBarkFieldsVisibility() {
    const enabledEl = document.getElementById("notifyBarkEnabled");
    const enabled = !!(enabledEl && enabledEl.checked);
    const fields = document.getElementById("settingsBarkFields");
    if (fields) fields.hidden = !enabled;
    const testBtn = document.getElementById("settingsTestBarkBtn");
    if (testBtn) testBtn.hidden = !enabled;
    if (!enabled) setBarkDeviceKeyRevealed(false);
  }

  // The master switch gates every channel (the server sends nothing when it is off), so the channels
  // under it look inactive. They stay usable: Bark can be set up before the master switch is turned on.
  function syncChannelsMuted() {
    const master = document.getElementById("notifyEnabled");
    const channels = document.getElementById("settingsChannels");
    if (!master || !channels) return;
    channels.classList.toggle("is-muted", !master.checked);
  }

  function populateSettingsForm(settings) {
    isPopulatingSettingsForm = true;
    try {
      const setChecked = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.checked = !!value;
      };
      const setValue = (id, value) => {
        const el = document.getElementById(id);
        if (el)
          el.value = value === undefined || value === null ? "" : String(value);
      };

      const s = settings || {};
      setChecked("notifyEnabled", s.enabled);
      setChecked("notifyMacOSNativeEnabled", s.macosNativeEnabled);

      setChecked("notifyBarkEnabled", s.barkEnabled);
      setValue("notifyBarkUrl", s.barkUrl);
      setValue("notifyBarkDeviceKey", s.barkDeviceKey);
      setValue("notifyBarkIcon", s.barkIcon);
      setValue("notifyBarkAction", s.barkAction);
      setValue("notifyBarkUrlTemplate", s.barkUrlTemplate);
      syncBarkFieldsVisibility();
      syncChannelsMuted();
    } finally {
      isPopulatingSettingsForm = false;
    }
  }

  function collectSettingsForm() {
    const getChecked = (id) => {
      const el = document.getElementById(id);
      return !!(el && el.checked);
    };
    const getValue = (id) => {
      const el = document.getElementById(id);
      return el ? String(el.value || "") : "";
    };

    return {
      enabled: getChecked("notifyEnabled"),
      macosNativeEnabled: getChecked("notifyMacOSNativeEnabled"),

      barkEnabled: getChecked("notifyBarkEnabled"),
      barkUrl: getValue("notifyBarkUrl") || "https://api.day.app/push",
      barkDeviceKey: getValue("notifyBarkDeviceKey"),
      barkIcon: getValue("notifyBarkIcon"),
      barkAction: getValue("notifyBarkAction") || "none",
      barkUrlTemplate:
        getValue("notifyBarkUrlTemplate") || "{base_url}/?task_id={task_id}",
    };
  }

  function markSettingsDirty() {
    if (isPopulatingSettingsForm) return;
    settingsEditEpoch += 1;
    settingsDirty = true;
    scheduleSettingsAutoSave();
  }

  function scheduleSettingsAutoSave() {
    if (!isSettingsOverlayOpen()) return;
    if (settingsAutoSaveTimer) {
      clearTimeout(settingsAutoSaveTimer);
      settingsAutoSaveTimer = null;
    }
    settingsAutoSaveTimer = setTimeout(() => {
      saveSettings({ silent: true });
    }, SETTINGS_AUTO_SAVE_DEBOUNCE_MS);
  }

  function stopSettingsAutoSave() {
    if (settingsAutoSaveTimer) {
      clearTimeout(settingsAutoSaveTimer);
      settingsAutoSaveTimer = null;
    }
    settingsAutoSavePending = false;
    settingsAutoSaveFlushWhenClosed = false;
    try {
      if (
        settingsAutoSaveAbortController &&
        typeof settingsAutoSaveAbortController.abort === "function"
      ) {
        settingsAutoSaveAbortController.abort();
      }
    } catch (e) {

    } finally {
      settingsAutoSaveAbortController = null;
      settingsAutoSaveInFlight = false;
    }
  }

  function flushSettingsAutoSaveBeforeClose() {
    const hadScheduledSave = !!settingsAutoSaveTimer;
    if (settingsAutoSaveTimer) {
      clearTimeout(settingsAutoSaveTimer);
      settingsAutoSaveTimer = null;
    }
    if (
      hadScheduledSave ||
      settingsDirty ||
      settingsAutoSavePending ||
      settingsAutoSaveInFlight
    ) {
      settingsAutoSaveFlushWhenClosed = true;
      saveSettings({ silent: true, allowWhenClosed: true });
    }
  }

  function startSettingsAutoRefresh() {
    if (settingsAutoRefreshTimer) return;
    settingsAutoRefreshTimer = setInterval(() => {

      refreshNotificationSettingsFromServer({ force: false, silent: true });
    }, SETTINGS_AUTO_REFRESH_MS);
  }

  function stopSettingsAutoRefresh({ preserveAutoSave = false } = {}) {
    if (settingsAutoRefreshTimer) {
      clearInterval(settingsAutoRefreshTimer);
      settingsAutoRefreshTimer = null;
    }
    if (!preserveAutoSave) {
      stopSettingsAutoSave();
      settingsDirty = false;
      settingsRemoteChangedWhileDirty = false;
    }
  }

  async function refreshNotificationSettingsFromServer({
    force = false,
    silent = false,
    allowWhenClosed = false,
  } = {}) {
    const overlayOpen = isSettingsOverlayOpen();

    if (!overlayOpen && !allowWhenClosed) return false;

    const core = getNotifyCore();
    if (
      !core ||
      typeof core.refreshNotificationSettingsFromServer !== "function"
    ) {
      if (!silent && overlayOpen) {
        setSettingsHint(t("settings.hint.coreNotReady"), true);
      }
      return false;
    }

    const refreshEditEpoch = settingsEditEpoch;
    let result = null;
    try {
      result = await core.refreshNotificationSettingsFromServer({
        force,
        silent: true,
      });
    } catch (e) {
      result = null;
    }
    if (!result || !result.ok) {
      if (!silent && overlayOpen) {
        const msg =
          result && result.message
            ? String(result.message)
            : t("settings.hint.loadFailed");
        setSettingsHint(
          t("settings.hint.loadFailedReason", { reason: msg }),
          true,
        );
      }
      return false;
    }

    const next =
      result && result.settings
        ? result.settings
        : core.getCachedNotificationSettings
          ? core.getCachedNotificationSettings()
          : null;
    const nextHash = computeHash(next);
    const changed =
      !lastNotificationSettingsHash ||
      nextHash !== lastNotificationSettingsHash;
    const editedDuringRefresh = refreshEditEpoch !== settingsEditEpoch;

    if (force || (!settingsDirty && changed)) {
      if (editedDuringRefresh) {
        return true;
      }
      lastNotificationSettingsHash = nextHash;
      settingsDirty = false;
      settingsRemoteChangedWhileDirty = false;
      if (overlayOpen) {
        populateSettingsForm(next);
        if (!silent) {

          setSettingsHint(t("settings.hint.synced"), false, 1200);
        }
      }
      return true;
    }

    if (changed && settingsDirty && !settingsRemoteChangedWhileDirty) {
      settingsRemoteChangedWhileDirty = true;
      if (!silent && overlayOpen) {
        setSettingsHint(t("settings.hint.remoteChanged"), true);
      }
    }

    return true;
  }

  function focusElement(el) {
    if (!el || typeof el.focus !== "function") return false;
    try {
      el.focus({ preventScroll: true });
      return true;
    } catch (_e) {
      try {
        el.focus();
        return true;
      } catch (_e2) {
        return false;
      }
    }
  }

  // While the dialog is open nothing behind it can be reached: not by the pointer, Tab or a screen reader.
  // The toast host stays live (it carries the messages the dialog raises); only what this code made inert
  // is made reachable again, so a part of the page that was inert before stays that way.
  function setBackgroundInert(on) {
    if (!on) {
      const held = settingsInertElements;
      settingsInertElements = [];
      for (const el of held) {
        try {
          el.removeAttribute("inert");
        } catch (_e) {
          // the element is gone; nothing to give back
        }
      }
      return;
    }
    const body = document.body;
    if (!body || !body.children) return;
    for (const child of Array.from(body.children)) {
      const tag = String(child.tagName || "").toLowerCase();
      if (
        tag === "script" ||
        tag === "style" ||
        tag === "link" ||
        tag === "template"
      ) {
        continue;
      }
      if (child.id === "settingsOverlay" || child.id === "toastHost") continue;
      if (child.hasAttribute("inert")) continue;
      try {
        child.setAttribute("inert", "");
        settingsInertElements.push(child);
      } catch (_e) {
        // not an element we can mark; leave it
      }
    }
  }

  // Where focus goes when the dialog closes: back to what opened it; failing that to the settings button
  // that is on screen (the toolbar has one, the page without a task has its own).
  function restoreFocusAfterSettings() {
    const opener = settingsOpener;
    settingsOpener = null;
    if (opener && document.contains(opener)) {
      focusElement(opener);
      if (document.activeElement === opener) return;
    }
    // A button that is not on screen cannot take focus, so the check after the call passes it by.
    for (const id of ["settingsBtn", "settingsBtnNoContent"]) {
      const button = document.getElementById(id);
      if (!button) continue;
      focusElement(button);
      if (document.activeElement === button) return;
    }
  }

  function openSettingsOverlay() {
    const overlay = document.getElementById("settingsOverlay");
    const wasOpen = isSettingsOverlayOpen();
    if (!wasOpen) {
      const active = document.activeElement;
      settingsOpener = active && active !== document.body ? active : null;
    }
    if (overlay) overlay.classList.remove("hidden");
    if (!wasOpen) {
      setBackgroundInert(true);
      focusElement(document.getElementById("settingsPanel"));
    }
    startSettingsAutoRefresh();
  }

  function closeSettingsOverlay() {
    const wasOpen = isSettingsOverlayOpen();
    flushSettingsAutoSaveBeforeClose();
    _flushPendingFeedbackConfigSaveFromUi();
    const overlay = document.getElementById("settingsOverlay");
    if (overlay) overlay.classList.add("hidden");
    stopSettingsAutoRefresh({ preserveAutoSave: true });
    setSettingsHint("", false);
    try {
      setBarkDeviceKeyRevealed(false);
    } catch (_e) {

    }
    if (wasOpen) {
      setBackgroundInert(false);
      restoreFocusAfterSettings();
    }
  }

  // Tab stays inside the dialog: the controls that can take focus right now (a collapsed Bark group has none).
  function settingsTabStops() {
    const panel = document.getElementById("settingsPanel");
    if (!panel || typeof panel.querySelectorAll !== "function") return [];
    return Array.from(panel.querySelectorAll(SETTINGS_FOCUSABLE_SELECTOR)).filter(
      (el) => {
        if (el.disabled || el.hidden) return false;
        return (
          typeof el.getClientRects !== "function" ||
          el.getClientRects().length > 0
        );
      },
    );
  }

  function trapSettingsTab(event) {
    const panel = document.getElementById("settingsPanel");
    const stops = settingsTabStops();
    if (stops.length === 0) {
      event.preventDefault();
      focusElement(panel);
      return;
    }
    const active = document.activeElement;
    const inside = !!(panel && active && panel.contains(active));
    const first = stops[0];
    const last = stops[stops.length - 1];
    if (event.shiftKey) {
      if (!inside || active === panel || active === first) {
        event.preventDefault();
        focusElement(last);
      }
    } else if (!inside || active === last) {
      event.preventDefault();
      focusElement(first);
    }
  }

  function onSettingsKeydown(event) {
    if (!isSettingsOverlayOpen()) return;
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeSettingsOverlay();
      return;
    }
    if (event.key === "Tab") trapSettingsTab(event);
  }

  // What the server does with a countdown: 0 turns auto-resubmit off, anything else is held to 10..3600.
  // null: not a number (the field is put back and the user is told).
  function normalizeFeedbackCountdown(raw) {
    const text = String(raw === undefined || raw === null ? "" : raw).trim();
    if (!text) return null;
    const n = Number(text);
    if (!Number.isFinite(n)) return null;
    if (n === 0) return 0;
    return Math.min(
      FEEDBACK_COUNTDOWN_MAX,
      Math.max(FEEDBACK_COUNTDOWN_MIN, Math.round(n)),
    );
  }

  async function openSettings() {
    initUiOnce();
    openSettingsOverlay();
    setSettingsHint(t("settings.hint.loading"), false);

    try {
      await refreshNotificationSettingsFromServer({
        force: true,
        silent: false,
      });
    } catch (e) {
      setSettingsHint(
        t("settings.hint.loadFailedReason", {
          reason: e && e.message ? e.message : String(e),
        }),
        true,
      );
    }
    loadFeedbackConfig();
  }

  async function saveSettings({ silent = false, allowWhenClosed = false } = {}) {
    if (!allowWhenClosed && !isSettingsOverlayOpen()) return;
    if (!SERVER_URL) {
      if (!silent) setSettingsHint(t("settings.hint.syncFailedNoUrl"), true);
      return;
    }
    if (settingsAutoSaveInFlight) {

      settingsAutoSavePending = true;
      if (allowWhenClosed) {
        settingsAutoSaveFlushWhenClosed = true;
      }
      return;
    }
    settingsAutoSaveInFlight = true;

    let timeoutId = null;
    let currentSettingsAutoSaveAbortController = null;
    try {
      const core = getNotifyCore();
      const updates = collectSettingsForm();
      const base =
        core && typeof core.getCachedNotificationSettings === "function"
          ? core.getCachedNotificationSettings() || {}
          : {};
      const mergedFull = Object.assign({}, base, updates);
      const mergedHash = computeHash(mergedFull);

      if (mergedHash === lastNotificationSettingsHash) {
        settingsDirty = false;
        settingsRemoteChangedWhileDirty = false;
        if (!silent) setSettingsHint(t("settings.hint.noChange"), false, 1200);
        return;
      }

      if (!silent) {
        setSettingsHint(t("settings.hint.syncing"), false);
      }

      try {
        if (
          settingsAutoSaveAbortController &&
          typeof settingsAutoSaveAbortController.abort === "function"
        ) {
          settingsAutoSaveAbortController.abort();
        }
      } catch (e) {

      }

      const fetchOptions = {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(updates),
        cache: "no-store",
      };
      if (typeof AbortController !== "undefined") {
        settingsAutoSaveAbortController = new AbortController();
        currentSettingsAutoSaveAbortController = settingsAutoSaveAbortController;
        fetchOptions.signal = currentSettingsAutoSaveAbortController.signal;
        timeoutId = setTimeout(() => {
          try {
            currentSettingsAutoSaveAbortController.abort();
          } catch (e) {

          }
        }, SETTINGS_AUTO_SAVE_TIMEOUT_MS);
      } else {
        settingsAutoSaveAbortController = null;
      }

      const resp = await fetch(
        SERVER_URL + "/api/update-notification-config",
        fetchOptions,
      );
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data || data.status !== "success") {
        const msg =
          data && data.message
            ? data.message
            : t("settings.hint.syncFailedHttp", { status: resp.status });
        setSettingsHint(msg, true);
        return;
      }

      try {
        if (core && typeof core.setCachedNotificationSettings === "function") {
          core.setCachedNotificationSettings(mergedFull);
        }
      } catch (e) {

      }
      postMessage({ type: "notificationSettingsChanged" });

      const hasPendingSave = settingsAutoSavePending;
      lastNotificationSettingsHash = mergedHash;
      settingsDirty = hasPendingSave;
      if (!hasPendingSave) {
        settingsRemoteChangedWhileDirty = false;
      }

      setSettingsHint(t("settings.hint.synced"), false, 1200);
    } catch (e) {
      const msg =
        e && e.name === "AbortError"
          ? t("settings.hint.timeout")
          : e && e.message
            ? e.message
            : String(e);
      setSettingsHint(t("settings.hint.syncFailed", { reason: msg }), true);
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
      if (
        settingsAutoSaveAbortController ===
        currentSettingsAutoSaveAbortController
      ) {
        settingsAutoSaveAbortController = null;
      }
      settingsAutoSaveInFlight = false;
      if (settingsAutoSavePending) {
        settingsAutoSavePending = false;

        if (settingsDirty) {
          if (isSettingsOverlayOpen()) {
            scheduleSettingsAutoSave();
          } else if (settingsAutoSaveFlushWhenClosed || allowWhenClosed) {
            saveSettings({ silent: true, allowWhenClosed: true });
          }
        }
      } else if (!settingsDirty) {
        settingsAutoSaveFlushWhenClosed = false;
      }
    }
  }

  function nativeNotificationsAvailable() {
    // The extension host decides: a remote or non-macOS host cannot raise a macOS banner.
    const el = document.getElementById("aiia-config");
    const platform = el ? el.getAttribute("data-host-platform") : "";
    return !platform || platform === "darwin";
  }

  function testNotification() {
    try {
      const updates = collectSettingsForm();
      if (updates && updates.enabled === false) {
        setSettingsHint(t("settings.hint.notifyDisabled"), true);
        return;
      }
      const wantsNative = !!(updates && updates.macosNativeEnabled);
      const bannerShown = wantsNative && nativeNotificationsAvailable();
      // Both keys are spelled out in full on purpose: the i18n scans only find plain string literals.
      const hintText = bannerShown
        ? t("settings.hint.macosTestTriggered")
        : t("settings.hint.testInAppSent");
      setSettingsHint(hintText, false, 2000);

      const posted = postMessage({
        type: "notify",
        event: {
          title: t("settings.test.title"),
          message: t("settings.test.message"),
          trigger: "immediate",
          types: wantsNative ? ["vscode", "macos_native"] : ["vscode"],
          metadata: {
            isTest: true,
            diagnostic: true,
            kind: "test_notification",
            presentation: "auto",
            severity: "info",
            timeoutMs: 3000,
          },
          source: "webview-settings-ui",
          dedupeKey: "test:notification",
        },
      });
      if (!posted) {
        setSettingsHint(t("settings.hint.postFailed"), true);
        return;
      }
    } catch (e) {
      setSettingsHint(
        t("settings.hint.testFailed", {
          reason: e && e.message ? e.message : String(e),
        }),
        true,
      );
    }
  }

  async function initBarkBaseUrlStatus() {
    const item = document.getElementById("settingsBarkBaseUrlStatus");
    const message = document.getElementById("settingsBarkBaseUrlMessage");
    const suggestion = document.getElementById("settingsBarkBaseUrlSuggestion");
    const copyBtn = document.getElementById("settingsBarkBaseUrlCopyBtn");
    const recheckBtn = document.getElementById("settingsBarkBaseUrlRecheckBtn");
    if (!item || !message || !suggestion) return;

    const renderData = (data) => {
      const isLoopback = data.is_loopback === true;
      const effective = String(data.effective_base_url || "");
      const suggested = String(data.suggested_lan_base_url || "");
      const recommendation = String(data.recommendation || "ok");

      if (recommendation === "ok") {

        message.textContent = String(
          t("settings.bark.baseUrlStatusOk") || "",
        ).replace("{url}", effective);
        suggestion.textContent = "";
        if (copyBtn) copyBtn.hidden = true;
        item.hidden = false;
        return;
      }

      item.hidden = false;
      message.textContent =
        isLoopback && effective
          ? String(t("settings.bark.baseUrlStatusLoopback") || "").replace(
              "{url}",
              effective,
            )
          : t("settings.bark.baseUrlStatusUnreachable");

      if (suggested) {
        suggestion.textContent = t("settings.bark.baseUrlSuggestLan");
        if (copyBtn) {
          copyBtn.hidden = false;
          copyBtn.dataset.lanUrl = suggested;
          copyBtn.title = suggested;
        }
      } else {
        suggestion.textContent = t("settings.bark.baseUrlSuggestNoLan");
        if (copyBtn) {
          copyBtn.hidden = true;
          copyBtn.dataset.lanUrl = "";
        }
      }
    };

    const renderStatus = async () => {
      if (!SERVER_URL) {
        item.hidden = true;
        return;
      }
      try {
        const resp = await fetch(
          SERVER_URL + "/api/system/network-base-url-status",
          {
            method: "GET",
            cache: "no-store",
          },
        );
        if (!resp.ok) {
          item.hidden = true;
          return;
        }
        const data = await resp.json().catch(() => null);
        if (!data || data.success === false) {
          item.hidden = true;
          return;
        }

        lastBarkBaseUrlStatus = data;
        renderData(data);
      } catch (_e) {
        item.hidden = true;
      }
    };

    rerenderBarkBaseUrlStatus = () => {
      if (!lastBarkBaseUrlStatus || item.hidden) return;
      try {
        renderData(lastBarkBaseUrlStatus);
      } catch (_e) {

      }
    };

    if (recheckBtn) {
      recheckBtn.addEventListener("click", () => {
        renderStatus();
      });
    }
    if (copyBtn) {
      let feedbackTimer = null;
      copyBtn.addEventListener("click", async () => {
        const url =
          copyBtn.dataset && copyBtn.dataset.lanUrl
            ? copyBtn.dataset.lanUrl
            : "";
        if (!url) return;
        let copied = false;
        try {
          await navigator.clipboard.writeText(url);
          copied = true;
        } catch (_e) {
          copied = false;
        }
        copyBtn.textContent = copied
          ? t("settings.bark.baseUrlCopied")
          : t("ui.copy.failed");
        clearTimeout(feedbackTimer);
        feedbackTimer = setTimeout(() => {
          feedbackTimer = null;
          copyBtn.textContent = t("settings.bark.baseUrlCopyLan");
        }, 1500);
      });
    }

    await renderStatus();
  }

  async function testBark() {
    try {
      if (!SERVER_URL) {
        setSettingsHint(t("settings.hint.testFailedNoUrl"), true);
        return;
      }

      const updates = collectSettingsForm();
      setSettingsHint(t("settings.hint.testing"), false);
      const resp = await fetch(SERVER_URL + "/api/test-bark", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          bark_url: updates.barkUrl || "https://api.day.app/push",
          bark_device_key: updates.barkDeviceKey || "",
          bark_icon: updates.barkIcon || "",
          bark_action: updates.barkAction || "none",
          bark_url_template:
            updates.barkUrlTemplate || "{base_url}/?task_id={task_id}",
        }),
        cache: "no-store",
      });

      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data || data.status !== "success") {
        const msg =
          data && data.message
            ? data.message
            : t("settings.hint.testFailedHttp", { status: resp.status });
        setSettingsHint(msg, true);
        return;
      }

      setSettingsHint(data.message || t("settings.hint.barkTestSent"), false);
      postStatusInfo(data.message || t("settings.hint.barkTestSent"));
    } catch (e) {
      setSettingsHint(
        t("settings.hint.testFailed", {
          reason: e && e.message ? e.message : String(e),
        }),
        true,
      );
    }
  }

  function _queueFeedbackConfigSaveFromUi(updates) {
    feedbackConfigEditEpoch += 1;
    if (feedbackConfigDebounceTimer) clearTimeout(feedbackConfigDebounceTimer);
    pendingDebouncedFeedbackConfigUpdates = Object.assign(
      pendingDebouncedFeedbackConfigUpdates || {},
      updates || {},
    );
    feedbackConfigDebounceTimer = setTimeout(() => {
      const merged = pendingDebouncedFeedbackConfigUpdates;
      pendingDebouncedFeedbackConfigUpdates = null;
      feedbackConfigDebounceTimer = null;
      saveFeedbackConfig(merged);
    }, FEEDBACK_CONFIG_SAVE_DEBOUNCE_MS);
  }

  function _flushPendingFeedbackConfigSaveFromUi() {
    if (feedbackConfigDebounceTimer) {
      clearTimeout(feedbackConfigDebounceTimer);
      feedbackConfigDebounceTimer = null;
    }
    if (!pendingDebouncedFeedbackConfigUpdates) return false;
    const merged = pendingDebouncedFeedbackConfigUpdates;
    pendingDebouncedFeedbackConfigUpdates = null;
    saveFeedbackConfig(merged);
    return true;
  }

  function initUiOnce() {
    if (uiInitialized) return;
    uiInitialized = true;

    try {
      const settingsOverlay = document.getElementById("settingsOverlay");
      const settingsPanel = document.getElementById("settingsPanel");
      const settingsClose = document.getElementById("settingsClose");
      const settingsTestNotifyBtn = document.getElementById(
        "settingsTestNotifyBtn",
      );
      const settingsTestBarkBtn = document.getElementById(
        "settingsTestBarkBtn",
      );

      if (settingsClose)
        settingsClose.addEventListener("click", closeSettingsOverlay);
      if (settingsTestNotifyBtn)
        settingsTestNotifyBtn.addEventListener("click", testNotification);
      if (settingsTestBarkBtn)
        settingsTestBarkBtn.addEventListener("click", testBark);
      const barkKeyToggleBtn = document.getElementById(
        "settingsBarkDeviceKeyToggleBtn",
      );
      if (barkKeyToggleBtn)
        barkKeyToggleBtn.addEventListener("click", () => {
          const barkKeyInput = document.getElementById("notifyBarkDeviceKey");
          setBarkDeviceKeyRevealed(
            !!barkKeyInput && barkKeyInput.type === "password",
          );
        });

      try {
        initBarkBaseUrlStatus();
      } catch (_e) {

      }

      const settingsFooterLinks = document.querySelectorAll(
        '.settings-footer-link[target="_blank"]',
      );
      settingsFooterLinks.forEach((linkEl) => {
        linkEl.addEventListener("click", (e) => {
          try {
            const href = linkEl.getAttribute("href") || "";
            if (!/^https?:\/\//i.test(href)) return;
            e.preventDefault();
            e.stopPropagation();
            postMessage({ type: "openExternal", url: href });
          } catch (_e) {

          }
        });
      });

      const fbCountdown = document.getElementById("feedbackCountdown");
      const fbPrompt = document.getElementById("feedbackResubmitPrompt");
      const fbSuffix = document.getElementById("feedbackPromptSuffix");
      if (fbCountdown) {
        fbCountdown.addEventListener("change", () => {
          const v = normalizeFeedbackCountdown(fbCountdown.value);
          if (v === null) {
            fbCountdown.value = String(lastFeedbackCountdown);
            setSettingsHint(t("settings.hint.countdownInvalid"), true);
            return;
          }
          // show what the server will keep, not what was typed
          if (fbCountdown.value !== String(v)) fbCountdown.value = String(v);
          lastFeedbackCountdown = v;
          _queueFeedbackConfigSaveFromUi({ frontend_countdown: v });
        });
      }
      if (fbPrompt) {
        fbPrompt.addEventListener("input", () =>
          _queueFeedbackConfigSaveFromUi({ resubmit_prompt: fbPrompt.value }),
        );
      }
      if (fbSuffix) {
        fbSuffix.addEventListener("input", () =>
          _queueFeedbackConfigSaveFromUi({ prompt_suffix: fbSuffix.value }),
        );
      }

      const openConfigBtn = document.getElementById("settingsOpenConfigBtn");
      if (openConfigBtn) {
        openConfigBtn.addEventListener("click", (e) => {
          try {
            e.preventDefault();
            e.stopPropagation();
            const pathInput = document.getElementById("settingsConfigPath");
            const configPath =
              pathInput && pathInput.value ? String(pathInput.value).trim() : "";
            if (!configPath) return;
            postMessage({ type: "openConfigFile", path: configPath });
          } catch (_e) {

          }
        });
      }

      if (settingsOverlay) {
        settingsOverlay.addEventListener("click", (e) => {
          if (e.target === settingsOverlay) {
            closeSettingsOverlay();
          }
        });
      }
      if (settingsPanel) {
        settingsPanel.addEventListener("click", (e) => e.stopPropagation());

        const maybeMarkDirty = (e) => {
          const t = e && e.target;
          const id = t && t.id ? String(t.id) : "";
          if (!id || !id.startsWith("notify")) return;
          if (id === "notifyBarkEnabled") syncBarkFieldsVisibility();
          if (id === "notifyEnabled") syncChannelsMuted();
          markSettingsDirty();
        };
        settingsPanel.addEventListener("input", maybeMarkDirty);
        settingsPanel.addEventListener("change", maybeMarkDirty);
      }
      if (typeof document.addEventListener === "function") {
        document.addEventListener("keydown", onSettingsKeydown);
      }
    } catch (e) {

    }
  }

  async function loadFeedbackConfig() {
    if (!SERVER_URL) return;
    const loadEpoch = feedbackConfigEditEpoch;
    try {
      const resp = await fetch(SERVER_URL + "/api/get-feedback-prompts", {
        cache: "no-store",
      });
      if (!resp.ok) return;
      const data = await resp.json();
      if (data && data.status === "success") {
        const el = (id, v) => {
          const e = document.getElementById(id);
          if (e) e.value = v == null ? "" : String(v);
        };
        if (data.config) {
          const c = data.config;
          if (loadEpoch === feedbackConfigEditEpoch) {
            el("feedbackCountdown", c.frontend_countdown ?? 240);
            const held = normalizeFeedbackCountdown(c.frontend_countdown ?? 240);
            if (held !== null) lastFeedbackCountdown = held;
            el("feedbackResubmitPrompt", c.resubmit_prompt ?? "");
            el("feedbackPromptSuffix", c.prompt_suffix ?? "");
          }
        }
        if (data.meta && data.meta.config_file) {
          el("settingsConfigPath", data.meta.config_file);
        }
      }
    } catch (e) {

    }
  }

  function saveFeedbackConfig(updates) {
    if (!SERVER_URL) return;
    pendingFeedbackConfigUpdates = Object.assign(
      pendingFeedbackConfigUpdates || {},
      updates || {},
    );
    if (!feedbackConfigSavePromise) {
      feedbackConfigSavePromise = drainFeedbackConfigSaveQueue();
    }
    return feedbackConfigSavePromise;
  }

  async function drainFeedbackConfigSaveQueue() {
    let finalResult = null;
    try {
      while (pendingFeedbackConfigUpdates) {
        const updates = pendingFeedbackConfigUpdates;
        pendingFeedbackConfigUpdates = null;
        finalResult = await postFeedbackConfigUpdates(updates);
        if (!finalResult.ok && !pendingFeedbackConfigUpdates) {
          showFeedbackConfigSaveResult(finalResult);
          return;
        }
      }
      if (finalResult) {
        showFeedbackConfigSaveResult(finalResult);
      }
    } finally {
      feedbackConfigSavePromise = null;
    }
  }

  async function postFeedbackConfigUpdates(updates) {
    try {
      const resp = await fetch(SERVER_URL + "/api/update-feedback-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data.status === "success") {
        return { ok: true };
      }
      return {
        ok: false,
        message:
          t("settings.feedback.saveFailed") +
          " (" +
          (data.message || "HTTP " + resp.status) +
          ")",
      };
    } catch (e) {
      return {
        ok: false,
        message:
          t("settings.feedback.saveFailed") +
          (e && e.message ? " (" + e.message + ")" : ""),
      };
    }
  }

  function showFeedbackConfigSaveResult(result) {
    if (result && result.ok) {
      setSettingsHint(t("settings.feedback.saved"), false, 1200);
    } else {
      setSettingsHint(
        (result && result.message) || t("settings.feedback.saveFailed"),
        true,
      );
    }
  }

  function dispose() {
    try {
      _flushPendingFeedbackConfigSaveFromUi();
    } catch (e) {

    }
    try {
      stopSettingsAutoRefresh();
    } catch (e) {

    }
    try {
      if (settingsHintClearTimer) {
        clearTimeout(settingsHintClearTimer);
        settingsHintClearTimer = null;
      }
    } catch (e) {

    }
  }

  const api = {
    openSettings,
    closeSettingsOverlay,
    refreshNotificationSettingsFromServer,
    dispose,
  };

  try {
    globalThis.AIIAWebviewSettingsUi = api;
  } catch (e) {
    try {
      window.AIIAWebviewSettingsUi = api;
    } catch (_) {

    }
  }
})();
