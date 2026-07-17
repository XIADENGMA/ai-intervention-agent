"""R566 regression coverage for VS Code webview sanitizer NodeList traversal."""

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


def test_sanitize_prompt_html_walks_static_nodelist_in_reverse_without_array_copy() -> (
    None
):
    source = _source()
    body = _extract_function(source, "function sanitizePromptHtml(")

    assert "Array.from(container.querySelectorAll('*')).reverse()" not in body
    assert "const all = container.querySelectorAll('*')" in body
    assert "all.forEach" not in body
    assert "for (let allIndex = all.length - 1; allIndex >= 0; allIndex -= 1)" in body
    assert "all[allIndex]" in body
    assert "all.item(allIndex)" in body
    assert "if (!el) continue" in body


def test_reverse_indexed_walk_accepts_nodelist_like_without_array_methods() -> None:
    script = textwrap.dedent(
        """
        const order = []

        class Node {
          constructor(tagName) {
            this.tagName = tagName
            this.attributes = []
            this.children = []
            this.parentNode = null
            this.removed = false
          }

          get firstChild() {
            return this.children[0] || null
          }

          appendChild(child) {
            child.parentNode = this
            this.children.push(child)
          }

          insertBefore(child, reference) {
            if (child.parentNode) child.parentNode.removeChild(child)
            child.parentNode = this
            const referenceIndex = this.children.indexOf(reference)
            this.children.splice(referenceIndex === -1 ? this.children.length : referenceIndex, 0, child)
          }

          removeChild(child) {
            const index = this.children.indexOf(child)
            if (index !== -1) this.children.splice(index, 1)
            child.parentNode = null
          }

          remove() {
            if (this.parentNode) this.parentNode.removeChild(this)
            this.removed = true
          }

          removeAttribute() {}
          setAttribute() {}
        }

        const DROP_TAGS = new Set(['script'])
        const ALLOWED_TAGS = new Set(['div', 'span'])
        const ALLOWED_ATTR = {}

        function unwrapElement(el) {
          const parent = el.parentNode
          if (!parent) return
          while (el.firstChild) {
            parent.insertBefore(el.firstChild, el)
          }
          parent.removeChild(el)
          el.removed = true
        }

        function walk(all) {
          for (let allIndex = all.length - 1; allIndex >= 0; allIndex -= 1) {
            const el =
              all[allIndex] ||
              (typeof all.item === 'function' ? all.item(allIndex) : null)
            if (!el) continue
            const tag = String(el.tagName || '').toLowerCase()
            if (!tag) continue
            order.push(tag)

            if (DROP_TAGS.has(tag)) {
              el.remove()
              continue
            }

            if (!ALLOWED_TAGS.has(tag)) {
              unwrapElement(el)
              continue
            }

            const allowed = ALLOWED_ATTR[tag] || new Set(['class'])
            Array.from(el.attributes || []).forEach(attr => {
              const name = String(attr.name || '').toLowerCase()
              if (!allowed.has(name)) el.removeAttribute(attr.name)
            })
          }
        }

        const root = new Node('root')
        const outer = new Node('div')
        const dropped = new Node('script')
        const unwrapped = new Node('x-widget')
        const preservedChild = new Node('span')
        root.appendChild(outer)
        outer.appendChild(dropped)
        outer.appendChild(unwrapped)
        unwrapped.appendChild(preservedChild)

        const all = {
          0: outer,
          2: unwrapped,
          length: 3,
          item(index) {
            return index === 1 ? dropped : this[index] || null
          },
        }
        Object.defineProperty(all, 'reverse', {
          get() {
            throw new Error('reverse should not be read')
          },
        })
        Object.defineProperty(all, 'forEach', {
          get() {
            throw new Error('forEach should not be read')
          },
        })

        walk(all)

        process.stdout.write(JSON.stringify({
          order,
          rootChildren: root.children.map(node => node.tagName),
          outerChildren: outer.children.map(node => node.tagName),
          droppedRemoved: dropped.removed,
          unwrappedRemoved: unwrapped.removed,
          preservedChildParent: preservedChild.parentNode && preservedChild.parentNode.tagName,
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
        "order": ["x-widget", "script", "div"],
        "rootChildren": ["div"],
        "outerChildren": ["span"],
        "droppedRemoved": True,
        "unwrappedRemoved": True,
        "preservedChildParent": "div",
    }
