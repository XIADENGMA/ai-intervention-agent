/**
 * MathJax 懒加载器
 *
 * 功能说明：
 *   MathJax 库较大（约 1.17MB），为优化首屏加载性能，
 *   仅在检测到数学公式时才动态加载该库。
 *
 * 支持的公式语法：
 *   - 行内公式：$...$, \(...\)
 *   - 块级公式：$$...$$, \[...\]
 *
 * 加载流程：
 *   1. renderMarkdownContent 调用 loadMathJaxIfNeeded
 *   2. 检测内容是否包含数学公式
 *   3. 首次检测到时，动态创建 <script> 加载 tex-mml-chtml.js
 *   4. 加载完成后，MathJax.startup.ready 回调渲染所有待处理元素
 *
 * 状态管理：
 *   - _mathJaxLoading: 标记是否正在加载（防止重复加载）
 *   - _mathJaxLoaded: 标记是否加载完成
 *   - _mathJaxPendingElements: 存储加载期间需要渲染的元素队列
 */

// MathJax 配置（预设，实际脚本按需加载）
window.MathJax = {
  tex: {
    inlineMath: [
      ['$', '$'],
      ['\\(', '\\)']
    ],
    displayMath: [
      ['$$', '$$'],
      ['\\[', '\\]']
    ],
    processEscapes: true,
    processEnvironments: true,
    packages: { '[+]': ['ams', 'newcommand', 'configmacros'] },
    tags: 'ams'
  },
  options: {
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
    ignoreHtmlClass: 'tex2jax_ignore',
    processHtmlClass: 'tex2jax_process'
  },
  startup: {
    ready: () => {
      console.log('MathJax loaded')
      MathJax.startup.defaultReady()
      if (window._mathJaxPendingElements) {
        window._mathJaxPendingElements.forEach(el => {
          MathJax.typesetPromise([el]).catch(err => console.warn('MathJax render failed:', err))
        })
        window._mathJaxPendingElements = []
      }
    }
  }
}

// MathJax 懒加载状态标记
window._mathJaxLoading = false // 是否正在加载脚本
window._mathJaxLoaded = false // 是否加载完成
window._mathJaxPendingElements = [] // 待渲染的元素队列

/**
 * 检测内容是否包含数学公式
 * @param {string} text - 要检测的文本内容
 * @returns {boolean} 是否包含数学公式
 */
window.hasMathContent = function (text) {
  if (!text) return false
  // 检测 LaTeX 数学公式语法（四种常见格式）
  const mathPatterns = [
    /\$[^$]+\$/, // 行内公式：$E=mc^2$
    /\$\$[^$]+\$\$/, // 块级公式：$$\int_0^\infty$$
    /\\\([^)]+\\\)/, // 行内公式（LaTeX 风格）：\(E=mc^2\)
    /\\\[[^\]]+\\\]/ // 块级公式（LaTeX 风格）：\[\int_0^\infty\]
  ]
  return mathPatterns.some(pattern => pattern.test(text))
}

/**
 * 按需加载 MathJax 并渲染数学公式
 *
 * @param {HTMLElement} element - 包含数学内容的 DOM 元素
 * @param {string} text - 元素的文本内容（用于公式检测）
 *
 * 执行逻辑：
 *   1. 检测是否有数学内容 → 无则直接返回
 *   2. 若 MathJax 已加载 → 直接调用 typesetPromise 渲染
 *   3. 若正在加载中 → 将元素加入待渲染队列
 *   4. 若未加载 → 触发脚本加载，完成后批量渲染队列中的元素
 */
window.loadMathJaxIfNeeded = function (element, text) {
  // 检测是否有数学内容
  if (!window.hasMathContent(text)) {
    return // 无数学公式，不加载
  }

  // 已加载完成，直接渲染
  if (window._mathJaxLoaded && window.MathJax && window.MathJax.typesetPromise) {
    MathJax.typesetPromise([element]).catch(err => console.warn('MathJax render failed:', err))
    return
  }

  // 记录待渲染元素（脚本加载完成后批量处理）
  window._mathJaxPendingElements.push(element)

  // 正在加载中，等待完成即可
  if (window._mathJaxLoading) {
    return
  }

  // 开始加载 MathJax 脚本
  window._mathJaxLoading = true
  console.log('MathJax: math content detected, loading MathJax (~1.17MB)…')

  // 动态创建 <script> 元素加载 MathJax
  const script = document.createElement('script')
  script.id = 'MathJax-script'
  script.async = true
  script.src = '/static/js/tex-mml-chtml.js' // 本地托管的 MathJax 脚本
  script.onload = function () {
    window._mathJaxLoaded = true
    console.log('MathJax script loaded')
  }
  script.onerror = function () {
    console.error('MathJax script load failed')
    window._mathJaxLoading = false
  }
  document.head.appendChild(script)
}
