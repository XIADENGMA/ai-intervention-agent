"""R718 回归护栏：VS Code 扩展宿主不得被异常的 HTTP / SSE 流放大成资源问题。

背景（TODO「修复三：插件偶发 bug」，日志
``UtilityProcess ... type: extensionHost ... crashed with code 9 and reason 'killed'``）。
code 9 是 SIGKILL，扩展自己没有任何路径能产生它（Python 侧只会
``terminate()/kill()`` 自己 ``Popen`` 出来的子进程，VS Code 侧只有 ``execFile`` 超时会
杀掉自己拉起的 ``osascript``）；macOS 26 上同类现象的公开根因是系统内存压力或 Mach
端口耗尽（microsoft/vscode#326338），单凭一行日志无法证明具体原因。

但在真实 VS Code 1.110 扩展宿主里对扩展做故障注入压测（SSE 抖动、6600 条事件风暴、
60 次 serverUrl 翻转、20 次 SSE 突断、32 次 8 MB 的 500 响应、一行 64 MiB 且没有换行的
SSE）时，测得三处**宿主侧**的资源放大（修复前 → 修复后）：

1. **SSE 解析缓冲无界且二次方复制**：``buffer += chunk; buffer.split("\\n")`` 对一直
   不换行的数据每个 chunk 都复制整个缓冲区。64 MiB 的一行让宿主堆峰值
   1798 MB（RSS 1961 MB），修复后 36.8 MB。
2. **SSE 抖动时每秒重连一次、永不退避**：``_sseReconnectDelay`` 在任意 200 响应上都被
   重置为 1 秒，服务端「接受后立刻断开」时 25 秒内重连 24 次（修复后 5 次）。
3. **非 2xx 响应体既不读也不取消**：连接被未消费的响应体占着，直到 GC 才释放。8 MB 的
   500 响应下服务端同时看到 14 条在途连接、宿主 fd 峰值 85（修复后 1 条、75）。

契约：

- SSE 解析走 ``sse-parser.ts`` 的 ``SseParser``：行、单个事件的 ``data`` 总量、未结束的
  尾部都不得超过 ``SSE_MAX_BUFFER_CHARS``（1 MiB），超限抛 ``SseBufferOverflowError``；
  实现中不得对累计缓冲区调用 ``split``；宿主收到超限后丢弃连接并按退避重连。
- 重连退避只在连接稳定（``SSE_STABLE_CONNECTION_MS``）之后才回到起点；serverUrl 变化
  视为新目标，退避回到起点；失败 / 非 200 / 短命连接继续指数退避到上限。
- 所有 ``!resp.ok`` 的 fetch 路径（状态轮询、语言预取、通知配置）都通过
  ``discardResponseBody`` 取消响应体。
- 新增的 TS 模块列入 ``tsconfig.json`` 的 ``include``。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_vscode_extension_status_poll_url_change_r452 import (
    _extract_config_change_handler,
    _extract_function_body,
)
from tests.test_vscode_server_language_prefetch_stale_r452 import (
    _extract_method_body,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
EXTENSION_TS = VSCODE_DIR / "extension.ts"
WEBVIEW_TS = VSCODE_DIR / "webview.ts"
SSE_PARSER_TS = VSCODE_DIR / "sse-parser.ts"
NET_UTILS_TS = VSCODE_DIR / "net-utils.ts"
TSCONFIG = VSCODE_DIR / "tsconfig.json"
TSC = REPO_ROOT / "node_modules" / ".bin" / "tsc"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _connect_sse_body() -> str:
    return _extract_function_body(_read(EXTENSION_TS), "_connectSSE")


def _handle_sse_error_body() -> str:
    return _extract_function_body(_read(EXTENSION_TS), "_handleSSEError")


class TestSseParserSource(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _read(SSE_PARSER_TS)

    def test_limit_is_one_mebichar(self) -> None:
        self.assertIn("export const SSE_MAX_BUFFER_CHARS = 1024 * 1024;", self.src)

    def test_every_accumulation_path_is_bounded(self) -> None:
        self.assertGreaterEqual(
            self.src.count("throw new SseBufferOverflowError(this.maxChars);"),
            3,
            "尾部累计、单行长度、单事件 data 总量三处都必须有上限检查",
        )

    def test_parser_never_rescans_the_accumulated_buffer(self) -> None:
        self.assertNotIn(
            ".split(",
            self.src,
            "对累计缓冲区 split 会让不换行的数据变成二次方复制（64 MiB → 1.8 GB 堆峰值）",
        )

    def test_overflow_error_is_a_distinct_class(self) -> None:
        self.assertRegex(self.src, r"export class SseBufferOverflowError extends Error")


class TestExtensionUsesBoundedParser(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _read(EXTENSION_TS)
        self.connect = _connect_sse_body()

    def test_imports(self) -> None:
        self.assertIn('from "./sse-parser"', self.src)
        self.assertIn('from "./net-utils"', self.src)

    def test_connect_sse_uses_parser_not_manual_buffer(self) -> None:
        self.assertIn("new SseParser(handleSseEvent)", self.connect)
        self.assertNotIn('buffer.split("\\n")', self.connect)
        self.assertNotIn("buffer += chunk", self.connect)
        self.assertNotIn("pendingDataLines", self.connect)

    def test_overflow_drops_the_connection(self) -> None:
        data_idx = self.connect.index('res.on("data"')
        data_handler = self.connect[data_idx : data_idx + 1500]
        self.assertIn("parser.push(chunk)", data_handler)
        self.assertIn("e instanceof SseBufferOverflowError", data_handler)
        self.assertIn('"sse.buffer_overflow"', data_handler)
        overflow_idx = data_handler.index("e instanceof SseBufferOverflowError")
        branch_end = data_handler.index("return;", overflow_idx)
        self.assertIn(
            "_handleSSEError();",
            data_handler[overflow_idx:branch_end],
            "超限分支必须在 return 之前丢弃连接并触发退避重连",
        )
        self.assertLess(
            overflow_idx,
            data_handler.index('"sse.handler_error"'),
            "超限分支必须先于通用异常分支",
        )

    def test_backoff_constants(self) -> None:
        self.assertIn("const SSE_RECONNECT_BASE_MS = 1000;", self.src)
        self.assertIn("const SSE_RECONNECT_MAX_MS = 30000;", self.src)
        self.assertIn("const SSE_STABLE_CONNECTION_MS = 10000;", self.src)

    def test_200_response_no_longer_resets_the_backoff(self) -> None:
        start = self.connect.index("_sseConnected = true;")
        end = self.connect.index('logger.event("sse.connected"', start)
        header = self.connect[start:end]
        self.assertIn("_sseConnectedAtMs = Date.now();", header)
        self.assertNotIn(
            "_sseReconnectDelay",
            header,
            "在任意 200 上重置退避会让抖动的服务端被每秒重连一次",
        )

    def test_backoff_resets_only_after_a_stable_connection(self) -> None:
        body = _handle_sse_error_body()
        reset_idx = body.index("_sseReconnectDelay = SSE_RECONNECT_BASE_MS;")
        guard_idx = body.index("connectedForMs >= SSE_STABLE_CONNECTION_MS")
        self.assertLess(guard_idx, reset_idx)
        self.assertEqual(body.count("_sseReconnectDelay = SSE_RECONNECT_BASE_MS;"), 1)
        self.assertLess(
            body.index("_sseConnectedAtMs = 0;"),
            body.index("setTimeout("),
            "连接时长必须在安排重连之前结算并清零",
        )
        self.assertIn("Math.min(SSE_RECONNECT_MAX_MS, _sseReconnectDelay * 2)", body)

    def test_every_teardown_ends_the_stability_clock(self) -> None:
        disconnect = _extract_function_body(_read(EXTENSION_TS), "_disconnectSSE")
        self.assertIn(
            "_sseConnectedAtMs = 0;",
            disconnect,
            "手动拆连后残留的连接起始时刻会让下一次失败被误判为「稳定过」",
        )

    def test_server_url_change_restarts_the_backoff(self) -> None:
        handler = _extract_config_change_handler(self.src)
        reset_idx = handler.index("_sseReconnectDelay = SSE_RECONNECT_BASE_MS;")
        self.assertLess(handler.index("_lastEventId = null;"), reset_idx)
        self.assertLess(reset_idx, handler.index("_connectSSE();"))


class TestErrorBodiesAreReleased(unittest.TestCase):
    def test_status_poll_cancels_non_ok_bodies(self) -> None:
        body = _extract_function_body(_read(EXTENSION_TS), "updateStatusBar")
        ok_idx = body.index("if (!resp.ok) {")
        discard_idx = body.index("discardResponseBody(resp);", ok_idx)
        throw_idx = body.index("throw new Error(`HTTP ${resp.status}`);", ok_idx)
        self.assertLess(discard_idx, throw_idx)

    def test_language_prefetch_cancels_stale_and_non_200_bodies(self) -> None:
        body = _extract_method_body(_read(WEBVIEW_TS), "_prefetchServerLanguage")
        self.assertEqual(body.count("discardResponseBody(resp);"), 2)
        stale_idx = body.index("if (this._serverUrl !== requestServerUrl)")
        self.assertLess(stale_idx, body.index("discardResponseBody(resp);"))
        non200_idx = body.index("[i18n] Server non-200 response")
        self.assertLess(body.rindex("discardResponseBody(resp);"), non200_idx)

    def test_notification_config_cancels_non_ok_bodies(self) -> None:
        body = _extract_method_body(_read(WEBVIEW_TS), "_fetchNotificationConfig")
        ok_idx = body.index("if (!resp.ok) {")
        self.assertIn("discardResponseBody(resp);", body[ok_idx : ok_idx + 120])

    def test_helper_swallows_every_failure(self) -> None:
        src = _read(NET_UTILS_TS)
        self.assertIn("export function discardResponseBody(", src)
        self.assertIn("body.cancel().catch(", src)
        self.assertGreaterEqual(src.count("catch"), 2)

    def test_every_fetch_with_a_non_ok_branch_goes_through_the_helper(self) -> None:
        for path in (EXTENSION_TS, WEBVIEW_TS):
            src = _read(path)
            fetch_calls = len(re.findall(r"\bawait fetch\(", src))
            non_ok_branches = len(re.findall(r"if \(!resp\.ok\)", src)) + len(
                re.findall(r"if \(resp\.ok\)", src)
            )
            self.assertGreaterEqual(non_ok_branches, 1, path.name)
            self.assertGreaterEqual(
                src.count("discardResponseBody(resp);"),
                fetch_calls,
                f"{path.name}: 每个 fetch 的非成功分支都要取消响应体",
            )


class TestPackaging(unittest.TestCase):
    def test_new_modules_are_compiled(self) -> None:
        include = json.loads(_read(TSCONFIG))["include"]
        for name in ("sse-parser.ts", "net-utils.ts"):
            self.assertIn(name, include)

    def test_every_relative_ts_import_is_listed(self) -> None:
        include = set(json.loads(_read(TSCONFIG))["include"])
        for path in (EXTENSION_TS, WEBVIEW_TS):
            for match in re.finditer(r'from "\./([\w-]+)"', _read(path)):
                candidate = VSCODE_DIR / f"{match.group(1)}.ts"
                if candidate.exists():
                    self.assertIn(
                        candidate.name,
                        include,
                        f"{path.name} 导入了 {candidate.name}，但 tsconfig include 没列出",
                    )


_NODE_SCRIPT = r"""
const { SseParser, SseBufferOverflowError, SSE_MAX_BUFFER_CHARS } = require(OUT + '/sse-parser.js')
const { discardResponseBody } = require(OUT + '/net-utils.js')

function legacy(stream, size) {
  const events = []
  let buffer = ''
  let id = null, type = null, data = []
  const flush = () => {
    if (data.length === 0 && type === null && id === null) return
    events.push({ id, type, data: data.join('\n') })
    id = null; type = null; data = []
  }
  for (let i = 0; i < stream.length; i += size) {
    buffer += stream.slice(i, i + size)
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line === '') { flush(); continue }
      if (line.startsWith(':')) continue
      if (line.startsWith('id:')) { id = line.slice(3).replace(/^\s+/, ''); continue }
      if (line.startsWith('event:')) { type = line.slice(6).replace(/^\s+/, ''); continue }
      if (line.startsWith('data:')) { data.push(line.slice(5).replace(/^\s/, '')); continue }
    }
  }
  return events
}

function modern(stream, size) {
  const events = []
  const parser = new SseParser(ev => events.push(ev))
  for (let i = 0; i < stream.length; i += size) parser.push(stream.slice(i, i + size))
  return events
}

const streams = [
  ': hello\n\nid: 1\nevent: task_changed\ndata: {"a":1}\n\nevent: heartbeat\ndata: {}\n\n',
  'id: 5\ndata: a\ndata: b\ndata:  c\n\n\n\nevent:\n\nretry: 3\n\n',
  'event: config_changed\ndata: {"hint":"é中文"}\n\n: tail without newline',
]
let equivalent = true
for (const s of streams) {
  for (const size of [1, 2, 3, 5, 7, 64, s.length + 1]) {
    if (JSON.stringify(modern(s, size)) !== JSON.stringify(legacy(s, size))) equivalent = false
  }
}

const hostile = new SseParser(() => {})
const chunk = 'z'.repeat(64 * 1024)
let accepted = 0
let overflowed = false
const started = process.hrtime.bigint()
try {
  hostile.push('data: ')
  for (let i = 0; i < 1024; i++) { hostile.push(chunk); accepted += 1 }
} catch (e) {
  overflowed = e instanceof SseBufferOverflowError
}
const hostileMs = Number(process.hrtime.bigint() - started) / 1e6

const tiny = new SseParser(() => {})
const tinyStarted = process.hrtime.bigint()
tiny.push('data: ')
for (let i = 0; i < 900000; i++) tiny.push('a')
const tinyMs = Number(process.hrtime.bigint() - tinyStarted) / 1e6

let cancelled = 0
const calls = []
discardResponseBody({ body: { cancel() { cancelled += 1; return Promise.resolve() } } })
for (const bad of [null, undefined, {}, { body: null }, { body: {} }, { body: { cancel() { throw new Error('x') } } }]) {
  try { discardResponseBody(bad); calls.push('ok') } catch (e) { calls.push('threw') }
}

console.log(JSON.stringify({
  equivalent, overflowed, accepted, hostileMs, tinyMs, cancelled, calls,
  limit: SSE_MAX_BUFFER_CHARS, chunk: chunk.length,
}))
"""


@unittest.skipUnless(shutil.which("node"), "node runtime unavailable")
@unittest.skipUnless(TSC.exists(), "repo-root TypeScript compiler not installed")
class TestRuntimeBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="aiia-r718-")
        out = Path(cls._tmp.name)
        subprocess.run(
            [
                str(TSC),
                "--outDir",
                str(out),
                "--module",
                "commonjs",
                "--target",
                "ES2022",
                "--strict",
                "--skipLibCheck",
                str(SSE_PARSER_TS),
                str(NET_UTILS_TS),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        script = f"const OUT = {json.dumps(str(out))};\n" + _NODE_SCRIPT
        completed = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        cls.result = json.loads(completed.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_parser_matches_the_legacy_split_parser(self) -> None:
        self.assertTrue(self.result["equivalent"])

    def test_hostile_unterminated_line_is_rejected_at_the_limit(self) -> None:
        self.assertTrue(self.result["overflowed"])
        self.assertLessEqual(
            self.result["accepted"], self.result["limit"] // self.result["chunk"] + 1
        )
        self.assertLess(self.result["hostileMs"], 1000)

    def test_tiny_chunks_accumulate_in_linear_time(self) -> None:
        self.assertLess(self.result["tinyMs"], 1000)

    def test_discard_helper_cancels_and_never_throws(self) -> None:
        self.assertEqual(self.result["cancelled"], 1)
        self.assertEqual(self.result["calls"], ["ok"] * 6)


if __name__ == "__main__":
    unittest.main()
