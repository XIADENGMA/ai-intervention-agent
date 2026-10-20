import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath, pathToFileURL } from "node:url";

const ANSI_ESCAPE = /\u001b\[[0-9;]*m/g;

const WORKBENCH_NETWORK_LINES = [
  /^\[LM\] Failed to request chat control data\b/,
  /^Error while getting the latest version for the extension \S+/,
  /^Failed to fetch(: (Failed|TypeError): Failed to fetch)?$/,
  /^\[\d+:\d+\/\d+\.\d+:ERROR:net\/socket\/ssl_client_socket_impl\.cc:\d+\] handshake failed\b/,
];

const WORKBENCH_STACK_LINE = /^\s+at .*vscode-file:\/\/vscode-app\//;

export function createWorkbenchNetworkFilter() {
  let insideNoise = false;
  return function isWorkbenchNetworkNoise(rawLine) {
    const line = rawLine.replace(ANSI_ESCAPE, "");
    if (WORKBENCH_NETWORK_LINES.some((pattern) => pattern.test(line))) {
      insideNoise = true;
      return true;
    }
    if (insideNoise && WORKBENCH_STACK_LINE.test(line)) {
      return true;
    }
    insideNoise = false;
    return false;
  };
}

function pipeFiltered(stream, target, onHidden) {
  const isNoise = createWorkbenchNetworkFilter();
  const lines = readline.createInterface({
    input: stream,
    crlfDelay: Infinity,
  });
  lines.on("line", (line) => {
    if (isNoise(line)) {
      onHidden();
      return;
    }
    target.write(`${line}\n`);
  });
  return new Promise((resolve) => lines.once("close", resolve));
}

export async function runFiltered(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: options.cwd,
    env: options.env ?? process.env,
    stdio: ["inherit", "pipe", "pipe"],
  });
  let hidden = 0;
  const countHidden = () => {
    hidden += 1;
  };
  const drained = Promise.all([
    pipeFiltered(child.stdout, process.stdout, countHidden),
    pipeFiltered(child.stderr, process.stderr, countHidden),
  ]);
  const exitCode = await new Promise((resolve) => {
    child.once("error", (error) => {
      process.stderr.write(`${error.message}\n`);
      resolve(1);
    });
    child.once("close", (code) => resolve(code ?? 1));
  });
  await drained;
  if (hidden > 0) {
    process.stdout.write(
      `(left out ${hidden} line${hidden === 1 ? "" : "s"} VS Code printed about its own ` +
        "marketplace, chat and alert lookups; the test instance has no reliable network)\n",
    );
  }
  return exitCode;
}

function defaultCommand() {
  const require = createRequire(import.meta.url);
  const cliBin = path.join(
    path.dirname(require.resolve("@vscode/test-cli")),
    "bin.mjs",
  );
  const extensionDir = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "..",
    "packages",
    "vscode",
  );
  return {
    command: process.execPath,
    args: [cliBin, "--config", ".vscode-test.mjs"],
    cwd: extensionDir,
  };
}

async function main() {
  const separator = process.argv.indexOf("--");
  let plan;
  if (separator === -1) {
    plan = defaultCommand();
  } else {
    const [command, ...args] = process.argv.slice(separator + 1);
    plan = { command, args, cwd: process.cwd() };
  }
  const env = { ...process.env };
  if (process.stdout.isTTY && env.FORCE_COLOR === undefined) {
    env.FORCE_COLOR = "1";
  }
  process.exitCode = await runFiltered(plan.command, plan.args, {
    cwd: plan.cwd,
    env,
  });
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href
) {
  await main();
}
