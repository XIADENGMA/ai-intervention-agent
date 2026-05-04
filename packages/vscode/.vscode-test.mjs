import { defineConfig } from "@vscode/test-cli";

export default defineConfig({
  files: "test/**/*.test.js",
  // 固定 VSCode 版本，避免 CI 频繁查询 update 服务导致网络波动
  // 如需升级，请同时更新 .github/workflows/vscode.yml 的缓存 key
  version: "1.110.0",
  // macOS 的 IPC socket 路径上限较短；项目目录较深时 VSCode 会打印 WARNING。
  // 使用短路径 user-data-dir，保持本地/CI 输出干净。
  launchArgs: ["--user-data-dir=/tmp/aiia-vscode-user-data"],
});
