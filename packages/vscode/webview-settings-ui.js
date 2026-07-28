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

  function openSettingsOverlay() {
    const overlay = document.getElementById("settingsOverlay");
    if (overlay) overlay.classList.remove("hidden");
    startSettingsAutoRefresh();
  }

  function closeSettingsOverlay() {
    flushSettingsAutoSaveBeforeClose();
    _flushPendingFeedbackConfigSaveFromUi();
    const overlay = document.getElementById("settingsOverlay");
    if (overlay) overlay.classList.add("hidden");
    stopSettingsAutoRefresh({ preserveAutoSave: true });
    setSettingsHint("", false);
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

  function testMacOSNativeNotification() {
    try {
      const updates = collectSettingsForm();
      if (updates && updates.enabled === false) {
        setSettingsHint(t("settings.hint.notifyDisabled"), true);
        return;
      }
      if (!updates || !updates.macosNativeEnabled) {
        setSettingsHint(t("settings.hint.macosNotEnabled"), true, 2000);
      } else {
        setSettingsHint(t("settings.hint.macosTestTriggered"), false, 2000);
      }

      const posted = postMessage({
        type: "notify",
        event: {
          title: t("settings.test.macosTitle"),
          message: t("settings.test.macosMessage"),
          trigger: "immediate",
          types: ["macos_native"],
          metadata: {
            isTest: true,
            diagnostic: true,
            kind: "test_macos_native",
          },
          source: "webview-settings-ui",
          dedupeKey: "test:macos_native",
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
      } catch (_e) {
        item.hidden = true;
      }
    };

    if (recheckBtn) {
      recheckBtn.addEventListener("click", () => {
        renderStatus();
      });
    }
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        const url =
          copyBtn.dataset && copyBtn.dataset.lanUrl
            ? copyBtn.dataset.lanUrl
            : "";
        if (!url) return;
        try {
          if (
            navigator &&
            navigator.clipboard &&
            navigator.clipboard.writeText
          ) {
            await navigator.clipboard.writeText(url);
          } else {
            const ta = document.createElement("textarea");
            ta.value = url;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            try {
              document.execCommand("copy");
            } finally {
              document.body.removeChild(ta);
            }
          }
          const original = copyBtn.textContent;
          copyBtn.textContent = t("settings.bark.baseUrlCopied");
          setTimeout(() => {
            copyBtn.textContent = original;
          }, 1500);
        } catch (_e) {

        }
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
      const settingsTestNativeBtn = document.getElementById(
        "settingsTestNativeBtn",
      );
      const settingsTestBarkBtn = document.getElementById(
        "settingsTestBarkBtn",
      );

      if (settingsClose)
        settingsClose.addEventListener("click", closeSettingsOverlay);
      if (settingsTestNativeBtn)
        settingsTestNativeBtn.addEventListener(
          "click",
          testMacOSNativeNotification,
        );
      if (settingsTestBarkBtn)
        settingsTestBarkBtn.addEventListener("click", testBark);

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
          const v = parseInt(fbCountdown.value, 10);

          if (!isNaN(v) && v >= 0 && v <= 3600)
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
          markSettingsDirty();
        };
        settingsPanel.addEventListener("input", maybeMarkDirty);
        settingsPanel.addEventListener("change", maybeMarkDirty);
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
