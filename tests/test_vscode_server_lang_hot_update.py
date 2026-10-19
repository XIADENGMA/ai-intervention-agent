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

## R717 修订：``auto`` 不再被忽略

原契约把 ``'auto'`` 当作「永远跳过」，结果服务端从显式语言切回 ``auto`` 后，
插件卡在上一个显式语言上（宿主缓存和 ``hostLang`` 也不回退）。现契约：

- ``'auto'`` 解析为 VS Code 显示语言（``getAutoLanguage()``：宿主注入的
  ``__AIIA_I18N_AUTO_LANG``，缺失时回落 ``navigator.language``），照常走
  值比较幂等 → 切换 → ``langDetected('auto')`` 回传宿主；
- 空值仍然跳过；
- 伪语言（``pseudo``，开发用）永远优先，服务端语言（含 ``auto``）不得覆盖，
  但 ``langDetected`` 仍回传宿主，宿主侧文案继续跟随服务端；
- 切换后除 ``retranslateAllI18nElements()`` 外还要重绘 JS 动态拼出的设置文案
  （``rerenderSettingsDynamicText()``）。
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
    def _run_case(self, *, start_lang: str = "en") -> dict:
        src = _source()
        fn = _extract_function(src, "function applyServerLanguage(lang)")
        script = (
            textwrap.dedent(
                """
            const calls = {
              setLang: [], retranslate: 0, rerender: 0, postMessage: [],
            };
            let currentLang = '__START__';

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
            function getAutoLanguage() { return 'zh-TW'; }
            function ensureLocaleRegistered() { return true; }
            function retranslateAllI18nElements() { calls.retranslate += 1; }
            function rerenderSettingsDynamicText() { calls.rerender += 1; }

            let _serverLangLastApplied = '';
            __FN__

            applyServerLanguage('zh-CN');   // 首次：切换
            applyServerLanguage('zh-CN');   // 重复：幂等跳过
            applyServerLanguage('en');      // 热更新：再次切换
            applyServerLanguage('auto');    // auto：解析为 VS Code 语言后切换
            applyServerLanguage('auto');    // auto 重复：幂等跳过
            applyServerLanguage('');        // 空值：跳过

            process.stdout.write(JSON.stringify(calls));
            """
            )
            .replace("__FN__", fn)
            .replace("__START__", start_lang)
        )
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
        # zh-CN → en → auto(=zh-TW) 各切换一次；重复值与空值都不切
        assert calls["setLang"] == ["zh-CN", "en", "zh-TW"]
        assert calls["retranslate"] == 3
        assert calls["rerender"] == 3
        # langDetected 只在值变化时回传，auto 以原值回传给宿主
        langs = [m.get("language") for m in calls["postMessage"]]
        assert langs == ["zh-CN", "en", "auto"]

    def test_pseudo_locale_wins_but_host_is_still_informed(self) -> None:
        calls = self._run_case(start_lang="pseudo")
        assert calls["setLang"] == [], "伪语言不得被服务端语言（含 auto）覆盖"
        assert calls["retranslate"] == 0
        assert calls["rerender"] == 0
        langs = [m.get("language") for m in calls["postMessage"]]
        assert langs == ["zh-CN", "en", "auto"], "宿主侧文案仍需跟随服务端语言"
