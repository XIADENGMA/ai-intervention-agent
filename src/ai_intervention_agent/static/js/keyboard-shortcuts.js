/**
 * ========================================================================
 * AI Intervention Agent - 键盘快捷键模块 (Keyboard Shortcuts)
 * ========================================================================
 *
 * 功能说明：
 *   - 全局快捷键管理
 *   - 可自定义快捷键映射
 *   - 冲突检测和处理
 *   - 上下文感知（不同页面区域使用不同快捷键）
 *
 * 使用方法：
 *   KeyboardShortcuts.register('ctrl+s', () => save());
 *   KeyboardShortcuts.unregister('ctrl+s');
 *
 * ========================================================================
 */

const KeyboardShortcuts = (function () {
  'use strict';

  // ========================================
  // 常量和配置
  // ========================================

  // 修饰键映射
  const MODIFIER_KEYS = {
    ctrl: 'ctrlKey',
    alt: 'altKey',
    shift: 'shiftKey',
    meta: 'metaKey',
    cmd: 'metaKey',
    command: 'metaKey',
    option: 'altKey'
  };

  // 特殊键名映射
  const KEY_ALIASES = {
    'esc': 'Escape',
    'escape': 'Escape',
    'enter': 'Enter',
    'return': 'Enter',
    'space': ' ',
    'spacebar': ' ',
    'up': 'ArrowUp',
    'down': 'ArrowDown',
    'left': 'ArrowLeft',
    'right': 'ArrowRight',
    'delete': 'Delete',
    'del': 'Delete',
    'backspace': 'Backspace',
    'tab': 'Tab',
    'home': 'Home',
    'end': 'End',
    'pageup': 'PageUp',
    'pagedown': 'PageDown'
  };

  // 默认忽略快捷键的元素类型
  const IGNORED_ELEMENTS = ['INPUT', 'TEXTAREA', 'SELECT'];

  // ========================================
  // 内部状态
  // ========================================

  // 注册的快捷键 Map<string, { callback: Function, options: Object }>
  const shortcuts = new Map();

  // 是否已初始化
  let initialized = false;

  // ========================================
  // 工具函数
  // ========================================

  /**
   * 解析快捷键字符串
   * @param {string} shortcut - 快捷键字符串 (如 "ctrl+shift+s")
   * @returns {{ modifiers: Set, key: string }}
   */
  function parseShortcut(shortcut) {
    const normalized = shortcut.toLowerCase();
    const modifiers = new Set();
    let key = '';

    for (let start = 0, i = 0; i <= normalized.length; i += 1) {
      if (i < normalized.length && normalized.charCodeAt(i) !== 43) continue;
      const part = normalized.slice(start, i).trim();
      start = i + 1;
      if (MODIFIER_KEYS[part]) {
        modifiers.add(MODIFIER_KEYS[part]);
      } else {
        key = KEY_ALIASES[part] || part;
      }
    }

    return { modifiers, key };
  }

  /**
   * Normalize a key name into the token used by shortcut IDs.
   * @param {string} key - Parsed shortcut key or KeyboardEvent.key
   * @returns {string}
   */
  function normalizeKeyForId(key) {
    const normalized = String(key || '').toLowerCase();
    const aliased = KEY_ALIASES[normalized] || normalized;
    if (aliased === ' ') return 'space';
    return String(aliased).toLowerCase();
  }

  /**
   * Build a canonical shortcut ID from parsed modifiers and key.
   * @param {Set} modifiers - Normalized modifier property names
   * @param {string} key - Parsed shortcut key or KeyboardEvent.key
   * @returns {string}
   */
  function buildShortcutId(modifiers, key) {
    const parts = [];
    if (modifiers.has('ctrlKey')) parts.push('ctrl');
    if (modifiers.has('altKey')) parts.push('alt');
    if (modifiers.has('shiftKey')) parts.push('shift');
    if (modifiers.has('metaKey')) parts.push('meta');
    parts.push(normalizeKeyForId(key));
    return parts.join('+');
  }

  /**
   * 生成标准化的快捷键 ID
   * @param {KeyboardEvent} event - 键盘事件
   * @returns {string}
   */
  function getShortcutId(event) {
    const parts = [];

    if (event.ctrlKey) parts.push('ctrl');
    if (event.altKey) parts.push('alt');
    if (event.shiftKey) parts.push('shift');
    if (event.metaKey) parts.push('meta');

    // 标准化键名
    parts.push(normalizeKeyForId(event.key));

    return parts.join('+');
  }

  /**
   * Find the active visible task tab index without materializing the NodeList.
   * @param {NodeList} tabs - Visible task tabs from querySelectorAll()
   * @returns {number}
   */
  function getActiveTaskTabIndex(tabs) {
    for (let i = 0; i < tabs.length; i += 1) {
      if (tabs[i].classList.contains('active')) {
        return i;
      }
    }
    return -1;
  }

  /**
   * 检查是否应该忽略快捷键
   * @param {KeyboardEvent} event - 键盘事件
   * @param {Object} options - 选项
   * @returns {boolean}
   */
  function shouldIgnore(event, options) {
    // 检查是否在忽略元素内
    if (!options.allowInInputs) {
      const target = event.target;
      if (!target) {
        return false;
      }
      const tagName = typeof target.tagName === 'string' ? target.tagName.toUpperCase() : '';
      if (IGNORED_ELEMENTS.includes(tagName)) {
        return true;
      }
      if (target.isContentEditable) {
        return true;
      }
    }
    return false;
  }

  /**
   * 主键盘事件处理器
   * @param {KeyboardEvent} event
   */
  function handleKeydown(event) {
    const id = getShortcutId(event);
    const shortcutData = shortcuts.get(id);

    if (!shortcutData) return;

    const { callback, options } = shortcutData;

    // 检查是否应该忽略
    if (shouldIgnore(event, options)) return;

    // 阻止默认行为
    if (options.preventDefault) {
      event.preventDefault();
    }

    // 阻止事件冒泡
    if (options.stopPropagation) {
      event.stopPropagation();
    }

    // 执行回调
    try {
      callback(event);
    } catch (error) {
      console.error(`[KeyboardShortcuts] Error while executing shortcut "${id}":`, error);
    }
  }

  // ========================================
  // 公共 API
  // ========================================

  return {
    /**
     * 初始化快捷键系统
     */
    init: function () {
      if (initialized) return;

      document.addEventListener('keydown', handleKeydown);
      initialized = true;

      // 注册默认快捷键
      this.registerDefaults();

      console.debug('[KeyboardShortcuts] initialized');
    },

    /**
     * 注册快捷键
     * @param {string} shortcut - 快捷键字符串 (如 "ctrl+s", "cmd+enter")
     * @param {Function} callback - 回调函数
     * @param {Object} [options] - 选项
     * @param {boolean} [options.preventDefault=true] - 是否阻止默认行为
     * @param {boolean} [options.stopPropagation=false] - 是否阻止事件冒泡
     * @param {boolean} [options.allowInInputs=false] - 是否在输入框内生效
     */
    register: function (shortcut, callback, options = {}) {
      const defaultOptions = {
        preventDefault: true,
        stopPropagation: false,
        allowInInputs: false
      };

      const mergedOptions = { ...defaultOptions, ...options };
      const { modifiers, key } = parseShortcut(shortcut);
      const id = buildShortcutId(modifiers, key);

      if (shortcuts.has(id)) {
        console.warn(`[KeyboardShortcuts] Shortcut "${shortcut}" already exists, will be overridden`);
      }

      shortcuts.set(id, { callback, options: mergedOptions });
      console.debug(`[KeyboardShortcuts] registered: ${id}`);
    },

    /**
     * 注销快捷键
     * @param {string} shortcut - 快捷键字符串
     */
    unregister: function (shortcut) {
      const { modifiers, key } = parseShortcut(shortcut);
      const id = buildShortcutId(modifiers, key);

      if (shortcuts.delete(id)) {
        console.debug(`[KeyboardShortcuts] unregistered: ${id}`);
      }
    },

    /**
     * 注册默认快捷键
     */
    registerDefaults: function () {
      // Escape - 关闭模态框/设置面板
      //
      // R272 / cycle-23 fix: 必须 delegate 到 settingsManager.hideSettings()
      // 与 closeImageModal()，**不能**裸 remove class。
      //
      // 真 bug 复现路径：
      //   1. Cmd+, 打开 settings-panel → settingsManager.showSettings() 做了
      //      a) 捕获 _previouslyFocusedElement (R264 capture-activeElement)
      //      b) 注册 _settingsEscHandler (内部 escape listener)
      //      c) _setContainerSiblingsInert(panel, true) (背景 inert)
      //      d) container.style.overflow = "hidden"
      //   2. 用户按 Esc → 命中本 handler → 旧实现仅 classList swap
      //   3. 漏: a) 焦点不回归 → 漂浮 / b) inert 不解除 → 背景仍键盘锁死
      //      c) _settingsEscHandler 不解绑 → memory leak + 下次 Esc 二次触发
      //      d) overflow 未恢复 → 滚动卡死
      //
      // 同 image-modal: closeImageModal() 必须解绑 keydown + tab trap +
      // restore _imageModalPreviouslyFocusedElement，裸 remove("show")
      // 全部漏掉。
      //
      // Delegation 安全性: settingsManager / closeImageModal 都是 top-level
      // const / function (settings-manager.js + image-upload.js 在
      // keyboard-shortcuts.js 之前加载, 见 web_ui.html script order)；
      // typeof 守卫兼容潜在的延迟加载 / VSCode webview 部分 bundle 场景。
      this.register('escape', () => {
        // 关闭设置面板 — delegate 到 settingsManager.hideSettings() (R272)
        const settingsPanel = document.getElementById('settings-panel');
        if (settingsPanel && settingsPanel.classList.contains('show')) {
          if (
            typeof settingsManager !== 'undefined' &&
            settingsManager &&
            typeof settingsManager.hideSettings === 'function'
          ) {
            settingsManager.hideSettings();
          } else {
            // Fallback: settings-manager.js 未加载（极端 race / bundle 错
            // 切场景），裸 remove class 至少恢复视觉可见性，但漏的清理由
            // 后续 reload / re-init 自然修复。
            settingsPanel.classList.remove('show');
            settingsPanel.classList.add('hidden');
          }
          return;
        }

        // 关闭图片模态框 — delegate 到 closeImageModal() (R272)
        const imageModal = document.getElementById('image-modal');
        if (imageModal && imageModal.classList.contains('show')) {
          if (typeof closeImageModal === 'function') {
            closeImageModal();
          } else {
            // Fallback: image-upload.js 未加载（同上）
            imageModal.classList.remove('show');
          }
          return;
        }
      });

      // Ctrl/Cmd + Enter - 提交
      const submitShortcut = navigator.platform.includes('Mac') ? 'meta+enter' : 'ctrl+enter';
      this.register(submitShortcut, () => {
        const submitBtn = document.getElementById('submit-btn');
        if (submitBtn && !submitBtn.disabled) {
          submitBtn.click();
        }
      }, { allowInInputs: true });

      // Ctrl/Cmd + / - 显示快捷键帮助
      const helpShortcut = navigator.platform.includes('Mac') ? 'meta+/' : 'ctrl+/';
      this.register(helpShortcut, () => {
        this.showHelp();
      });

      // Ctrl/Cmd + , - 打开设置
      const settingsShortcut = navigator.platform.includes('Mac') ? 'meta+,' : 'ctrl+,';
      this.register(settingsShortcut, () => {
        const settingsBtn = document.getElementById('settings-btn');
        if (settingsBtn) settingsBtn.click();
      });

      // T - 切换主题
      this.register('t', () => {
        if (typeof ThemeManager !== 'undefined') {
          ThemeManager.toggle();
        }
      });

      // Tab - 在任务间切换
      this.register('tab', (event) => {
        const tabs = document.querySelectorAll('.task-tab:not(.hidden)');
        if (tabs.length > 1) {
          event.preventDefault();
          const currentIndex = getActiveTaskTabIndex(tabs);
          const nextIndex = (currentIndex + 1) % tabs.length;
          tabs[nextIndex].click();
        }
      });

      // Shift + Tab - 反向切换任务
      this.register('shift+tab', (event) => {
        const tabs = document.querySelectorAll('.task-tab:not(.hidden)');
        if (tabs.length > 1) {
          event.preventDefault();
          const currentIndex = getActiveTaskTabIndex(tabs);
          const prevIndex = (currentIndex - 1 + tabs.length) % tabs.length;
          tabs[prevIndex].click();
        }
      });
    },

    /**
     * 显示快捷键帮助
     *
     * R267 / cycle-22 unify-help-entrypoints: 优先调用
     * `window.AIIA_KEYBOARD_SHORTCUT_HELP.showOverlay()`（`?` cheatsheet
     * 模态浮层），让 Cmd+/ 和 `?` 两个入口都展示同一个真正的 UI overlay。
     *
     * 旧实现把 help text 输出到 console.debug + 弹浏览器通知 —— 在 IDE
     * webview / iframe / 关掉通知权限的场景下用户根本看不到任何反馈，
     * Cmd+/ 等于"按了没反应"。改成走 modal overlay 后：
     * 1. 视觉一致 — 两个入口（`?` 和 Cmd+/）展示同一份 cheatsheet
     * 2. 可达性 — 不依赖通知权限 / console 打开
     * 3. 可发现性 — overlay 列出完整的 10 个 shortcut（含 system 级）
     *
     * Fallback：overlay 模块未加载（CSP block / 静态资源 404）时退回
     * 原 console.debug，保证 Cmd+/ 不"假死"。
     */
    showHelp: function () {
      // R267 优先：弹真正的 modal overlay（`?` cheatsheet 同款）。
      if (
        typeof window !== 'undefined' &&
        window.AIIA_KEYBOARD_SHORTCUT_HELP &&
        typeof window.AIIA_KEYBOARD_SHORTCUT_HELP.showOverlay === 'function'
      ) {
        try {
          window.AIIA_KEYBOARD_SHORTCUT_HELP.showOverlay();
          return;
        } catch (_e) {
          // overlay 渲染异常 → 走通知 + console fallback（保留旧行为）
        }
      }

      const isMac = navigator.platform.includes('Mac');
      const mod = isMac ? '⌘' : 'Ctrl';

      const t = (key, params) => window.AIIA_I18N ? window.AIIA_I18N.t(key, params) : key;
      const helpText = [
        '╔══════════════════════════════════════╗',
        `║  ${t('shortcuts.helpTitle')}  ║`.padEnd(42, ' ') + '║',
        '╠══════════════════════════════════════╣',
        `║  ${mod}+Enter    ${t('shortcuts.submitFeedback')}`,
        `║  ${mod}+,        ${t('shortcuts.openSettings')}`,
        `║  ${mod}+/        ${t('shortcuts.showHelp')}`,
        `║  T             ${t('shortcuts.toggleTheme')}`,
        `║  Tab           ${t('shortcuts.nextTask')}`,
        `║  Shift+Tab     ${t('shortcuts.prevTask')}`,
        `║  Escape        ${t('shortcuts.closeModal')}`,
        '╚══════════════════════════════════════╝'
      ].join('\n');

      console.debug(helpText);

      // R228 invariant: overlay 不可用时（CSP block / 静态资源 404 / SW
      // stale cache 等极少数 edge case），把 notifyBody 通知作为兜底 ——
      // 普通浏览器场景下至少给用户一个视觉反馈。IDE webview 通常通知
      // 也被 suppress，所以本路径主要服务于 plain browser fallback。
      if (typeof notificationManager !== 'undefined') {
        notificationManager.sendNotification(
          t('shortcuts.notifyTitle'),
          t('shortcuts.notifyBody', { mod }),
          { tag: 'keyboard-help', requireInteraction: false }
        );
      }
    },

    /**
     * 获取所有注册的快捷键
     * @returns {Map}
     */
    getAll: function () {
      return new Map(shortcuts);
    },

    /**
     * 销毁快捷键系统
     */
    destroy: function () {
      document.removeEventListener('keydown', handleKeydown);
      shortcuts.clear();
      initialized = false;
      console.debug('[KeyboardShortcuts] destroyed');
    }
  };
})();

if (typeof window !== 'undefined') {
  window.KeyboardShortcuts = KeyboardShortcuts;
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
  KeyboardShortcuts.init();
});

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = KeyboardShortcuts;
}
