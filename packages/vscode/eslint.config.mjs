import globals from 'globals'

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
      'mathjax/**'
    ]
  },
  // Node.js / test 侧 JS（如 test/*.test.js、scripts/*.mjs）
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
  // Webview 侧 JS（运行在浏览器环境）
  {
    files: [
      'webview-ui.js',
      'webview-helpers.js',
      'webview-notify-core.js',
      'webview-settings-ui.js',
      'i18n.js',
      'prism-bootstrap.js'
    ],
    languageOptions: {
      globals: {
        ...globals.browser,
        acquireVsCodeApi: 'readonly',
        marked: 'readonly',
        Prism: 'readonly',
        MathJax: 'readonly',
        AIIA_I18N: 'readonly'
      }
    }
  }
]
