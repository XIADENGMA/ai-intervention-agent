"""R131d · Quick Phrases Alt+1..9 键盘快捷键契约。

背景
----
R130/R131/R131b 把面板做完整后，熟手用户的体感诉求依次是「常用条目
优先排序」（R131c 已闭环）→「键盘快速插入」。竞品 mcp-feedback-
enhanced / cunzhi 的 Prompt 面板都支持 1..9 数字键插入。

为何选 ``Alt+1..9`` 而不是 ``Ctrl/Cmd+1..9``：

- ``Ctrl+1..9`` / ``Cmd+1..9`` 在主流浏览器是「切换到第 N 个 tab」
  的硬编码快捷键，``preventDefault`` 在多数实现里**无法阻止**；
- Slack / Discord / Notion 都用 Alt+N（macOS 上 Option+N）解决这个
  冲突；
- ``KeyboardShortcuts`` 模块的 ``MODIFIER_KEYS`` 里 ``alt`` / ``option``
  都映射到 ``altKey``，单一 ``"alt+N"`` 字符串在 macOS / Windows /
  Linux 通用，不需要 platform sniffing。

R131d 在 ``init()`` 末尾调 ``setupKeyboardShortcuts()`` 注册 9 个
``alt+1..alt+9`` 快捷键，``allowInInputs: true`` 让 Alt+N 即使在
``#feedback-text`` textarea 焦点时也能触发；form 打开时（用户在编辑
phrase）禁用快捷键避免与 Esc/Enter 冲突。

UI 提示：``renderList`` 给前 9 条 chip 写 ``data-shortcut-index``
属性 + ``title="Click or press Alt+N to insert"``（i18n 化）。

测试覆盖五个层面（共 14 cases / 5 invariant classes）：

1.  **JS API 扩展** — ``setupKeyboardShortcuts`` / ``_activateShortcut``
    函数存在，公开 API 暴露这两个名字。
2.  **快捷键注册路径** — 函数体内含 ``KeyboardShortcuts.register`` 调
    用，prefix ``alt+`` + indices 1..9，``allowInInputs: true`` +
    ``preventDefault: true`` options。
3.  **fallback keydown 路径** — 当 ``KeyboardShortcuts`` 不可用时
    自挂 ``document.addEventListener("keydown", ...)``，含
    ``e.altKey`` 检测且排除 ``ctrlKey`` / ``metaKey`` 组合。
4.  **chip UI 提示** — ``renderList`` 给前 9 条 chip 写
    ``data-shortcut-index`` + 走 ``quickPhrases.chipShortcutTitle``
    i18n key。
5.  **i18n 完备性 + form 模式互斥** — 3 份 locale 含
    ``chipShortcutTitle``；``_activateShortcut`` 函数体内含 form
    open 检测分支（``.quick-phrases-form`` querySelector）。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
JS_QP = SRC / "static" / "js" / "quick_phrases.js"
LOCALE_EN = SRC / "static" / "locales" / "en.json"
LOCALE_ZH = SRC / "static" / "locales" / "zh-CN.json"
LOCALE_PSEUDO = SRC / "static" / "locales" / "_pseudo" / "pseudo.json"


def _read(p: Path) -> str:
    assert p.is_file(), f"缺失文件: {p}"
    return p.read_text(encoding="utf-8")


def _read_locale(p: Path) -> dict:
    return json.loads(_read(p))


def _extract_function_body(src: str, signature_regex: str) -> str:
    """与 R131b/R131c/R133 测试同款 brace counter（嵌套 {} 安全）。"""
    m = re.search(signature_regex, src)
    if not m:
        raise AssertionError(f"找不到签名: {signature_regex}")
    open_brace = src.find("{", m.end())
    if open_brace == -1:
        raise AssertionError(f"签名 {signature_regex} 之后找不到 ``{{``")
    depth = 0
    in_str: str | None = None
    in_block_comment = False
    in_line_comment = False
    i = open_brace
    while i < len(src):
        ch = src[i]
        nxt = src[i + 1] if i + 1 < len(src) else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 1
        elif in_str is not None:
            if ch == "\\":
                i += 1
            elif ch == in_str:
                in_str = None
        else:
            if ch == "/" and nxt == "/":
                in_line_comment = True
                i += 1
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                i += 1
            elif ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return src[open_brace + 1 : i]
        i += 1
    raise AssertionError(f"签名 {signature_regex} 函数体未闭合")


# ---------------------------------------------------------------------------
# 1. JS API 扩展
# ---------------------------------------------------------------------------


class TestKeyboardShortcutApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_setup_keyboard_shortcuts_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+setupKeyboardShortcuts\s*\(\s*\)",
            "必须存在 setupKeyboardShortcuts() 函数",
        )

    def test_activate_shortcut_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+_activateShortcut\s*\(\s*index\s*\)",
            "必须存在 _activateShortcut(index) 函数",
        )

    def test_public_api_exposes_shortcut_handles(self) -> None:
        for sym in ("setupKeyboardShortcuts", "_activateShortcut"):
            self.assertRegex(
                self.js,
                rf"{sym}\s*:\s*{sym}",
                f"AIIA_QUICK_PHRASES 必须暴露 {sym}",
            )


# ---------------------------------------------------------------------------
# 2. 快捷键注册路径
# ---------------------------------------------------------------------------


class TestRegisterPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_uses_keyboard_shortcuts_register(self) -> None:
        body = _extract_function_body(
            self.js, r"function\s+setupKeyboardShortcuts\s*\(\s*\)"
        )
        self.assertIn(
            "window.KeyboardShortcuts.register",
            body,
            "setupKeyboardShortcuts 必须用 window.KeyboardShortcuts.register API（避免重复造轮子）",
        )

    def test_register_path_passes_required_options(self) -> None:
        body = _extract_function_body(
            self.js, r"function\s+setupKeyboardShortcuts\s*\(\s*\)"
        )
        self.assertIn(
            "preventDefault: true",
            body,
            "register 必须传 preventDefault: true（防 Firefox/Edge 触发 alt 访问键）",
        )
        self.assertIn(
            "allowInInputs: true",
            body,
            "register 必须传 allowInInputs: true（textarea 焦点时也要触发）",
        )

    def test_shortcut_indices_one_through_nine(self) -> None:
        # SHORTCUT_INDICES 必须是 1..9（与 Slack/Discord 模式一致）
        m = re.search(
            r"SHORTCUT_INDICES\s*=\s*\[([^\]]+)\]",
            self.js,
        )
        assert m is not None, "找不到 SHORTCUT_INDICES 常量定义"
        nums = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
        self.assertEqual(
            nums,
            list(range(1, 10)),
            "SHORTCUT_INDICES 必须严格是 [1, 2, ..., 9]",
        )

    def test_shortcut_prefix_is_alt(self) -> None:
        self.assertRegex(
            self.js,
            r'SHORTCUT_PREFIX\s*=\s*"alt\+"',
            "SHORTCUT_PREFIX 必须是 'alt+'（避开 Ctrl/Cmd+N 切 tab 冲突）",
        )


# ---------------------------------------------------------------------------
# 3. fallback keydown 路径
# ---------------------------------------------------------------------------


class TestFallbackPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)
        cls.body = _extract_function_body(
            cls.js, r"function\s+setupKeyboardShortcuts\s*\(\s*\)"
        )

    def test_fallback_attaches_keydown_listener(self) -> None:
        self.assertIn(
            'document.addEventListener("keydown"',
            self.body,
            "fallback 路径必须自挂 document keydown listener",
        )

    def test_fallback_checks_alt_and_excludes_ctrl_meta(self) -> None:
        self.assertIn(
            "e.altKey",
            self.body,
            "fallback 必须检测 e.altKey",
        )
        self.assertIn(
            "e.ctrlKey",
            self.body,
            "fallback 必须显式排除 e.ctrlKey 组合（避免误触 Ctrl+Alt+N）",
        )
        self.assertIn(
            "e.metaKey",
            self.body,
            "fallback 必须显式排除 e.metaKey 组合（避免误触 Cmd+Alt+N）",
        )


# ---------------------------------------------------------------------------
# 4. chip UI 提示 + form 模式互斥
# ---------------------------------------------------------------------------


class TestChipShortcutHint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_render_list_writes_data_shortcut_index_for_first_n(self) -> None:
        body = _extract_function_body(self.js, r"function\s+renderList\s*\(\s*\)")
        self.assertIn(
            "data-shortcut-index",
            body,
            "renderList 必须给前 9 条 chip 写 data-shortcut-index 属性（R131d UI 提示）",
        )
        self.assertIn(
            "quickPhrases.chipShortcutTitle",
            body,
            "renderList 必须用 quickPhrases.chipShortcutTitle i18n key",
        )

    def test_render_list_uses_idx_lt_shortcut_count_guard(self) -> None:
        # 前 9 条 chip 才挂快捷键提示，第 10+ 条仍走 chipTitle
        body = _extract_function_body(self.js, r"function\s+renderList\s*\(\s*\)")
        self.assertRegex(
            body,
            r"idx\s*<\s*SHORTCUT_INDICES\.length",
            "renderList 必须用 idx < SHORTCUT_INDICES.length 限定前 9 条才标 shortcut hint",
        )

    def test_activate_shortcut_blocks_when_form_open(self) -> None:
        # form 打开时禁用快捷键避免与编辑模式 Esc/Enter 冲突
        body = _extract_function_body(
            self.js, r"function\s+_activateShortcut\s*\([^)]*\)"
        )
        self.assertIn(
            ".quick-phrases-form",
            body,
            "_activateShortcut 必须检测 .quick-phrases-form 是否打开（form 模式互斥）",
        )

    def test_activate_shortcut_uses_sorted_phrases(self) -> None:
        body = _extract_function_body(
            self.js, r"function\s+_activateShortcut\s*\([^)]*\)"
        )
        self.assertIn(
            "_sortPhrasesByUsage",
            body,
            "_activateShortcut 必须用 _sortPhrasesByUsage（与 R131c 的 chip 排序一致）",
        )

    def test_activate_shortcut_records_usage(self) -> None:
        body = _extract_function_body(
            self.js, r"function\s+_activateShortcut\s*\([^)]*\)"
        )
        self.assertIn(
            "insertTextIntoFeedback",
            body,
            "_activateShortcut 必须调用 insertTextIntoFeedback（与 chip click 同款）",
        )
        self.assertIn(
            "recordPhraseUsage",
            body,
            "_activateShortcut 必须调用 recordPhraseUsage（让快捷键插入也参与频率排序）",
        )


# ---------------------------------------------------------------------------
# 5. i18n 完备性
# ---------------------------------------------------------------------------


class TestShortcutI18n(unittest.TestCase):
    def test_zh_cn_has_chip_shortcut_title(self) -> None:
        data = _read_locale(LOCALE_ZH)
        qp = data.get("quickPhrases", {})
        self.assertIn(
            "chipShortcutTitle",
            qp,
            "zh-CN.json 必须含 quickPhrases.chipShortcutTitle",
        )
        self.assertIn(
            "{{index}}",
            qp["chipShortcutTitle"],
            "chipShortcutTitle 必须含 {{index}} 占位符",
        )

    def test_en_has_chip_shortcut_title(self) -> None:
        data = _read_locale(LOCALE_EN)
        qp = data.get("quickPhrases", {})
        self.assertIn(
            "chipShortcutTitle",
            qp,
            "en.json 必须含 quickPhrases.chipShortcutTitle",
        )
        self.assertIn(
            "{{index}}",
            qp["chipShortcutTitle"],
            "chipShortcutTitle 必须含 {{index}} 占位符",
        )

    def test_pseudo_has_chip_shortcut_title(self) -> None:
        data = _read_locale(LOCALE_PSEUDO)
        qp = data.get("quickPhrases", {})
        self.assertIn(
            "chipShortcutTitle",
            qp,
            "_pseudo/pseudo.json 必须含 quickPhrases.chipShortcutTitle",
        )


if __name__ == "__main__":
    unittest.main()
