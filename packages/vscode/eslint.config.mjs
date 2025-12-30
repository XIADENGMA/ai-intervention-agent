import globals from 'globals'

export default [
  // 避免把 VSCode 下载缓存/产物/依赖也拉进 lint（会导致极慢甚至 OOM）
  {
    ignores: [
      '**/node_modules/**',
      '**/.vscode-test/**',
      '**/out/**',
      '**/dist/**',
      '**/result/**',
      '**/*.vsix',
      'marked.min.js',
      'prism.min.js',
      'lottie.min.js'
    ]
  },
  {
    files: ['**/*.js'],
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
      'no-unused-vars': 'warn',
      'constructor-super': 'warn',
      'valid-typeof': 'warn'
    }
  }
]
