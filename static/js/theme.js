/**
 * ========================================================================
 * AI Intervention Agent - 主题切换模块 (Theme Switcher)
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
 *   - config.jsonc: 服务端持久化（可选）
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

  /**
   * 检测系统颜色偏好
   * @returns {string} 'dark' 或 'light'
   */
  function detectSystemPreference() {
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      return THEMES.LIGHT;
    }
    return THEMES.DARK;
  }

  /**
   * 监听系统偏好变化
   */
  function listenSystemPreference() {
    if (!window.matchMedia) return;

    mediaQuery = window.matchMedia('(prefers-color-scheme: light)');

    const handleChange = (e) => {
      systemPreference = e.matches ? THEMES.LIGHT : THEMES.DARK;
      console.log('系统主题偏好变更:', systemPreference);

      // 如果是自动模式，跟随系统变化
      if (currentTheme === THEMES.AUTO) {
        applyTheme(systemPreference);
      }
    };

    // 现代浏览器使用 addEventListener
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handleChange);
    } else if (mediaQuery.addListener) {
      // 兼容旧版浏览器
      mediaQuery.addListener(handleChange);
    }

    // 初始化系统偏好
    systemPreference = detectSystemPreference();
  }

  /**
   * 应用主题到 DOM
   * @param {string} theme - 'dark' 或 'light'
   */
  function applyTheme(theme) {
    const html = document.documentElement;
    const effectiveTheme = theme === THEMES.AUTO ? systemPreference : theme;

    // 设置 data-theme 属性
    if (effectiveTheme === THEMES.DARK) {
      html.removeAttribute('data-theme');
    } else {
      html.setAttribute('data-theme', effectiveTheme);
    }

    // 更新 meta 标签（用于移动端状态栏颜色）
    updateMetaThemeColor(effectiveTheme);

    // 触发自定义事件
    window.dispatchEvent(new CustomEvent('theme-changed', {
      detail: { theme: effectiveTheme, mode: theme }
    }));

    console.log('主题已应用:', effectiveTheme, '(模式:', theme + ')');
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
      console.warn('无法保存主题偏好到 localStorage:', e);
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
      console.warn('无法从 localStorage 加载主题偏好:', e);
      return null;
    }
  }

  /**
   * 同步主题偏好到服务端配置
   * @param {string} theme - 主题模式
   */
  async function syncToServer(theme) {
    try {
      const response = await fetch('/api/update-notification-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme_preference: theme })
      });

      if (!response.ok) {
        console.warn('同步主题到服务端失败:', response.status);
      }
    } catch (e) {
      // 静默失败，不影响用户体验
      console.debug('同步主题到服务端失败:', e);
    }
  }

  /**
   * 创建主题切换按钮
   * @returns {HTMLElement}
   */
  function createToggleButton() {
    const button = document.createElement('button');
    button.className = 'theme-toggle-btn';
    button.setAttribute('aria-label', '切换主题');
    button.setAttribute('title', '切换主题');

    // 图标 SVG
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

    button.addEventListener('click', () => {
      // 使用内部 toggle 逻辑，而非 ThemeManager.toggle()
      const effectiveTheme = currentTheme === THEMES.AUTO ? systemPreference : currentTheme;
      const newTheme = effectiveTheme === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK;

      currentTheme = newTheme;
      savePreference(newTheme);
      applyTheme(newTheme);
      updateToggleButton();
    });

    return button;
  }

  /**
   * 更新切换按钮状态
   */
  function updateToggleButton() {
    const effectiveTheme = currentTheme === THEMES.AUTO ? systemPreference : currentTheme;
    const buttons = document.querySelectorAll('.theme-toggle-btn');

    buttons.forEach(button => {
      button.classList.toggle('is-light', effectiveTheme === THEMES.LIGHT);
    });
  }

  /**
   * 为已存在的按钮绑定点击事件
   * 注意：使用内部函数而非 ThemeManager 引用，避免 IIFE 作用域问题
   */
  function bindExistingButtons() {
    const buttons = document.querySelectorAll('.theme-toggle-btn');
    buttons.forEach(button => {
      // 避免重复绑定
      if (!button.hasAttribute('data-theme-bound')) {
        button.addEventListener('click', () => {
          // 使用内部 toggle 逻辑，而非 ThemeManager.toggle()
          const effectiveTheme = currentTheme === THEMES.AUTO ? systemPreference : currentTheme;
          const newTheme = effectiveTheme === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK;

          currentTheme = newTheme;
          savePreference(newTheme);
          applyTheme(newTheme);
          updateToggleButton();
        });
        button.setAttribute('data-theme-bound', 'true');
        console.debug('主题切换按钮已绑定:', button.id || '(无ID)');
      }
    });
  }

  // 公共 API
  return {
    /**
     * 初始化主题管理器
     * @param {Object} options - 配置选项
     * @param {boolean} options.syncToServer - 是否同步到服务端
     * @param {string} options.defaultTheme - 默认主题
     */
    init: function (options = {}) {
      const { syncToServer: doSync = false, defaultTheme = THEMES.AUTO } = options;

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

      console.log('主题管理器已初始化:', currentTheme);
    },

    /**
     * 设置主题
     * @param {string} theme - 'dark', 'light', 或 'auto'
     */
    setTheme: function (theme) {
      if (!Object.values(THEMES).includes(theme)) {
        console.warn('无效的主题:', theme);
        return;
      }

      currentTheme = theme;
      savePreference(theme);
      applyTheme(theme);
      updateToggleButton();
    },

    /**
     * 切换主题（dark ↔ light）
     */
    toggle: function () {
      const effectiveTheme = currentTheme === THEMES.AUTO ? systemPreference : currentTheme;
      const newTheme = effectiveTheme === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK;

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
