"""R360 · _classifyFetchError / _classifyHttpResponse i18n key forward
resolution invariant (cycle-41 #B1, **cross-language 4th 应用 — 工业化
深化期**)。

cycle-28 / cycle-30 引入 ``_classifyFetchError`` 与 ``_classifyHttpResponse``
作为 web 端唯一的 fetch / HTTP error 分类入口, 返回 ``status.xxx`` i18n
key。本 invariant 锁住:

1. 这两个 classifier 函数实际**返回**的 i18n key 集合 (sentinel + 完整 set);
2. 集合内每个 key 必须在 ``en.json`` / ``zh-CN.json`` / ``zh-TW.json``
   三大 locale 都能解析 (否则用户会看到字面 ``status.networkError`` 而非
   翻译);
3. 关键 sentinel key (``status.networkError`` / ``status.requestTimeout``
   / ``status.unauthorized``) 不能被重构静默删除 (是 user-visible 错误
   反馈契约的一部分)。

R360 cross-language lineage
---------------------------

- R213 (cycle-19 #?): cross-language 1st app — JSON field map
- R297 (cycle-29 #?): cross-language 2nd app — Python TypedDict ↔ JS
  event payload field schema 反向校验
- R302 (cycle-30 #?): cross-language 3rd app — REST API response schema
  cross-language
- **R360 (本 commit, cycle-41)**: **4th app 工业化深化期** — JS
  classifier 输出 i18n key ↔ locales JSON 反向解析

与 R350 (i18n consistency: zh-CN vs en 翻译完整度) 互补 — R350 锁
**翻译质量**, R360 锁 **JS 引用 vs locales 完整性** (orphan key
detection)。

methodology
-----------

3 层 invariant, AST 风格的正则解析 (JS 不在 Python AST 范围内, 用 regex
扫 classifier 函数体内的 ``return "status.xxx"`` 字面字符串)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static"
APP_JS = STATIC_DIR / "js" / "app.js"
LOCALES_DIR = STATIC_DIR / "locales"

# Sentinel keys — 必须始终被 classifier 返回, 否则错误 UX 退化
SENTINEL_KEYS = frozenset(
    {
        "status.networkError",
        "status.requestTimeout",
        "status.unauthorized",
    }
)

# 应该被 audit 的 locale 文件 (排除 _pseudo 内部 pseudo-localization)
AUDIT_LOCALES = ("en.json", "zh-CN.json", "zh-TW.json")


def _extract_classifier_returned_keys() -> set[str]:
    """从 app.js 解析两个 classifier 函数内 ``return "status.xxx"`` 字面值。"""
    text = APP_JS.read_text(encoding="utf-8")
    keys: set[str] = set()
    for fn_name in ("_classifyFetchError", "_classifyHttpResponse"):
        # 找到函数体 (function name(...) { ... })
        pattern = re.compile(
            rf"function {re.escape(fn_name)}\([^)]*\)\s*\{{(.*?)^\}}",
            re.DOTALL | re.MULTILINE,
        )
        match = pattern.search(text)
        assert match, f"R360: cannot locate function {fn_name} in app.js"
        body = match.group(1)
        body_no_comments = re.sub(r"//[^\n]*", "", body)
        # 匹配 return "status.something" 或 return 'status.something'
        for m in re.finditer(
            r"""return\s+["'](status\.[a-zA-Z]+)["']""", body_no_comments
        ):
            keys.add(m.group(1))
    return keys


def _flatten_keys(prefix: str, obj: dict) -> set[str]:
    out: set[str] = set()
    for k, v in obj.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out |= _flatten_keys(full, v)
        else:
            out.add(full)
    return out


def _load_locale_keys(locale_name: str) -> set[str]:
    p = LOCALES_DIR / locale_name
    data = json.loads(p.read_text(encoding="utf-8"))
    return _flatten_keys("", data)


class TestLayer1ClassifierKeysExtractable:
    """Layer 1: anchor — 至少能从 classifier 提取出 5 个 status.* key。"""

    def test_at_least_5_keys_extracted(self):
        keys = _extract_classifier_returned_keys()
        assert len(keys) >= 5, (
            f"R360-L1: only {len(keys)} classifier-returned status.* "
            f"keys extracted from app.js — expected >= 5. Regex parser "
            f"likely broken or classifier functions removed."
        )


class TestLayer2ForwardI18nResolution:
    """Layer 2: classifier 返回的每个 key 必须在 3 大 locale 都能解析。"""

    def test_every_classifier_key_resolves_in_all_locales(self, subtests):
        keys = _extract_classifier_returned_keys()
        missing: list[str] = []
        for locale in AUDIT_LOCALES:
            locale_keys = _load_locale_keys(locale)
            for key in sorted(keys):
                with subtests.test(locale=locale, key=key):
                    if key not in locale_keys:
                        missing.append(f"  {locale}: {key}")
        if missing:
            raise AssertionError(
                f"R360-L2: {len(missing)} classifier-returned i18n "
                f"key(s) cannot be resolved in locale JSON:\n"
                + "\n".join(missing)
                + "\nFix: add the missing keys to the locale file or "
                "remove them from the classifier (orphan reference)."
            )


class TestLayer3SentinelKeysMustExist:
    """Layer 3: 关键 sentinel key 必须在 classifier 输出集内。"""

    def test_all_sentinel_keys_returned(self):
        keys = _extract_classifier_returned_keys()
        missing_sentinel = SENTINEL_KEYS - keys
        assert not missing_sentinel, (
            f"R360-L3: sentinel keys missing from classifier output: "
            f"{sorted(missing_sentinel)}. These keys define core error "
            f"UX contracts and must not be removed during refactor."
        )


class TestR360LineageMarker:
    def test_this_file_contains_r360_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R360" in text

    def test_this_file_references_r302_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R302" in text, "R360 must cite R302 (3rd cross-lang app)"

    def test_this_file_marks_industrialization(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "4th 应用" in text or "工业化深化期" in text, (
            "R360: must explicitly mark 4th app industrialization stage"
        )
