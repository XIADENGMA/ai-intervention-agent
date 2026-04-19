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
      // locale 源文件自己不应参与 lint（其内容用于 rule 的 validKeys 集）
      'locales/**',
      'l10n/**',
      // 测试 fixture 目录（见 tests/vscode_eslint_i18n_fixture/）由外部 pytest
      // 拉起，避免本地 npm run lint 被虚构数据污染。
      'test/eslint-fixtures/**'
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
  // T1 · C10c：tri-state-panel*.js 是 static/ 真源的字节级镜像（由
  // tests/test_tri_state_panel_parity.py 强制 sha256 一致），不能在源里加
  // /* eslint-env browser */ 否则 Web UI 一侧也得跟着改 → 这里以 file glob
  // 明确把它们也归入浏览器作用域，避免 26 条 'window/document is not defined'
  // 噪音淹没真正的告警。
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
  // L4·G2：i18n key 静态校验。对所有非 vendor 的 webview JS + 测试 JS 开启，
  // 插件自己通过 CallExpression 走查所有 t/_t/tl/hostT/__vuT/__domSecT/__ncT
  // 调用，对比 locales/en.json + static/locales/en.json 的 key 并 --max-warnings
  // 0（由 npm run lint 已默认）将任何 undefined key 视为 fail。
  {
    files: ['**/*.js', '**/*.mjs'],
    plugins: { 'aiia-i18n': aiiaI18n },
    rules: {
      'aiia-i18n/no-missing-i18n-key': 'error'
    }
  }
]
