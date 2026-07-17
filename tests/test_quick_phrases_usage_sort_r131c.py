"""R131c · Quick Phrases 按使用频率排序契约。

背景
----
R130 v1 的 chip 渲染顺序是「插入顺序」（即 ``loadPhrases`` 返回的
天然顺序）。随着 phrase 数量增多到 10-20 条，用户高频使用的常用
回复会被「最近新增的」挤到列表中段，每次都得用眼睛扫一遍找到熟悉的
chip。竞品 ``mcp-feedback-enhanced`` v1.2.23 的 Prompt Management
明确按「最近使用」排序——是熟手用户体感差异最大的一项。

R131c 在不破坏 storage schema_version 的前提下，扩展每条 phrase
两个可选字段（v1 内向前兼容）：

- ``last_used_at`` (number, ms epoch)：``recordPhraseUsage`` 调用时
  刷新；新建 phrase 默认 0；老数据 ``loadPhrases`` 兜底 0。
- ``use_count`` (number)：``recordPhraseUsage`` 自增 1；新建 phrase
  默认 0；老数据 ``loadPhrases`` 兜底 0。

renderList 之前用 ``_sortPhrasesByUsage`` 按 ``last_used_at`` desc
主排 + ``use_count`` desc 二排 + ``created_at`` desc 三排。

测试覆盖五个层面（共 14 cases / 5 invariant classes）：

1.  **JS API 扩展** — ``recordPhraseUsage`` 与 ``_sortPhrasesByUsage``
    函数存在，前者暴露在 ``window.AIIA_QUICK_PHRASES``。
2.  **schema 字段兼容** — ``loadPhrases`` 给老数据兜底 ``last_used_at``
    / ``use_count``；``addPhrase`` 新建时显式写入两个字段（默认 0）。
3.  **chip click 行为** — ``renderList`` 内的 chip click handler
    依次调用 ``insertTextIntoFeedback`` 与 ``recordPhraseUsage``，
    且不影响 R131 的「光标位置插入」契约。
4.  **排序顺序** — ``_sortPhrasesByUsage`` 按 ``last_used_at`` desc
    主排，``use_count`` desc 二排，``created_at`` desc 三排，``id``
    字符串兜底。
5.  **schema 不破裂** — ``STORAGE_KEY`` / ``SCHEMA_VERSION`` 仍是
    ``aiia.quickPhrases.v1`` / 1（v1 内可选字段扩展不需要 migrator）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ai_intervention_agent"
JS_QP = SRC / "static" / "js" / "quick_phrases.js"


def _read(p: Path) -> str:
    assert p.is_file(), f"缺失文件: {p}"
    return p.read_text(encoding="utf-8")


def _extract_function_body(src: str, signature_regex: str) -> str:
    """与 R131b 测试同款 brace counter（嵌套 {} 安全）。"""
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


class TestUsageSortApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_record_phrase_usage_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+recordPhraseUsage\s*\(\s*id\s*\)",
            "必须存在 recordPhraseUsage(id) 函数",
        )

    def test_sort_helper_function_present(self) -> None:
        self.assertRegex(
            self.js,
            r"function\s+_sortPhrasesByUsage\s*\(\s*phrases\s*\)",
            "必须存在 _sortPhrasesByUsage(phrases) 函数",
        )

    def test_public_api_exposes_record_usage(self) -> None:
        self.assertRegex(
            self.js,
            r"recordPhraseUsage\s*:\s*recordPhraseUsage",
            "AIIA_QUICK_PHRASES 必须暴露 recordPhraseUsage",
        )


# ---------------------------------------------------------------------------
# 2. schema 字段兼容（兜底 + 显式写入）
# ---------------------------------------------------------------------------


class TestSchemaFieldCompat(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_load_phrases_backfills_last_used_at_and_use_count(self) -> None:
        body = _extract_function_body(self.js, r"function\s+loadPhrases\s*\(\s*\)")
        # 必须显式给 last_used_at / use_count 兜底（typeof === "number"）
        self.assertRegex(
            body,
            r'typeof\s+p\.last_used_at\s*===\s*"number"',
            "loadPhrases 必须给老数据 last_used_at 兜底（typeof 检查）",
        )
        self.assertRegex(
            body,
            r'typeof\s+p\.use_count\s*===\s*"number"',
            "loadPhrases 必须给老数据 use_count 兜底（typeof 检查）",
        )

    def test_add_phrase_writes_usage_fields_with_zero(self) -> None:
        body = _extract_function_body(self.js, r"function\s+addPhrase\s*\([^)]*\)")
        self.assertRegex(
            body,
            r"last_used_at\s*:\s*0",
            "addPhrase 必须显式写入 last_used_at: 0",
        )
        self.assertRegex(
            body,
            r"use_count\s*:\s*0",
            "addPhrase 必须显式写入 use_count: 0",
        )

    def test_record_phrase_usage_increments_counters(self) -> None:
        body = _extract_function_body(
            self.js, r"function\s+recordPhraseUsage\s*\([^)]*\)"
        )
        self.assertIn(
            "Date.now()",
            body,
            "recordPhraseUsage 必须把 last_used_at 设为 Date.now()",
        )
        self.assertRegex(
            body,
            r"use_count\s*\|\|\s*0\)\s*\+\s*1",
            "recordPhraseUsage 必须把 use_count 自增 1（兼容 undefined → 0+1）",
        )


# ---------------------------------------------------------------------------
# 3. chip click 行为：插入 + 记录
# ---------------------------------------------------------------------------


class TestChipClickRecordsUsage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_render_list_chip_click_calls_insert_then_record(self) -> None:
        body = _extract_function_body(self.js, r"function\s+renderList\s*\(\s*\)")
        # chip click handler 必须同时含 insertTextIntoFeedback 和
        # recordPhraseUsage 两个调用
        self.assertIn(
            "insertTextIntoFeedback(p.text)",
            body,
            "chip click 必须仍调用 insertTextIntoFeedback（R131 契约）",
        )
        self.assertIn(
            "recordPhraseUsage(p.id)",
            body,
            "chip click 必须调用 recordPhraseUsage（R131c 新增）",
        )
        # 顺序：insertTextIntoFeedback 在 recordPhraseUsage 之前——
        # 文本插入是核心副作用，使用记录是 nice-to-have，前者失败不影响
        # 后者，但要先把用户的核心诉求满足了再记录
        insert_idx = body.find("insertTextIntoFeedback(p.text)")
        record_idx = body.find("recordPhraseUsage(p.id)")
        self.assertLess(
            insert_idx,
            record_idx,
            "chip click 必须先 insertTextIntoFeedback 再 recordPhraseUsage",
        )


# ---------------------------------------------------------------------------
# 4. 排序顺序
# ---------------------------------------------------------------------------


class TestSortOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_sort_uses_last_used_at_descending_first(self) -> None:
        body = _extract_function_body(
            self.js, r"function\s+_sortPhrasesByUsage\s*\([^)]*\)"
        )
        # 主排 last_used_at desc：``b.last_used_at - a.last_used_at``
        self.assertRegex(
            body,
            r"b\.last_used_at\s*-\s*a\.last_used_at",
            "排序主键应为 b.last_used_at - a.last_used_at（desc）",
        )

    def test_sort_uses_use_count_descending_second(self) -> None:
        body = _extract_function_body(
            self.js, r"function\s+_sortPhrasesByUsage\s*\([^)]*\)"
        )
        self.assertRegex(
            body,
            r"b\.use_count\s*-\s*a\.use_count",
            "排序二级键应为 b.use_count - a.use_count（desc）",
        )

    def test_sort_uses_created_at_descending_third(self) -> None:
        body = _extract_function_body(
            self.js, r"function\s+_sortPhrasesByUsage\s*\([^)]*\)"
        )
        self.assertRegex(
            body,
            r"b\.created_at\s*-\s*a\.created_at",
            "排序三级键应为 b.created_at - a.created_at（desc）",
        )

    def test_render_list_sorts_before_iteration(self) -> None:
        body = _extract_function_body(self.js, r"function\s+renderList\s*\(\s*\)")
        sort_idx = body.find("_sortPhrasesByUsage(phrases)")
        loop_idx = body.find("var phraseCount =")
        self.assertGreaterEqual(
            sort_idx,
            0,
            "renderList 必须调用 _sortPhrasesByUsage(phrases)",
        )
        self.assertNotIn("phrases.forEach", body)
        self.assertGreaterEqual(loop_idx, 0)
        self.assertLess(
            sort_idx,
            loop_idx,
            "_sortPhrasesByUsage 必须在 phraseCount indexed loop 之前调用",
        )


# ---------------------------------------------------------------------------
# 5. schema 不破裂（v1 内向前兼容）
# ---------------------------------------------------------------------------


class TestStorageSchemaIntact(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(JS_QP)

    def test_storage_key_unchanged(self) -> None:
        # R131c 的两个新字段是 v1 内可选扩展，绝不能改 STORAGE_KEY
        # 否则用户既有 phrase 数据全部失效
        self.assertIn(
            'STORAGE_KEY = "aiia.quickPhrases.v1"',
            self.js,
            "STORAGE_KEY 仍必须是 aiia.quickPhrases.v1（R131c 不引入 v2）",
        )

    def test_schema_version_unchanged(self) -> None:
        self.assertIn(
            "SCHEMA_VERSION = 1",
            self.js,
            "SCHEMA_VERSION 仍必须是 1（R131c 是可选字段扩展）",
        )

    def test_load_phrases_returns_objects_with_full_shape(self) -> None:
        body = _extract_function_body(self.js, r"function\s+loadPhrases\s*\(\s*\)")
        # 兜底之后 .map 返回的对象必须包含全部 6 个字段
        for field in (
            "id",
            "label",
            "text",
            "created_at",
            "last_used_at",
            "use_count",
        ):
            self.assertRegex(
                body,
                rf"{field}\s*:",
                f"loadPhrases 返回对象必须含 {field} 字段",
            )


if __name__ == "__main__":
    unittest.main()
