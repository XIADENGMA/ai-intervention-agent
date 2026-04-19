/**
 * ESLint flat-config plugin: aiia-i18n (L4·G2).
 *
 * Two rules, both share the same AST walker but differ in severity /
 * default wiring per the TODO copy:
 *
 *   aiia-i18n/no-missing-i18n-key
 *     -- Any ``t|_t|tl|hostT|__vuT|__domSecT|__ncT`` call whose string
 *        literal argument is a key that is NOT present in the loaded
 *        locale JSON files is an error. Catches typos, renames that
 *        missed a call site, and copy-paste errors.
 *
 *   aiia-i18n/no-undefined-i18n-key (alias of the above)
 *     -- Kept because TODO lists both names (ICU/react-intl convention
 *        varies). Downstream can enable either.
 *
 * **Non-goals**:
 *   - We do NOT validate parameter names (``{{count}}`` vs function
 *     args) — that's better handled at runtime and already covered by
 *     ``check_i18n_locale_parity.py`` for placeholder parity.
 *   - We do NOT scan the JSON itself for typo'd keys (orphans) — see
 *     ``scripts/check_i18n_orphan_keys.py``.
 *
 * **Locale resolution**:
 *   The rule loads ``<repoRoot>/packages/vscode/locales/en.json`` at
 *   rule-init time. For a mono-locale-root repo that's enough; when a
 *   project has multiple locale roots, pass them via rule options::
 *
 *     rules: {
 *       'aiia-i18n/no-missing-i18n-key': ['error', {
 *         localePaths: ['path/to/en.json', 'path/to/zh-CN.json']
 *       }]
 *     }
 *
 *   We union keys across all loaded locales and use the union as the
 *   "valid" set. That means a key only present in the secondary
 *   locale still counts as valid (the runtime fallback chain handles
 *   that). We rely on ``check_i18n_locale_parity.py`` + its pytest
 *   mirror to catch per-locale gaps.
 */

import fs from 'node:fs'
import path from 'node:path'
import url from 'node:url'

const __dirname = path.dirname(url.fileURLToPath(import.meta.url))
const DEFAULT_LOCALE_PATHS = [
  path.resolve(__dirname, 'locales', 'en.json'),
  path.resolve(__dirname, '..', '..', 'static', 'locales', 'en.json')
]

const WRAPPERS = new Set(['t', '_t', 'tl', 'hostT', '__vuT', '__domSecT', '__ncT'])

function flatten(obj, prefix, out) {
  for (const k of Object.keys(obj)) {
    const v = obj[k]
    const p = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      flatten(v, p, out)
    } else {
      out.add(p)
    }
  }
  return out
}

function loadKeySet(paths) {
  const all = new Set()
  for (const p of paths) {
    try {
      const raw = fs.readFileSync(p, 'utf8')
      const data = JSON.parse(raw)
      flatten(data, '', all)
    } catch (_e) {
      // 静默 — 让用户在 rule options 里指定 localePaths 时得到空集即可。
      // 真正的硬错误（文件损坏等）由 check_i18n_locale_parity 报。
    }
  }
  return all
}

function makeRule(name) {
  return {
    meta: {
      type: 'problem',
      docs: {
        description:
          `Require every key passed to ${[...WRAPPERS].map(x => `\`${x}()\``).join(' / ')} ` +
          'to exist in at least one loaded locale JSON.',
        recommended: true
      },
      schema: [
        {
          type: 'object',
          properties: {
            localePaths: {
              type: 'array',
              items: { type: 'string' }
            },
            // Extra wrapper identifiers to recognize beyond the default
            // set (future-proofing — add rarely, the default set should
            // cover every production call site).
            extraWrappers: {
              type: 'array',
              items: { type: 'string' }
            }
          },
          additionalProperties: false
        }
      ],
      messages: {
        missing:
          `i18n key "{{key}}" not found in any loaded locale (${name}). ` +
          'Add the key to static/locales/*.json or packages/vscode/locales/*.json, ' +
          'or correct the typo.'
      }
    },
    create(context) {
      const opts = context.options[0] || {}
      const paths =
        Array.isArray(opts.localePaths) && opts.localePaths.length
          ? opts.localePaths
          : DEFAULT_LOCALE_PATHS
      const wrappers = new Set(WRAPPERS)
      if (Array.isArray(opts.extraWrappers)) {
        for (const name of opts.extraWrappers) wrappers.add(name)
      }
      const validKeys = loadKeySet(paths)
      if (validKeys.size === 0) return {} // No locales → nothing to check.

      return {
        CallExpression(node) {
          const callee = node.callee
          let name = null
          if (callee.type === 'Identifier') {
            name = callee.name
          } else if (callee.type === 'MemberExpression' && callee.property.type === 'Identifier') {
            // ``obj.t(...)`` deliberately skipped — matches the regex
            // scanner in scripts/check_i18n_orphan_keys.py.
            return
          }
          if (!name || !wrappers.has(name)) return
          const first = node.arguments[0]
          if (!first) return
          // Only literal string args are statically checkable.
          if (first.type !== 'Literal' || typeof first.value !== 'string') {
            return
          }
          const key = first.value
          if (!validKeys.has(key)) {
            context.report({
              node: first,
              messageId: 'missing',
              data: { key }
            })
          }
        }
      }
    }
  }
}

export default {
  meta: {
    name: 'aiia-i18n',
    version: '1.0.0'
  },
  rules: {
    'no-missing-i18n-key': makeRule('no-missing-i18n-key'),
    'no-undefined-i18n-key': makeRule('no-undefined-i18n-key')
  }
}
