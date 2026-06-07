"""mining-9 Track C + mining-10 Track C — kickoff template hygiene markers.

确保所有 cycle doc 不会误继承 template 的
``DELETE-ON-COPY-START/END`` 标记或 "Usage notes" 段。

**cycle-10 generalization** (cr45 §7 follow-up #1):
扩展 glob 从 ``feature-mining-cycle-*.md`` 到所有
``*-cycle-*.md``（含 ``perf-audit-cycle-N.md`` /
未来的 ``security-audit-cycle-N.md`` 等审计 cycle doc），
让模板 hygiene invariant 对**所有** cycle-doc 类型生效。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCS_DIR = _REPO_ROOT / "docs"
_TEMPLATE = _DOCS_DIR / "feature-mining-cycle-kickoff-template.md"

# 这些**结构性散文**仅允许出现在 template 文件中。
#
# cycle-10 refinement (cr45 §7 #1)：原始检查用裸 marker
# (``<!-- DELETE-ON-COPY-START``) 在 cycle-9 闭幕 doc 中
# false-positive —— 闭幕 doc 在 markdown 表格内**引用**
# (作为文档说明) 该 marker 字符串。
#
# cycle-11 refinement (R254 / cr46 follow-up Russell's-
# paradox)：cycle-10 闭幕 doc 在 §5.1 lesson 里**引用**
# 上一轮 refinement 后的 fingerprint ("Everything between
# DELETE-ON-COPY-START and DELETE-ON-COPY-END") 又触发了
# false-positive。改用**整句模板独有 prose**（包含 "must
# be removed when starting a real cycle doc. These markers
# also let `scripts/check"）—— 该完整句子只在模板内部出现，
# cycle docs 描述时极不可能完全复述。
_BOILERPLATE_MARKERS = (
    # 模板内部 marker 用途解释 —— 完整跨行 prose snippet，
    # 即使 cycle docs 描述 marker 也不会照搬整段
    "must be removed when starting a real cycle doc. These markers\n"
    "also let `scripts/check_cycle_doc_no_template_boilerplate.py`",
    # Usage notes 段完整标题（含 "delete this section" 提示语）
    "Usage notes (delete this section when starting",
)


def _cycle_docs() -> list[Path]:
    """所有 cycle doc（mining + perf-audit + 未来审计类）.

    glob 模式 ``*-cycle-*.md`` 涵盖：
      - ``feature-mining-cycle-N.md``
      - ``perf-audit-cycle-N.md``
      - 未来 ``security-audit-cycle-N.md`` / ``a11y-audit-cycle-N.md`` /
        ``dx-audit-cycle-N.md`` 等

    排除：``feature-mining-cycle-kickoff-template.md``（模板自身允许含
    boilerplate 标记）。
    """
    return sorted(
        p
        for p in _DOCS_DIR.glob("*-cycle-*.md")
        if p.name != "feature-mining-cycle-kickoff-template.md"
    )


def _mining_cycle_docs() -> list[Path]:
    """仅 ``feature-mining-cycle-N.md`` 子集——保留给原 mining-9 测试."""
    return sorted(
        p
        for p in _DOCS_DIR.glob("feature-mining-cycle-*.md")
        if p.name != "feature-mining-cycle-kickoff-template.md"
    )


class TestTemplateHasMarkers(unittest.TestCase):
    """模板自己**必须**带 DELETE-ON-COPY 标记 + Usage notes."""

    def test_template_exists(self) -> None:
        self.assertTrue(_TEMPLATE.exists(), "template 文件缺失")

    def test_template_has_delete_on_copy_start(self) -> None:
        # 模板必须含**实际**的 DELETE-ON-COPY-START 标记
        content = _TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("<!-- DELETE-ON-COPY-START", content)

    def test_template_has_delete_on_copy_end(self) -> None:
        content = _TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("<!-- DELETE-ON-COPY-END -->", content)

    def test_template_has_usage_notes_block(self) -> None:
        content = _TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            "Usage notes (delete this section when starting",
            content,
        )

    def test_template_has_structural_marker_explanation(self) -> None:
        # cycle-11 fingerprint：完整跨行 prose snippet 必须存在于模板（用于反向校验）
        content = _TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            "must be removed when starting a real cycle doc. These markers\n"
            "also let `scripts/check_cycle_doc_no_template_boilerplate.py`",
            content,
        )


class TestCycleDocsCleanOfBoilerplate(unittest.TestCase):
    """**所有** cycle doc（含 perf-audit / security-audit / 等）不允许含 boilerplate."""

    def test_no_cycle_doc_inherits_boilerplate(self) -> None:
        offenders: list[tuple[Path, str]] = []
        for doc in _cycle_docs():
            content = doc.read_text(encoding="utf-8")
            for marker in _BOILERPLATE_MARKERS:
                if marker in content:
                    offenders.append((doc, marker))
        self.assertEqual(
            offenders,
            [],
            "下列 cycle doc 误继承了 template 的 boilerplate；"
            "请手动删除 DELETE-ON-COPY-START/END 中间的所有内容 "
            "(包括标记本身)：\n"
            + "\n".join(f"  {p.name}: 含 marker '{m}'" for p, m in offenders),
        )

    def test_at_least_one_cycle_doc_exists(self) -> None:
        # sanity check —— 防止 glob 失败导致 invariant 被静默 bypass
        docs = _cycle_docs()
        self.assertGreaterEqual(len(docs), 1, "至少应有一个 *-cycle-*.md doc 存在")

    def test_covers_multiple_cycle_doc_kinds(self) -> None:
        # cycle-10 generalization 必须覆盖 mining + perf-audit 两类
        # （未来 security-audit 等加进来时也会自动 sweep）
        docs = _cycle_docs()
        kinds = {p.name.split("-cycle-", 1)[0] for p in docs}
        self.assertIn(
            "feature-mining",
            kinds,
            "至少应含一个 feature-mining-cycle-*.md",
        )
        self.assertIn(
            "perf-audit",
            kinds,
            "至少应含一个 perf-audit-cycle-*.md（cycle-9 R250 ship）",
        )


class TestCycleDocFilenameConvention(unittest.TestCase):
    """R254 / mining-11 Track B — 强制 cycle doc 文件名约定.

    template §0.0 codified: ``<kind>-cycle-<N>.md`` where
    ``<kind>`` is kebab-case and ``<N>`` is positive integer.
    """

    _NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-cycle-\d+\.md$")

    def test_all_cycle_docs_follow_naming_convention(self) -> None:
        offenders: list[str] = []
        for doc in _cycle_docs():
            if not self._NAME_RE.match(doc.name):
                offenders.append(doc.name)
        self.assertEqual(
            offenders,
            [],
            "下列 cycle doc 文件名违反 template §0.0 约定 "
            "(<kind>-cycle-<N>.md, kebab-case + positive int)：\n"
            + "\n".join(f"  {n}" for n in offenders),
        )

    def test_template_excluded_from_naming_check(self) -> None:
        # 模板自身用 ``-kickoff-template.md`` 后缀，故意不匹配，
        # 验证 _cycle_docs() 已正确排除模板
        template = _TEMPLATE
        docs = _cycle_docs()
        self.assertNotIn(template, docs)


class TestMiningSubsetUnchanged(unittest.TestCase):
    """保留 mining-9 原签名：仅 ``feature-mining-cycle-N.md`` 子集 sanity."""

    def test_mining_subset_at_least_one(self) -> None:
        docs = _mining_cycle_docs()
        self.assertGreaterEqual(
            len(docs),
            1,
            "至少应有一个 feature-mining-cycle-N.md doc 存在",
        )

    def test_mining_subset_subset_of_general(self) -> None:
        general = set(_cycle_docs())
        mining = set(_mining_cycle_docs())
        self.assertTrue(
            mining.issubset(general),
            "mining cycle docs 必须是 general cycle docs 的子集",
        )


if __name__ == "__main__":
    unittest.main()
