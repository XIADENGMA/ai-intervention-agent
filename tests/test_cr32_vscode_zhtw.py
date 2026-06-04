"""cr32 §3.2 fix [medium]：VSCode 插件端 zh-TW locale 完整性。

背景
----
feat-zhtw-locale (§3.3) 更新了 ``packages/vscode/i18n.js::normalizeLang``
把 ``zh-TW / zh-HK / zh-MO / zh-Hant*`` 折叠到 ``zh-TW``，但没有同步
ship ``packages/vscode/locales/zh-TW.json``。运行时行为：

1. zh-TW 用户打开扩展，``setLang('zh-TW')`` → ``currentLang = 'zh-TW'``
2. ``_t('settings.title')`` 走 ``locales[currentLang]`` → undefined
3. fallback 到 ``locales[DEFAULT_LANG]`` → 'en'
4. 用户体感："web UI 显示繁中、扩展显示英文"

cr32 §3.2 fix
-------------
1. ``scripts/gen_zhtw_from_zhcn.py`` 加 ``--variant {web|vscode}`` /
   ``--all`` 参数，从 ``packages/vscode/locales/zh-CN.json`` 派生
   ``packages/vscode/locales/zh-TW.json``。
2. ``packages/vscode/webview.ts::_preloadResources`` 把
   ``loadLocale('zh-TW')`` 加进 ``Promise.all`` 并行预加载。
3. ``packages/vscode/webview.ts::_getHtmlContent`` 的 fallback 列表
   ``['en', 'zh-CN']`` → ``['en', 'zh-CN', 'zh-TW']``。

本测试套件锁四件事：

1. ``packages/vscode/locales/zh-TW.json`` 文件存在且 JSON 可解析。
2. ``_meta.translationNote`` 字段存在（标注派生来源 + 邀请 PR review）。
3. ``packages/vscode/i18n.js`` 的 normalizeLang 折叠表与
   ``static/js/i18n.js`` 行为一字不差（reuse feat-zhtw 既有测试覆盖）。
4. ``packages/vscode/webview.ts`` 预加载 + fallback 列表都包含 zh-TW。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_VSCODE = REPO_ROOT / "packages" / "vscode"
VSCODE_ZH_TW = PKG_VSCODE / "locales" / "zh-TW.json"
VSCODE_ZH_CN = PKG_VSCODE / "locales" / "zh-CN.json"
VSCODE_EN = PKG_VSCODE / "locales" / "en.json"
VSCODE_WEBVIEW_TS = PKG_VSCODE / "webview.ts"
GEN_SCRIPT = REPO_ROOT / "scripts" / "gen_zhtw_from_zhcn.py"


# ---------------------------------------------------------------------------
# 1. zh-TW.json 文件存在 + 解析 OK
# ---------------------------------------------------------------------------


class TestZhTwJsonShipped(unittest.TestCase):
    def test_vscode_locales_zh_tw_json_exists(self) -> None:
        self.assertTrue(
            VSCODE_ZH_TW.is_file(),
            f"VSCode 插件必须 ship {VSCODE_ZH_TW}，"
            "否则 normalizeLang('zh-TW') 后 locales[zh-TW] undefined → "
            "用户看到英文（cr32 §3.2 bug）。",
        )

    def test_vscode_zh_tw_is_valid_json(self) -> None:
        try:
            data = json.loads(VSCODE_ZH_TW.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            self.fail(f"{VSCODE_ZH_TW} 不是有效 JSON: {e}")
        self.assertIsInstance(data, dict)
        self.assertGreater(
            len(data),
            1,  # 至少 _meta + 1 个其它顶层 namespace
            "zh-TW.json 至少应有 _meta + 1 个其它顶层 key",
        )


# ---------------------------------------------------------------------------
# 2. _meta.translationNote 邀请 native review
# ---------------------------------------------------------------------------


class TestZhTwMetaPresent(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(VSCODE_ZH_TW.read_text(encoding="utf-8"))

    def test_meta_field_present(self) -> None:
        self.assertIn(
            "_meta",
            self.data,
            "zh-TW.json 必须有 _meta 字段标注派生来源（让 native zh-TW 知道这是 MVP）",
        )
        meta = self.data["_meta"]
        self.assertIsInstance(meta, dict)
        self.assertIn("translationNote", meta)
        note = meta["translationNote"]
        self.assertIsInstance(note, str)
        # 邀请 PR review 是 _meta 存在的核心目的
        self.assertIn("PR", note, "translationNote 应邀请 PR review")
        self.assertIn(
            "scripts/gen_zhtw_from_zhcn.py",
            note,
            "translationNote 应注明派生来源 script",
        )

    def test_meta_derived_from_zh_cn(self) -> None:
        self.assertEqual(
            self.data["_meta"].get("derivedFrom"),
            "zh-CN",
            "VSCode 端 zh-TW 也派生自 zh-CN（同 web 端 invariant）",
        )


# ---------------------------------------------------------------------------
# 3. schema parity vs zh-CN.json（除 _meta 元数据外 key 集严格一致）
# ---------------------------------------------------------------------------


class TestSchemaParityWithZhCn(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cn = json.loads(VSCODE_ZH_CN.read_text(encoding="utf-8"))
        cls.tw = json.loads(VSCODE_ZH_TW.read_text(encoding="utf-8"))

    @staticmethod
    def _flatten(d: dict, prefix: str = "") -> set[str]:
        """递归收集所有 dotted key path；忽略顶层 _* 元数据 namespace
        （与 tests/test_i18n_locale_key_parity.py 同款 invariant 松弛）。
        """
        out: set[str] = set()
        for k, v in d.items():
            if not prefix and k.startswith("_"):
                continue
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out |= TestSchemaParityWithZhCn._flatten(v, full)
            else:
                out.add(full)
        return out

    def test_zh_tw_has_same_key_set_as_zh_cn(self) -> None:
        cn_keys = self._flatten(self.cn)
        tw_keys = self._flatten(self.tw)
        only_in_cn = cn_keys - tw_keys
        only_in_tw = tw_keys - cn_keys
        self.assertEqual(
            only_in_cn,
            set(),
            f"zh-CN 中存在但 zh-TW 中缺失的 key：{sorted(only_in_cn)}\n"
            "解决：重跑 ``python scripts/gen_zhtw_from_zhcn.py --variant vscode``",
        )
        self.assertEqual(
            only_in_tw,
            set(),
            f"zh-TW 中存在但 zh-CN 中没有的 key：{sorted(only_in_tw)}\n"
            "解决：先在 zh-CN.json 加 key，再重跑生成脚本",
        )


# ---------------------------------------------------------------------------
# 4. webview.ts 预加载 + fallback 列表都包含 zh-TW
# ---------------------------------------------------------------------------


class TestWebviewTsLoadsZhTw(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = VSCODE_WEBVIEW_TS.read_text(encoding="utf-8")

    def test_preload_resources_loads_zh_tw(self) -> None:
        # 必须出现 ``loadLocale("zh-TW")`` 调用
        self.assertIn(
            'loadLocale("zh-TW")',
            self.src,
            "webview.ts::_preloadResources 必须 await loadLocale('zh-TW')，"
            "否则 _cachedLocales['zh-TW'] 永远 undefined（cr32 §3.2 fix）",
        )

    def test_html_fallback_list_includes_zh_tw(self) -> None:
        # 同步 fallback 路径里的 for loop 列表必须包含 zh-TW
        # 找出形如 ``for (const loc of ["en", "zh-CN", "zh-TW"])`` 的字面量
        self.assertRegex(
            self.src,
            r'\["en",\s*"zh-CN",\s*"zh-TW"\]',
            "webview.ts 的 allLocales 同步 fallback 列表必须包含 'zh-TW'，"
            "否则 _preloadResources 失败时 zh-TW 不被注入 webview",
        )


# ---------------------------------------------------------------------------
# 5. gen 脚本 --variant / --all 参数存在
# ---------------------------------------------------------------------------


class TestGenScriptVariantSupport(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = GEN_SCRIPT.read_text(encoding="utf-8")

    def test_variant_argument_present(self) -> None:
        self.assertIn(
            '"--variant"',
            self.src,
            "gen_zhtw_from_zhcn.py 必须支持 --variant 让维护者切换 web/vscode 输出",
        )

    def test_vscode_variant_path_present(self) -> None:
        self.assertIn(
            '"vscode"',
            self.src,
            "_VARIANTS 必须有 'vscode' 入口",
        )
        self.assertIn(
            'packages" / "vscode" / "locales"',
            self.src,
            "_VARIANTS['vscode'] 必须指向 packages/vscode/locales/",
        )

    def test_all_argument_present(self) -> None:
        self.assertIn(
            '"--all"',
            self.src,
            "--all 让 CI / 维护者一次重生成所有 variant，避免 web/vscode drift",
        )


# ---------------------------------------------------------------------------
# 6. 翻译质量基线：核心 GUI 字符已转繁体
# ---------------------------------------------------------------------------


class TestTranslationQualityBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = VSCODE_ZH_TW.read_text(encoding="utf-8")

    def test_no_high_frequency_simplified_residue(self) -> None:
        """常见 GUI 简体字残留 = phrase/char map 没覆盖到的 case。
        发现新残留时把字加进 ``scripts/gen_zhtw_from_zhcn.py::CHAR_MAP_v2``
        并重跑 ``--all`` 即可。"""
        residue_chars = ["测", "缀"]  # cr32 §3.2 fix 顺手补的字
        offenders: list[str] = []
        for ch in residue_chars:
            cnt = cls = self.text.count(ch)
            if cnt:
                offenders.append(f"{ch!r}({cnt}x)")
        self.assertEqual(
            offenders,
            [],
            f"VSCode zh-TW.json 仍有简体残留 GUI 字符：{offenders}。"
            "解决：在 CHAR_MAP_v2 加映射重跑 ``--all`` 后再 commit。",
        )

    def test_contains_traditional_chinese_markers(self) -> None:
        """随机抽 3 个高频繁体字必须出现（保证 char-map 真的跑了）。

        挑的字必须在 ``packages/vscode/locales/zh-CN.json`` 内实际出现过的
        简体源字符（不然简-繁映射根本没机会触发），且对应繁体在台湾标准是
        与简体不同的字形。
        """
        # ``設定`` / ``回饋`` / ``開啟`` 来自插件 ``settings.title`` /
        # ``settings.feedback.title`` / 一系列 "通知" 文案
        markers = ["設", "饋", "關"]
        missing = [m for m in markers if m not in self.text]
        self.assertEqual(
            missing,
            [],
            f"VSCode zh-TW.json 缺失高频繁体字 {missing}（说明转换没跑成功）",
        )


if __name__ == "__main__":
    unittest.main()
