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
    tags: 'ams',
    // A formula must not be able to link, restyle or re-id the approval page.
    // The html extension (\href, \class, \style, \cssId) and \bbox (whose
    // option takes any CSS) can do all of that, so autoload registers none of
    // their macros and \require refuses to load them.
    autoload: { html: [], bbox: [] },
    require: { allow: { html: false, bbox: false } }
  },
  options: {
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
    ignoreHtmlClass: 'tex2jax_ignore',
    processHtmlClass: 'tex2jax_process'
  },
  startup: {
    typeset: false,
    ready: () => {
      console.debug('MathJax loaded')
      MathJax.startup.defaultReady()
      if (window._mathJaxPendingElements) {
        const pendingElements = window._mathJaxPendingElements
        const pendingElementCount = pendingElements.length
        for (let index = 0; index < pendingElementCount; index += 1) {
          if (!(index in pendingElements)) continue
          const el = pendingElements[index]
          window._mathJaxTypeset(el)
        }
        window._mathJaxPendingElements = []
      }
    }
  }
}

window._mathJaxLoading = false
window._mathJaxLoaded = false
window._mathJaxPendingElements = []

window._mathJaxTypeset = function (element) {
  return MathJax.typesetPromise([element]).catch(error => {
    console.warn('MathJax render failed:', error)
    if (!element || typeof element.querySelectorAll !== 'function') return undefined
    const spans = element.querySelectorAll('.tex2jax_process')
    if (spans.length < 2) return undefined
    if (typeof MathJax.typesetClear === 'function') MathJax.typesetClear([element])
    let chain = Promise.resolve()
    for (let index = 0; index < spans.length; index += 1) {
      const span = spans[index]
      chain = chain.then(() =>
        MathJax.typesetPromise([span]).catch(spanError => {
          console.warn('MathJax render failed:', spanError)
          if (typeof MathJax.typesetClear === 'function') MathJax.typesetClear([span])
        })
      )
    }
    return chain
  })
}

;(function () {
  const SLOT_PREFIX = '%%AIIA_MATH_SLOT_'
  const SLOT_SUFFIX = '%%'
  const MAX_INLINE = 2000
  const MAX_DISPLAY = 30000
  const BLANK_LINE = /\n[ \t]*\r?\n/
  const DISPLAY_ENVIRONMENT = /^(?:align|alignat|equation|flalign|gather|multline|eqnarray)\*?$/

  window.protectMathDelimiters = function (text) {
    if (
      typeof text !== 'string' ||
      (text.indexOf('$') === -1 &&
        text.indexOf('\\(') === -1 &&
        text.indexOf('\\[') === -1 &&
        text.indexOf('\\begin{') === -1)
    ) {
      return { text, segments: [] }
    }

    const n = text.length
    const segments = []
    const out = []
    let copied = 0
    let i = 0

    function finder(needle) {
      let cached = -2
      return function (from) {
        if (cached === -1) return -1
        if (cached >= from) return cached
        cached = text.indexOf(needle, from)
        return cached
      }
    }
    const nextDollar = finder('$')
    const nextDoubleDollar = finder('$$')
    const nextParenClose = finder('\\)')
    const nextBracketClose = finder('\\]')
    const nextEnvironmentEnd = {}

    function isEscaped(position) {
      let backslashes = 0
      while (position - 1 - backslashes >= 0 && text.charCodeAt(position - 1 - backslashes) === 92) {
        backslashes += 1
      }
      return backslashes % 2 === 1
    }

    function isSpace(code) {
      return code === 32 || code === 9 || code === 10 || code === 13
    }

    function isDigit(code) {
      return code >= 48 && code <= 57
    }

    let nextNewline = text.indexOf('\n')
    let lineStart = 0
    function startOfLine(position) {
      while (nextNewline !== -1 && nextNewline < position) {
        lineStart = nextNewline + 1
        nextNewline = text.indexOf('\n', lineStart)
      }
      return lineStart
    }

    function quoteDepth(from, limit) {
      let depth = 0
      let p = from
      for (;;) {
        let spaces = 0
        while (p < limit && spaces < 3 && text.charCodeAt(p) === 32) {
          p += 1
          spaces += 1
        }
        if (p >= limit || text.charCodeAt(p) !== 62) return depth
        depth += 1
        p += 1
        if (text.charCodeAt(p) === 32) p += 1
      }
    }

    function stripQuoteMarkers(line, depth) {
      let p = 0
      for (let removed = 0; removed < depth; removed += 1) {
        let q = p
        while (q < line.length && q - p < 3 && line.charCodeAt(q) === 32) q += 1
        if (line.charCodeAt(q) !== 62) break
        q += 1
        if (line.charCodeAt(q) === 32) q += 1
        p = q
      }
      return line.slice(p)
    }

    function formulaText(start, end) {
      const raw = text.slice(start, end)
      if (raw.indexOf('\n') === -1) return raw
      const depth = quoteDepth(startOfLine(start), start)
      if (depth === 0) return raw
      const lines = raw.split('\n')
      for (let k = 1; k < lines.length; k += 1) lines[k] = stripQuoteMarkers(lines[k], depth)
      return lines.join('\n')
    }

    function emit(start, end) {
      out.push(text.slice(copied, start), SLOT_PREFIX + segments.length + SLOT_SUFFIX)
      segments.push(formulaText(start, end))
      copied = end
      i = end
    }

    function crossesBlankLine(start, end) {
      return BLANK_LINE.test(text.slice(start, end))
    }

    function skipFence(lineStart) {
      let p = lineStart
      while (p < n && p - lineStart < 3 && text.charCodeAt(p) === 32) p += 1
      const marker = text.charCodeAt(p)
      if (marker !== 96 && marker !== 126) return -1
      let q = p
      while (q < n && text.charCodeAt(q) === marker) q += 1
      const run = q - p
      if (run < 3) return -1
      let eol = text.indexOf('\n', q)
      if (marker === 96 && text.slice(q, eol === -1 ? n : eol).indexOf('`') !== -1) return -1
      while (eol !== -1) {
        const next = eol + 1
        let r = next
        while (r < n && r - next < 3 && text.charCodeAt(r) === 32) r += 1
        let s = r
        while (s < n && text.charCodeAt(s) === marker) s += 1
        if (s - r >= run) {
          let t = s
          while (t < n && (text.charCodeAt(t) === 32 || text.charCodeAt(t) === 9 || text.charCodeAt(t) === 13)) {
            t += 1
          }
          if (t >= n || text.charCodeAt(t) === 10) return t
        }
        eol = text.indexOf('\n', next)
      }
      return n
    }

    function skipCodeSpan(start) {
      let q = start
      while (q < n && text.charCodeAt(q) === 96) q += 1
      const run = q - start
      let p = q
      for (;;) {
        const k = text.indexOf('`', p)
        if (k === -1) return q
        let e = k
        while (e < n && text.charCodeAt(e) === 96) e += 1
        if (e - k === run) return crossesBlankLine(start, k) ? q : e
        p = e
      }
    }

    function skipLinkDestination(start) {
      let p = start
      let depth = 1
      while (p < n && p - start < 2000) {
        const code = text.charCodeAt(p)
        if (code === 92) {
          p += 2
          continue
        }
        if (isSpace(code)) break
        if (code === 40) depth += 1
        else if (code === 41) {
          depth -= 1
          if (depth === 0) break
        }
        p += 1
      }
      return p
    }

    function skipImage(start) {
      let p = start + 2
      while (p < n && p - start < 500) {
        const code = text.charCodeAt(p)
        if (code === 92) {
          p += 2
          continue
        }
        if (code === 10 || code === 93) break
        p += 1
      }
      if (text.charCodeAt(p) !== 93 || text.charCodeAt(p + 1) !== 40) return -1
      return skipLinkDestination(p + 2)
    }

    function isUrlStart(position) {
      return (
        text.startsWith('http://', position) ||
        text.startsWith('https://', position) ||
        text.startsWith('ftp://', position) ||
        text.startsWith('www.', position)
      )
    }

    function skipBareUrl(start) {
      let p = start
      while (p < n) {
        const code = text.charCodeAt(p)
        if (isSpace(code) || code === 60 || code === 62) break
        p += 1
      }
      return p
    }

    function tryEnclosed(start, find) {
      let close = find(start + 2)
      while (close !== -1 && isEscaped(close)) close = find(close + 1)
      if (close === -1 || close - start > MAX_DISPLAY) return false
      if (text.slice(start + 2, close).trim() === '') return false
      emit(start, close + 2)
      return true
    }

    function tryEnvironment(start) {
      const nameEnd = text.indexOf('}', start + 7)
      if (nameEnd === -1 || nameEnd - start > 24) return false
      const name = text.slice(start + 7, nameEnd)
      if (!DISPLAY_ENVIRONMENT.test(name)) return false
      const endMarker = '\\end{' + name + '}'
      if (!nextEnvironmentEnd[name]) nextEnvironmentEnd[name] = finder(endMarker)
      const find = nextEnvironmentEnd[name]
      let close = find(nameEnd + 1)
      while (close !== -1 && isEscaped(close)) close = find(close + 1)
      if (close === -1 || close - start > MAX_DISPLAY) return false
      emit(start, close + endMarker.length)
      return true
    }

    function tryDisplayDollars(start) {
      let close = nextDoubleDollar(start + 2)
      while (close !== -1 && isEscaped(close)) close = nextDoubleDollar(close + 1)
      if (close === -1 || close - start > MAX_DISPLAY) return false
      if (text.slice(start + 2, close).trim() === '') return false
      emit(start, close + 2)
      return true
    }

    function tryInlineDollar(start) {
      let close = nextDollar(start + 1)
      while (close !== -1 && isEscaped(close)) close = nextDollar(close + 1)
      if (close === -1 || close - start > MAX_INLINE) return false
      if (isSpace(text.charCodeAt(close - 1)) || isDigit(text.charCodeAt(close + 1))) return false
      if (crossesBlankLine(start, close)) return false
      emit(start, close + 1)
      return true
    }

    while (i < n) {
      if (i === 0 || text.charCodeAt(i - 1) === 10) {
        const fenceEnd = skipFence(i)
        if (fenceEnd > i) {
          i = fenceEnd
          continue
        }
      }
      const code = text.charCodeAt(i)
      if (code === 96) {
        i = skipCodeSpan(i)
      } else if (code === 92) {
        const next = text.charCodeAt(i + 1)
        let handled = false
        if (next === 40) handled = tryEnclosed(i, nextParenClose)
        else if (next === 91) handled = tryEnclosed(i, nextBracketClose)
        else if (next === 98 && text.startsWith('\\begin{', i)) handled = tryEnvironment(i)
        if (!handled) i += 2
      } else if (code === 36) {
        const next = text.charCodeAt(i + 1)
        let handled = false
        if (next === 36) {
          if (text.charCodeAt(i + 2) === 36) {
            while (i < n && text.charCodeAt(i) === 36) i += 1
            continue
          }
          handled = tryDisplayDollars(i)
          if (!handled) i += 2
        } else {
          if (!Number.isNaN(next) && !isSpace(next)) handled = tryInlineDollar(i)
          if (!handled) i += 1
        }
      } else if (code === 33 && text.charCodeAt(i + 1) === 91) {
        const end = skipImage(i)
        i = end === -1 ? i + 1 : end
      } else if (code === 93 && text.charCodeAt(i + 1) === 40) {
        i = skipLinkDestination(i + 2)
      } else if (
        (code === 104 || code === 102 || code === 119) &&
        isUrlStart(i) &&
        (i === 0 || !/[A-Za-z0-9]/.test(text.charAt(i - 1)))
      ) {
        i = skipBareUrl(i)
      } else {
        i += 1
      }
    }

    if (segments.length === 0) return { text, segments }
    out.push(text.slice(copied))
    return { text: out.join(''), segments }
  }

  function escapeHtml(value) {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;')
  }

  window.restoreMathDelimiters = function (html, segments) {
    if (typeof html !== 'string' || !segments || segments.length === 0) {
      return html
    }
    let codeDepth = 0
    return html.replace(/(<[^>]*>)|%%AIIA_MATH_SLOT_(\d+)%%/g, (match, tag, rawIndex) => {
      if (tag) {
        const codeTag = /^<(\/?)(?:pre|code)(?=[\s>/])/i.exec(tag)
        if (codeTag) codeDepth = Math.max(0, codeDepth + (codeTag[1] ? -1 : 1))
        if (tag.indexOf(SLOT_PREFIX) === -1) return tag
        return tag.replace(/%%AIIA_MATH_SLOT_(\d+)%%/g, (slot, index) => {
          const original = segments[Number(index)]
          return original === undefined ? slot : escapeAttribute(original)
        })
      }
      const segment = segments[Number(rawIndex)]
      if (segment === undefined) return match
      if (codeDepth > 0) return escapeHtml(segment)
      return '<span class="tex2jax_process">' + escapeHtml(segment) + '</span>'
    })
  }
})()

window.hasMathContent = function (text) {
  if (!text) return false
  return /\$|\\\(|\\\[|\\begin\{/.test(text)
}

window.loadMathJaxIfNeeded = function (element, text) {
  if (!window.hasMathContent(text)) {
    return
  }
  if (
    !element ||
    typeof element.querySelector !== 'function' ||
    !element.querySelector('.tex2jax_process')
  ) {
    return
  }
  if (element.classList) {
    element.classList.add('tex2jax_ignore')
  }

  if (window._mathJaxLoaded && window.MathJax && window.MathJax.typesetPromise) {
    window._mathJaxTypeset(element)
    return
  }

  window._mathJaxPendingElements.push(element)

  if (window._mathJaxLoading) {
    return
  }

  window._mathJaxLoading = true
  console.debug('MathJax: math content detected, loading MathJax (~1.17MB)…')

  const script = document.createElement('script')
  script.id = 'MathJax-script'
  script.async = true
  script.src = '/static/js/tex-mml-chtml.js'
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
