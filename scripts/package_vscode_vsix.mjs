import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

function copyRecursive(src, dest) {
  const stat = fs.statSync(src)
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true })
    for (const entry of fs.readdirSync(src)) {
      copyRecursive(path.join(src, entry), path.join(dest, entry))
    }
    return
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  fs.copyFileSync(src, dest)
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const vscodeDir = path.join(repoRoot, 'packages', 'vscode')

const pkgPath = path.join(vscodeDir, 'package.json')
if (!fs.existsSync(pkgPath)) {
  console.error(`找不到 VSCode 插件 package.json：${pkgPath}`)
  process.exit(1)
}

const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'))
const extName = pkg.name
const extVersion = pkg.version
if (!extName || !extVersion) {
  console.error('VSCode 插件 package.json 缺少 name/version')
  process.exit(1)
}

const outVsix = path.join(vscodeDir, `${extName}-${extVersion}.vsix`)

// 只复制打包所需的最小文件集合，避免 monorepo 下 vsce 误打包整个仓库。
// TS 迁移后：Node.js 模块由 tsc 编译到 dist/，Webview 端 JS + 静态资源从源目录复制。
const includeList = [
  'package.json',
  'dist',
  'webview-state.js',
  'webview-ui.js',
  'webview-helpers.js',
  'webview-notify-core.js',
  'webview-settings-ui.js',
  'i18n.js',
  'prism-bootstrap.js',
  'webview.css',
  // T1 · C10c · @aiia/tri-state-panel 共享组件四件套（与 static/ 字节级一致）。
  // 真源在 static/js|css/，packages/vscode/ 是打包期镜像，由
  // tests/test_tri_state_panel_parity.py::sha256 守护；本脚本上方的
  // syncSharedTriStatePanel() 会在每次打包前自动从真源同步过来，避免漂移。
  'tri-state-panel.js',
  'tri-state-panel-loader.js',
  'tri-state-panel-bootstrap.js',
  'tri-state-panel.css',
  'vendor',
  'README.md',
  'README.zh-CN.md',
  'LICENSE',
  'activity-icon.svg',
  'icon.png',
  'icon.svg',
  'lottie',
  'mathjax',
  'lottie.min.js',
  'marked.min.js',
  'prism.min.css',
  'prism.min.js',
  'locales',
  // VSCode extension host l10n bundle (vscode.l10n.t backing store).
  // Declared via "l10n": "./l10n" in package.json so the marketplace +
  // VSCode runtime both pick it up; must be copied into the vsix root.
  'l10n',
  'package.nls.json',
  'package.nls.zh-CN.json'
]

// T1 · C10c · @aiia/tri-state-panel：单一真源 → 镜像同步。
// Web UI 与 VSCode webview 共享四个文件，真源放在 static/js|css/，
// packages/vscode/ 持有的副本仅作为 vsix 打包入口（webview 不能直接
// 跨 extension 根目录读取 ../static/ 资源）。每次打包先 hard-overwrite
// packages/vscode/<basename>，再让 includeList 把它们打入 vsix。
// CI 端的 tests/test_tri_state_panel_parity.py 用 sha256 强制两端一致，
// 任何手工编辑 packages/vscode/tri-state-panel*.{js,css} 都会被发现并被回退。
const SHARED_TRI_STATE_PANEL_FILES = [
  ['static/js/tri-state-panel.js', 'tri-state-panel.js'],
  ['static/js/tri-state-panel-loader.js', 'tri-state-panel-loader.js'],
  ['static/js/tri-state-panel-bootstrap.js', 'tri-state-panel-bootstrap.js'],
  ['static/css/tri-state-panel.css', 'tri-state-panel.css']
]

function syncSharedTriStatePanel() {
  for (const [srcRel, destRel] of SHARED_TRI_STATE_PANEL_FILES) {
    const src = path.join(repoRoot, srcRel)
    const dest = path.join(vscodeDir, destRel)
    if (!fs.existsSync(src)) {
      console.error(`@aiia/tri-state-panel 真源缺失：${srcRel}`)
      process.exit(1)
    }
    const srcBuf = fs.readFileSync(src)
    let needsCopy = true
    if (fs.existsSync(dest)) {
      const destBuf = fs.readFileSync(dest)
      if (srcBuf.equals(destBuf)) needsCopy = false
    }
    if (needsCopy) {
      fs.writeFileSync(dest, srcBuf)
      console.log(`@aiia/tri-state-panel 同步：${srcRel} → packages/vscode/${destRel}`)
    }
  }
}

syncSharedTriStatePanel()

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-intervention-agent-vscode-'))
try {
  // 若已有同名产物，先清理，避免误用旧文件或因文件锁导致打包失败
  try {
    if (fs.existsSync(outVsix)) fs.rmSync(outVsix, { force: true })
  } catch {
    // 忽略：清理失败不应阻断后续尝试（vsce 可能会覆盖）
  }

  // dist/ 不存在时自动编译（Release CI 中可能跳过了显式 compile 步骤）
  const distDir = path.join(vscodeDir, 'dist')
  if (!fs.existsSync(distDir)) {
    console.log('dist/ 不存在，自动运行 tsc 编译...')
    const compileResult = spawnSync('npx', ['tsc', '-p', '.'], {
      cwd: vscodeDir,
      stdio: 'inherit',
      timeout: 60000
    })
    if (compileResult.status !== 0) {
      console.error('TypeScript 编译失败，终止打包')
      process.exit(compileResult.status ?? 1)
    }
  }

  for (const rel of includeList) {
    const src = path.join(vscodeDir, rel)
    if (!fs.existsSync(src)) {
      console.error(`VSIX 打包缺少必要文件/目录：${rel}（${src}）`)
      process.exit(1)
    }
    copyRecursive(src, path.join(tmpDir, rel))
  }

  // 注入 git short SHA 作为 BUILD_ID（替换 extension.js 中的 __BUILD_SHA__ 占位符）
  try {
    const sha = spawnSync('git', ['rev-parse', '--short', 'HEAD'], {
      cwd: repoRoot, encoding: 'utf8', timeout: 5000
    }).stdout.trim()
    if (sha) {
      const extJs = path.join(tmpDir, 'dist', 'extension.js')
      if (fs.existsSync(extJs)) {
        const content = fs.readFileSync(extJs, 'utf8')
        fs.writeFileSync(extJs, content.replace('__BUILD_SHA__', sha), 'utf8')
        console.log(`BUILD_ID 注入：${sha}`)
      }
    }
  } catch {
    console.warn('无法注入 BUILD_ID（git rev-parse 失败），使用开发回退')
  }

  const args = ['package', '--no-dependencies', '--no-rewrite-relative-links', '--out', outVsix]

  const r = spawnSync('npx', ['--yes', '@vscode/vsce', ...args], {
    cwd: tmpDir,
    stdio: 'inherit'
  })

  if (r.status !== 0) {
    process.exit(r.status ?? 1)
  }

  console.log(`已生成 VSIX：${outVsix}`)
} finally {
  fs.rmSync(tmpDir, { recursive: true, force: true })
}
