import fs from 'node:fs'
import path from 'node:path'
import url from 'node:url'

const __dirname = path.dirname(url.fileURLToPath(import.meta.url))

const DEFAULT_LOCALE_PATHS = [
  path.resolve(__dirname, 'locales', 'en.json'),
  path.resolve(__dirname, '..', '..', 'src', 'ai_intervention_agent', 'static', 'locales', 'en.json'),
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
          'Add the key to src/ai_intervention_agent/static/locales/*.json or packages/vscode/locales/*.json, ' +
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
      if (validKeys.size === 0) return {}

      return {
        CallExpression(node) {
          const callee = node.callee
          let name = null
          if (callee.type === 'Identifier') {
            name = callee.name
          } else if (callee.type === 'MemberExpression' && callee.property.type === 'Identifier') {

            return
          }
          if (!name || !wrappers.has(name)) return
          const first = node.arguments[0]
          if (!first) return

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
