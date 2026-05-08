"""R72-D · CodeQL js/client-side-request-forgery #35 修复回归测试。

锁定 ``static/js/i18n.js::normalizeLang`` 的白名单语义：

- 已知语言（``pseudo`` / ``zh-*`` / ``en-*``）返回各自的 canonical tag。
- 任何**未知输入**（包括路径穿越 attempt、异常字符、其他 BCP-47 语言）一律
  折叠到 ``DEFAULT_LANG``（=``en``），不能再透传到 ``loadLocale`` 的
  fetch URL 里。

老实现 ``return s || DEFAULT_LANG`` 让 ``lang='evil/path'`` 这种值原样
回传，理论上能把 ``loadLocale`` 的 ``<base>/<lang>.json`` 拼成
``<base>/evil/path.json``。同源攻击面有限，但 CodeQL 仍正确把它标记成
client-side-request-forgery。R72-D 把 fallback 收紧成 DEFAULT_LANG。

执行方式
========

走 Node ``vm`` 包载入 ``static/js/i18n.js``，调用挂在 globalThis 上的
``window.aiia_i18n.normalizeLang(...)``，断言返回值。这与
``test_i18n_pseudo_runtime_switch.py`` 是同一套技术。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_I18N_JS_STATIC = (
    _PROJECT_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "i18n.js"
)
_I18N_JS_VSCODE = _PROJECT_ROOT / "packages" / "vscode" / "i18n.js"
_RUN_NORMALIZE_HARNESS = """
const fs = require('fs');
const vm = require('vm');
const i18nPath = {i18n_path};
const code = fs.readFileSync(i18nPath, 'utf8');
const sandbox = {{ window: {{}}, document: {{}}, location: {{ search: '' }} }};
sandbox.globalThis = sandbox;
sandbox.global = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
// 两份 i18n.js 用了不同的 export 路径：
//   - static/js/i18n.js:                    window.AIIA_I18N = api（写死 window）
//   - packages/vscode/i18n.js:              globalThis.AIIA_I18N = api（走 globalThis，try-catch fallback 到 window）
// vm.runInContext 让 globalThis === sandbox，所以 vscode 版的 api 落在 sandbox.AIIA_I18N
// 而**不是** sandbox.window.AIIA_I18N。R96 之前 harness 只读 sandbox.window.AIIA_I18N，
// 在 vscode 这条 export 路径下永远拿不到，于是 ``test_packages_vscode_i18n_consistency``
// 总是 skip ——CSRF 加固的"vscode 镜像也必须有"这条契约表面上有测试，实际从未跑过。
// 同时 fallback ``sandbox.AIIA_I18N``（或任意 ``window.AIIA_I18N``）满足两份文件。
const api = sandbox.window.AIIA_I18N || sandbox.AIIA_I18N;
if (!api || typeof api.normalizeLang !== 'function') {{
  process.stderr.write('FAIL: normalizeLang not exported from ' + i18nPath);
  process.exit(1);
}}
process.stdout.write(api.normalizeLang({raw_arg}));
"""


def _run_normalize(i18n_path: Path, raw: str) -> str | None:
    """Invoke ``api.normalizeLang(raw)`` from a JS sandbox, return its output."""
    node = shutil.which("node")
    if node is None:
        return None
    harness = _RUN_NORMALIZE_HARNESS.format(
        i18n_path=json.dumps(str(i18n_path)),
        raw_arg=json.dumps(raw),
    )
    proc = subprocess.run(
        [node, "-e", harness],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return f"NODE_FAIL: {proc.stderr.strip()}"
    return proc.stdout


@unittest.skipIf(shutil.which("node") is None, "node not on PATH; skip JS unit tests")
class TestNormalizeLangCsrfHardening(unittest.TestCase):
    """`normalizeLang` 必须把未知输入折叠到 DEFAULT_LANG（=en）。"""

    KNOWN_GOOD = (
        # (input, expected canonical)
        ("zh-CN", "zh-CN"),
        ("zh-cn", "zh-CN"),
        ("zh-TW", "zh-CN"),  # 当前实现把所有 zh* 都折叠到 zh-CN
        ("ZH", "zh-CN"),
        ("en", "en"),
        ("en-US", "en"),
        ("EN-GB", "en"),
        ("pseudo", "pseudo"),
        ("PSEUDO", "pseudo"),
        ("xx-AC", "pseudo"),
        ("xx", "pseudo"),
        ("  pseudo  ", "pseudo"),
    )

    UNKNOWN_OR_HOSTILE = (
        # 路径穿越 attempt — 必须被绑到 DEFAULT_LANG
        "evil/path",
        "../../../etc/passwd",
        "%2e%2e%2fpasswd",
        "../../../private",
        # 协议混入
        "javascript:alert(1)",
        # 其他真实但项目不支持的 BCP-47 tag
        "fr-FR",
        "ja-JP",
        "es-ES",
        # 空字符串 / null / 噪声
        "",
        "   ",
        "null",
        "undefined",
        "Object.prototype",
        "constructor",
    )

    def _assert_default_lang(self, i18n_path: Path) -> None:
        for raw in self.UNKNOWN_OR_HOSTILE:
            with self.subTest(file=i18n_path.name, raw=raw):
                got = _run_normalize(i18n_path, raw)
                self.assertEqual(
                    got,
                    "en",
                    f"{i18n_path.name}: normalizeLang({raw!r}) should fold to "
                    f"DEFAULT_LANG (en), got {got!r}",
                )

    def _assert_known_canonical(self, i18n_path: Path) -> None:
        for raw, expected in self.KNOWN_GOOD:
            with self.subTest(file=i18n_path.name, raw=raw):
                got = _run_normalize(i18n_path, raw)
                self.assertEqual(
                    got,
                    expected,
                    f"{i18n_path.name}: normalizeLang({raw!r}) should be "
                    f"{expected!r}, got {got!r}",
                )

    def test_static_i18n_known_inputs_canonical(self) -> None:
        self._assert_known_canonical(_I18N_JS_STATIC)

    def test_static_i18n_unknown_inputs_fold_to_default(self) -> None:
        self._assert_default_lang(_I18N_JS_STATIC)

    def test_static_i18n_path_traversal_blocked(self) -> None:
        """路径穿越尝试必须不能透传到 fetch URL。"""
        for traversal in (
            "../../etc/passwd",
            "..%2f..%2fpasswd",
            "x/../y",
            "//evil.com/x",
        ):
            with self.subTest(traversal=traversal):
                got = _run_normalize(_I18N_JS_STATIC, traversal)
                self.assertEqual(got, "en")

    def test_packages_vscode_i18n_consistency(self) -> None:
        """``packages/vscode/i18n.js`` 镜像 ``static/js/i18n.js`` 行为；如果它存在，
        则必须有同样的 csrf 加固 + canonical 折叠表。如果不存在或没有 normalizeLang
        函数，跳过。

        R96 之前本测试的 harness 只读 ``sandbox.window.AIIA_I18N``，但 vscode 版
        i18n.js 的 export 路径是 ``globalThis.AIIA_I18N = api``（``vm.runInContext``
        让 ``globalThis === sandbox``，所以 api 落在 ``sandbox.AIIA_I18N`` 而非
        ``sandbox.window.AIIA_I18N``）——结果 ``getNormalize`` 永远返回 None，本
        测试始终 skip，CSRF 加固在 vscode 镜像里是否真存在从未真正被 CI 验证。
        R96 把 harness 改成同时尝试 ``sandbox.window.AIIA_I18N`` 与
        ``sandbox.AIIA_I18N``，并把 smoke 升级为完整的 KNOWN_GOOD / HOSTILE 双
        集合断言（与 static 侧 ``test_static_i18n_*`` 保持等价覆盖），这样
        vscode 端的 normalizeLang 漂移（漏掉 ``xx-AC → pseudo`` / ``zh-TW →
        zh-CN`` / 路径穿越未折叠）等任意一项都会 fail。
        """
        # R105：缺文件 → fail-loud，不再 silent skip。``packages/vscode/
        # i18n.js`` 是 VS Code 镜像 i18n 实现的单一源；缺失即配置漂移
        # （与 R104 main.css/webview.css 同款修复）。R96 已把 harness 修对
        # 让 vscode 镜像的 normalizeLang 真能跑，但没动这条 silent skip——
        # 现在补上。
        if not _I18N_JS_VSCODE.exists():
            try:
                rel = _I18N_JS_VSCODE.relative_to(_PROJECT_ROOT).as_posix()
            except ValueError:
                rel = str(_I18N_JS_VSCODE)
            self.fail(
                f"R105: packages/vscode/i18n.js missing: {rel}\n"
                f"  Resolved absolute path: {_I18N_JS_VSCODE}\n"
                f"  This is configuration drift, not 'OK' — failing loud (R105;\n"
                f"  matches R88/R100/R101/R102/R104 family). Either update\n"
                f"  _I18N_JS_VSCODE in tests/test_i18n_normalize_lang_csrf_r72d.py\n"
                f"  or restore the missing mirror file."
            )
        # R105：sentinel = "NODE_FAIL: ..." 表示 i18n.js 没正确导出
        # ``normalizeLang``——R96 修过 harness 后这种状态是真 bug 信号
        # （比如 export 路径漂移、syntax error、API 名字漂移），而不是合法
        # 环境缺失（class-level ``@unittest.skipIf(node is None)`` 已经守住
        # node 不可用的合法 skip 路径）。原 silent skip 让这种 bug 在 CI 输
        # 出里和合法 skip 混在一起，没人看；改成 fail-loud。
        sentinel = _run_normalize(_I18N_JS_VSCODE, "evil/path")
        self.assertIsNotNone(
            sentinel,
            msg=(
                "R105: _run_normalize returned None despite class-level node-skip "
                "guard. This indicates a regression in the test harness itself."
            ),
        )
        if isinstance(sentinel, str) and sentinel.startswith("NODE_FAIL"):
            self.fail(
                f"R105: packages/vscode/i18n.js failed to export normalizeLang.\n"
                f"  Sentinel: {sentinel}\n"
                f"  This is a real export/wiring bug (not a missing-Node skip).\n"
                f"  R96 fixed the harness to read sandbox.window.AIIA_I18N OR\n"
                f"  sandbox.AIIA_I18N — if NODE_FAIL still happens, either:\n"
                f"    1. i18n.js has a syntax error / runtime exception, or\n"
                f"    2. the export path drifted again (e.g. someone renamed\n"
                f"       AIIA_I18N → AIIA_I18N_API), or\n"
                f"    3. normalizeLang got renamed / deleted."
            )
        # 等价 coverage：与 static 侧保持一致的双集合断言。
        self._assert_known_canonical(_I18N_JS_VSCODE)
        self._assert_default_lang(_I18N_JS_VSCODE)


@unittest.skipIf(shutil.which("node") is None, "node not on PATH")
class TestNormalizeLangSourceContract(unittest.TestCase):
    """直接 grep 源码确认 R72-D 修复没被静默回退到老的 ``return s || DEFAULT_LANG``。"""

    def test_old_unsafe_fallback_removed(self) -> None:
        """老的 ``return s || DEFAULT_LANG`` 必须不能在 normalizeLang 函数体里出现。

        Note：注释/docstring 里可以保留这串字符（用于解释历史漏洞），但
        函数主体里**必须**走显式 ``return DEFAULT_LANG``。这里用 multiline
        regex 限定到 ``function normalizeLang`` 的函数体范围内匹配。
        """
        import re

        text = _I18N_JS_STATIC.read_text(encoding="utf-8")
        match = re.search(
            r"function\s+normalizeLang\s*\([^)]*\)\s*\{(.*?)\n\s{0,4}\}",
            text,
            re.DOTALL,
        )
        assert match is not None, "源码必须包含 normalizeLang 函数定义"
        body = match.group(1)
        self.assertNotIn(
            "return s || DEFAULT_LANG",
            body,
            "R72-D 契约：老 fallback ``return s || DEFAULT_LANG`` 必须从函数"
            "主体里删除（让任意未知 lang 透传到 fetch URL，是 "
            "client-side-request-forgery）",
        )

    def test_normalize_lang_returns_default_for_unknown(self) -> None:
        """函数体里必须出现 ``return DEFAULT_LANG`` 作为 fallback。"""
        text = _I18N_JS_STATIC.read_text(encoding="utf-8")
        # normalizeLang 函数体里必须明确 fallback 到 DEFAULT_LANG
        # （白名单语义）
        self.assertRegex(
            text,
            r"function\s+normalizeLang\s*\([^)]*\)\s*\{[^}]*?return\s+DEFAULT_LANG",
            "normalizeLang 必须显式 fallback 到 DEFAULT_LANG（R72-D 契约）",
        )


if __name__ == "__main__":
    unittest.main()
