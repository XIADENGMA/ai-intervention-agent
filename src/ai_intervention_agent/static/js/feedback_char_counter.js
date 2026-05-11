/**
 * R138 — Feedback textarea 字符计数器
 *
 * 背景
 * ----
 * ``mcp-feedback-enhanced`` v2.4.x 把 character counter 列入版本
 * highlight：长 prompt 用户在拼接多段 LLM 输出 / 复制粘贴长技术
 * 文档时常常超出心理预期，counter 让"输入长度"这条不可见维度变
 * 显式，避免误超出后端 / Bark 通知的隐性 size 约束。
 *
 * 项目里既有 ``feedback-resubmit-prompt`` / ``feedback-prompt-suffix``
 * textarea 已经用 ``maxlength="100000"`` 做硬约束（R166 与 ``PROMPT_MAX_LENGTH``
 * 对齐）——R138 把视觉警告阈值用作主输入框 (#feedback-text) 的 advisory
 * warning，不强加 maxlength（避免截断用户内容造成数据丢失），仅做视觉提示。
 *
 * 设计原则
 * --------
 * - 纯前端、无服务端状态、无 localStorage（不污染用户痕迹）。
 * - count == 0 时隐藏 counter（避免空 textarea 时显示 ``0`` 喧宾夺主）。
 * - 三段阈值变色：默认 → ``warn`` (橘) → ``danger`` (红)，提供视觉
 *   渐进信号；R166 后阈值与服务端 ``MAX_MESSAGE_LENGTH=1_000_000`` 软上限对齐。
 * - 监听 ``input`` 事件涵盖 paste / cut / drag / IME composition end
 *   全场景；初始化时算一次，应对 R137 height restore + 外部
 *   setValue 等非 input 事件的初始化路径。
 * - ``aria-live="polite"`` 让屏幕阅读器只在用户停顿时念字数，不打
 *   断主流程；不用 ``assertive`` 避免每次输入都触发朗读。
 * - 字符计数用 ``textarea.value.length``（UTF-16 code unit），与
 *   后端 ``len(feedback_text)`` 计算口径一致；不做 grapheme cluster
 *   split，避免引入 ``Intl.Segmenter`` 增加 polyfill 体积，且对
 *   warning 阈值精度无实质影响。
 */

(function () {
  "use strict";

  const TARGET_ID = "feedback-text";
  const COUNTER_ID = "feedback-char-counter";
  // R166：与服务端 ``MAX_MESSAGE_LENGTH`` 软上限对齐。
  // 旧值 WARN=8000 / DANGER=10000 已经低于 LLM 长上下文 / 用户粘贴长技术
  // 文档的合理上限；按 R166 把后端软上限抬到 1_000_000 字符（~1MB UTF-8），
  // 前端 counter 也跟随放大到同量级，避免出现"还远没到后端硬上限就被
  // counter 标红"的误导。视觉阈值仍按 80% / 100% 比例分段，给用户渐进信号。
  const WARN_THRESHOLD = 800_000;
  const DANGER_THRESHOLD = 1_000_000;
  const WARN_CLASS = "warn";
  const DANGER_CLASS = "danger";
  const I18N_KEY = "feedback.charCounter";

  function _formatCount(count) {
    // 大数字本地化：用 Intl.NumberFormat 让千位分隔符自动适配
    // zh-CN / en 都正确（zh: 8,000 / en: 8,000）。
    if (typeof Intl !== "undefined" && Intl.NumberFormat) {
      try {
        return new Intl.NumberFormat().format(count);
      } catch (_e) {
        return String(count);
      }
    }
    return String(count);
  }

  // 与 quick_phrases.js / app.js 同款 i18n fallback：runtime 缺失 /
  // i18n 加载前页面已就绪等罕见路径下，用模块内 FALLBACK_TEXT 兜底，
  // 走 ``{{count}}`` mustache 替换与 ``static/js/i18n.js::
  // _interpolateMustache`` 完全一致。fallback 用英文与项目级 i18n
  // 默认 base locale 对齐（``test_i18n_js_no_hardcoded_cjk`` 护栏：
  // JS 内禁中文字面值，CJK 必须走 locale 文件）。
  const FALLBACK_TEXT = {
    "feedback.charCounter": "{{count}} chars",
  };

  // 模块内 ``_t`` helper，与 quick_phrases.js / app.js 同款实现。
  // 走顶层 helper 名（不是 ``window.AIIA_I18N.t`` 字面调用）让 i18n
  // orphan / dead-key 扫描器（``scripts/check_i18n_orphan_keys.py::
  // JS_T_CALL_RE``）能匹配模块内 helper 的字面 key 调用形式，避免
  // 常量 ``I18N_KEY`` indirect 调用让扫描器漏识别。
  function _t(key, params) {
    try {
      if (
        typeof window !== "undefined" &&
        window.AIIA_I18N &&
        typeof window.AIIA_I18N.t === "function"
      ) {
        const v = window.AIIA_I18N.t(key, params);
        if (typeof v === "string" && v && v !== key) return v;
      }
    } catch (_e) {
      /* fallback 路径见下方 */
    }
    const fb = FALLBACK_TEXT[key];
    if (typeof fb !== "string") return key;
    if (!params) return fb;
    return fb.replace(/\{\{(\w+)\}\}/g, function (_m, k) {
      return params[k] != null ? String(params[k]) : "";
    });
  }

  function _resolveLabel(count) {
    const formatted = _formatCount(count);
    return _t("feedback.charCounter", { count: formatted });
  }

  function _applyThresholdClass(node, count) {
    if (!node || !node.classList) return;
    node.classList.remove(WARN_CLASS, DANGER_CLASS);
    if (count >= DANGER_THRESHOLD) {
      node.classList.add(DANGER_CLASS);
    } else if (count >= WARN_THRESHOLD) {
      node.classList.add(WARN_CLASS);
    }
  }

  function updateCounter(textarea, counter) {
    if (!textarea || !counter) return 0;
    const value = textarea.value || "";
    const count = value.length;
    if (count === 0) {
      counter.hidden = true;
      counter.textContent = "";
      _applyThresholdClass(counter, 0);
      return 0;
    }
    counter.hidden = false;
    counter.textContent = _resolveLabel(count);
    _applyThresholdClass(counter, count);
    return count;
  }

  function init() {
    const textarea = document.getElementById(TARGET_ID);
    const counter = document.getElementById(COUNTER_ID);
    if (!textarea || !counter) return null;
    const handler = function () {
      updateCounter(textarea, counter);
    };
    textarea.addEventListener("input", handler);
    // 初次渲染：处理 R137 height restore / 外部 setValue / 表单回填
    // 等非 ``input`` 事件路径下的非空初始值。
    updateCounter(textarea, counter);
    return { textarea: textarea, counter: counter, handler: handler };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.AIIA_FEEDBACK_CHAR_COUNTER = {
    TARGET_ID: TARGET_ID,
    COUNTER_ID: COUNTER_ID,
    WARN_THRESHOLD: WARN_THRESHOLD,
    DANGER_THRESHOLD: DANGER_THRESHOLD,
    WARN_CLASS: WARN_CLASS,
    DANGER_CLASS: DANGER_CLASS,
    I18N_KEY: I18N_KEY,
    _formatCount: _formatCount,
    _resolveLabel: _resolveLabel,
    _applyThresholdClass: _applyThresholdClass,
    updateCounter: updateCounter,
    init: init,
  };
})();
