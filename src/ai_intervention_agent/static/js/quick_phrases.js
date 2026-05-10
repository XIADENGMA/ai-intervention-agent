/**
 * Quick Phrases / 常用回复（R130）
 *
 * @description
 *   反馈输入框上方的「常用回复」面板：把高频文本片段（"继续"、
 *   "这个方案不错"、"修复这个 bug" 等）持久化到 localStorage，
 *   单击 chip 即把内容追加到 #feedback-text 末尾，避免反复手敲。
 *
 *   竞品对齐：
 *     - mcp-feedback-enhanced 的「Prompt Management / Quick Replies」
 *     - imhuso/cunzhi 的「常用回复和快捷面板」
 *
 *   设计原则：
 *     1. **纯前端 + localStorage**：零后端 API、零 schema 漂移、
 *        卸载后端不影响 UI 已有数据。
 *     2. **单一职责**：只负责片段 CRUD + 插入文本到 textarea；
 *        不染指任务状态 / 配置 / 通知。
 *     3. **失败优雅降级**：localStorage 不可用（隐身模式 / 配额满 /
 *        浏览器禁用）时面板自动隐藏，不让运行时炸面板。
 *     4. **零 innerHTML**：所有 chip / 按钮 / 输入框走 createElement +
 *        textContent，遵循项目 R71-CSP / DOMSecurity 防 XSS 基线。
 *     5. **i18n 全覆盖**：所有可见文案走 window.AIIA_I18N.t；fallback
 *        到内置中文，保证 i18n 模块加载前面板首次渲染也不会显示
 *        裸 key。
 *
 *   存储格式（localStorage key: ``aiia.quickPhrases.v1``）：
 *     {
 *       "schema_version": 1,
 *       "phrases": [
 *         {
 *           "id": "qp_1715000000000_a3f",   // 时间戳 + 3 位随机
 *           "label": "继续",                  // ≤ 30 字（trim 后）
 *           "text": "请继续完成剩下的任务",      // ≤ 2000 字（trim 后）
 *           "created_at": 1715000000000      // ms epoch
 *         },
 *         ...
 *       ]
 *     }
 *
 *   容量上限：20 条 phrase，避免 localStorage 失控（5 MB 配额是
 *   单 origin 共享池）。
 */

(function () {
  "use strict";

  // ============================================================================
  // 常量
  // ============================================================================

  /** localStorage key（v1：未来 schema 升级时改 v2 / v3 …，旧 key 自动失效） */
  var STORAGE_KEY = "aiia.quickPhrases.v1";
  /** 当前 schema 版本（数据 reader 用此字段判断是否需要 migrate） */
  var SCHEMA_VERSION = 1;
  /** label 字段长度上限（trim 后） */
  var LABEL_MAX_LEN = 30;
  /** text 字段长度上限（trim 后） */
  var TEXT_MAX_LEN = 2000;
  /** 单个 origin 最多保存的 phrase 条数 */
  var MAX_PHRASES = 20;

  // ============================================================================
  // i18n helper（与 dom-security.js / validation-utils.js 同模式）
  // ============================================================================

  /**
   * 获取本地化文案；i18n 模块尚未加载时回退到内置英文兜底。
   *
   * 英文兜底是为了**首次渲染**也不显示裸 key —— 实际 zh-CN / en
   * 文案走 ``static/locales/*.json``，``i18n.init()`` 完成后通过
   * ``applyTranslationsToDOM`` 自动覆盖。这里特意不用中文兜底，
   * 配合 ``check_i18n_js_no_cjk.py`` 守门，让 JS 源里零硬编码
   * 中文，符合项目 i18n 策略。
   */
  var FALLBACK_TEXT = {
    "quickPhrases.label": "Quick replies",
    "quickPhrases.addBtn": "Add",
    "quickPhrases.addBtnAriaLabel": "Add quick reply",
    "quickPhrases.empty": 'No quick replies yet. Click "Add" to create one.',
    "quickPhrases.disabled": "Local storage unavailable; quick replies disabled.",
    "quickPhrases.formLabelPlaceholder": "Label (max 30 chars)",
    "quickPhrases.formTextPlaceholder": "Content (max 2000 chars)",
    "quickPhrases.formSave": "Save",
    "quickPhrases.formCancel": "Cancel",
    "quickPhrases.deleteBtnAriaLabel": "Delete quick reply",
    "quickPhrases.editBtnAriaLabel": "Edit quick reply",
    "quickPhrases.chipTitle": "Click to insert into feedback",
    "quickPhrases.errorLabelEmpty": "Label cannot be empty",
    "quickPhrases.errorTextEmpty": "Content cannot be empty",
    "quickPhrases.errorLabelTooLong": "Label is longer than 30 characters",
    "quickPhrases.errorTextTooLong": "Content is longer than 2000 characters",
    "quickPhrases.errorTooMany": "At most 20 quick replies can be saved",
    "quickPhrases.confirmDelete": "Delete '{{label}}'?",
  };

  // 项目 i18n runtime 只识别 ``{{name}}`` 双花括号 Mustache 语法（详见
  // ``static/js/i18n.js::_interpolateMustache``）。本模块的 fallback 路径
  // 与之保持完全一致，避免 i18n 加载前后行为漂移。
  function _t(key, params) {
    try {
      if (
        typeof window !== "undefined" &&
        window.AIIA_I18N &&
        typeof window.AIIA_I18N.t === "function"
      ) {
        var v = window.AIIA_I18N.t(key, params);
        if (v && v !== key) return v;
      }
    } catch (_e) {
      /* fallback 路径见下方 */
    }
    var fb = FALLBACK_TEXT[key];
    if (typeof fb !== "string") return key;
    if (!params) return fb;
    return fb.replace(/\{\{(\w+)\}\}/g, function (_m, k) {
      return params[k] != null ? String(params[k]) : "";
    });
  }

  // ============================================================================
  // localStorage 读写（带损坏自愈）
  // ============================================================================

  /**
   * localStorage 是否可用（部分浏览器隐身模式或被禁用时 setItem 直接抛错）。
   * 检测一次缓存到模块作用域，避免反复 try/catch 触发 quota 弹窗。
   */
  var _storageAvailable = null;
  function isStorageAvailable() {
    if (_storageAvailable !== null) return _storageAvailable;
    try {
      var probeKey = "__aiia_qp_probe__";
      window.localStorage.setItem(probeKey, "1");
      window.localStorage.removeItem(probeKey);
      _storageAvailable = true;
    } catch (_e) {
      _storageAvailable = false;
    }
    return _storageAvailable;
  }

  /**
   * 从 localStorage 读取 phrase 数组；任何解析失败 / schema 不匹配
   * 都返回空数组，让 UI 走「空列表」路径。**不抛错**——保证主流程
   * 鲁棒。
   */
  function loadPhrases() {
    if (!isStorageAvailable()) return [];
    var raw;
    try {
      raw = window.localStorage.getItem(STORAGE_KEY);
    } catch (_e) {
      return [];
    }
    if (raw == null) return [];
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (_e) {
      return [];
    }
    if (!parsed || typeof parsed !== "object") return [];
    if (parsed.schema_version !== SCHEMA_VERSION) return [];
    if (!Array.isArray(parsed.phrases)) return [];
    return parsed.phrases.filter(function (p) {
      return (
        p &&
        typeof p === "object" &&
        typeof p.id === "string" &&
        typeof p.label === "string" &&
        typeof p.text === "string"
      );
    });
  }

  /**
   * 把 phrase 数组写回 localStorage。配额满 / disabled 时静默失败
   * （配合 isStorageAvailable() 已经把面板隐藏，此处 return false
   * 给 caller 看到失败，但不抛错以免破坏 UI 主流程）。
   */
  function savePhrases(phrases) {
    if (!isStorageAvailable()) return false;
    var payload = {
      schema_version: SCHEMA_VERSION,
      phrases: phrases,
    };
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      return true;
    } catch (_e) {
      return false;
    }
  }

  /**
   * 生成 phrase id：时间戳 (ms) + 3 位 base36 随机后缀，防止同一毫秒
   * 内连续 add 撞 id。不依赖 crypto.randomUUID（旧浏览器 / 某些
   * webview 没有）。
   */
  function generateId() {
    var ts = Date.now();
    var rand = Math.floor(Math.random() * 46656).toString(36);
    while (rand.length < 3) rand = "0" + rand;
    return "qp_" + ts + "_" + rand;
  }

  // ============================================================================
  // 校验：trim + 长度上限 + 容量上限
  // ============================================================================

  // 5 条错误 key 直接走字面量 ``_t("...")`` 调用，让 i18n orphan/param
  // 扫描器（``scripts/check_i18n_orphan_keys.py`` /
  // ``check_i18n_param_signatures.py``）都能静态识别。如果改成
  // ``return { key: dyn }; _t(dyn)``，扫描器看到的 ``_t(...)`` 不是
  // literal key 调用就会判这 5 条是 orphan。
  function validatePhraseInput(label, text, currentCount) {
    var trimmedLabel = String(label || "").trim();
    var trimmedText = String(text || "").trim();
    if (!trimmedLabel) {
      return { ok: false, message: _t("quickPhrases.errorLabelEmpty") };
    }
    if (!trimmedText) {
      return { ok: false, message: _t("quickPhrases.errorTextEmpty") };
    }
    if (trimmedLabel.length > LABEL_MAX_LEN) {
      return { ok: false, message: _t("quickPhrases.errorLabelTooLong") };
    }
    if (trimmedText.length > TEXT_MAX_LEN) {
      return { ok: false, message: _t("quickPhrases.errorTextTooLong") };
    }
    if (currentCount >= MAX_PHRASES) {
      return { ok: false, message: _t("quickPhrases.errorTooMany") };
    }
    return { ok: true, label: trimmedLabel, text: trimmedText };
  }

  // ============================================================================
  // 文本插入：在 #feedback-text 当前光标位置插入，选中文本会被替换；
  // 触发 input 事件让 multi_task 的 taskTextareaContents 同步保存。
  // ============================================================================

  /**
   * 把 text 插入到 ``#feedback-text`` 的当前光标位置；如果用户已经选
   * 中一段文本（``selectionStart !== selectionEnd``），选区内的旧文本
   * 会被新 text 替换；插入完成后光标停在新插入文本之后，方便继续输入。
   *
   * R131 之前（R130 v1）的实现是无脑追加到末尾，破坏选区上下文。
   * R131 改为「光标位置插入」更接近 mcp-feedback-enhanced 的
   * Quick Replies 与 cunzhi「常用回复」的体验。
   *
   * 边界保护：
   * - textarea 不存在 → no-op，返回 false（init 阶段防御）
   * - 老浏览器不支持 ``selectionStart`` → fallback 到末尾追加 +
   *   插入前后必要换行，与 R130 v1 行为一致
   * - dispatchEvent ``new Event(...)`` 在 IE 等老引擎抛错 → fallback
   *   到 ``document.createEvent``
   */
  function insertTextIntoFeedback(text) {
    var textarea = document.getElementById("feedback-text");
    if (!textarea) return false;
    var current = textarea.value || "";

    var hasSelectionApi =
      typeof textarea.selectionStart === "number" &&
      typeof textarea.selectionEnd === "number";

    var newValue;
    var newCursorPos;
    if (hasSelectionApi) {
      var start = textarea.selectionStart;
      var end = textarea.selectionEnd;
      newValue =
        current.substring(0, start) + text + current.substring(end);
      newCursorPos = start + text.length;
    } else {
      // 老引擎兜底：保留 R130 v1「追加到末尾」语义
      var prefix = "";
      if (current.length > 0 && !current.endsWith("\n")) {
        prefix = "\n";
      }
      newValue = current + prefix + text;
      newCursorPos = newValue.length;
    }

    textarea.value = newValue;
    var event;
    try {
      event = new Event("input", { bubbles: true });
    } catch (_e) {
      event = document.createEvent("Event");
      event.initEvent("input", true, true);
    }
    textarea.dispatchEvent(event);
    textarea.focus();
    try {
      textarea.setSelectionRange(newCursorPos, newCursorPos);
    } catch (_e) {
      /* 老浏览器不支持 setSelectionRange，忽略 */
    }
    return true;
  }

  // ============================================================================
  // 渲染
  // ============================================================================

  /**
   * 重新渲染整个 list（chip + 空状态文案）。每次状态变更后调用。
   *
   * 性能：phrase 上限 20 条，每次重渲只产生 ≤ 20 个 DOM 节点，
   * 远低于 16 ms/帧成本。无需 diff。
   */
  function renderList() {
    var listEl = document.getElementById("quick-phrases-list");
    if (!listEl) return;
    while (listEl.firstChild) listEl.removeChild(listEl.firstChild);

    var phrases = loadPhrases();
    if (phrases.length === 0) {
      var empty = document.createElement("span");
      empty.className = "quick-phrases-empty";
      empty.textContent = _t("quickPhrases.empty");
      empty.setAttribute("data-i18n", "quickPhrases.empty");
      listEl.appendChild(empty);
      return;
    }

    phrases.forEach(function (p) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "quick-phrase-chip";
      chip.setAttribute("data-phrase-id", p.id);
      chip.setAttribute("title", _t("quickPhrases.chipTitle"));
      chip.textContent = p.label;
      chip.addEventListener("click", function (e) {
        e.preventDefault();
        insertTextIntoFeedback(p.text);
      });

      // R131 — chip 上的 ✎ 编辑按钮：进入内嵌编辑模式
      var edit = document.createElement("button");
      edit.type = "button";
      edit.className = "quick-phrase-chip-edit";
      edit.setAttribute("aria-label", _t("quickPhrases.editBtnAriaLabel"));
      edit.setAttribute(
        "data-i18n-aria-label",
        "quickPhrases.editBtnAriaLabel"
      );
      edit.setAttribute("title", _t("quickPhrases.editBtnAriaLabel"));
      edit.textContent = "\u270e"; // ✎ pencil — 不会被 check_i18n_js_no_cjk 误报，是 BMP 拉丁补充
      edit.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        openEditForm(p.id);
      });

      var del = document.createElement("button");
      del.type = "button";
      del.className = "quick-phrase-chip-delete";
      del.setAttribute("aria-label", _t("quickPhrases.deleteBtnAriaLabel"));
      del.setAttribute(
        "data-i18n-aria-label",
        "quickPhrases.deleteBtnAriaLabel"
      );
      del.textContent = "\u00d7"; // × multiplication sign（与 page.removeImage 同款符号）
      del.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var msg = _t("quickPhrases.confirmDelete", { label: p.label });
        if (typeof window.confirm === "function" && !window.confirm(msg)) {
          return;
        }
        deletePhrase(p.id);
      });

      var wrap = document.createElement("span");
      wrap.className = "quick-phrase-chip-wrap";
      wrap.appendChild(chip);
      wrap.appendChild(edit);
      wrap.appendChild(del);
      listEl.appendChild(wrap);
    });
  }

  /**
   * 公共 form 渲染：``mode = "add" | "edit"``。
   *
   * - ``add`` 模式：label / text 起始空白；保存时 push 一个新 phrase
   *   （受 MAX_PHRASES 容量上限约束）。
   * - ``edit`` 模式：label / text 起始填入既有 phrase；保存时
   *   ``editPhrase`` 替换同 id 的 label / text，但保留 created_at /
   *   id 不变（避免破坏未来排序逻辑）。
   *
   * 同一时刻最多一个内嵌 form——重复触发会复用既有 form 并
   * focus 到 label input；切换 mode 时先 close 旧 form 再开新的。
   */
  function _openForm(mode, phrase) {
    var formHost = document.getElementById("quick-phrases-form-host");
    if (!formHost) return;
    var existing = formHost.querySelector(".quick-phrases-form");
    if (existing) {
      // 同 mode + 同 phrase 复用；其他情况清空重建
      var existingMode = existing.dataset.qpMode || "add";
      var existingId = existing.dataset.qpEditId || "";
      var nextId = phrase ? phrase.id : "";
      if (existingMode === mode && existingId === nextId) {
        var firstField = existing.querySelector("input, textarea");
        if (firstField) firstField.focus();
        return;
      }
      closeAddForm();
    }

    var form = document.createElement("div");
    form.className = "quick-phrases-form";
    form.dataset.qpMode = mode;
    if (mode === "edit" && phrase) {
      form.dataset.qpEditId = phrase.id;
    }

    var labelInput = document.createElement("input");
    labelInput.type = "text";
    labelInput.className = "quick-phrases-form-label";
    labelInput.maxLength = LABEL_MAX_LEN;
    labelInput.placeholder = _t("quickPhrases.formLabelPlaceholder");
    labelInput.setAttribute(
      "data-i18n-placeholder",
      "quickPhrases.formLabelPlaceholder"
    );
    if (phrase) labelInput.value = phrase.label;

    var textInput = document.createElement("textarea");
    textInput.className = "quick-phrases-form-text";
    textInput.maxLength = TEXT_MAX_LEN;
    textInput.rows = 3;
    textInput.placeholder = _t("quickPhrases.formTextPlaceholder");
    textInput.setAttribute(
      "data-i18n-placeholder",
      "quickPhrases.formTextPlaceholder"
    );
    if (phrase) textInput.value = phrase.text;

    var error = document.createElement("div");
    error.className = "quick-phrases-form-error";
    error.setAttribute("role", "alert");

    var btnRow = document.createElement("div");
    btnRow.className = "quick-phrases-form-actions";

    var saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "quick-phrases-form-save";
    saveBtn.textContent = _t("quickPhrases.formSave");
    saveBtn.setAttribute("data-i18n", "quickPhrases.formSave");

    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "quick-phrases-form-cancel";
    cancelBtn.textContent = _t("quickPhrases.formCancel");
    cancelBtn.setAttribute("data-i18n", "quickPhrases.formCancel");

    btnRow.appendChild(saveBtn);
    btnRow.appendChild(cancelBtn);

    form.appendChild(labelInput);
    form.appendChild(textInput);
    form.appendChild(error);
    form.appendChild(btnRow);
    formHost.appendChild(form);

    labelInput.focus();
    if (mode === "edit") {
      // 进入编辑时让光标停在 text 末尾，方便用户继续编辑
      try {
        textInput.setSelectionRange(textInput.value.length, textInput.value.length);
      } catch (_e) {
        /* 老浏览器忽略 */
      }
    }

    saveBtn.addEventListener("click", function () {
      error.textContent = "";
      // edit 模式不计入容量上限校验（替换不增加条数）
      var capCount = mode === "edit" ? 0 : loadPhrases().length;
      var validation = validatePhraseInput(
        labelInput.value,
        textInput.value,
        capCount
      );
      if (!validation.ok) {
        error.textContent = validation.message;
        return;
      }
      if (mode === "edit" && phrase) {
        editPhrase(phrase.id, validation.label, validation.text);
      } else {
        addPhrase(validation.label, validation.text);
      }
      closeAddForm();
    });

    cancelBtn.addEventListener("click", function () {
      closeAddForm();
    });

    labelInput.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeAddForm();
    });
    textInput.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeAddForm();
    });
  }

  function openAddForm() {
    _openForm("add", null);
  }

  function openEditForm(id) {
    var phrase = loadPhrases().find(function (p) {
      return p.id === id;
    });
    if (!phrase) return;
    _openForm("edit", phrase);
  }

  function closeAddForm() {
    var formHost = document.getElementById("quick-phrases-form-host");
    if (!formHost) return;
    while (formHost.firstChild) formHost.removeChild(formHost.firstChild);
  }

  // ============================================================================
  // CRUD（公开 + 内部都共用）
  // ============================================================================

  function addPhrase(label, text) {
    var phrases = loadPhrases();
    if (phrases.length >= MAX_PHRASES) return false;
    phrases.push({
      id: generateId(),
      label: label,
      text: text,
      created_at: Date.now(),
    });
    var ok = savePhrases(phrases);
    if (ok) renderList();
    return ok;
  }

  function deletePhrase(id) {
    var phrases = loadPhrases();
    var filtered = phrases.filter(function (p) {
      return p.id !== id;
    });
    if (filtered.length === phrases.length) return false;
    var ok = savePhrases(filtered);
    if (ok) renderList();
    return ok;
  }

  /**
   * 替换同 id phrase 的 label / text（id 与 created_at 保持不变，
   * 让"编辑"看起来像就地更新而不是删除重建）。caller 应当先走
   * ``validatePhraseInput`` 校验过 label / text，本函数只负责存储。
   */
  function editPhrase(id, label, text) {
    var phrases = loadPhrases();
    var found = false;
    for (var i = 0; i < phrases.length; i += 1) {
      if (phrases[i].id === id) {
        phrases[i].label = label;
        phrases[i].text = text;
        found = true;
        break;
      }
    }
    if (!found) return false;
    var ok = savePhrases(phrases);
    if (ok) renderList();
    return ok;
  }

  // ============================================================================
  // 初始化：DOMContentLoaded 之后挂事件 + 首次渲染
  // ============================================================================

  function bindEventsOnce() {
    var addBtn = document.getElementById("quick-phrases-add-btn");
    if (addBtn && !addBtn.dataset.qpBound) {
      addBtn.addEventListener("click", function (e) {
        e.preventDefault();
        openAddForm();
      });
      addBtn.dataset.qpBound = "1";
    }
  }

  function init() {
    var container = document.getElementById("quick-phrases-container");
    if (!container) return;
    if (!isStorageAvailable()) {
      container.classList.add("quick-phrases-disabled");
      var listEl = document.getElementById("quick-phrases-list");
      if (listEl) {
        while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
        var note = document.createElement("span");
        note.className = "quick-phrases-empty";
        note.textContent = _t("quickPhrases.disabled");
        note.setAttribute("data-i18n", "quickPhrases.disabled");
        listEl.appendChild(note);
      }
      var addBtn = document.getElementById("quick-phrases-add-btn");
      if (addBtn) addBtn.disabled = true;
      return;
    }
    bindEventsOnce();
    renderList();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // ============================================================================
  // 公开 API（仅给测试 / 调试 / 未来 R131 编辑功能用，不进入业务热路径）
  // ============================================================================

  window.AIIA_QUICK_PHRASES = {
    STORAGE_KEY: STORAGE_KEY,
    SCHEMA_VERSION: SCHEMA_VERSION,
    LABEL_MAX_LEN: LABEL_MAX_LEN,
    TEXT_MAX_LEN: TEXT_MAX_LEN,
    MAX_PHRASES: MAX_PHRASES,
    loadPhrases: loadPhrases,
    savePhrases: savePhrases,
    addPhrase: addPhrase,
    deletePhrase: deletePhrase,
    editPhrase: editPhrase,
    insertTextIntoFeedback: insertTextIntoFeedback,
    validatePhraseInput: validatePhraseInput,
    renderList: renderList,
    openAddForm: openAddForm,
    openEditForm: openEditForm,
    closeAddForm: closeAddForm,
    init: init,
  };
})();
