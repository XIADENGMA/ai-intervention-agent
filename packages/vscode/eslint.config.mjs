import globals from 'globals'
import aiiaI18n from './eslint-plugin-aiia-i18n.mjs'

export default [
  {
    ignores: [
      '**/node_modules/**',
      '**/.vscode-test/**',
      '**/dist/**',
      '**/*.vsix',
      'marked.min.js',
      'prism.min.js',
      'lottie.min.js',
      'mathjax/**',

      'locales/**',
      'l10n/**',

      'test/eslint-fixtures/**'
    ]
  },

  {
    files: ['**/*.js', '**/*.mjs'],
    languageOptions: {
      globals: {
        ...globals.commonjs,
        ...globals.node,
        ...globals.mocha
      },
      ecmaVersion: 2022,
      sourceType: 'module'
    },
    rules: {
      'no-const-assign': 'warn',
      'no-this-before-super': 'warn',
      'no-undef': 'warn',
      'no-unreachable': 'warn',
      'no-unused-vars': ['warn', { caughtErrors: 'none' }],
      'constructor-super': 'warn',
      'valid-typeof': 'warn'
    }
  },

  // /* eslint-env browser */ 否则 Web UI 一侧也得跟着改 → 这里以 file glob

  {
    files: [
      'webview-ui.js',
      'webview-helpers.js',
      'webview-notify-core.js',
      'webview-settings-ui.js',
      'webview-state.js',
      'i18n.js',
      'prism-bootstrap.js',
      'tri-state-panel.js',
      'tri-state-panel-loader.js',
      'tri-state-panel-bootstrap.js'
    ],
    languageOptions: {
      globals: {
        ...globals.browser,
        acquireVsCodeApi: 'readonly',
        marked: 'readonly',
        Prism: 'readonly',
        MathJax: 'readonly',
        AIIA_I18N: 'readonly',
        AIIAState: 'readonly',
        AIIA_TRI_STATE_PANEL: 'readonly',
        AIIA_TRI_STATE_PANEL_ACTIONS: 'readonly',
        AIIA_TRI_STATE_PANEL_CONTROLLER: 'readonly',
        AIIA_CONTENT_SM: 'readonly'
      }
    }
  },

  {
    files: ['**/*.js', '**/*.mjs'],
    plugins: { 'aiia-i18n': aiiaI18n },
    rules: {
      'aiia-i18n/no-missing-i18n-key': 'error'
    }
  }
]
