## WorkFlow

本文档描述本项目的推荐开发 / 发布流程。`TODO.md` 作为本地待办可能会被忽略（gitignore），因此将可复用的流程沉淀在 `docs/` 里，便于长期维护与共享。

### Web UI/交互真机验证

- `uv run python scripts/manual_test.py --port 8080 --verbose --thread-timeout 0`
- 打开（本机）：`http://127.0.0.1:8080`（局域网：`http://ai.local:8080` 或 `http://<局域网IP>:8080`）
- VSCode 插件（可选）：在 VSCode 设置里配置 `ai-intervention-agent.serverUrl` 为你的服务端地址（例如 `http://ai.local:8080`）

### 提交前（本地 CI Gate）

- 一键运行（推荐）：`uv run python scripts/ci_gate.py`
  - 默认是“本地模式”：会自动格式化（`ruff format`），并运行 ruff/ty/pytest/minify
  - CI 模式（只检查；不自动格式化源码，但会生成 gitignore 的构建产物如 `.min`）：`uv run python scripts/ci_gate.py --ci --with-coverage`
  - 若希望一并跑 VSCode 插件门禁：`uv run python scripts/ci_gate.py --with-vscode`
- VSCode 插件：`npm run vscode:check`（Linux/headless：`xvfb-run -a npm run vscode:check`）
  - 若 Node 由 `fnm` 管理且在非交互 shell 下 `node` 不可用，可用：`fnm exec --using v24.14.0 -- npm run vscode:check`
  - 说明：`vscode:check` 包含打包步骤，会在 `packages/vscode/` 目录生成 `.vsix`（已 gitignore）
    - 若通过 `uv run python scripts/ci_gate.py --with-vscode` 执行：脚本会在运行前/后自动清理 `.vsix`（避免 CI 污染）
    - 若手动执行 `npm run vscode:check`：完成测试后请清理：`rm -f packages/vscode/*.vsix`

### 发布（tag 触发 GitHub Actions Release）

- 一键同步版本号（不带 `v` 前缀）：`uv run python scripts/bump_version.py X.Y.Z`
  - 会同步：`pyproject.toml` / `uv.lock` / `package.json` / `package-lock.json` / `packages/vscode/package.json` / `.github/ISSUE_TEMPLATE/bug_report.md`
  - 可选：`--ci-gate --with-vscode`（同步后跑一轮本地 CI Gate）
- `git commit -m "<type>: <message>"`
- `git tag -a vX.Y.Z -m "vX.Y.Z"`
- `git push --follow-tags origin main`
- 若发布流水线失败：**修复后 bump 补丁版本再重新打 tag（例如 `v1.4.17` → `v1.4.18`）**，不要移动/重打已发布的 tag

### 发布后（在线验收）

- GitHub Actions：确认 `Tests` / `VSCode Extension (Lint/Test)` / `Release` 均为 Success
  - [GitHub Actions](https://github.com/XIADENGMA/ai-intervention-agent/actions)
  - 推荐命令：
    - `gh run list --limit 20`
    - `gh run watch <run-id> --exit-status`（对 `Tests` / `VSCode Extension (Lint/Test)` / `Release` 分别 watch）
- PyPI：确认 `ai-intervention-agent` 最新版本号为 `X.Y.Z`
  - [PyPI 项目页](https://pypi.org/project/ai-intervention-agent/)
  - 可选命令：`python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/ai-intervention-agent/json'))['info']['version'])"`
- Open VSX：确认扩展 `xiadengma.ai-intervention-agent` 最新版本号为 `X.Y.Z`
  - [Open VSX 扩展页](https://open-vsx.org/extension/xiadengma/ai-intervention-agent)
  - 可选命令：`python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://open-vsx.org/api/xiadengma/ai-intervention-agent')).get('version',''))"`
- GitHub Releases：确认对应 tag 的 release assets（`.whl` / `.tar.gz` / `.vsix`）已生成
  - [GitHub Releases](https://github.com/XIADENGMA/ai-intervention-agent/releases)
  - 可选命令：`gh release view vX.Y.Z`
