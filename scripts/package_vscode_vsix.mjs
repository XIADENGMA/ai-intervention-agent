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
const includeList = [
  'package.json',
  'extension.js',
  'applescript-executor.js',
  'webview.js',
  'webview.css',
  'webview-helpers.js',
  'logger.js',
  'webview-ui.js',
  'webview-notify-core.js',
  'webview-settings-ui.js',
  'notification-models.js',
  'notification-center.js',
  'notification-providers.js',
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
  'prism-bootstrap.js',
  'prism.min.css',
  'prism.min.js'
]

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-intervention-agent-vscode-'))
try {
  // 若已有同名产物，先清理，避免误用旧文件或因文件锁导致打包失败
  try {
    if (fs.existsSync(outVsix)) fs.rmSync(outVsix, { force: true })
  } catch {
    // 忽略：清理失败不应阻断后续尝试（vsce 可能会覆盖）
  }

  for (const rel of includeList) {
    const src = path.join(vscodeDir, rel)
    if (!fs.existsSync(src)) {
      console.error(`VSIX 打包缺少必要文件/目录：${rel}（${src}）`)
      process.exit(1)
    }
    copyRecursive(src, path.join(tmpDir, rel))
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
