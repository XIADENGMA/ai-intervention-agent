
;(function () {
  try {
    // 必须在 prism.min.js 加载前设置，才能禁用自动高亮（由 webview-ui.js 手动触发 highlightAllUnder）
    if (typeof globalThis !== 'undefined') {
      globalThis.Prism = globalThis.Prism || {}
      globalThis.Prism.manual = true
    } else if (typeof window !== 'undefined') {
      window.Prism = window.Prism || {}
      window.Prism.manual = true
    }
  } catch (_) {
    // 忽略：配置失败不应影响 Webview 启动
  }
})()
