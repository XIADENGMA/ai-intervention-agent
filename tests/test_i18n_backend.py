"""P9·L7 — backend（Python）i18n 加固。

``i18n.py`` 是后端对位于 ``static/js/i18n.js`` 的一半——Flask/FastMCP
层回传给 Web UI 的错误 / 通知文案。早期没测试覆盖，以下坑全是「沉默
降级」：
  * ``en`` 加了 key 但 ``zh-CN`` 没补 → 用户明明选中文仍出英文；
  * 单侧 rename → 一侧 dead、另一侧 missing；
  * ``{param}`` 占位符只在一侧 → call site 静默丢上下文；
  * ``get_locale_message("does.not.exist")`` 从 route 走出来 → 只有打开
    DevTools 才能发现。

本文件锁合约，保整条链一致。每个测试的动机见各自 docstring。
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

i18n = importlib.import_module("ai_intervention_agent.i18n")

ROOT = Path(__file__).resolve().parent.parent
PKG_ROOT = ROOT / "src" / "ai_intervention_agent"
SERVER_PY_GLOB = [
    PKG_ROOT / "web_ui.py",
    PKG_ROOT / "web_ui_routes" / "feedback.py",
    PKG_ROOT / "web_ui_routes" / "notification.py",
    PKG_ROOT / "web_ui_routes" / "task.py",
]

# Matches ``msg("x.y")`` and ``get_locale_message("x.y")`` across the
# codebase. Use a conservative non-greedy regex so we don't match
# across newlines or interpolate variable keys.
_CALL_RE = re.compile(
    r"""(?x)
    \b(?:get_locale_message|msg)\s*\(
        \s*
        (['\"])([a-zA-Z][a-zA-Z0-9_.-]*)\1
    """,
)
# ``{param}`` placeholder extractor (Python ``str.format`` style —
# distinct from the frontend's ``{{param}}`` Mustache syntax).
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _collect_backend_used_keys() -> set[str]:
    """Grep every server-side module for ``get_locale_message(...)``
    and ``msg(...)`` calls with a literal string first argument. We
    use a regex rather than AST to stay robust against f-strings and
    multi-line call formatting that can confuse ``ast.walk``."""
    used: set[str] = set()
    for path in SERVER_PY_GLOB:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for _, key in _CALL_RE.findall(text):
            used.add(key)
    return used


def _placeholders(s: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(s))


class TestBackendLocaleParity:
    """Every key on one side must exist on the other."""

    def test_zh_cn_matches_en_key_set(self) -> None:
        # Rationale: if ``en`` ships a key the user's active locale
        # can't resolve, ``get_locale_message`` silently falls back to
        # English. That breaks the i18n contract for zh-CN users.
        en = set(i18n._MESSAGES["en"].keys())
        zh = set(i18n._MESSAGES["zh-CN"].keys())
        missing_in_zh = en - zh
        missing_in_en = zh - en
        assert not missing_in_zh, (
            f"zh-CN missing keys that exist in en: {sorted(missing_in_zh)}"
        )
        assert not missing_in_en, (
            f"en missing keys that exist in zh-CN: {sorted(missing_in_en)}"
        )

    def test_placeholder_parity(self) -> None:
        # Rationale: a call site like
        # ``msg("x.y", detail=err)`` depends on ``{detail}`` being in
        # BOTH locales. If one side drops the placeholder, the context
        # vanishes and users get e.g. "发送失败" without the ``err``
        # payload they'd see in English.
        for key, en_val in i18n._MESSAGES["en"].items():
            zh_val = i18n._MESSAGES["zh-CN"][key]
            en_ph = _placeholders(en_val)
            zh_ph = _placeholders(zh_val)
            assert en_ph == zh_ph, f"{key}: placeholder mismatch en={en_ph} zh={zh_ph}"


class TestBackendKeyCoverage:
    """Every call site must reach a real key; every defined key
    must be reached from somewhere."""

    def test_no_missing_keys_in_call_sites(self) -> None:
        used = _collect_backend_used_keys()
        defined = set(i18n._MESSAGES["en"].keys())
        missing = used - defined
        assert not missing, (
            f"{len(missing)} key(s) referenced in code but not declared "
            f"in i18n._MESSAGES: {sorted(missing)}"
        )

    def test_no_orphan_keys(self) -> None:
        # Rationale: dead keys signal either a missed deletion (noise
        # for translators) or a typo at the call site (user-visible
        # regression hiding in plain sight). We keep this strict —
        # unlike the JS side which is still ramping — because the
        # backend dict is tiny (<50 entries).
        used = _collect_backend_used_keys()
        defined = set(i18n._MESSAGES["en"].keys())
        orphan = defined - used
        assert not orphan, (
            f"{len(orphan)} orphan key(s) defined in i18n._MESSAGES but "
            f"never referenced: {sorted(orphan)}"
        )


class TestBackendLookup:
    """End-to-end sanity over the public API."""

    def test_missing_key_returns_key_like_js(self) -> None:
        # Behavior parity with static/js/i18n.js::t() — missing keys
        # echo back rather than crashing.
        out = i18n.get_locale_message("totally.not.real", lang="en")
        assert out == "totally.not.real"

    def test_en_fallback_for_zh_missing(self) -> None:
        # Simulate a half-translated key by temporarily poking the
        # module dict. We restore in teardown to keep other tests
        # isolated.
        key = "_test_only.fallback_probe"
        i18n._MESSAGES["en"][key] = "hello en"
        try:
            # No zh-CN entry → must fall through to en.
            out = i18n.get_locale_message(key, lang="zh-CN")
            assert out == "hello en"
        finally:
            del i18n._MESSAGES["en"][key]

    def test_placeholder_substitution(self) -> None:
        # Rationale: guard against a future refactor that swaps
        # ``.format`` for ``.format_map`` or ICU — ``{detail}`` must
        # continue to interpolate.
        out = i18n.get_locale_message(
            "notify.sendFailedDetail", lang="en", detail="timeout"
        )
        assert "timeout" in out

    def test_normalize_lang_collapses_variants(self) -> None:
        assert i18n.normalize_lang("zh-HK") == "zh-CN"
        assert i18n.normalize_lang("en-GB") == "en"
        assert i18n.normalize_lang("fr") == i18n.DEFAULT_LANG
        assert i18n.normalize_lang("") == i18n.DEFAULT_LANG


class TestBackendDetectRequestLang:
    """R78b：``detect_request_lang`` 三条 fallback 路径覆盖。

    R76 之前未覆盖 Accept-Language 头解析（L100-105）+ config_manager
    fallback（L112-114），导致 i18n.py 整体覆盖率只有 75.81%。本类把
    三条路径 + 模板格式化失败兜底一并锁住。
    """

    def test_detect_lang_from_accept_language_header_zh(self) -> None:
        """Accept-Language: zh-* → normalize 到 'zh-CN'。"""
        from flask import Flask

        app = Flask(__name__)
        with app.test_request_context(headers={"Accept-Language": "zh-CN,en;q=0.7"}):
            assert i18n.detect_request_lang() == "zh-CN"

    def test_detect_lang_from_accept_language_header_en(self) -> None:
        """Accept-Language: en-US → normalize 到 'en'。"""
        from flask import Flask

        app = Flask(__name__)
        with app.test_request_context(headers={"Accept-Language": "en-US,en;q=0.5"}):
            assert i18n.detect_request_lang() == "en"

    def test_detect_lang_unknown_accept_language_normalizes_to_default(self) -> None:
        """Accept-Language: fr-FR → ``normalize_lang`` 把它映射到 DEFAULT_LANG (en)。

        说明：``detect_request_lang`` 不会因为 fr-FR 「不在支持集」就跳过
        header 路径——``normalize_lang`` 设计上永远返回支持集中的值（zh/en/
        DEFAULT_LANG），fr-FR 经 normalize 后是 'en'，header 路径直接命中
        返回，不查 config。本测试锁住这个事实，防止未来引入 ``ja`` 等新
        语言后 ``normalize_lang`` 改成可能返回非支持值时出现意外的 config
        穿透行为。
        """
        from unittest.mock import MagicMock, patch

        from flask import Flask

        app = Flask(__name__)

        fake_config = MagicMock()
        fake_config.get_section.return_value = {"language": "zh-CN"}

        with (
            app.test_request_context(headers={"Accept-Language": "fr-FR"}),
            patch(
                "ai_intervention_agent.config_manager.get_config",
                return_value=fake_config,
            ) as mock_get_config,
        ):
            assert i18n.detect_request_lang() == "en"
            # 关键断言：config 路径不应被触达——header 路径已经吃掉请求
            mock_get_config.assert_not_called()

    def test_detect_lang_no_request_context_uses_config(self) -> None:
        """没有 Flask request context（``RuntimeError``）→ 直接走 config 路径。"""
        from unittest.mock import MagicMock, patch

        fake_config = MagicMock()
        fake_config.get_section.return_value = {"language": "zh-CN"}

        with patch(
            "ai_intervention_agent.config_manager.get_config",
            return_value=fake_config,
        ):
            assert i18n.detect_request_lang() == "zh-CN"

    def test_detect_lang_config_auto_falls_through_to_default(self) -> None:
        """config.web_ui.language == 'auto' → 跳过 config 路径，返回 DEFAULT_LANG。"""
        from unittest.mock import MagicMock, patch

        fake_config = MagicMock()
        fake_config.get_section.return_value = {"language": "auto"}

        with patch(
            "ai_intervention_agent.config_manager.get_config",
            return_value=fake_config,
        ):
            assert i18n.detect_request_lang() == i18n.DEFAULT_LANG

    def test_detect_lang_returns_default_when_all_paths_fail(self) -> None:
        """所有 fallback 都挂掉（Flask 没初始化 + config_manager 抛异常） → DEFAULT_LANG。"""
        from unittest.mock import patch

        with patch(
            "ai_intervention_agent.config_manager.get_config",
            side_effect=RuntimeError("config not initialized"),
        ):
            assert i18n.detect_request_lang() == i18n.DEFAULT_LANG

    def test_get_locale_message_auto_detects_lang_when_none(self) -> None:
        """``lang=None`` → 自动调用 ``detect_request_lang()``。

        覆盖 ``get_locale_message`` 的 L131-132 分支：caller 不显式传 lang 时
        应当走自动检测路径，返回应是检测出的语言对应的本地化值。
        """
        from unittest.mock import patch

        with patch(
            "ai_intervention_agent.i18n.detect_request_lang", return_value="zh-CN"
        ):
            out = i18n.get_locale_message("feedback.submitted")
        assert out == "反馈已提交"

    def test_format_error_falls_back_to_unformatted_template(self) -> None:
        """``str.format`` 抛 ``KeyError`` 时静默返回原模板（不让上层 caller 崩）。

        触发条件：caller 传了 kwargs（进入 ``if kwargs`` 分支），但模板里的
        ``{detail}`` 占位符在 kwargs 里没有对应 key，``str.format`` 因此抛
        ``KeyError: 'detail'``。规约：catch + 返回原模板字符串。
        """
        out = i18n.get_locale_message(
            "notify.sendFailedDetail",
            lang="en",
            wrong_kwarg_name="this kwarg has nothing to do with {detail}",
        )
        assert "{detail}" in out, (
            "模板里的 {detail} 未匹配 kwargs 时应原样返回，不抛 KeyError"
        )


class TestBackendStaticStructure:
    """Guard the shape of ``i18n.py`` itself so a future refactor
    can't silently drop ``_MESSAGES`` or change the public surface."""

    def test_supported_langs_includes_default(self) -> None:
        assert i18n.DEFAULT_LANG in i18n.SUPPORTED_LANGS

    def test_msg_alias_matches_get_locale_message(self) -> None:
        # ``msg`` is documented as an alias; treating it as such in
        # call sites MUST continue to work.
        assert i18n.msg is i18n.get_locale_message

    def test_i18n_module_has_no_syntax_drift(self) -> None:
        # A small AST probe to catch accidental top-level statements
        # (e.g. a stray ``print(...)`` landing in the dict block)
        # without running the module.
        src = (ROOT / "src" / "ai_intervention_agent" / "i18n.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        offenders = [
            ast.dump(node)
            for node in tree.body
            if isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant)
        ]
        assert not offenders, (
            f"Unexpected top-level expression(s) in i18n.py: {offenders}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
