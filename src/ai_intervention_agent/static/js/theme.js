/**
 * ========================================================================
 * AI Intervention Agent - 主题切换模块（主题切换器）
 * ========================================================================
 *
 * 功能说明：
 *   - 支持暗色/亮色主题切换
 *   - 检测并跟随系统颜色偏好
 *   - 主题偏好持久化存储
 *   - 平滑过渡动画
 *
 * 主题模式：
 *   - "dark": 强制暗色主题
 *   - "light": 强制亮色主题
 *   - "auto": 跟随系统偏好（默认）
 *
 * 使用方法：
 *   // 初始化
 *   ThemeManager.init();
 *
 *   // 切换主题
 *   ThemeManager.setTheme('light');
 *   ThemeManager.toggle();
 *
 *   // 获取当前主题
 *   const theme = ThemeManager.getTheme();
 *
 * 存储机制：
 *   - localStorage: 本地快速存取
 *
 * ========================================================================
 */

const ThemeManager = (function () {
  'use strict';

  // 常量定义
  const STORAGE_KEY = 'theme-preference';
  const THEMES = {
    DARK: 'dark',
    LIGHT: 'light',
    AUTO: 'auto'
  };

  // 内部状态
  let currentTheme = THEMES.AUTO;
  let systemPreference = null;
  let mediaQuery = null;
  let systemPreferenceListenerInstalled = false;
  let storageSyncListenerInstalled = false;

  /**
   * 检测系统颜色偏好
   * @returns {string} 'dark' 或 'light'
   */
  function detectSystemPreference() {
    const query = getSystemPreferenceMediaQuery();
    if (query && query.matches) {
      return THEMES.LIGHT;
    }
    return THEMES.DARK;
  }

  function getSystemPreferenceMediaQuery() {
    if (!window.matchMedia) return null;
    if (!mediaQuery) {
      mediaQuery = window.matchMedia('(prefers-color-scheme: light)');
    }
    return mediaQuery;
  }

  function handleSystemPreferenceChange(e) {
    systemPreference = e.matches ? THEMES.LIGHT : THEMES.DARK;
    console.debug('System theme preference changed:', systemPreference);

    // 无条件刷新按钮标签：在 auto 模式下，切换系统偏好也需要同步 aria-label/title
    // 与 .is-light 类，避免按钮显示与真实主题不一致（P7 yellow finding）
    if (currentTheme === THEMES.AUTO) {
      applyTheme(systemPreference);
    }
    updateToggleButton();
  }

  /**
   * 监听系统偏好变化
   */
  function listenSystemPreference() {
    systemPreference = detectSystemPreference();

    const query = getSystemPreferenceMediaQuery();
    if (!query || systemPreferenceListenerInstalled) return;

    // 现代浏览器使用 addEventListener
    if (query.addEventListener) {
      query.addEventListener('change', handleSystemPreferenceChange);
      systemPreferenceListenerInstalled = true;
    } else if (query.addListener) {
      // 兼容旧版浏览器
      query.addListener(handleSystemPreferenceChange);
      systemPreferenceListenerInstalled = true;
    }
  }

  /**
   * 应用主题到 DOM
   * @param {string} theme - 'dark' 或 'light'
   */
  function applyTheme(theme) {
    const html = document.documentElement;
    const effectiveTheme = theme === THEMES.AUTO ? systemPreference : theme;

    // 设置 data-theme 属性
    //
    // 关键修复：
    // 不能用“移除 data-theme”来表示深色主题。
    // 因为 main.css 里存在 `@media (prefers-color-scheme: light) { :root:not([data-theme]) { ... } }`
    // 当系统偏好为浅色时，移除 data-theme 会让页面变量回到浅色，导致“仅局部变暗（如 .container）”的错位效果。
    //
    // 因此这里始终显式写入 `dark` / `light`，确保用户手动切换能覆盖系统偏好。
    if (effectiveTheme === THEMES.DARK || effectiveTheme === THEMES.LIGHT) {
      html.setAttribute('data-theme', effectiveTheme);
    } else {
      html.removeAttribute('data-theme');
    }

    // 更新 meta 标签（用于移动端状态栏颜色）
    updateMetaThemeColor(effectiveTheme);

    // 触发自定义事件
    window.dispatchEvent(new CustomEvent('theme-changed', {
      detail: { theme: effectiveTheme, mode: theme }
    }));

    console.debug('Theme applied:', effectiveTheme, '(mode:', theme + ')');
  }

  /**
   * 更新 meta theme-color
   * @param {string} theme - 'dark' 或 'light'
   */
  function updateMetaThemeColor(theme) {
    let metaThemeColor = document.querySelector('meta[name="theme-color"]');

    if (!metaThemeColor) {
      metaThemeColor = document.createElement('meta');
      metaThemeColor.name = 'theme-color';
      document.head.appendChild(metaThemeColor);
    }

    metaThemeColor.content = theme === THEMES.LIGHT ? '#f8fafc' : '#1a1a1f';
  }

  /**
   * 保存主题偏好到 localStorage
   * @param {string} theme - 主题模式
   */
  function savePreference(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      console.warn('Cannot save theme preference to localStorage:', e);
    }
  }

  /**
   * 从 localStorage 加载主题偏好
   * @returns {string|null}
   */
  function loadPreference() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      console.warn('Cannot load theme preference from localStorage:', e);
      return null;
    }
  }

  /**
   * 创建主题切换按钮
   * @returns {HTMLElement}
   */
  function createToggleButton() {
    const button = document.createElement('button');
    button.className = 'theme-toggle-btn';

    button.innerHTML = `
      <svg class="theme-icon theme-icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="5"/>
        <line x1="12" y1="1" x2="12" y2="3"/>
        <line x1="12" y1="21" x2="12" y2="23"/>
        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
        <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
        <line x1="1" y1="12" x2="3" y2="12"/>
        <line x1="21" y1="12" x2="23" y2="12"/>
        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
        <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
      </svg>
      <svg class="theme-icon theme-icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
      </svg>
    `;

    button.addEventListener('click', toggleThemeInternal);

    return button;
  }

  function toggleThemeInternal() {
    const cycle = { [THEMES.AUTO]: THEMES.LIGHT, [THEMES.LIGHT]: THEMES.DARK, [THEMES.DARK]: THEMES.AUTO };
    currentTheme = cycle[currentTheme] || THEMES.AUTO;
    savePreference(currentTheme);
    applyTheme(currentTheme);
    updateToggleButton();
  }

  /**
   * 更新切换按钮状态
   */
  function updateToggleButton() {
    const effectiveTheme = currentTheme === THEMES.AUTO ? systemPreference : currentTheme;
    const buttons = document.querySelectorAll('.theme-toggle-btn');
    const t = (key) => window.AIIA_I18N ? window.AIIA_I18N.t(key) : key;
    const labels = {
      [THEMES.AUTO]: t('theme.auto'),
      [THEMES.LIGHT]: t('theme.light'),
      [THEMES.DARK]: t('theme.dark')
    };
    const label = labels[currentTheme] || labels[THEMES.AUTO];

    const buttonCount = buttons.length;
    for (let index = 0; index < buttonCount; index += 1) {
      const button = buttons[index];
      if (!button) continue;
      button.classList.toggle('is-light', effectiveTheme === THEMES.LIGHT);
      button.classList.toggle('is-auto', currentTheme === THEMES.AUTO);
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
    }
  }

  /**
   * 为已存在的按钮绑定点击事件
   * 注意：使用内部函数而非 ThemeManager 引用，避免 IIFE 作用域问题
   */
  function bindExistingButtons() {
    const buttons = document.querySelectorAll('.theme-toggle-btn');
    const buttonCount = buttons.length;
    for (let index = 0; index < buttonCount; index += 1) {
      const button = buttons[index];
      if (!button) continue;
      if (!button.hasAttribute('data-theme-bound')) {
        button.addEventListener('click', toggleThemeInternal);
        button.setAttribute('data-theme-bound', 'true');
      }
    }
  }

  function handleStorageChange(event) {
    if (event.key !== STORAGE_KEY) return;
    const newTheme = event.newValue;
    if (!newTheme || !Object.values(THEMES).includes(newTheme)) return;
    if (newTheme === currentTheme) return;
    currentTheme = newTheme;
    applyTheme(newTheme);
    updateToggleButton();
  }

  function setupStorageSync() {
    if (storageSyncListenerInstalled) return;

    // R452: ThemeManager.init() is intentionally repeatable; storage sync is
    // a process-lifetime listener and must be installed once.
    try {
      window.addEventListener('storage', handleStorageChange);
      storageSyncListenerInstalled = true;
    } catch (e) {
      // 极少数浏览器 (very old IE) 不支持 storage event；不致命
    }
  }

  // 公共 API
  return {
    /**
     * 初始化主题管理器
     * @param {Object} options - 配置选项
     * @param {string} options.defaultTheme - 默认主题
     */
    init: function (options = {}) {
      const { defaultTheme = THEMES.AUTO } = options;

      // 监听系统偏好
      listenSystemPreference();

      // 加载保存的偏好
      const savedTheme = loadPreference();
      currentTheme = savedTheme || defaultTheme;

      // 应用主题
      applyTheme(currentTheme);
      updateToggleButton();

      // 为已存在的按钮绑定点击事件
      bindExistingButtons();

      // R253 / cycle-10 bonus：cross-tab theme sync
      // tab A 改主题 → localStorage 写入 → 其他 tab 收到 ``storage`` 事件
      // → 自动应用相同主题，无需 reload。事件只在**其他** tab 触发
      // （origin tab 不会收到自己的写入），所以无递归风险。
      setupStorageSync();

      console.debug('Theme manager initialized:', currentTheme);
    },

    /**
     * 设置主题
     * @param {string} theme - 'dark', 'light', 或 'auto'
     */
    setTheme: function (theme) {
      if (!Object.values(THEMES).includes(theme)) {
        console.warn('Invalid theme:', theme);
        return;
      }

      currentTheme = theme;
      savePreference(theme);
      applyTheme(theme);
      updateToggleButton();
    },

    /**
     * 切换主题（auto → light → dark → auto 三态循环）
     */
    toggle: function () {
      const cycle = { [THEMES.AUTO]: THEMES.LIGHT, [THEMES.LIGHT]: THEMES.DARK, [THEMES.DARK]: THEMES.AUTO };
      const newTheme = cycle[currentTheme] || THEMES.AUTO;
      this.setTheme(newTheme);
    },

    /**
     * 获取当前主题模式
     * @returns {string} 'dark', 'light', 或 'auto'
     */
    getTheme: function () {
      return currentTheme;
    },

    /**
     * 获取当前生效的主题
     * @returns {string} 'dark' 或 'light'
     */
    getEffectiveTheme: function () {
      return currentTheme === THEMES.AUTO ? systemPreference : currentTheme;
    },

    /**
     * 创建并插入主题切换按钮
     * @param {HTMLElement|string} container - 容器元素或选择器
     */
    insertToggleButton: function (container) {
      const target = typeof container === 'string'
        ? document.querySelector(container)
        : container;

      if (target) {
        const button = createToggleButton();
        target.appendChild(button);
        updateToggleButton();
      }
    },

    // 常量导出
    THEMES: THEMES
  };
})();

// 自动初始化
document.addEventListener('DOMContentLoaded', () => {
  ThemeManager.init();
});

// 导出（如果支持模块）
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ThemeManager;
}
