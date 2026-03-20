/* eslint-disable */
(function (root, factory) {
  const api = factory()
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api
  }
  if (root) {
    root.AIIAWebviewHelpers = api
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function getNavigatorValue(nav, key) {
    if (!nav || typeof nav !== 'object') return ''
    const value = nav[key]
    return typeof value === 'string' ? value : ''
  }

  function detectMacLikePlatform(nav) {
    const uaDataPlatform =
      nav &&
      nav.userAgentData &&
      typeof nav.userAgentData.platform === 'string'
        ? nav.userAgentData.platform
        : ''
    const platform = getNavigatorValue(nav, 'platform')
    const userAgent = getNavigatorValue(nav, 'userAgent')
    const maxTouchPoints =
      nav && Number.isFinite(Number(nav.maxTouchPoints))
        ? Number(nav.maxTouchPoints)
        : 0

    const haystacks = [uaDataPlatform, platform, userAgent]
      .filter(Boolean)
      .map((value) => value.toLowerCase())

    if (haystacks.some((value) => value.includes('mac'))) return true
    if (haystacks.some((value) => /iphone|ipad|ipod/.test(value))) return true

    // iPadOS 桌面模式经常暴露为 MacIntel，但同时存在触摸点。
    if (platform === 'MacIntel' && maxTouchPoints > 1) return true

    return false
  }

  function buildClipboardFileKey(file) {
    if (!file) return ''
    return [
      file.name || '',
      file.type || '',
      Number.isFinite(Number(file.size)) ? Number(file.size) : '',
      Number.isFinite(Number(file.lastModified)) ? Number(file.lastModified) : ''
    ].join('::')
  }

  function pushUniqueImageFile(target, seenKeys, file) {
    if (!file || !file.type || !String(file.type).startsWith('image/')) return
    const key = buildClipboardFileKey(file)
    if (key && seenKeys.has(key)) return
    if (key) seenKeys.add(key)
    target.push(file)
  }

  function collectImageFilesFromClipboard(clipboardData) {
    const files = []
    const seenKeys = new Set()
    if (!clipboardData) return files

    const items = Array.from(clipboardData.items || [])
    for (const item of items) {
      if (!item || item.kind !== 'file') continue
      if (!item.type || !String(item.type).startsWith('image/')) continue
      const file = typeof item.getAsFile === 'function' ? item.getAsFile() : null
      pushUniqueImageFile(files, seenKeys, file)
    }

    if (files.length > 0) return files

    const clipboardFiles = Array.from(clipboardData.files || [])
    for (const file of clipboardFiles) {
      pushUniqueImageFile(files, seenKeys, file)
    }
    return files
  }

  function parseRgbColor(color) {
    if (!color) return null
    const value = String(color).trim()
    if (!value) return null
    const match = value.match(/^rgba?\(([^)]+)\)$/i)
    if (!match) return null
    const parts = match[1].split(',').map((part) => Number(part.trim()))
    if (parts.length < 3 || parts.slice(0, 3).some((part) => !Number.isFinite(part))) {
      return null
    }
    return { r: parts[0], g: parts[1], b: parts[2] }
  }

  function resolveThemeKind(doc) {
    const body = doc && doc.body
    const html = doc && doc.documentElement
    if (body && body.classList) {
      if (
        body.classList.contains('vscode-light') ||
        body.classList.contains('vscode-high-contrast-light')
      ) {
        return 'light'
      }
      if (
        body.classList.contains('vscode-dark') ||
        body.classList.contains('vscode-high-contrast')
      ) {
        return 'dark'
      }
    }

    if (doc && typeof doc.defaultView !== 'undefined' && body) {
      try {
        const colorScheme = String(doc.defaultView.getComputedStyle(body).colorScheme || '').toLowerCase()
        if (colorScheme.includes('light')) return 'light'
        if (colorScheme.includes('dark')) return 'dark'

        const rgb = parseRgbColor(doc.defaultView.getComputedStyle(body).backgroundColor)
        if (rgb) {
          const luminance = (0.2126 * rgb.r) + (0.7152 * rgb.g) + (0.0722 * rgb.b)
          return luminance < 128 ? 'dark' : 'light'
        }
      } catch (_) {
        // 忽略：某些宿主环境可能不支持 getComputedStyle / colorScheme
      }
    }

    if (html && html.getAttribute) {
      const existing = html.getAttribute('data-vscode-theme-kind')
      if (existing === 'light' || existing === 'dark') {
        return existing
      }
    }

    return 'dark'
  }

  function applyThemeKindToDocument(doc) {
    const html = doc && doc.documentElement
    if (!html) return 'dark'

    const themeKind = resolveThemeKind(doc)
    if (typeof html.setAttribute === 'function') {
      html.setAttribute('data-vscode-theme-kind', themeKind)
    }
    if (html.style) {
      html.style.colorScheme = themeKind
    }
    return themeKind
  }

  return {
    applyThemeKindToDocument,
    collectImageFilesFromClipboard,
    detectMacLikePlatform,
    resolveThemeKind
  }
})
