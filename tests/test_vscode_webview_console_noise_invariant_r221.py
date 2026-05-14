"""R221 / Cycle 12 · F-cycle11-1: packages/vscode/ console.log invariant.

设计目标
========

CR#24 (Cycle 11) 列了 `F-cycle11-1` 作为 "VSCode webview console.*
audit": 既然 R216/R217/R218 把 Web UI (`src/ai_intervention_agent/
static/js/`) 的 117 处 `console.log` 全部 demote 为 `console.debug`
/ `_debugLog`，VSCode 扩展的 webview JS (`packages/vscode/`) 也应该
得到同款审计——毕竟扩展用户跟 Web UI 用户看到的是同一份 DevTools。

R221 Discovery 阶段实测扫描结果 (2026-05-14)：

| 文件                              | log | warn | error | debug | info | 归类       |
| --------------------------------- | --- | ---- | ----- | ----- | ---- | ---------- |
| `i18n.js`                         | 0   | 6    | 0     | 0     | 0    | project    |
| `tri-state-panel-bootstrap.js`    | 0   | 4    | 12    | 2     | 2    | project    |
| `tri-state-panel-loader.js`       | 0   | 0    | 2     | 0     | 0    | project    |
| `tri-state-panel.js`              | 0   | 0    | 2     | 0     | 0    | project    |
| `webview-state.js`                | 0   | 0    | 0     | 1     | 0    | project (twin)  |
| `lottie.min.js`                   | 0   | 2    | 0     | 0     | 0    | vendor     |
| `marked.min.js`                   | 0   | 0    | 4     | 0     | 0    | vendor     |
| `mathjax/tex-mml-svg.js`          | 7   | 6    | 18    | 0     | 11   | vendor     |
| `prism.min.js`                    | 0   | 1    | 0     | 0     | 0    | vendor     |

**结论**：所有项目自有 (project-owned) VSCode webview JS 文件已经
zero `console.log`。F-cycle11-1 的 audit 部分实际上**已经做对了**
——可能因为：
- `webview-state.js` 是 `src/ai_intervention_agent/static/js/state.js`
  的 byte-twin，R217 demotion 同步过来；
- `tri-state-panel-*.js` 系列从一开始就按 `console.error` /
  `console.warn` / `console.debug` 三档分级（而非 R216 之前的 web
  ui 普遍 `console.log` 风格）。

但是 **没有 invariant test 锁定这一良好状态**。任何未来的 VSCode
扩展开发者 (含 contributor / AI 助手 / future me) 都可能不知道
项目契约而引入 `console.log`，重新污染 webview DevTools。R221 加
一个守护测试，复用 R217 的"严格 allow-list + forward-compat"模式：

设计契约
========

1. **5 个 project-owned 文件 zero `console.log(` 调用**：每个文件
   单独 subTest，定位错误位置在毫秒级。
2. **vendor allow-list 严格**：4 个 vendor 文件 hardcode 在测试里，
   防止有人把项目自有 JS 误标 vendor 绕过。
3. **forward-compat**：未来加入 `packages/vscode/` 的新 .js 文件
   如果既不在 `PROJECT_OWNED` 也不在 `VENDOR_ALLOW`，默认按 strict
   分类（== 0 `console.log`）。强制贡献者在 PR-author time 想清楚
   新文件归类。
4. **`console.warn` / `console.error` / `console.debug` / `console.
   info` 不被本测试限制**：这些是真实信号或低噪声诊断，R221 不动。
5. **跳过 `.vscode-test/` fixture + `node_modules/`**：VSCode test
   runner 下载的 Visual Studio Code.app 内包含 hundreds of vendored
   node_modules，扫描这些既慢又毫无意义。
6. **跳过 `test/*.js`** 单元测试：测试代码偶尔需要 `console.log`
   debug 失败用例，不应被限制。

为什么和 R217 分开两个测试文件？
================================

两个文件锁定**不同目录**：R217 守 `src/ai_intervention_agent/static
/js/`，R221 守 `packages/vscode/`。两个目录的 vendor 集合、project
ownership、文件命名规范完全不同，强行合并会让 allow-list 难以维护。
分开的好处是错误定位更精确，且 PR 评审时可以独立审视每个目录的
契约调整。

实施于 2026-05-14，共 5 个测试用例 + ~10 subtests。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"

PROJECT_OWNED_FILES: tuple[str, ...] = (
    "i18n.js",
    "tri-state-panel-bootstrap.js",
    "tri-state-panel-loader.js",
    "tri-state-panel.js",
    "webview-state.js",
    # 以下文件 R221 Discovery 阶段扫描 0 console.log，但未在表格中显式
    # 列出 (它们没有任何 console.* 调用)。加入 PROJECT_OWNED 让
    # forward-compat 测试不会因为它们存在而报告 "unclassified"。
    "webview-notify-core.js",
    "webview-helpers.js",
    "webview-settings-ui.js",
    "webview-ui.js",
    "prism-bootstrap.js",
)

VENDOR_ALLOW_FILES: tuple[str, ...] = (
    "lottie.min.js",
    "marked.min.js",
    "prism.min.js",
    "mathjax/tex-mml-svg.js",
)

SKIP_DIR_FRAGMENTS: tuple[str, ...] = (
    ".vscode-test",
    "node_modules",
    # `dist/` / `out/` 是 TypeScript -> JS 编译产物（.gitignore 已忽略），
    # 不应被 R221 enforce console-log discipline——console.log 出现在 dist/
    # 通常是来自 src/ 的 TS 编译结果，应该由 src/ TS 文件的 linter
    # (而非本测试) 把关。本测试聚焦于 commit-tracked 的 webview .js 文件。
    "/dist/",
    "/out/",
)

# test/*.js 单元测试不参与本 invariant：测试代码偶尔需要 console.log。
SKIP_PATH_PREFIXES: tuple[str, ...] = ("test/",)

CONSOLE_LOG_RE = re.compile(r"\bconsole\.log\s*\(")


def _list_vscode_js_files() -> list[Path]:
    """枚举 packages/vscode/ 下所有 *.js，跳过 fixture / node_modules / test/。

    返回相对路径 Path（相对 VSCODE_DIR），按字典序稳定。
    """
    out: list[Path] = []
    for f in sorted(VSCODE_DIR.rglob("*.js")):
        if not f.is_file():
            continue
        rel = f.relative_to(VSCODE_DIR)
        rel_str = str(rel).replace("\\", "/")
        # 用 `/{frag}/` 形式匹配中间目录段，避免文件名误中（例如
        # `.vscode-test` 在 fragment 中带斜杠包装）。SKIP_DIR_FRAGMENTS
        # 中的条目本身可以带或不带斜杠，靠下面的统一包装兜底。
        guarded = "/" + rel_str + "/"
        if any(
            (frag if frag.startswith("/") else f"/{frag}/") in guarded
            for frag in SKIP_DIR_FRAGMENTS
        ):
            continue
        if any(rel_str.startswith(p) for p in SKIP_PATH_PREFIXES):
            continue
        out.append(rel)
    return out


def _count_console_log(rel_path: Path) -> int:
    abs_path = VSCODE_DIR / rel_path
    text = abs_path.read_text(encoding="utf-8")
    return len(CONSOLE_LOG_RE.findall(text))


class TestProjectOwnedZeroConsoleLog(unittest.TestCase):
    """1. 每个 project-owned 文件个体上 `console.log` 计数为 0。"""

    def test_each_project_owned_has_zero_console_log(self) -> None:
        for fname in PROJECT_OWNED_FILES:
            rel = Path(fname)
            with self.subTest(file=fname):
                abs_path = VSCODE_DIR / rel
                self.assertTrue(
                    abs_path.is_file(),
                    f"PROJECT_OWNED_FILES references missing file: {fname}",
                )
                count = _count_console_log(rel)
                self.assertEqual(
                    count,
                    0,
                    (
                        f"{fname} has {count} `console.log(` calls; R221 "
                        "contract requires zero. If this is intentional "
                        "(e.g. you added a deliberate dev-debug log), use "
                        "`console.debug(...)` so DevTools filters it by "
                        "default, or move it behind a `if (DEBUG) {...}` "
                        "guard."
                    ),
                )


class TestVendorAllowList(unittest.TestCase):
    """2. vendor allow-list 文件存在且严格保留 (catch typo / 删除)。"""

    def test_all_vendor_files_exist(self) -> None:
        for fname in VENDOR_ALLOW_FILES:
            rel = Path(fname)
            with self.subTest(vendor_file=fname):
                self.assertTrue(
                    (VSCODE_DIR / rel).is_file(),
                    (
                        f"VENDOR_ALLOW_FILES references missing file: "
                        f"{fname}. If the file was renamed / removed, "
                        "update VENDOR_ALLOW_FILES; if it was promoted "
                        "to project-owned (rare), move to "
                        "PROJECT_OWNED_FILES instead."
                    ),
                )


class TestForwardCompatStrictDefault(unittest.TestCase):
    """3. 未来加入的 .js 文件如果两个 list 都不在，必须被发现 (强制分类)。"""

    def test_no_unclassified_js_files_present(self) -> None:
        observed = {str(p).replace("\\", "/") for p in _list_vscode_js_files()}
        classified = set(PROJECT_OWNED_FILES) | set(VENDOR_ALLOW_FILES)
        unclassified = sorted(observed - classified)
        if unclassified:
            self.fail(
                "Found new packages/vscode/*.js files not yet classified "
                "as PROJECT_OWNED or VENDOR_ALLOW:\n  "
                + "\n  ".join(unclassified)
                + (
                    "\n\nAdd each to PROJECT_OWNED_FILES (zero "
                    "`console.log` enforced) or VENDOR_ALLOW_FILES "
                    "(no enforcement, third-party code). Do NOT silently "
                    "skip this test — the whole point of R221 is to make "
                    "new VSCode webview JS opt-in to console-log "
                    "discipline at PR-author time."
                )
            )


class TestNoAccidentalSkipOfTestFiles(unittest.TestCase):
    """4. 跳过逻辑确实只跳过 fixture / test/，不会误跳过 project-owned。"""

    def test_skip_logic_does_not_swallow_project_owned(self) -> None:
        listed = {str(p).replace("\\", "/") for p in _list_vscode_js_files()}
        for fname in PROJECT_OWNED_FILES:
            with self.subTest(file=fname):
                self.assertIn(
                    fname,
                    listed,
                    (
                        f"{fname} is in PROJECT_OWNED_FILES but was not "
                        "returned by _list_vscode_js_files(). Check "
                        "SKIP_DIR_FRAGMENTS / SKIP_PATH_PREFIXES — they "
                        "may be over-broad."
                    ),
                )

    def test_skip_logic_does_skip_vscode_test_fixtures(self) -> None:
        """`.vscode-test/` 下面有几百个 vendored node_modules，扫描它们会
        显著拖慢测试且毫无意义。验证 SKIP_DIR_FRAGMENTS 真的跳过了。"""
        listed = {str(p).replace("\\", "/") for p in _list_vscode_js_files()}
        leaked = [
            p
            for p in listed
            if ".vscode-test" in p
            or "node_modules" in p
            or p.startswith(("dist/", "out/"))
        ]
        self.assertEqual(
            leaked,
            [],
            (
                "_list_vscode_js_files() leaked files from skip dirs: "
                f"{leaked!r}. SKIP_DIR_FRAGMENTS is not being applied."
            ),
        )


class TestModuleDocstringCount(unittest.TestCase):
    """5. 元测试：每次 R221 加 / 减 project-owned 文件时记得同步本文档表格。"""

    def test_project_owned_count_matches_docstring_claim(self) -> None:
        """模块 docstring 里声明 "5 个 project-owned 文件 zero `console.log`"
        来自原始 Discovery 输出。但在 R221 commit 时实际加入了更多 0-
        console-log 文件 (webview-notify-core.js 等)。本测试只锁 docstring
        中显式带数据的那 5 个文件 (i18n.js / tri-state-panel-* / webview-
        state.js) 与 PROJECT_OWNED_FILES 集合的交集，确保不会因 PR 删除
        其中之一而漏检。"""
        core_documented = {
            "i18n.js",
            "tri-state-panel-bootstrap.js",
            "tri-state-panel-loader.js",
            "tri-state-panel.js",
            "webview-state.js",
        }
        owned_set = set(PROJECT_OWNED_FILES)
        missing = core_documented - owned_set
        self.assertEqual(
            missing,
            set(),
            (
                "Project-owned files documented in R221 docstring are "
                f"missing from PROJECT_OWNED_FILES: {missing!r}. Re-add "
                "them so the invariant continues to guard them."
            ),
        )


if __name__ == "__main__":
    unittest.main()
