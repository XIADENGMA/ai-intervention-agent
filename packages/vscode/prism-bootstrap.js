;(function () {
  try {

    if (typeof globalThis !== 'undefined') {
      globalThis.Prism = globalThis.Prism || {}
      globalThis.Prism.manual = true
    } else if (typeof window !== 'undefined') {
      window.Prism = window.Prism || {}
      window.Prism.manual = true
    }
  } catch (_) {

  }
})()
