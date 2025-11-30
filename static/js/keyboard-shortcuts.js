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
    const parts = shortcut.toLowerCase().split('+').map(p => p.trim());
    const modifiers = new Set();
    let key = '';

    for (const part of parts) {
      if (MODIFIER_KEYS[part]) {
        modifiers.add(MODIFIER_KEYS[part]);
      } else {
        key = KEY_ALIASES[part] || part;
      }
    }

    return { modifiers, key };
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
    let key = event.key.toLowerCase();
    if (key === ' ') key = 'space';
    parts.push(key);

    return parts.join('+');
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
      if (IGNORED_ELEMENTS.includes(target.tagName)) {
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
      console.error(`[KeyboardShortcuts] 执行快捷键 "${id}" 时出错:`, error);
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

      console.log('[KeyboardShortcuts] 已初始化');
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

      // 生成标准化 ID
      const parts = [];
      if (modifiers.has('ctrlKey')) parts.push('ctrl');
      if (modifiers.has('altKey')) parts.push('alt');
      if (modifiers.has('shiftKey')) parts.push('shift');
      if (modifiers.has('metaKey')) parts.push('meta');
      parts.push(key.toLowerCase());

      const id = parts.join('+');

      if (shortcuts.has(id)) {
        console.warn(`[KeyboardShortcuts] 快捷键 "${shortcut}" 已存在，将被覆盖`);
      }

      shortcuts.set(id, { callback, options: mergedOptions });
      console.debug(`[KeyboardShortcuts] 注册: ${id}`);
    },

    /**
     * 注销快捷键
     * @param {string} shortcut - 快捷键字符串
     */
    unregister: function (shortcut) {
      const { modifiers, key } = parseShortcut(shortcut);

      const parts = [];
      if (modifiers.has('ctrlKey')) parts.push('ctrl');
      if (modifiers.has('altKey')) parts.push('alt');
      if (modifiers.has('shiftKey')) parts.push('shift');
      if (modifiers.has('metaKey')) parts.push('meta');
      parts.push(key.toLowerCase());

      const id = parts.join('+');

      if (shortcuts.delete(id)) {
        console.debug(`[KeyboardShortcuts] 注销: ${id}`);
      }
    },

    /**
     * 注册默认快捷键
     */
    registerDefaults: function () {
      // Escape - 关闭模态框/设置面板
      this.register('escape', () => {
        // 关闭设置面板
        const settingsPanel = document.getElementById('settings-panel');
        if (settingsPanel && settingsPanel.classList.contains('show')) {
          settingsPanel.classList.remove('show');
          settingsPanel.classList.add('hidden');
          return;
        }

        // 关闭图片模态框
        const imageModal = document.getElementById('image-modal');
        if (imageModal && imageModal.classList.contains('show')) {
          imageModal.classList.remove('show');
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
          const currentIndex = Array.from(tabs).findIndex(
            tab => tab.classList.contains('active')
          );
          const nextIndex = (currentIndex + 1) % tabs.length;
          tabs[nextIndex].click();
        }
      });

      // Shift + Tab - 反向切换任务
      this.register('shift+tab', (event) => {
        const tabs = document.querySelectorAll('.task-tab:not(.hidden)');
        if (tabs.length > 1) {
          event.preventDefault();
          const currentIndex = Array.from(tabs).findIndex(
            tab => tab.classList.contains('active')
          );
          const prevIndex = (currentIndex - 1 + tabs.length) % tabs.length;
          tabs[prevIndex].click();
        }
      });
    },

    /**
     * 显示快捷键帮助
     */
    showHelp: function () {
      const isMac = navigator.platform.includes('Mac');
      const mod = isMac ? '⌘' : 'Ctrl';
      const alt = isMac ? '⌥' : 'Alt';

      const helpText = `
╔══════════════════════════════════════╗
║       ⌨️ 键盘快捷键帮助             ║
╠══════════════════════════════════════╣
║  ${mod}+Enter    提交反馈              ║
║  ${mod}+,        打开设置              ║
║  ${mod}+/        显示此帮助            ║
║  T             切换主题              ║
║  Tab           下一个任务            ║
║  Shift+Tab     上一个任务            ║
║  Escape        关闭弹窗/面板         ║
╚══════════════════════════════════════╝
      `.trim();

      console.log(helpText);

      // 显示提示通知
      if (typeof notificationManager !== 'undefined') {
        notificationManager.sendNotification(
          '⌨️ 快捷键',
          `${mod}+Enter 提交 | T 切换主题 | Esc 关闭弹窗`,
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
      console.log('[KeyboardShortcuts] 已销毁');
    }
  };
})();

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
  KeyboardShortcuts.init();
});

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = KeyboardShortcuts;
}
