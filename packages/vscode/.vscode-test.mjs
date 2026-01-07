import { defineConfig } from "@vscode/test-cli";

export default defineConfig({
  files: "test/**/*.test.js",
  // 固定 VSCode 版本，避免 CI 频繁查询 update 服务导致网络波动
  // 如需升级，请同时更新 .github/workflows/vscode.yml 的缓存 key
  version: "1.107.1",
});
