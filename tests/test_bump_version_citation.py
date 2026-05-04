"""单元测试：``scripts/bump_version.py`` 的 ``CITATION.cff`` 同步逻辑。

历史背景
---------
``bump_version.py`` 守了 6 个版本号文件（``pyproject.toml`` /
``uv.lock`` / ``package.json`` / ``package-lock.json`` /
``packages/vscode/package.json`` / ``.github/ISSUE_TEMPLATE/bug_report.yml``）
但**漏掉**了 ``CITATION.cff::version``。后果：发布 v1.5.23 时
``.github/RELEASE_NOTES_DRAFT.md::step 1`` 让发布者跑
``bump_version.py 1.5.23``，结果 ``CITATION.cff`` 还停留在 v1.5.22 —
学术引用工具会显示错版本，且 ``--check`` 不会发现。

修复同时加 helper（``_update_citation_version`` /
``_extract_citation_version``）+ 把 ``CITATION.cff`` 接入 ``targets``
列表 + ``--check`` 校验段。本文件单元覆盖两个 helper，确保：

  - ``_extract_citation_version`` 能从合法 CITATION.cff 提取 version 字段；
  - ``_update_citation_version`` 重写 ``version: "X.Y.Z"`` 行而**不**误改
    ``cff-version: 1.2.0`` / ``date-released: ...`` 等姊妹字段；
  - 引号样式与原文一致（项目用双引号；裸值场景留作未来扩展）；
  - 整个文件的其他内容（authors / keywords / abstract）字节级保留。

不覆盖（独立的集成测试 + dry-run / --check 已 cover 的范围）：
  - ``bump_version.py main()`` 的 CLI 入口；那需要构造 fake repo，已通过
    实际跑 ``bump_version.py --dry-run 1.5.23`` 与 ``--check --from-pyproject``
    手工验证。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.bump_version import _extract_citation_version, _update_citation_version

SAMPLE_CITATION = """\
cff-version: 1.2.0
message: "If you use this software, please cite it as below."
title: "AI Intervention Agent"
abstract: >
  An MCP (Model Context Protocol) server that lets a human intervene
  in real time during AI-assisted development workflows.
type: software
license: MIT
url: "https://github.com/xiadengma/ai-intervention-agent"
repository-code: "https://github.com/xiadengma/ai-intervention-agent"
authors:
  - family-names: xiadengma
    alias: xiadengma
keywords:
  - mcp
  - feedback
version: "1.5.22"
date-released: "2026-05-04"
"""


class TestExtractCitationVersion(unittest.TestCase):
    def test_extracts_version_from_canonical_form(self) -> None:
        self.assertEqual(_extract_citation_version(SAMPLE_CITATION), "1.5.22")

    def test_does_not_pick_up_cff_version_field(self) -> None:
        # cff-version: 1.2.0 是 CFF 规范版本，不是项目版本。我们的正则
        # 用 ^version: 行首锚定刚好排除 cff-version: 行。
        text = 'cff-version: 1.2.0\nversion: "3.0.0"\n'
        self.assertEqual(_extract_citation_version(text), "3.0.0")

    def test_returns_none_when_version_missing(self) -> None:
        text = 'cff-version: 1.2.0\ntitle: "Demo"\n'
        self.assertIsNone(_extract_citation_version(text))

    def test_handles_pre_release_and_build_metadata(self) -> None:
        for raw, expected in [
            ('version: "1.5.23-rc.1"\n', "1.5.23-rc.1"),
            ('version: "1.5.23+local.dev"\n', "1.5.23+local.dev"),
            ('version: "10.20.30"\n', "10.20.30"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(_extract_citation_version(raw), expected)

    def test_extra_whitespace_around_colon_still_parses(self) -> None:
        text = 'version:   "1.5.22"\n'
        self.assertEqual(_extract_citation_version(text), "1.5.22")


class TestUpdateCitationVersion(unittest.TestCase):
    def test_replaces_only_top_level_version(self) -> None:
        result = _update_citation_version(SAMPLE_CITATION, "1.5.23")
        self.assertEqual(_extract_citation_version(result), "1.5.23")

    def test_preserves_cff_version_field(self) -> None:
        result = _update_citation_version(SAMPLE_CITATION, "1.5.23")
        self.assertIn("cff-version: 1.2.0", result)

    def test_preserves_date_released_field(self) -> None:
        # date-released 是另一条 release 信息；bump_version 不应该副作用地动它
        # （由发布者根据实际 tag 日期手动维护）
        result = _update_citation_version(SAMPLE_CITATION, "1.5.23")
        self.assertIn('date-released: "2026-05-04"', result)

    def test_preserves_authors_block(self) -> None:
        result = _update_citation_version(SAMPLE_CITATION, "1.5.23")
        self.assertIn("authors:", result)
        self.assertIn("family-names: xiadengma", result)

    def test_only_one_version_line_changed(self) -> None:
        # 字节级对比：原文行数 = 修改后行数；唯一差异是 version 那一行
        original_lines = SAMPLE_CITATION.splitlines()
        updated = _update_citation_version(SAMPLE_CITATION, "1.5.23")
        updated_lines = updated.splitlines()
        self.assertEqual(len(original_lines), len(updated_lines))
        diffs = [
            (i, o, n)
            for i, (o, n) in enumerate(zip(original_lines, updated_lines, strict=True))
            if o != n
        ]
        self.assertEqual(
            len(diffs), 1, f"expected exactly one line change, got: {diffs}"
        )
        idx, old, new = diffs[0]
        self.assertIn('version: "1.5.22"', old)
        self.assertIn('version: "1.5.23"', new)

    def test_idempotent_when_version_already_matches(self) -> None:
        result_once = _update_citation_version(SAMPLE_CITATION, "1.5.22")
        result_twice = _update_citation_version(result_once, "1.5.22")
        self.assertEqual(result_once, result_twice)
        self.assertEqual(result_twice, SAMPLE_CITATION)


class TestRoundTrip(unittest.TestCase):
    """``extract`` + ``update`` 组合在合法输入上的行为契约。"""

    def test_extract_after_update_returns_new_version(self) -> None:
        for new in ("1.5.23", "2.0.0-rc.1", "100.99.0"):
            with self.subTest(new=new):
                updated = _update_citation_version(SAMPLE_CITATION, new)
                self.assertEqual(_extract_citation_version(updated), new)

    def test_real_repository_citation_parses(self) -> None:
        # 集成 sanity：实际仓库的 CITATION.cff 必须能被 helper 解析。
        # 不断言具体版本（会随发布漂移），只断言 helper 能拿出一个非空字符串。
        cff = (REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
        ver = _extract_citation_version(cff)
        self.assertIsNotNone(
            ver, "real CITATION.cff must expose a parseable top-level version"
        )
        # 形态检查：SemVer 主干 (X.Y.Z[-prerelease][+buildmeta])
        self.assertRegex(
            ver or "",
            r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
        )


if __name__ == "__main__":
    unittest.main()
