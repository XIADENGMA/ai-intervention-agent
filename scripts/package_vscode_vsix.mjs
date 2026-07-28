import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

function copyRecursive(src, dest) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const entry of fs.readdirSync(src)) {
      copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
    return;
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const vscodeDir = path.join(repoRoot, "packages", "vscode");

const pkgPath = path.join(vscodeDir, "package.json");
if (!fs.existsSync(pkgPath)) {
  console.error(`找不到 VSCode 插件 package.json：${pkgPath}`);
  process.exit(1);
}

const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
const extName = pkg.name;
const extVersion = pkg.version;
if (!extName || !extVersion) {
  console.error("VSCode 插件 package.json 缺少 name/version");
  process.exit(1);
}

const outVsix = path.join(vscodeDir, `${extName}-${extVersion}.vsix`);

const includeList = [
  "package.json",
  "dist",
  "webview-state.js",
  "webview-ui.js",
  "webview-helpers.js",
  "webview-notify-core.js",
  "webview-settings-ui.js",
  "i18n.js",
  "prism-bootstrap.js",
  "webview.css",

  "tri-state-panel.js",
  "tri-state-panel-loader.js",
  "tri-state-panel-bootstrap.js",
  "tri-state-panel.css",
  "vendor",
  "README.md",
  "README.zh-CN.md",

  "CHANGELOG.md",
  "LICENSE",
  "activity-icon.svg",
  "icon.png",
  "icon.svg",
  "lottie",
  "mathjax",
  "lottie.min.js",
  "marked.min.js",
  "prism.min.css",
  "prism.min.js",
  "locales",

  "l10n",
  "package.nls.json",
  "package.nls.zh-CN.json",
];

const SHARED_TRI_STATE_PANEL_FILES = [
  [
    "src/ai_intervention_agent/static/js/tri-state-panel.js",
    "tri-state-panel.js",
  ],
  [
    "src/ai_intervention_agent/static/js/tri-state-panel-loader.js",
    "tri-state-panel-loader.js",
  ],
  [
    "src/ai_intervention_agent/static/js/tri-state-panel-bootstrap.js",
    "tri-state-panel-bootstrap.js",
  ],
  [
    "src/ai_intervention_agent/static/css/tri-state-panel.css",
    "tri-state-panel.css",
  ],
];

function syncSharedTriStatePanel() {
  for (const [srcRel, destRel] of SHARED_TRI_STATE_PANEL_FILES) {
    const src = path.join(repoRoot, srcRel);
    const dest = path.join(vscodeDir, destRel);
    if (!fs.existsSync(src)) {
      console.error(`@aiia/tri-state-panel 真源缺失：${srcRel}`);
      process.exit(1);
    }
    const srcBuf = fs.readFileSync(src);
    let needsCopy = true;
    if (fs.existsSync(dest)) {
      const destBuf = fs.readFileSync(dest);
      if (srcBuf.equals(destBuf)) needsCopy = false;
    }
    if (needsCopy) {
      fs.writeFileSync(dest, srcBuf);
      console.log(
        `@aiia/tri-state-panel 同步：${srcRel} → packages/vscode/${destRel}`,
      );
    }
  }
}

syncSharedTriStatePanel();

const tmpDir = fs.mkdtempSync(
  path.join(os.tmpdir(), "ai-intervention-agent-vscode-"),
);
try {

  try {
    if (fs.existsSync(outVsix)) fs.rmSync(outVsix, { force: true });
  } catch {

  }

  const distDir = path.join(vscodeDir, "dist");
  if (!fs.existsSync(distDir)) {
    console.log("dist/ 不存在，自动运行 tsc 编译...");
    const compileResult = spawnSync("npx", ["tsc", "-p", "."], {
      cwd: vscodeDir,
      stdio: "inherit",
      timeout: 60000,
    });
    if (compileResult.status !== 0) {
      console.error("TypeScript 编译失败，终止打包");
      process.exit(compileResult.status ?? 1);
    }
  }

  for (const rel of includeList) {
    const src = path.join(vscodeDir, rel);
    if (!fs.existsSync(src)) {
      console.error(`VSIX 打包缺少必要文件/目录：${rel}（${src}）`);
      process.exit(1);
    }
    copyRecursive(src, path.join(tmpDir, rel));
  }

  try {
    const sha = spawnSync("git", ["rev-parse", "--short", "HEAD"], {
      cwd: repoRoot,
      encoding: "utf8",
      timeout: 5000,
    }).stdout.trim();
    if (sha) {
      const extJs = path.join(tmpDir, "dist", "extension.js");
      if (fs.existsSync(extJs)) {
        const content = fs.readFileSync(extJs, "utf8");
        fs.writeFileSync(extJs, content.replace("__BUILD_SHA__", sha), "utf8");
        console.log(`BUILD_ID 注入：${sha}`);
      }
    }
  } catch {
    console.warn("无法注入 BUILD_ID（git rev-parse 失败），使用开发回退");
  }

  const args = [
    "package",
    "--no-dependencies",
    "--no-rewrite-relative-links",
    "--out",
    outVsix,
  ];

  const r = spawnSync("npx", ["--yes", "@vscode/vsce", ...args], {
    cwd: tmpDir,
    stdio: "inherit",
  });

  if (r.status !== 0) {
    process.exit(r.status ?? 1);
  }

  console.log(`已生成 VSIX：${outVsix}`);

  const WARN_PACKED_MB_DEFAULT = 3;
  const FAIL_PACKED_MB_DEFAULT = 5;
  const _parseMbEnv = (envName, fallback) => {
    const raw = process.env[envName];
    if (raw === undefined || raw === "") return fallback;
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0) {
      console.warn(
        `无效的 ${envName}=${JSON.stringify(raw)}，回退到默认 ${fallback} MB`,
      );
      return fallback;
    }
    return n;
  };
  const warnMb = _parseMbEnv(
    "AIIA_VSCODE_VSIX_WARN_PACKED_MB",
    WARN_PACKED_MB_DEFAULT,
  );
  const failMb = _parseMbEnv(
    "AIIA_VSCODE_VSIX_MAX_PACKED_MB",
    FAIL_PACKED_MB_DEFAULT,
  );
  if (failMb < warnMb) {
    console.error(
      `配置错误：FAIL 阈值 (${failMb} MB) 小于 WARN 阈值 (${warnMb} MB)；` +
        `请检查 AIIA_VSCODE_VSIX_MAX_PACKED_MB / AIIA_VSCODE_VSIX_WARN_PACKED_MB`,
    );
    process.exit(1);
  }
  const packedBytes = fs.statSync(outVsix).size;
  const packedMb = packedBytes / (1024 * 1024);
  const failBytes = failMb * 1024 * 1024;
  const warnBytes = warnMb * 1024 * 1024;
  console.log(
    `VSIX 尺寸预算检查：实际 ${packedMb.toFixed(2)} MB（${packedBytes} bytes）` +
      `；review threshold ≥ ${warnMb} MB；hard limit ≥ ${failMb} MB`,
  );
  if (packedBytes >= failBytes) {
    console.error(
      `❌ VSIX 超出硬上限：${packedMb.toFixed(2)} MB ≥ ${failMb} MB。` +
        `请检查是否意外打入了大型资源（mathjax/lottie/字体等）；` +
        `如确需放行，临时设 AIIA_VSCODE_VSIX_MAX_PACKED_MB=N（必须同时更新 ` +
        `tests/test_vscode_vsix_size_budget.py 的合理性范围，并在 PR 描述里说明原因）。`,
    );
    process.exit(1);
  }
  if (packedBytes >= warnBytes) {
    console.warn(
      `⚠️  VSIX 接近预算：${packedMb.toFixed(2)} MB ≥ ${warnMb} MB（WARN 阈值）。` +
        `若非有意增量，请检查 includeList 是否多打了文件。`,
    );
  }
} finally {
  fs.rmSync(tmpDir, { recursive: true, force: true });
}
