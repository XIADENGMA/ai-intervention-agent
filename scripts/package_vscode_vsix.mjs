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
  // Marketplace + Open VSX render this file on the extension's "Changelog"
  // tab. Source-of-truth lives at the repo root (`CHANGELOG.md`); this
  // file is the per-release extension-only excerpt with a link back to the
  // project-wide changelog. Maintained alongside the package.json `version`
  // bump so users see what changed in the wheel they just installed.
  'CHANGELOG.md',
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
      cwd: repoRoot,
      encoding: 'utf8',
      timeout: 5000
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

  // ──────────────────────────────────────────────────────────────────
  // R12·A4 · VSIX 尺寸预算守卫
  //
  // 历史教训：VS Code extension 一旦把 mathjax/lottie/字体等大资源整
  // 个 bundle 进去，VSIX 体积会从 KB 级跳到 50+ MB，导致：
  //   1. Marketplace 安装/更新慢，用户卷曲；
  //   2. ``code --install-extension`` 在窄带 CI 上 timeout；
  //   3. Air-gapped 运维下载/分发成本高。
  // 本守卫在打包末尾对 .vsix 做"压缩后"尺寸 check：
  //   - 超 ``WARN_PACKED_BYTES`` → console.warn 提示 review；
  //   - 超 ``FAIL_PACKED_BYTES`` → 直接 ``process.exit(1)`` fail-closed。
  // 阈值刻意比当前实际尺寸（约 2.7 MB / 1.5.22）留有充足 headroom，
  // 既不会让一次正常的 +X KB 增量被误报，又能在 4-6 MB 的"意外飞涨"
  // 区间立刻 trip。两个阈值都可通过 env var 覆盖，方便临时大幅增量
  // 上线前调高，但默认必须保守。
  //
  // 数值合理性由 ``tests/test_vscode_vsix_size_budget.py`` 静态守护，
  // 防止"为通过 CI 把阈值改到 100 MB"这种自残式 escape hatch。
  // ──────────────────────────────────────────────────────────────────
  const WARN_PACKED_MB_DEFAULT = 4
  const FAIL_PACKED_MB_DEFAULT = 6
  const _parseMbEnv = (envName, fallback) => {
    const raw = process.env[envName]
    if (raw === undefined || raw === '') return fallback
    const n = Number(raw)
    if (!Number.isFinite(n) || n <= 0) {
      console.warn(`无效的 ${envName}=${JSON.stringify(raw)}，回退到默认 ${fallback} MB`)
      return fallback
    }
    return n
  }
  const warnMb = _parseMbEnv('AIIA_VSCODE_VSIX_WARN_PACKED_MB', WARN_PACKED_MB_DEFAULT)
  const failMb = _parseMbEnv('AIIA_VSCODE_VSIX_MAX_PACKED_MB', FAIL_PACKED_MB_DEFAULT)
  if (failMb < warnMb) {
    console.error(
      `配置错误：FAIL 阈值 (${failMb} MB) 小于 WARN 阈值 (${warnMb} MB)；` +
        `请检查 AIIA_VSCODE_VSIX_MAX_PACKED_MB / AIIA_VSCODE_VSIX_WARN_PACKED_MB`
    )
    process.exit(1)
  }
  const packedBytes = fs.statSync(outVsix).size
  const packedMb = packedBytes / (1024 * 1024)
  const failBytes = failMb * 1024 * 1024
  const warnBytes = warnMb * 1024 * 1024
  console.log(
    `VSIX 尺寸预算检查：实际 ${packedMb.toFixed(2)} MB（${packedBytes} bytes）` +
      `；WARN ≥ ${warnMb} MB；FAIL ≥ ${failMb} MB`
  )
  if (packedBytes >= failBytes) {
    console.error(
      `❌ VSIX 超出硬上限：${packedMb.toFixed(2)} MB ≥ ${failMb} MB。` +
        `请检查是否意外打入了大型资源（mathjax/lottie/字体等）；` +
        `如确需放行，临时设 AIIA_VSCODE_VSIX_MAX_PACKED_MB=N（必须同时更新 ` +
        `tests/test_vscode_vsix_size_budget.py 的合理性范围，并在 PR 描述里说明原因）。`
    )
    process.exit(1)
  }
  if (packedBytes >= warnBytes) {
    console.warn(
      `⚠️  VSIX 接近预算：${packedMb.toFixed(2)} MB ≥ ${warnMb} MB（WARN 阈值）。` +
        `若非有意增量，请检查 includeList 是否多打了文件。`
    )
  }
} finally {
  fs.rmSync(tmpDir, { recursive: true, force: true })
}
