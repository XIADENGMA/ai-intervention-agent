"""R717 回归护栏：VS Code 插件必须真正跟随 Web UI 的语言设置。

背景（用户反馈「插件语言切换还是有问题」）。在 Web UI 里把语言从 A 切到 B 之后，
插件侧的表现是下面七类问题的叠加：

1. **空闲态永远不跟随**：webview 只在「有任务」时才 ``pollConfig`` 并应用
   ``config.language``，没有任务的时候（插件最常见的状态）从不请求配置，语言切换
   在下一个任务到来之前完全不可见。
2. **有任务时延迟 30 秒**：SSE 连接成功后轮询退到 30 秒；服务端的 ``config_changed``
   事件却没人消费，语言变化只能等下一次轮询。
3. **繁体中文被折叠成简体**：宿主侧生成 HTML 的语言解析把 ``zh-*`` 一律当成
   ``zh-CN``，``extension.ts`` 的状态栏文案也只加载 ``en`` / ``zh-CN``。
4. **``auto`` 被忽略**：服务端从显式语言切回 ``auto`` 后，插件停在上一个显式语言上，
   宿主缓存和 ``hostLang`` 也不回退。
5. **静态 ``aria-label`` 与动态复制按钮不随语言重译**：图标按钮只有 ``aria-label``
   却没有 ``data-i18n-aria-label``；复制按钮的 ``title`` / ``aria-label`` 在创建时
   写死一次。
6. **设置面板里 JS 拼出来的文案不重绘**：Bark 基址状态的消息 / 建议文案在切换语言
   后仍是旧语言。
7. **视图没打开时状态栏不跟随**：宿主只在侧边栏视图被解析（以及服务器地址变化）时
   才读取服务端语言；视图从未打开、或断线期间服务端改了语言，状态栏文案一直停在旧语言。

契约：

- 空闲轮询与 SSE ``config_changed`` 都会触发一次轻量的 ``/api/config`` 语言同步
  （``syncServerLanguage``：单飞、带超时、静默失败）。
- ``auto`` = VS Code 显示语言（宿主注入 ``__AIIA_I18N_AUTO_LANG``），不是「跳过」。
- 宿主与 webview 共用同一张映射表（``lang.ts`` 与 ``i18n.js::normalizeLang`` 一致）。
- 宿主 SSE 在（重）连成功与 ``config_changed`` 时强制同步一次服务端语言
  （``syncServerLanguage``：绕过缓存、先中止在途预取、失败保留上一个已知语言）。
- 伪语言（``pseudo``，开发用）永远优先，但宿主仍会收到 ``langDetected``。
- 切换后：静态 ``data-i18n*`` 重译 + 动态设置文案重绘。
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
import unittest
from pathlib import Path

from tests.test_vscode_poll_failure_preserves_drafts_r452 import (
    _extract_function,
    _node_available,
)
from tests.test_vscode_server_language_prefetch_stale_r452 import (
    _extract_method_body,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
WEBVIEW_UI_JS = VSCODE_DIR / "webview-ui.js"
SETTINGS_UI_JS = VSCODE_DIR / "webview-settings-ui.js"
WEBVIEW_TS = VSCODE_DIR / "webview.ts"
EXTENSION_TS = VSCODE_DIR / "extension.ts"
LANG_TS = VSCODE_DIR / "lang.ts"
TSCONFIG = VSCODE_DIR / "tsconfig.json"
LOCALES_DIR = VSCODE_DIR / "locales"

LOCALES = ("en", "zh-CN", "zh-TW")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_node(script: str, *, timeout: float = 30.0) -> str:
    """Run ``script`` in node; a hung scenario must fail the test, never hang CI."""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout


def _flatten(node: object, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}{key}."))
    elif isinstance(node, str):
        out[prefix[:-1]] = node
    return out


def _locale(name: str) -> dict[str, str]:
    return _flatten(json.loads(_read(LOCALES_DIR / f"{name}.json")))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestSyncServerLanguageRuntime(unittest.TestCase):
    """``syncServerLanguage`` 的真实行为：单飞、超时、静默失败、只应用字符串语言。"""

    def _run(self) -> dict:
        src = _read(WEBVIEW_UI_JS)
        fn = _extract_function(src, "syncServerLanguage")
        script = textwrap.dedent(
            """
            const SERVER_URL = 'http://server.test';
            const POLL_CONFIG_TIMEOUT_MS = 25;
            const applied = [];
            function applyServerLanguage(lang) { applied.push(lang); }
            const fetchCalls = [];
            let fetchImpl = null;
            function fetch(url, options) {
              fetchCalls.push({
                url, method: options.method, cache: options.cache,
                accept: options.headers && options.headers.Accept,
                hasSignal: !!options.signal,
              });
              return fetchImpl(url, options);
            }
            let languageSyncInFlight = false;
            __FN__

            const ok = (data) => async () => ({ ok: true, json: async () => data });
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const settles = (promise, ms) =>
              Promise.race([promise.then(() => true), sleep(ms).then(() => false)]);

            (async () => {
              const out = {};

              fetchImpl = ok({ language: 'zh-TW' });
              await syncServerLanguage();
              out.success = { applied: applied.slice(), calls: fetchCalls.slice() };

              applied.length = 0; fetchCalls.length = 0;
              fetchImpl = async () => ({ ok: false, json: async () => ({ language: 'en' }) });
              await syncServerLanguage();
              out.httpError = { applied: applied.slice(), calls: fetchCalls.length };

              applied.length = 0;
              for (const payload of [{}, { language: 5 }, { language: null }, null]) {
                fetchImpl = ok(payload);
                await syncServerLanguage();
              }
              out.badPayloads = applied.slice();

              applied.length = 0; fetchCalls.length = 0;
              fetchImpl = async () => { throw new Error('network down'); };
              await syncServerLanguage();
              fetchImpl = ok({ language: 'en' });
              await syncServerLanguage();
              out.afterNetworkFailure = { applied: applied.slice(), calls: fetchCalls.length };

              applied.length = 0; fetchCalls.length = 0;
              let release = null;
              fetchImpl = () => new Promise((resolve) => {
                release = () => resolve({ ok: true, json: async () => ({ language: 'zh-CN' }) });
              });
              const first = syncServerLanguage();
              const second = syncServerLanguage();
              const third = syncServerLanguage();
              release();
              const collapsed = await settles(Promise.all([first, second, third]), 1000);
              out.singleFlight = {
                settled: collapsed,
                applied: applied.slice(),
                calls: fetchCalls.length,
              };

              applied.length = 0; fetchCalls.length = 0;
              fetchImpl = (_url, options) => new Promise((_resolve, reject) => {
                options.signal.addEventListener('abort', () => reject(new Error('aborted')));
              });
              const started = Date.now();
              const aborted = await settles(syncServerLanguage(), 2000);
              const elapsed = Date.now() - started;
              fetchImpl = ok({ language: 'en' });
              await settles(syncServerLanguage(), 1000);
              out.timeout = {
                abortedWithinBudget: aborted && elapsed >= 15 && elapsed < 1500,
                applied: applied.slice(),
                calls: fetchCalls.length,
              };

              process.stdout.write(JSON.stringify(out), () => process.exit(0));
            })();
            """
        ).replace("__FN__", fn)
        return json.loads(_run_node(script))

    def test_applies_a_string_language_from_api_config(self) -> None:
        out = self._run()["success"]
        self.assertEqual(out["applied"], ["zh-TW"])
        self.assertEqual(len(out["calls"]), 1)
        call = out["calls"][0]
        self.assertEqual(call["url"], "http://server.test/api/config")
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["cache"], "no-store")
        self.assertEqual(call["accept"], "application/json")
        self.assertTrue(call["hasSignal"], "必须带 AbortController 超时信号")

    def test_non_ok_responses_and_malformed_payloads_are_ignored(self) -> None:
        out = self._run()
        self.assertEqual(out["httpError"], {"applied": [], "calls": 1})
        self.assertEqual(out["badPayloads"], [])

    def test_network_failure_is_swallowed_and_releases_the_in_flight_guard(
        self,
    ) -> None:
        out = self._run()["afterNetworkFailure"]
        self.assertEqual(out["calls"], 2, "失败后守卫必须释放，下一次同步照常发请求")
        self.assertEqual(out["applied"], ["en"])

    def test_concurrent_syncs_collapse_into_one_request(self) -> None:
        out = self._run()["singleFlight"]
        self.assertEqual(out["calls"], 1)
        self.assertEqual(out["applied"], ["zh-CN"])

    def test_hung_request_is_aborted_by_the_timeout_and_does_not_wedge_the_guard(
        self,
    ) -> None:
        out = self._run()["timeout"]
        self.assertTrue(out["abortedWithinBudget"], "超时必须通过 abort 结束挂起的请求")
        self.assertEqual(out["calls"], 2, "超时后守卫必须释放")
        self.assertEqual(out["applied"], ["en"])


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestAutoLanguageSource(unittest.TestCase):
    """``getAutoLanguage``：宿主注入的 VS Code 语言优先，其次 navigator，最后 en。"""

    def _resolve(self, window_js: str, navigator_js: str) -> str:
        fn = _extract_function(_read(WEBVIEW_UI_JS), "getAutoLanguage")
        script = (
            "const make = new Function('window', 'navigator', "
            + json.dumps(fn + "\nreturn getAutoLanguage();")
            + ");\n"
            + f"process.stdout.write(String(make({window_js}, {navigator_js})));\n"
        )
        return _run_node(script)

    def test_injected_vscode_language_wins_over_navigator(self) -> None:
        self.assertEqual(
            self._resolve(
                "{ __AIIA_I18N_AUTO_LANG: 'zh-TW' }", "{ language: 'en-US' }"
            ),
            "zh-TW",
        )

    def test_navigator_language_is_the_fallback(self) -> None:
        self.assertEqual(self._resolve("{}", "{ language: 'zh-CN' }"), "zh-CN")

    def test_defaults_to_english_when_nothing_is_available(self) -> None:
        self.assertEqual(self._resolve("{}", "{}"), "en")
        self.assertEqual(self._resolve("undefined", "undefined"), "en")


class TestWebviewPropagationHooks(unittest.TestCase):
    """语言变化必须从三条路径到达 ``applyServerLanguage``：忙时轮询、空闲轮询、SSE。"""

    def test_empty_task_poll_branch_syncs_language_after_showing_idle_state(
        self,
    ) -> None:
        body = _extract_function(_read(WEBVIEW_UI_JS), "pollAllData")
        show_idx = body.index("showNoContent()")
        sync_idx = body.index("syncServerLanguage()", show_idx)
        self.assertLess(show_idx, sync_idx)
        self.assertLess(
            sync_idx,
            body.index("return true", sync_idx),
            "空闲分支必须在返回前触发语言同步（fire-and-forget，不阻塞轮询）",
        )
        self.assertNotIn(
            "await syncServerLanguage()",
            body,
            "语言同步不得阻塞任务轮询",
        )

    def test_sse_config_changed_event_triggers_language_sync(self) -> None:
        src = _read(WEBVIEW_UI_JS)
        start = src.index("source.addEventListener('config_changed'")
        end = src.index("source.addEventListener('gap_warning'", start)
        handler = src[start:end]
        self.assertIn("_sseSource !== source", handler, "过期连接的事件必须被丢弃")
        self.assertIn("syncServerLanguage()", handler)
        self.assertNotIn(
            "pollAllData(",
            handler,
            "配置变更只需要轻量语言同步，不应触发整轮任务轮询",
        )

    def test_busy_poll_still_applies_the_language_from_config(self) -> None:
        self.assertIn("applyServerLanguage(config.language)", _read(WEBVIEW_UI_JS))

    def test_apply_server_language_order_host_pseudo_then_switch_and_redraw(
        self,
    ) -> None:
        body = _extract_function(_read(WEBVIEW_UI_JS), "applyServerLanguage")
        host_idx = body.index("type: 'langDetected'")
        pseudo_idx = body.index("getLang() === 'pseudo'")
        set_idx = body.index("i18n.setLang(")
        retranslate_idx = body.index("retranslateAllI18nElements()")
        redraw_idx = body.index("rerenderSettingsDynamicText()")
        self.assertLess(
            host_idx, pseudo_idx, "宿主必须先收到 langDetected，伪语言不能吞掉它"
        )
        self.assertLess(pseudo_idx, set_idx, "伪语言守卫必须在 setLang 之前")
        self.assertLess(set_idx, retranslate_idx)
        self.assertLess(retranslate_idx, redraw_idx)
        self.assertIn(
            "getAutoLanguage()", body, "auto 必须解析为 VS Code 语言而不是被跳过"
        )
        self.assertNotIn("lang === 'auto') return", body)

    def test_copy_button_labels_follow_language_switches(self) -> None:
        body = _extract_function(_read(WEBVIEW_UI_JS), "createCopyButton")
        self.assertIn("data-i18n-aria-label', 'ui.copy.label'", body)
        self.assertIn("data-i18n-title', 'ui.copy.label'", body)

    def test_settings_panel_exposes_and_uses_the_dynamic_text_redraw_hook(self) -> None:
        settings = _read(SETTINGS_UI_JS)
        self.assertIn("__AIIA_rerenderSettingsDynamicText", settings)
        self.assertIn("lastBarkBaseUrlStatus", settings)
        self.assertIn("rerenderBarkBaseUrlStatus", settings)
        ui = _read(WEBVIEW_UI_JS)
        wrapper = _extract_function(ui, "rerenderSettingsDynamicText")
        self.assertIn("__AIIA_rerenderSettingsDynamicText", wrapper)
        self.assertIn("catch", wrapper, "重绘钩子失败不得中断语言切换")


class TestHostLanguageContract(unittest.TestCase):
    """宿主侧：单一映射表、zh-TW 不再折叠、auto 回退到 VS Code 语言。"""

    def test_lang_module_exists_and_is_compiled(self) -> None:
        src = _read(LANG_TS)
        self.assertIn("export type UiLang", src)
        self.assertIn("export function normalizeUiLang", src)
        self.assertIn("export function resolveUiLang", src)
        include = json.loads(_read(TSCONFIG))["include"]
        self.assertIn(
            "lang.ts",
            include,
            "tsconfig 的显式 include 必须包含 lang.ts，否则 dist/lang.js 不会生成",
        )

    def test_resolution_has_no_silent_zh_collapse_in_host_code(self) -> None:
        for path in (WEBVIEW_TS, EXTENSION_TS):
            src = _read(path)
            self.assertNotRegex(
                src,
                r"""startsWith\(\s*["']zh["']\s*\)""",
                f"{path.name} 不应再自己折叠 zh-*，统一走 lang.ts",
            )

    def test_webview_html_uses_shared_resolution_and_injects_auto_language(
        self,
    ) -> None:
        src = _read(WEBVIEW_TS)
        self.assertIn('from "./lang"', src)
        self.assertIn("resolveUiLang(this._cachedServerLang, vsLang)", src)
        self.assertIn("window.__AIIA_I18N_AUTO_LANG=", src)
        self.assertIn("normalizeUiLang(vsLang)", src)

    def test_lang_detected_auto_clears_cache_and_notifies_host(self) -> None:
        src = _read(WEBVIEW_TS)
        start = src.index('case "langDetected"')
        end = src.index('case "', start + 10)
        block = src[start:end]
        auto_branch = block[
            block.index('if (lang === "auto")') : block.index("else if (lang &&")
        ]
        self.assertIn("this._cachedServerLang = null", auto_branch)
        self.assertIn("this._onLanguageChanged(lang)", auto_branch)

    def test_prefetch_reports_auto_to_the_host(self) -> None:
        body = _extract_method_body(_read(WEBVIEW_TS), "_prefetchServerLanguage")
        auto_idx = body.index('data.language === "auto"')
        self.assertIn("this._cachedServerLang = null", body[auto_idx:])
        self.assertIn('this._onLanguageChanged("auto")', body[auto_idx:])

    def test_host_sse_resyncs_server_language_on_config_changed_and_on_connect(
        self,
    ) -> None:
        src = _read(EXTENSION_TS)
        helper = src[
            src.index("const syncHostLanguage") : src.index("const _connectSSE")
        ]
        self.assertIn("provider.syncServerLanguage()", helper)
        self.assertIn(".catch(", helper, "同步失败不得产生未处理的 rejection")

        connected_idx = src.index('logger.event("sse.connected"')
        self.assertIn(
            "syncHostLanguage();",
            src[connected_idx : connected_idx + 120],
            "SSE（重）连成功必须校准一次语言：覆盖「从未打开侧边栏」与断线期间的改动",
        )
        config_idx = src.index('if (evType === "config_changed")')
        config_block = src[
            config_idx : src.index('if (evType === "heartbeat")', config_idx)
        ]
        self.assertIn("syncHostLanguage();", config_block)

    def test_forced_prefetch_skips_the_cache_and_aborts_the_in_flight_request(
        self,
    ) -> None:
        src = _read(WEBVIEW_TS)
        sync = src[
            src.index("syncServerLanguage(): Promise<void> {") : src.index(
                "private _prefetchServerLanguage("
            )
        ]
        self.assertLess(
            sync.index("this._abortPrefetchServerLanguage()"),
            sync.index("this._prefetchServerLanguage(true)"),
            "强制同步必须先中止在途预取，旧答案才不会覆盖新答案",
        )
        body = _extract_method_body(src, "_prefetchServerLanguage")
        self.assertIn("!force && this._cachedServerLang", body)

    def test_extension_host_strings_use_shared_resolution_and_ship_zh_tw(self) -> None:
        src = _read(EXTENSION_TS)
        self.assertIn('from "./lang"', src)
        self.assertIn('for (const loc of ["en", "zh-CN", "zh-TW"])', src)
        self.assertIn("hostLang = resolveUiLang(null, vscode.env.language)", src)
        self.assertIn("resolveUiLang(lang, vsLang)", src)


class TestIconButtonAriaLabelsAreTranslatable(unittest.TestCase):
    """图标按钮的 ``aria-label`` 必须带 ``data-i18n-aria-label``，否则切语言后读屏仍读旧语言。"""

    BUTTON_IDS = (
        "settingsBtn",
        "settingsBtnNoContent",
        "countdownExtendBtn",
        "countdownFreezeBtn",
        "insertCodeBtn",
        "uploadBtn",
        "submitBtn",
        "settingsClose",
    )

    def test_every_icon_button_with_an_aria_label_has_a_binding(self) -> None:
        src = _read(WEBVIEW_TS)
        for button_id in self.BUTTON_IDS:
            match = re.search(rf'<button[^>]*id="{button_id}"[^>]*>', src)
            self.assertIsNotNone(
                match, f"#{button_id} not found in webview.ts template"
            )
            assert match is not None
            tag = match.group(0)
            if "aria-label=" in tag:
                self.assertRegex(
                    tag,
                    r'data-i18n-aria-label="[^"]+"',
                    f"#{button_id} 有 aria-label 却没有 data-i18n-aria-label 绑定",
                )

    def test_every_webview_template_i18n_key_exists_in_all_locales(self) -> None:
        src = _read(WEBVIEW_TS) + "\n" + _read(WEBVIEW_UI_JS)
        keys = set(
            re.findall(
                r"""data-i18n(?:-html|-title|-placeholder|-alt|-aria-label|-value)?\s*[=,]\s*["']([A-Za-z0-9_.]+)["']""",
                src,
            )
        )
        keys.update(
            re.findall(
                r"""setAttribute\(\s*['"]data-i18n[a-z-]*['"]\s*,\s*['"]([A-Za-z0-9_.]+)['"]""",
                src,
            )
        )
        self.assertGreater(len(keys), 20, "key 抽取失败，测试本身失效")
        for name in LOCALES:
            flat = _locale(name)
            missing = sorted(k for k in keys if k not in flat)
            self.assertEqual(
                missing,
                [],
                f"locales/{name}.json 缺少宿主模板 / 动态节点引用的 i18n key；"
                "缺失时 translateDOM 会把原始 key 写进 aria-label / 文本",
            )


if __name__ == "__main__":
    unittest.main()
