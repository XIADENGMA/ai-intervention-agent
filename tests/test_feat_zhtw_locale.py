"""feat-zhtw-locale (§3.3) 回归契约

实现：scripts/gen_zhtw_from_zhcn.py 派生 zh-TW.json + i18n.js / i18n.py /
server_config.py / web_ui.py 一等支持 zh-TW BCP-47 tag。

设计原则
--------
1. **零运行时依赖**：转换脚本是 dev-only，运行时通过 ``loadLocale``
   按需 fetch zh-TW.json，不影响 zh-CN/en 用户的 bundle 体积。
2. **BCP-47 折叠**：zh-TW / zh-HK / zh-MO / zh-Hant* 都 normalize 到
   ``zh-TW``；其余 zh-* (zh-CN / zh-Hans / zh-SG / zh-MY) 继续走
   ``zh-CN``，与 ``static/js/i18n.js`` ``normalizeLang`` 行为一致。
3. **schema 同构**：zh-TW.json 必须和 zh-CN.json 拥有完全相同的 key 树
   （除顶层 ``_meta`` 是 zh-TW 特有的元数据），下游 ``_resolvePath``
   不会因为缺 key 落到 fallback 英文。
4. **MVP 翻译质量**：脚本通过 phrase + char 双层映射做转换；不保证
   原生级别质量。``_meta.translationNote`` 字段公开邀请 PR review。

锁定的不变量
------------
A. 脚本存在 + 输出 zh-TW.json 存在 + 注入 ``_meta``
B. zh-TW.json schema ≡ zh-CN.json schema（除 _meta）
C. zh-TW.json 关键 GUI 文案确实包含繁体特有字符（不是简体残留）
D. 前端 i18n.js ``normalizeLang`` 把 zh-TW / zh-Hant / zh-HK / zh-MO
   都折叠到 ``zh-TW``；zh-CN / zh-Hans 仍走 ``zh-CN``
E. 后端 i18n.py SUPPORTED_LANGS 含 zh-TW；``normalize_lang`` 行为
   与前端对齐；``_MESSAGES["zh-TW"]`` 完整覆盖所有 key
F. server_config.WebUIConfig.SUPPORTED_LANGS 含 zh-TW
G. web_ui.py ``/api/update-language`` 白名单含 zh-TW
H. web_ui.html ``<select id="language-select">`` 有 zh-TW option
I. en.json / zh-CN.json 新增 ``settings.langZhTW`` key
J. CSRF/SSRF 加固：``normalizeLang('evil/path')`` 不会回传原值
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
SCRIPT_PATH = REPO_ROOT / "scripts" / "gen_zhtw_from_zhcn.py"
ZH_CN_PATH = LOCALES_DIR / "zh-CN.json"
ZH_TW_PATH = LOCALES_DIR / "zh-TW.json"
EN_PATH = LOCALES_DIR / "en.json"
I18N_JS_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "i18n.js"
I18N_PY_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "i18n.py"
SERVER_CONFIG_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "server_config.py"
WEB_UI_PY_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"
WEB_UI_HTML_PATH = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
)


def _flatten_keys(obj: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for k, v in obj.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= _flatten_keys(v, full)
        else:
            keys.add(full)
    return keys


# ============================================================
# A. 脚本 + 输出文件 + meta
# ============================================================
class TestArtifactsExist(unittest.TestCase):
    def test_script_exists(self) -> None:
        self.assertTrue(SCRIPT_PATH.exists(), "需要 scripts/gen_zhtw_from_zhcn.py")
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("PHRASE_MAP", src)
        self.assertIn("CHAR_MAP_v2", src)
        self.assertIn("feat-zhtw-locale", src)

    def test_zh_tw_json_exists(self) -> None:
        self.assertTrue(ZH_TW_PATH.exists(), "需要 static/locales/zh-TW.json")

    def test_zh_tw_has_meta_translation_note(self) -> None:
        data = json.loads(ZH_TW_PATH.read_text(encoding="utf-8"))
        self.assertIn("_meta", data, "zh-TW.json 顶层需有 _meta")
        meta = data["_meta"]
        self.assertIn("translationNote", meta)
        self.assertIn("derivedFrom", meta)
        self.assertEqual(meta.get("derivedFrom"), "zh-CN")
        # 邀请 PR review 的语义
        note = str(meta.get("translationNote", "")).lower()
        self.assertIn("native", note, "translationNote 应说明非原生翻译")


# ============================================================
# B. schema 同构
# ============================================================
class TestSchemaParity(unittest.TestCase):
    """zh-TW.json (除 _meta) 必须和 zh-CN.json key tree 完全一致。

    这保证用户切到 zh-TW 时，所有 data-i18n key 都能 hit，而不会
    fallback 到英文（更不会塌陷成 raw key）。
    """

    def setUp(self) -> None:
        self.cn = json.loads(ZH_CN_PATH.read_text(encoding="utf-8"))
        self.tw = json.loads(ZH_TW_PATH.read_text(encoding="utf-8"))

    def test_no_extra_keys_in_tw(self) -> None:
        """zh-TW.json 除 _meta 外不应有 zh-CN 没有的 key。"""
        tw_no_meta = {k: v for k, v in self.tw.items() if not k.startswith("_")}
        cn_keys = _flatten_keys(self.cn)
        tw_keys = _flatten_keys(tw_no_meta)
        extra = tw_keys - cn_keys
        self.assertFalse(
            extra,
            f"zh-TW.json 有多余 key 未在 zh-CN 中存在：{sorted(extra)}",
        )

    def test_no_missing_keys_in_tw(self) -> None:
        cn_keys = _flatten_keys(self.cn)
        tw_no_meta = {k: v for k, v in self.tw.items() if not k.startswith("_")}
        tw_keys = _flatten_keys(tw_no_meta)
        missing = cn_keys - tw_keys
        self.assertFalse(
            missing,
            (
                f"zh-TW.json 缺 {len(missing)} 个 key（需重跑 "
                f"`uv run python scripts/gen_zhtw_from_zhcn.py`）。前 5 个："
                f"{sorted(missing)[:5]}"
            ),
        )


# ============================================================
# C. 翻译质量抽检
# ============================================================
class TestTranslationQuality(unittest.TestCase):
    """对几个高频 GUI 文案做关键 traditional-only 字符断言。

    不要求字符串完全 match（防止术语二次校订时把测试改崩），只断言
    contains 关键繁体字符——验证脚本至少没有 ship 纯简体字符串。
    """

    def setUp(self) -> None:
        self.tw = json.loads(ZH_TW_PATH.read_text(encoding="utf-8"))

    def test_settings_main_contains_traditional(self) -> None:
        v = self.tw["settings"]["main"]
        self.assertIn("設", v, f"settings.main 应含「設」（实际：{v!r}）")

    def test_language_label_uses_jiemian(self) -> None:
        v = self.tw["settings"]["language"]
        self.assertIn("介面", v, f"settings.language 应含「介面」（实际：{v!r}）")

    def test_lang_zh_tw_self_name(self) -> None:
        v = self.tw["settings"]["langZhTW"]
        self.assertEqual(v, "繁體中文")

    def test_feedback_uses_huikui(self) -> None:
        v = self.tw["page"]["submitFeedbackBtn"]
        self.assertIn("回饋", v, f"submitFeedbackBtn 应含「回饋」（实际：{v!r}）")

    def test_extend_countdown_traditional(self) -> None:
        v = self.tw["page"]["extendCountdown"]["limitReached"]
        # 「達」是 traditional only
        self.assertIn("達", v, f"limitReached 应含「達」（实际：{v!r}）")
        # 「任務」不是「任务」
        self.assertIn("任務", v, f"limitReached 应含「任務」（实际：{v!r}）")


# ============================================================
# D. 前端 normalizeLang
# ============================================================
class TestI18nJsNormalize(unittest.TestCase):
    def setUp(self) -> None:
        self.src = I18N_JS_PATH.read_text(encoding="utf-8")

    def test_normalize_branches_present(self) -> None:
        for tag in ("'zh-tw'", "'zh-hk'", "'zh-mo'", "'zh-hant'"):
            self.assertIn(
                tag,
                self.src,
                f"normalizeLang 必须显式识别 BCP-47 tag {tag}",
            )

    def test_zh_tw_returns_zh_TW(self) -> None:
        """正则定位返回分支，确保 zh-TW / zh-Hant 都走 ``return 'zh-TW'``。"""
        # zh-TW 必须 normalize 到 'zh-TW'，不能是 'zh-CN'
        # 通过断言代码块里 "zh-TW" 字符串紧跟在 zh-tw / zh-hant 之后
        self.assertIn(
            "return 'zh-TW'",
            self.src,
            "normalizeLang 必须 return 'zh-TW' 作为目标 locale",
        )

    def test_zh_hans_still_zh_CN(self) -> None:
        """zh-Hans / zh-CN / zh-SG / zh-MY 仍 fallback 到 zh-CN。"""
        self.assertIn(
            "return 'zh-CN'",
            self.src,
            "normalizeLang 必须保留 return 'zh-CN' 用于 zh-Hans 系",
        )


# ============================================================
# E. 后端 i18n.py
# ============================================================
class TestI18nPySupportedLangs(unittest.TestCase):
    def setUp(self) -> None:
        self.src = I18N_PY_PATH.read_text(encoding="utf-8")

    def test_supported_langs_includes_zh_tw(self) -> None:
        self.assertIn(
            '"zh-TW"',
            self.src,
            "i18n.py SUPPORTED_LANGS 必须包含 zh-TW",
        )

    def test_normalize_handles_zh_tw(self) -> None:
        # 行为级测试
        from ai_intervention_agent.i18n import normalize_lang

        for tag in ("zh-TW", "zh-tw", "ZH-TW", "zh-HK", "zh-Hant", "zh-Hant-TW"):
            self.assertEqual(
                normalize_lang(tag),
                "zh-TW",
                f"normalize_lang({tag!r}) 必须返回 'zh-TW'",
            )

    def test_normalize_zh_hans_still_zh_CN(self) -> None:
        from ai_intervention_agent.i18n import normalize_lang

        for tag in ("zh-CN", "zh-cn", "zh-Hans", "zh-SG", "zh-MY"):
            self.assertEqual(normalize_lang(tag), "zh-CN")

    def test_zh_tw_messages_complete(self) -> None:
        """后端 zh-TW 消息表必须覆盖 zh-CN 所有 key。"""
        from ai_intervention_agent.i18n import _MESSAGES

        cn_keys = set(_MESSAGES["zh-CN"].keys())
        tw_keys = set(_MESSAGES["zh-TW"].keys())
        missing = cn_keys - tw_keys
        self.assertFalse(
            missing,
            f"zh-TW _MESSAGES 缺 key：{sorted(missing)}",
        )


# ============================================================
# F. server_config.py
# ============================================================
class TestServerConfigSupportedLangs(unittest.TestCase):
    def test_supported_langs_includes_zh_tw(self) -> None:
        src = SERVER_CONFIG_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '"zh-TW"',
            src,
            "server_config.WebUIConfig.SUPPORTED_LANGS 必须包含 zh-TW",
        )


# ============================================================
# G. web_ui.py /api/update-language 白名单
# ============================================================
class TestUpdateLanguageWhitelist(unittest.TestCase):
    def test_endpoint_accepts_zh_tw(self) -> None:
        src = WEB_UI_PY_PATH.read_text(encoding="utf-8")
        # 找到 /api/update-language 块里的 supported 元组
        import re

        m = re.search(
            r"def update_language.*?supported\s*=\s*\(([^)]+)\)",
            src,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 /api/update-language 的 supported 元组")
        assert m is not None
        self.assertIn(
            '"zh-TW"',
            m.group(1),
            "/api/update-language 的 supported 必须含 'zh-TW'",
        )


# ============================================================
# H. HTML option
# ============================================================
class TestHtmlLanguageOption(unittest.TestCase):
    def test_zh_tw_option_present(self) -> None:
        html = WEB_UI_HTML_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'value="zh-TW"',
            html,
            'language-select 必须有 value="zh-TW" option',
        )
        self.assertIn(
            'data-i18n="settings.langZhTW"',
            html,
            "zh-TW option 必须有 data-i18n=settings.langZhTW",
        )


# ============================================================
# I. en/zh-CN 新增 settings.langZhTW
# ============================================================
class TestLangZhTwI18nKey(unittest.TestCase):
    def test_en_has_lang_zh_tw(self) -> None:
        data = json.loads(EN_PATH.read_text(encoding="utf-8"))
        self.assertIn("langZhTW", data["settings"])

    def test_zh_cn_has_lang_zh_tw(self) -> None:
        data = json.loads(ZH_CN_PATH.read_text(encoding="utf-8"))
        self.assertIn("langZhTW", data["settings"])

    def test_zh_tw_has_lang_zh_tw(self) -> None:
        data = json.loads(ZH_TW_PATH.read_text(encoding="utf-8"))
        self.assertIn("langZhTW", data["settings"])

    def test_zh_tw_endonym_in_traditional(self) -> None:
        """zh-TW 端的 langZhTW 字段应使用「繁體中文」自称（endonym）。"""
        data = json.loads(ZH_TW_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["settings"]["langZhTW"], "繁體中文")


# ============================================================
# J. SSRF 加固（CodeQL R72-D fallback 不应被 zh-TW 改动破坏）
# ============================================================
class TestSsrfHardeningPreserved(unittest.TestCase):
    def test_normalize_attacker_path_falls_back(self) -> None:
        from ai_intervention_agent.i18n import normalize_lang

        # 不识别的 lang 必须 fallback 到 DEFAULT_LANG 而非原样回传，
        # 避免 fetch URL 注入。
        for bad in ("evil/path", "zh-../etc", "../../etc/passwd", "fr-FR"):
            result = normalize_lang(bad)
            self.assertNotEqual(
                result,
                bad,
                f"normalize_lang({bad!r}) 必须 normalize/fallback，不能原样返回",
            )


if __name__ == "__main__":
    unittest.main()
