/**
 * MathJax 数学公式渲染配置
 *
 * 配置 MathJax 库的行为，支持在网页中渲染 LaTeX 数学公式。
 *
 * ## 功能概述
 *
 * - 支持内联数学公式和块级数学公式
 * - 支持 TeX/LaTeX 语法
 * - 自动处理转义字符
 * - 跳过特定 HTML 标签避免误渲染
 * - 加载 AMS 数学扩展包
 *
 * ## 配置说明
 *
 * ### tex 配置块
 * - **inlineMath**: 内联公式定界符（单行内显示）
 * - **displayMath**: 块级公式定界符（独立行显示）
 * - **processEscapes**: 处理反斜杠转义字符
 * - **processEnvironments**: 处理 LaTeX 环境
 * - **packages**: 加载的扩展包列表
 * - **tags**: 公式编号样式（AMS 风格）
 *
 * ### options 配置块
 * - **skipHtmlTags**: 跳过的 HTML 标签（避免在代码块等位置渲染公式）
 * - **ignoreHtmlClass**: 忽略的 CSS 类名
 * - **processHtmlClass**: 强制处理的 CSS 类名
 *
 * ### startup 配置块
 * - **ready**: MathJax 加载完成后的回调函数
 * - 输出日志确认加载状态
 * - 调用默认的初始化流程
 *
 * ## 使用场景
 *
 * - AI Intervention Agent 的 Markdown 内容渲染
 * - 用户反馈中包含的数学公式
 * - 技术文档和科学计算相关内容
 *
 * ## 支持的公式语法
 *
 * - 内联公式：使用 `$...$` 或 `\\(...\\)`
 * - 块级公式：使用 `$$...$$` 或 `\\[...\\]`
 * - LaTeX 命令：支持 AMS 数学扩展
 * - 自定义宏：支持 newcommand
 *
 * ## 注意事项
 *
 * - 配置必须在 MathJax 加载前设置
 * - 修改配置后需要刷新页面生效
 * - 避免在 code/pre 标签中渲染公式
 * - 使用 tex2jax_ignore 类可以跳过特定元素
 */
window.MathJax = {
  // TeX/LaTeX 输入处理器配置
  tex: {
    // 内联数学公式定界符
    // 格式：[开始符, 结束符]
    // $...$ 和 \\(...\\) 都可以用于内联公式
    inlineMath: [
      ['$', '$'],
      ['\\(', '\\)']
    ],

    // 块级数学公式定界符
    // $$...$$ 和 \\[...\\] 都可以用于块级公式
    // 块级公式会独占一行并居中显示
    displayMath: [
      ['$$', '$$'],
      ['\\[', '\\]']
    ],

    // 处理转义字符
    // true: 识别反斜杠转义（如 \$, \\）
    processEscapes: true,

    // 处理 LaTeX 环境
    // true: 支持 \begin{环境} ... \end{环境} 语法
    processEnvironments: true,

    // 加载的扩展包
    // ams: 美国数学学会扩展（提供高级数学符号）
    // newcommand: 支持自定义宏命令
    // configmacros: 支持配置宏
    packages: { '[+]': ['ams', 'newcommand', 'configmacros'] },

    // 公式编号样式
    // 'ams': 使用 AMS 风格的编号系统
    tags: 'ams'
  },

  // CHTML 输出配置
  chtml: {
    // 禁用字体预加载，避免 404 错误
    // MathJax 会在需要时动态生成字体，而不是预加载 WOFF 文件
    fontURL: null,
    // 使用内联 CSS 样式而不是外部字体文件
    // 这样可以避免加载 .woff 字体文件导致的 404 错误
    // MathJax 会将字体信息嵌入到生成的 SVG/HTML 中
  },

  // 渲染选项配置
  options: {
    // 跳过的 HTML 标签
    // 在这些标签内的内容不会被 MathJax 处理
    // 避免在代码块、脚本等位置误渲染公式
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],

    // 忽略的 CSS 类
    // 带有此类名的元素及其子元素不会被处理
    // 用于明确排除某些区域
    ignoreHtmlClass: 'tex2jax_ignore',

    // 强制处理的 CSS 类
    // 即使在 skipHtmlTags 中，带有此类名的元素仍会被处理
    // 用于特殊情况下强制渲染公式
    processHtmlClass: 'tex2jax_process'
  },

  // 启动配置
  startup: {
    // 加载完成回调
    // 在 MathJax 完全加载并准备就绪时调用
    ready: () => {
      // 输出加载状态到控制台
      // 用于调试和确认 MathJax 是否正常初始化
      console.log('MathJax 已加载完成')

      // 调用默认的初始化流程
      // 必须调用以完成 MathJax 的设置
      MathJax.startup.defaultReady()
    }
  }
}
