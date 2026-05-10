/**
 * R139 — Feedback textarea per-task 草稿持久化（autosave）
 *
 * 背景
 * ----
 * 项目内已存在 ``window.taskTextareaContents`` 内存字典（``multi_task.
 * js`` 维护），多任务并发场景下用户切换 task 时会保留 textarea 内容
 * 不丢——但**仅在内存里**。一旦用户刷新页面 / 关闭浏览器 / 进程崩
 * 溃，所有 draft 全部丢失。``mcp-feedback-enhanced`` v2.4.x 把
 * "Auto-save drafts" 列入版本 highlight 是因为长 prompt 用户在拼接
 * 多段 LLM 输出 / 复制粘贴长技术文档时最怕 30 分钟手敲被刷新一键清
 * 零，autosave 让内容不再因刷新 / 崩溃而消失。
 *
 * R139 在不侵入既有 ``multi_task.js`` 的前提下，把 ``taskTextarea
 * Contents`` 状态持久化到 localStorage：
 *
 *   - 启动时一次性 hydrate localStorage → ``window.taskTextareaContents``
 *     （不覆盖既存内存 entry，避免 race）；
 *   - input 事件 debounce 500ms 写盘当前 task 的 draft；
 *   - 周期性（30s）把整个 ``taskTextareaContents`` reconcile 到磁盘
 *     兜底程序赋值 / clear / submit 后清空等非 input 事件路径；
 *   - TTL 7 天 + LRU 50 task 双重容量约束，避免 storage 无界增长。
 *
 * 设计原则
 * --------
 * - **不侵入 multi_task.js / app.js** — R139 走外挂监听（textarea input
 *   event + setInterval 周期 sync），既有代码零改动，避免 1300 行
 *   ``switchTask()`` / submit handler 引入回归风险。
 * - **TTL 7 天** — draft 内容可能含敏感信息（API key / 密码 / 私聊
 *   片段），TTL 限定让 stale draft 自动 expire。saved_at 距今超 7 天
 *   时 hydrate 自动跳过。
 * - **LRU 50 task** — saved_at desc 排序后保留最近 50 个 task draft，
 *   超出时 evict 最旧。50 是经验值（典型用户 1-2 周内活跃 task ≤30）。
 * - **graceful failure** — localStorage 不可用（Safari 隐私模式 /
 *   quota 满 / cookie 禁用）时全 try/catch silent no-op，主路径不挂。
 * - **schema_version envelope** — 与 R130 quick_phrases / R137 textarea-
 *   height 同款 ``aiia.<feature>.v<schema>`` 命名约定，未来 schema
 *   升级有迁移空间。
 */

(function () {
  "use strict";

  const STORAGE_KEY = "aiia.feedbackDrafts.v1";
  const SCHEMA_VERSION = 1;
  const TARGET_ID = "feedback-text";
  const TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 天
  const MAX_DRAFTS = 50;
  const INPUT_DEBOUNCE_MS = 500;
  const SYNC_INTERVAL_MS = 30 * 1000; // 30s 周期 reconcile

  function _now() {
    return Date.now();
  }

  function _isStorageAvailable() {
    try {
      const probe = "__aiia_drafts_probe__";
      localStorage.setItem(probe, "1");
      localStorage.removeItem(probe);
      return true;
    } catch (_e) {
      return false;
    }
  }

  function _readEnvelope() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      if (parsed.schema_version !== SCHEMA_VERSION) return null;
      const drafts = parsed.drafts;
      if (!drafts || typeof drafts !== "object") return null;
      return drafts;
    } catch (_e) {
      return null;
    }
  }

  function _writeEnvelope(drafts) {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          schema_version: SCHEMA_VERSION,
          drafts: drafts,
          saved_at: _now(),
        }),
      );
      return true;
    } catch (_e) {
      // localStorage 满 / 不可用：silent no-op
      return false;
    }
  }

  // 把单条 draft 规范化为 ``{ text, saved_at }``，过滤掉非法 entry
  function _normalizeDraft(entry) {
    if (!entry || typeof entry !== "object") return null;
    const text = entry.text;
    if (typeof text !== "string") return null;
    const savedAt =
      typeof entry.saved_at === "number" && Number.isFinite(entry.saved_at)
        ? entry.saved_at
        : 0;
    return { text: text, saved_at: savedAt };
  }

  // 应用 TTL + LRU 两道容量约束。先按 TTL 过滤，再按 saved_at desc
  // 截前 MAX_DRAFTS 条；返回新字典（不变更入参）。
  function _applyTtlAndLru(drafts) {
    const result = {};
    const fresh = [];
    const cutoff = _now() - TTL_MS;
    for (const taskId in drafts) {
      if (!Object.prototype.hasOwnProperty.call(drafts, taskId)) continue;
      const norm = _normalizeDraft(drafts[taskId]);
      if (norm === null) continue;
      if (norm.saved_at < cutoff) continue;
      fresh.push({ taskId: taskId, draft: norm });
    }
    fresh.sort(function (a, b) {
      return b.draft.saved_at - a.draft.saved_at;
    });
    const kept = fresh.slice(0, MAX_DRAFTS);
    for (let i = 0; i < kept.length; i++) {
      result[kept[i].taskId] = kept[i].draft;
    }
    return result;
  }

  function loadAllDrafts() {
    const drafts = _readEnvelope();
    if (drafts === null) return {};
    return _applyTtlAndLru(drafts);
  }

  function getDraft(taskId) {
    if (typeof taskId !== "string" || !taskId) return null;
    const all = loadAllDrafts();
    if (!Object.prototype.hasOwnProperty.call(all, taskId)) return null;
    return all[taskId].text;
  }

  function saveDraft(taskId, text) {
    if (typeof taskId !== "string" || !taskId) return false;
    if (typeof text !== "string") return false;
    if (!_isStorageAvailable()) return false;
    const drafts = _readEnvelope() || {};
    if (text === "") {
      delete drafts[taskId];
    } else {
      drafts[taskId] = { text: text, saved_at: _now() };
    }
    const trimmed = _applyTtlAndLru(drafts);
    return _writeEnvelope(trimmed);
  }

  function clearDraft(taskId) {
    return saveDraft(taskId, "");
  }

  function clearAllDrafts() {
    if (!_isStorageAvailable()) return false;
    try {
      localStorage.removeItem(STORAGE_KEY);
      return true;
    } catch (_e) {
      return false;
    }
  }

  // 把 storage 里的 drafts hydrate 到 ``window.taskTextareaContents``
  // 字典；既存内存项**不覆盖**（避免 race：multi_task.js 可能已经在
  // 初始化阶段填充了 active task 的内容）。返回 hydrate 的条目数。
  function hydrateMemoryCache() {
    const drafts = loadAllDrafts();
    if (typeof window === "undefined") return 0;
    if (typeof window.taskTextareaContents !== "object" ||
        window.taskTextareaContents === null) {
      window.taskTextareaContents = {};
    }
    let hydrated = 0;
    for (const taskId in drafts) {
      if (!Object.prototype.hasOwnProperty.call(drafts, taskId)) continue;
      if (Object.prototype.hasOwnProperty.call(
        window.taskTextareaContents,
        taskId,
      )) {
        continue;
      }
      window.taskTextareaContents[taskId] = drafts[taskId].text;
      hydrated += 1;
    }
    return hydrated;
  }

  // 把 ``window.taskTextareaContents`` 内存状态全量写回 storage
  // （兜底程序赋值 / clear / submit 后清空等非 input 路径）。
  function reconcileMemoryToStorage() {
    if (typeof window === "undefined") return false;
    const memoryDrafts = window.taskTextareaContents;
    if (typeof memoryDrafts !== "object" || memoryDrafts === null) {
      return false;
    }
    const existing = _readEnvelope() || {};
    const merged = {};
    // 内存状态优先；text 非空才写盘
    for (const taskId in memoryDrafts) {
      if (!Object.prototype.hasOwnProperty.call(memoryDrafts, taskId)) continue;
      const text = memoryDrafts[taskId];
      if (typeof text !== "string" || text === "") continue;
      const prev = _normalizeDraft(existing[taskId]);
      const savedAt = prev !== null && prev.text === text
        ? prev.saved_at
        : _now();
      merged[taskId] = { text: text, saved_at: savedAt };
    }
    const trimmed = _applyTtlAndLru(merged);
    return _writeEnvelope(trimmed);
  }

  function _getActiveTaskId() {
    if (typeof window === "undefined") return null;
    const id = window.activeTaskId;
    if (typeof id !== "string" || !id) return null;
    return id;
  }

  function setupInputListener() {
    const textarea = document.getElementById(TARGET_ID);
    if (!textarea) return null;
    let timeoutId = null;
    const handler = function () {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      timeoutId = setTimeout(function () {
        timeoutId = null;
        const taskId = _getActiveTaskId();
        if (taskId === null) return;
        saveDraft(taskId, textarea.value || "");
      }, INPUT_DEBOUNCE_MS);
    };
    textarea.addEventListener("input", handler);
    return { textarea: textarea, handler: handler };
  }

  function setupPeriodicSync() {
    if (typeof setInterval !== "function") return null;
    const intervalId = setInterval(reconcileMemoryToStorage, SYNC_INTERVAL_MS);
    return intervalId;
  }

  function init() {
    if (!_isStorageAvailable()) return null;
    // 先 hydrate 让 multi_task.js 的 switchTask 能命中 storage 里的
    // 历史 draft；如果 multi_task.js 已经初始化（罕见时序），则
    // hydrateMemoryCache 跳过既存项不覆盖。
    hydrateMemoryCache();
    const inputHandle = setupInputListener();
    const intervalId = setupPeriodicSync();
    return { input: inputHandle, intervalId: intervalId };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AIIA_FEEDBACK_DRAFTS = {
    STORAGE_KEY: STORAGE_KEY,
    SCHEMA_VERSION: SCHEMA_VERSION,
    TARGET_ID: TARGET_ID,
    TTL_MS: TTL_MS,
    MAX_DRAFTS: MAX_DRAFTS,
    INPUT_DEBOUNCE_MS: INPUT_DEBOUNCE_MS,
    SYNC_INTERVAL_MS: SYNC_INTERVAL_MS,
    loadAllDrafts: loadAllDrafts,
    getDraft: getDraft,
    saveDraft: saveDraft,
    clearDraft: clearDraft,
    clearAllDrafts: clearAllDrafts,
    hydrateMemoryCache: hydrateMemoryCache,
    reconcileMemoryToStorage: reconcileMemoryToStorage,
    _applyTtlAndLru: _applyTtlAndLru,
    _normalizeDraft: _normalizeDraft,
    _isStorageAvailable: _isStorageAvailable,
    init: init,
  };
})();
