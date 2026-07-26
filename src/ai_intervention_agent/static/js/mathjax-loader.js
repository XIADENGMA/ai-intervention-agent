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
      console.debug('MathJax loaded')
      MathJax.startup.defaultReady()
      if (window._mathJaxPendingElements) {
        const pendingElements = window._mathJaxPendingElements
        const pendingElementCount = pendingElements.length
        for (let index = 0; index < pendingElementCount; index += 1) {
          if (!(index in pendingElements)) continue
          const el = pendingElements[index]
          MathJax.typesetPromise([el]).catch(err => console.warn('MathJax render failed:', err))
        }
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
 * R712：markdown 渲染前保护 LaTeX 风格数学定界符
 *
 * ``\(`` 是合法的 markdown 反斜杠转义（marked 输出 ``(``），因此
 * ``\(E=mc^2\)`` 经 marked 渲染后定界符被吞，MathJax 找不到公式——
 * 上面宣称支持的四种定界符里，LaTeX 风格的两种（``\(...\)`` /
 * ``\[...\]``）在渲染管道上一直是坏的；``$`` / ``$$`` 不含 markdown
 * 特殊字符、原样穿透，无需保护。
 *
 * 方案（Jupyter / GitHub 同款经典占位法）：
 *   1. protectMathDelimiters(md)：跳过代码区（fenced + inline code），
 *      把 ``\(...\)`` / ``\[...\]`` 片段抽成占位 token；
 *   2. marked.parse(受保护文本)；
 *   3. restoreMathDelimiters(html, segments)：按索引回填 HTML 转义后
 *      的原片段（转义防止 ``a < b`` 这类数学内容被解析成标签；
 *      MathJax 读的是 textContent，转义在 DOM 层自动还原）。
 */
window.protectMathDelimiters = function (text) {
  if (
    typeof text !== 'string' ||
    (text.indexOf('\\(') === -1 && text.indexOf('\\[') === -1)
  ) {
    return { text, segments: [] }
  }
  const segments = []
  const protectedText = text.replace(
    // 第 1 组：代码区（fenced ``` / ~~~ 与 inline `...`）原样放行，
    // 避免把代码里的字面 \( 误当公式抽走；第 2 组：数学片段。
    /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)|(\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\])/g,
    (match, code, math) => {
      if (code) return code
      const index = segments.push(math) - 1
      return '%%AIIA_MATH_SLOT_' + index + '%%'
    }
  )
  return { text: protectedText, segments }
}

window.restoreMathDelimiters = function (html, segments) {
  if (typeof html !== 'string' || !segments || segments.length === 0) {
    return html
  }
  return html.replace(/%%AIIA_MATH_SLOT_(\d+)%%/g, (match, rawIndex) => {
    const segment = segments[Number(rawIndex)]
    if (segment === undefined) return match
    return segment
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  })
}

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
  console.debug('MathJax: math content detected, loading MathJax (~1.17MB)…')

  // 动态创建 <script> 元素加载 MathJax
  const script = document.createElement('script')
  script.id = 'MathJax-script'
  script.async = true
  script.src = '/static/js/tex-mml-chtml.js' // 本地托管的 MathJax 脚本
  script.onload = function () {
    window._mathJaxLoaded = true
    console.debug('MathJax script loaded')
  }
  script.onerror = function () {
    console.error('MathJax script load failed')
    window._mathJaxLoading = false
  }
  document.head.appendChild(script)
}
