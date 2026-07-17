"""R569 regression coverage for VS Code webview sanitizer attribute traversal."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


def test_sanitize_prompt_html_walks_attributes_without_array_snapshot() -> None:
    source = _source()
    body = _extract_function(source, "function sanitizePromptHtml(")

    assert "Array.from(el.attributes || [])" not in body
    assert "const attributes = el.attributes || []" in body
    assert (
        "for (let attrIndex = attributes.length - 1; attrIndex >= 0; attrIndex -= 1)"
        in body
    )
    assert "attributes[attrIndex]" in body
    assert "attributes.item(attrIndex)" in body
    assert "if (!attr) continue" in body


def test_reverse_attribute_walk_handles_live_namednodemap_removals_and_appends() -> (
    None
):
    script = textwrap.dedent(
        """
        const itemCalls = []

        class Element {
          constructor(tagName, attrs) {
            this.tagName = tagName
            this._attrs = attrs.map(([name, value]) => ({ name, value }))
            this.removed = false
            this.attributes = new Proxy({}, {
              get: (_target, prop) => {
                if (prop === 'length') return this._attrs.length
                if (prop === 'item') {
                  return (index) => {
                    itemCalls.push(index)
                    return this._attrs[index] || null
                  }
                }
                if (prop === 'forEach') throw new Error('forEach should not be read')
                if (prop === Symbol.iterator) throw new Error('iterator should not be read')
                return undefined
              },
            })
          }

          removeAttribute(name) {
            const lower = String(name).toLowerCase()
            const index = this._attrs.findIndex(attr => String(attr.name).toLowerCase() === lower)
            if (index !== -1) this._attrs.splice(index, 1)
          }

          setAttribute(name, value) {
            const lower = String(name).toLowerCase()
            const existing = this._attrs.find(attr => String(attr.name).toLowerCase() === lower)
            if (existing) {
              existing.value = String(value)
            } else {
              this._attrs.push({ name, value: String(value) })
            }
          }

          remove() {
            this.removed = true
          }
        }

        function normalizeUrl(url, kind) {
          const trimmed = String(url || '').trim()
          if (!trimmed || /^javascript:/i.test(trimmed)) return ''
          if (kind === 'a' && trimmed.startsWith('/')) return 'https://server.test' + trimmed
          return trimmed
        }

        function cleanAttrs(el, tag) {
          const ALLOWED_ATTR = {
            a: new Set(['href', 'title', 'target', 'rel']),
            img: new Set(['src', 'alt', 'title']),
          }
          const allowed = ALLOWED_ATTR[tag] || new Set(['class'])
          const attributes = el.attributes || []
          for (let attrIndex = attributes.length - 1; attrIndex >= 0; attrIndex -= 1) {
            const attr =
              attributes[attrIndex] ||
              (typeof attributes.item === 'function' ? attributes.item(attrIndex) : null)
            if (!attr) continue
            const name = String(attr.name || '').toLowerCase()
            const value = String(attr.value || '')

            if (name.startsWith('on') || name === 'style') {
              el.removeAttribute(attr.name)
              continue
            }

            if (!allowed.has(name)) {
              el.removeAttribute(attr.name)
              continue
            }

            if (tag === 'a' && name === 'href') {
              const safe = normalizeUrl(value, 'a')
              if (!safe) {
                el.removeAttribute('href')
              } else {
                el.setAttribute('href', safe)
                el.setAttribute('target', '_blank')
                el.setAttribute('rel', 'noopener noreferrer')
              }
              continue
            }

            if (tag === 'img' && name === 'src') {
              const safe = normalizeUrl(value, 'img')
              if (!safe) {
                el.remove()
              } else {
                el.setAttribute('src', safe)
              }
              continue
            }

            el.setAttribute(attr.name, value)
          }
        }

        Object.defineProperty(Array, 'from', {
          value() {
            throw new Error('Array.from should not be called')
          },
          configurable: true,
        })

        const link = new Element('a', [
          ['href', ' /ok '],
          ['onclick', 'bad()'],
          ['style', 'color:red'],
          ['data-x', 'drop'],
          ['title', 'Keep'],
        ])
        cleanAttrs(link, 'a')

        const img = new Element('img', [
          ['src', 'javascript:bad()'],
          ['onerror', 'bad()'],
          ['alt', 'Keep'],
        ])
        cleanAttrs(img, 'img')

        process.stdout.write(JSON.stringify({
          linkAttrs: link._attrs,
          imgAttrs: img._attrs,
          imgRemoved: img.removed,
          itemCalls,
        }))
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "linkAttrs": [
            {"name": "href", "value": "https://server.test/ok"},
            {"name": "title", "value": "Keep"},
            {"name": "target", "value": "_blank"},
            {"name": "rel", "value": "noopener noreferrer"},
        ],
        "imgAttrs": [
            {"name": "src", "value": "javascript:bad()"},
            {"name": "alt", "value": "Keep"},
        ],
        "imgRemoved": True,
        "itemCalls": [4, 3, 2, 1, 0, 2, 1, 0],
    }
