"""R131 · Quick Phrases 编辑模式 + 光标位置插入契约。

背景
----
R130 v1 的 Quick Phrases 面板把 chip 的内容**追加到 textarea 末尾**——
对"组合多段常用语"友好，但对"在段落中间补一句常用语"不友好（用户
得手动剪贴）；同时 chip 不可编辑——拼错了只能删了重建。Code Review
#2 把这两个 UX 缺口列为 P1 follow-up。R131 补齐：

1. **chip 上的 ✎ 编辑按钮** — 进入内嵌编辑模式（复用 R130 的 form
   渲染，dataset 标 `qp-mode=edit` + `qp-edit-id=<id>`）。保存时调用
   ``editPhrase(id, label, text)`` 替换同 id 条目的 label / text，
   保留 ``id`` 与 ``created_at`` 不变。
2. **光标位置插入** — chip 单击不再无脑追加到末尾，而是把内容插到
   ``selectionStart..selectionEnd`` 区间，覆盖选中文本（如有）；插入
   完成后光标停在新插入文本之后，方便继续输入。老引擎不支持
   ``selectionStart`` 时回退到 R130 v1 的"末尾追加"行为。

测试覆盖五个层面（共 16 cases / 5 invariant classes）：

1.  **JS API 扩展** — ``editPhrase`` / ``openEditForm`` 函数存在，
    ``window.AIIA_QUICK_PHRASES`` 暴露这两个名字。
2.  **chip 编辑按钮** — ``renderList`` 创建的每个 chip wrapper 都含
    ``.quick-phrase-chip-edit`` 元素 + i18n aria-label + ✎ 字符。
3.  **form 模式标识** — ``_openForm`` 给 form 节点写
    ``dataset.qpMode = "add" | "edit"``，让重复触发能正确识别复用 vs
    重建；``edit`` 模式还要写 ``dataset.qpEditId`` 锚定哪条 phrase。
4.  **光标位置插入语义** — ``insertTextIntoFeedback`` 必须读
    ``selectionStart`` / ``selectionEnd`` 而不是无脑 append；老引擎
    fallback 路径仍存在。
5.  **i18n 完备性** — 三份 locale（zh-CN / en / _pseudo）都包含
    新增的 ``editBtnAriaLabel`` 键。
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
CSS = SRC / "static" / "css" / "main.css"


def _read(p: Path) -> str:
    assert p.is_file(), f"缺失文件: {p}"
    return p.read_text(encoding="utf-8")


def _read_locale(p: Path) -> dict:
    return json.loads(_read(p))


# ---------------------------------------------------------------------------
# 1. JS API 扩展
# ---------------------------------------------------------------------------


class TestQuickPhrasesEditApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_edit_phrase_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+editPhrase\s*\(\s*id\s*,\s*label\s*,\s*text\s*\)",
            "必须存在 editPhrase(id, label, text) 函数签名",
        )

    def test_open_edit_form_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+openEditForm\s*\(\s*id\s*\)",
            "必须存在 openEditForm(id) 函数签名",
        )

    def test_public_api_exposes_edit_handles(self) -> None:
        # 公开 API 必须能让测试 / 调试 / 跨模块代码访问 editPhrase 与 openEditForm
        self.assertRegex(
            self.js,
            r"editPhrase\s*:\s*editPhrase",
            "AIIA_QUICK_PHRASES 必须暴露 editPhrase",
        )
        self.assertRegex(
            self.js,
            r"openEditForm\s*:\s*openEditForm",
            "AIIA_QUICK_PHRASES 必须暴露 openEditForm",
        )

    def test_edit_phrase_preserves_id_and_created_at(self) -> None:
        # editPhrase 实现必须仅替换 label / text，不动 id / created_at
        # 即不存在 ``id: generateId()`` 或 ``created_at: Date.now()`` 这种
        # 重置语义的代码片段在 editPhrase 函数体内部
        match = re.search(
            r"function\s+editPhrase[\s\S]*?\n\s{0,4}\}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        body = match.group(0)
        self.assertNotIn(
            "generateId()",
            body,
            "editPhrase 不能调 generateId（id 必须保留）",
        )
        self.assertNotIn(
            "created_at: Date.now()",
            body,
            "editPhrase 不能重置 created_at（应保留原值）",
        )


# ---------------------------------------------------------------------------
# 2. chip 编辑按钮
# ---------------------------------------------------------------------------


class TestChipEditButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)
        cls.css = _read(CSS)

    def test_render_list_creates_edit_button(self) -> None:
        # renderList 内必须 createElement 一个 quick-phrase-chip-edit 节点
        self.assertIn(
            'edit.className = "quick-phrase-chip-edit"',
            self.js,
            "renderList 必须为每个 chip 创建 .quick-phrase-chip-edit 按钮",
        )

    def test_edit_button_uses_pencil_glyph(self) -> None:
        # ✎ 字符（U+270E）作为 textContent，而非 ASCII E / e；
        # 用 unicode escape 确保 grep 不依赖系统字体也能识别
        self.assertIn(
            '"\\u270e"',
            self.js,
            "编辑按钮必须用 \\u270e (✎) 字符作为 textContent",
        )

    def test_edit_button_has_i18n_aria_label(self) -> None:
        self.assertIn(
            '"data-i18n-aria-label",\n        "quickPhrases.editBtnAriaLabel"',
            self.js,
            "编辑按钮必须挂 data-i18n-aria-label=quickPhrases.editBtnAriaLabel",
        )

    def test_edit_button_css_selector_present(self) -> None:
        self.assertIn(
            ".quick-phrase-chip-edit",
            self.css,
            "main.css 必须含 .quick-phrase-chip-edit 规则块",
        )

    def test_edit_button_click_opens_edit_form(self) -> None:
        # 点击编辑按钮必须调用 openEditForm(p.id) 而非 openAddForm
        self.assertRegex(
            self.js,
            r"edit\.addEventListener\(\s*[\"']click[\"'][\s\S]*?openEditForm\(\s*p\.id\s*\)",
            "编辑按钮 click 必须调 openEditForm(p.id)",
        )


# ---------------------------------------------------------------------------
# 3. form mode + dataset 标记
# ---------------------------------------------------------------------------


class TestFormModeDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_form_carries_dataset_mode(self) -> None:
        # _openForm 必须给 form 节点写 dataset.qpMode（让重复触发能识别复用）
        self.assertIn(
            "form.dataset.qpMode",
            self.js,
            "_openForm 必须写 form.dataset.qpMode",
        )

    def test_form_carries_dataset_edit_id(self) -> None:
        self.assertIn(
            "form.dataset.qpEditId",
            self.js,
            "_openForm 必须写 form.dataset.qpEditId（edit 模式锚定 phrase）",
        )

    def test_save_branches_on_mode(self) -> None:
        # 保存按钮必须按 mode 分流到 editPhrase / addPhrase
        self.assertRegex(
            self.js,
            r'mode\s*===\s*["\']edit["\'][\s\S]*?editPhrase\(',
            "保存按钮必须在 mode==='edit' 分支调 editPhrase",
        )
        self.assertRegex(
            self.js,
            r"\}\s*else\s*\{\s*\n\s*addPhrase\(",
            "保存按钮必须在 else 分支调 addPhrase",
        )


# ---------------------------------------------------------------------------
# 4. insertTextIntoFeedback 光标语义
# ---------------------------------------------------------------------------


class TestCursorInsertion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_reads_selection_start_end(self) -> None:
        # 必须从 textarea 读 selectionStart / selectionEnd 才能精确插入
        self.assertIn(
            "selectionStart",
            self.js,
            "insertTextIntoFeedback 必须读 selectionStart",
        )
        self.assertIn(
            "selectionEnd",
            self.js,
            "insertTextIntoFeedback 必须读 selectionEnd",
        )

    def test_uses_substring_for_splice(self) -> None:
        # current.substring(0, start) + text + current.substring(end) 是
        # 标准 splice 模式，确保选中文本被替换而非保留
        self.assertRegex(
            self.js,
            r"current\.substring\(\s*0\s*,\s*start\s*\)\s*\+\s*text\s*\+\s*current\.substring\(\s*end\s*\)",
            "光标插入必须用 substring(0,start)+text+substring(end) 三段拼接",
        )

    def test_fallback_path_still_present(self) -> None:
        # 老引擎不支持 selectionStart 时仍要走 R130 v1 末尾追加
        self.assertIn(
            "hasSelectionApi",
            self.js,
            "必须有 hasSelectionApi 分支区分新老引擎",
        )

    def test_cursor_position_lands_after_inserted_text(self) -> None:
        # newCursorPos = start + text.length 是 R131 的正确光标停留点
        self.assertRegex(
            self.js,
            r"newCursorPos\s*=\s*start\s*\+\s*text\.length",
            "光标必须停在 start + text.length（即新插入文本的末尾）",
        )


# ---------------------------------------------------------------------------
# 5. i18n 完备性
# ---------------------------------------------------------------------------


class TestEditI18n(unittest.TestCase):
    def _assert_edit_key(self, path: Path, label: str) -> None:
        data = _read_locale(path)
        qp = data.get("quickPhrases")
        assert isinstance(qp, dict), f"{label} 必须含 quickPhrases 命名空间"
        v = qp.get("editBtnAriaLabel")
        self.assertIsInstance(
            v,
            str,
            f"{label}.quickPhrases.editBtnAriaLabel 必须是字符串",
        )
        assert isinstance(v, str)
        self.assertGreater(
            len(v.strip()),
            0,
            f"{label}.quickPhrases.editBtnAriaLabel 不能是空字符串",
        )

    def test_zh_cn_has_edit_key(self) -> None:
        self._assert_edit_key(LOCALE_ZH, "zh-CN.json")

    def test_en_has_edit_key(self) -> None:
        self._assert_edit_key(LOCALE_EN, "en.json")

    def test_pseudo_has_edit_key(self) -> None:
        self._assert_edit_key(LOCALE_PSEUDO, "_pseudo/pseudo.json")


if __name__ == "__main__":
    unittest.main()
