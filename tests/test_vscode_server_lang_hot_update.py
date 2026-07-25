"""TODO#11 — VS Code webview 服务器语言热更新跟随。

## 背景

历史实现用布尔标志 ``_serverLangApplied`` 把服务器 TOML 驱动的语言切换
限制为「仅首次生效」：

    let _serverLangApplied = false
    function applyServerLanguage(lang) {
      if (!lang || lang === 'auto' || _serverLangApplied) return
      _serverLangApplied = true
      ...
    }

后果：运行时修改 ``config.toml`` 的 ``web_ui.language``（服务端热更新）
后，webview 轮询每 2 秒都拿到新 language 却被布尔标志跳过——插件语言
"永远更新不及时"，直到用户重开面板。

## 新契约（本测试锁定）

1. ``applyServerLanguage`` 用**值比较**幂等（``lang === _serverLangLastApplied``
   时 return），而非一次性布尔。
2. 行为矩阵（Node vm 运行时验证）：
   - 首次 'zh-CN' → 切换（setLang + retranslate 各 1 次）
   - 重复 'zh-CN' → 幂等跳过（不重复切换）
   - 改 'en'（配置热更新）→ 再次切换
   - 'auto' / 空值 → 永远跳过
3. ``fetchConfig`` 调用点不再有 ``!_serverLangApplied`` 前置拦截
   （幂等判断收敛到 applyServerLanguage 单点）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start + len(marker) - 1)
    assert open_brace != -1
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


class TestStaticContract:
    def test_value_comparison_replaces_boolean_latch(self) -> None:
        src = _source()
        assert "_serverLangLastApplied" in src, (
            "应使用 _serverLangLastApplied 记录上次应用的语言值"
        )
        assert "_serverLangApplied = true" not in src, (
            "一次性布尔标志应已移除——它会挡住运行时配置热更新"
        )
        body = _extract_function(src, "function applyServerLanguage(lang)")
        assert "lang === _serverLangLastApplied" in body, (
            "applyServerLanguage 必须做值比较幂等"
        )

    def test_fetch_config_call_site_has_no_boolean_gate(self) -> None:
        src = _source()
        assert "!_serverLangApplied" not in src, (
            "fetchConfig 调用点不应再有布尔前置拦截（幂等在 applyServerLanguage 内）"
        )
        assert "applyServerLanguage(config.language)" in src, (
            "fetchConfig 必须继续把服务器 language 交给 applyServerLanguage"
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
class TestRuntimeBehaviour:
    def _run_case(self) -> dict:
        src = _source()
        fn = _extract_function(src, "function applyServerLanguage(lang)")
        script = textwrap.dedent(
            """
            const calls = { setLang: [], retranslate: 0, postMessage: [] };
            let currentLang = 'en';

            const vscode = {
              postMessage(msg) { calls.postMessage.push(msg); },
            };
            function getI18n() {
              return {
                setLang(l) { calls.setLang.push(l); currentLang = l; },
                getLang() { return currentLang; },
                normalizeLang(l) { return l; },
              };
            }
            function ensureLocaleRegistered() { return true; }
            function retranslateAllI18nElements() { calls.retranslate += 1; }

            let _serverLangLastApplied = '';
            __FN__

            applyServerLanguage('zh-CN');   // 首次：切换
            applyServerLanguage('zh-CN');   // 重复：幂等跳过
            applyServerLanguage('en');      // 热更新：再次切换
            applyServerLanguage('auto');    // auto：跳过
            applyServerLanguage('');        // 空值：跳过

            process.stdout.write(JSON.stringify(calls));
            """
        ).replace("__FN__", fn)
        proc = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0, (
            f"node exited {proc.returncode}\nstderr={proc.stderr!r}"
        )
        return json.loads(proc.stdout)

    def test_first_apply_repeat_skip_hot_update_reapplies(self) -> None:
        calls = self._run_case()
        # 首次 zh-CN + 热更新 en 各切换一次；重复/auto/空值都不切
        assert calls["setLang"] == ["zh-CN", "en"]
        assert calls["retranslate"] == 2
        # langDetected 只在值变化时回传（zh-CN / en 各一次）
        langs = [m.get("language") for m in calls["postMessage"]]
        assert langs == ["zh-CN", "en"]
