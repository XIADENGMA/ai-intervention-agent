"""防回归：``docs/configuration{,.zh-CN}.md`` 必须列出 ``config.toml.default`` 中的所有 key。

历史背景
---------
2026-05-04（v1.5.23 候选）一次审计发现三处真实漂移：

  1. ``[notification]::debug`` 在 TOML 模板中存在多个版本，但**两份**
     docs/configuration*.md 表格都未列出；
  2. ``[web_ui]::language`` 同上，是用户最常问的 key 之一却未文档化；
  3. ``docs/configuration.zh-CN.md::[mdns]::enabled`` 仍写 ``boolean / null``
     默认 ``null``，但运行时早已用字符串 sentinel ``"auto"``（英文版与
     ``config.toml.default`` 都是 ``"auto"``）。

修复完后加这个回归位，把"配置文档表格 = TOML 模板 key 集合"的契约
锁住——以后任何 ``config.toml.default`` 新增 / 重命名 / 删除 key 都
必须同时更新两份 ``docs/configuration*.md`` 才能合入。

设计原则
--------
- **只校验 key 集合**，不强约束默认值或类型描述（值可能因安全调整变更，
  类型描述涉及自然语言措辞，不适合做 byte-equal 断言）。这里和
  ``test_config_defaults_consistency.py`` 形成互补：那份守
  *运行时* 默认 dict ↔ TOML 模板，本份守 *文档表格* ↔ TOML 模板。
- 容忍中英两份文档的小幅措辞差异（中文用「配置项」，英文用「Key」），
  靠**表头匹配 + section 标题匹配**而非精确文本对齐。
- 仅扫描表格第一列里被反引号包裹的标识符，对自然语言的 notes 列完全不
  关心。
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOML_TEMPLATE = REPO_ROOT / "config.toml.default"
DOC_PATHS = {
    "en": REPO_ROOT / "docs" / "configuration.md",
    "zh-CN": REPO_ROOT / "docs" / "configuration.zh-CN.md",
}

# Section heading shapes:
#   English: "### `web_ui`"
#   Chinese: "### `web_ui`（Web UI）"
# Both produce the same captured `web_ui`. The (?:\W.*)? tail accepts the
# Chinese suffix without polluting the captured group.
SECTION_HEADING_RE = re.compile(
    r"^###\s+`([a-z_]+)`(?:\s*[（(].*?[）)])?\s*$", re.MULTILINE
)

# A row in a markdown table starts with `| ` and the first cell carries the
# key name in backticks: "| `enabled` | boolean | …".
TABLE_ROW_KEY_RE = re.compile(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", re.MULTILINE)


def _toml_section_keys(template_path: Path) -> dict[str, set[str]]:
    """Return ``{section_name: {key, …}}`` for every top-level table in the TOML template."""
    data = tomllib.loads(template_path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for section, body in data.items():
        if not isinstance(body, dict):
            # Top-level scalar — not a section; skip (current template has none).
            continue
        out[section] = set(body.keys())  # ty: ignore[invalid-assignment]
    return out


def _doc_section_keys(doc_path: Path) -> dict[str, set[str]]:
    """Parse a configuration doc and return ``{section_name: {key, …}}`` from its tables.

    Walks the markdown linearly: every ``### `name``` heading opens a new
    section, and every ``| `key` | …`` row inside that section contributes a
    key. We do **not** require the row to come from the *first* table after
    the heading — some sections (e.g. `mdns`) interleave prose with multiple
    tables, but only the per-key rows have backticked first cells.
    """
    text = doc_path.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}

    # Find every section heading + its body span (until next ### or EOF).
    heading_matches = list(SECTION_HEADING_RE.finditer(text))
    for i, m in enumerate(heading_matches):
        section = m.group(1)
        body_start = m.end()
        body_end = (
            heading_matches[i + 1].start()
            if i + 1 < len(heading_matches)
            else len(text)
        )
        body = text[body_start:body_end]
        keys = {km.group(1) for km in TABLE_ROW_KEY_RE.finditer(body)}
        # Merge — if the same `### \`name\`` appears more than once in a doc
        # (today they don't, but future-proof) union rather than overwrite.
        out.setdefault(section, set()).update(keys)
    return out


class TestConfigDocsKeyParity(unittest.TestCase):
    """`docs/configuration{,.zh-CN}.md` 表格里列出的 key 必须 = `config.toml.default` 的 key 集合。"""

    def setUp(self) -> None:
        self.assertTrue(
            TOML_TEMPLATE.exists(), f"missing TOML template: {TOML_TEMPLATE}"
        )
        self.toml_keys = _toml_section_keys(TOML_TEMPLATE)
        self.assertGreater(
            len(self.toml_keys),
            0,
            "TOML template parsed to zero sections — likely template parse failure",
        )

    def _assert_doc_matches(self, lang: str) -> None:
        doc_path = DOC_PATHS[lang]
        self.assertTrue(doc_path.exists(), f"missing doc: {doc_path}")
        doc_keys = _doc_section_keys(doc_path)

        # Sections present in TOML must be present in the doc; the doc may
        # legitimately introduce *extra* prose-only sections (e.g. headings
        # that don't correspond to a TOML table), so we walk TOML → doc
        # rather than asserting the full set is symmetric.
        toml_sections = set(self.toml_keys.keys())
        doc_sections = set(doc_keys.keys())
        missing_in_doc = toml_sections - doc_sections
        self.assertFalse(
            missing_in_doc,
            f"{doc_path.name}: TOML sections not documented as `### \\`<name>\\``: "
            f"{sorted(missing_in_doc)}",
        )

        for section in sorted(toml_sections):
            template_keys = self.toml_keys[section]
            documented_keys = doc_keys.get(section, set())

            missing_in_doc_keys = template_keys - documented_keys
            extra_in_doc = documented_keys - template_keys

            with self.subTest(lang=lang, section=section):
                self.assertFalse(
                    missing_in_doc_keys,
                    f"{doc_path.name}::[{section}]: keys present in "
                    f"config.toml.default but not in the doc table: "
                    f"{sorted(missing_in_doc_keys)}",
                )
                self.assertFalse(
                    extra_in_doc,
                    f"{doc_path.name}::[{section}]: keys documented but not "
                    f"in config.toml.default (likely deprecated; remove from doc "
                    f"or add to template): {sorted(extra_in_doc)}",
                )

    def test_english_doc_matches_template(self) -> None:
        self._assert_doc_matches("en")

    def test_chinese_doc_matches_template(self) -> None:
        self._assert_doc_matches("zh-CN")


class TestParserSelfChecks(unittest.TestCase):
    """守住解析器本身的契约 —— 重构 _toml_section_keys / _doc_section_keys 时不要悄悄变弱。"""

    def test_toml_parser_returns_at_least_known_sections(self) -> None:
        keys = _toml_section_keys(TOML_TEMPLATE)
        for required in (
            "notification",
            "web_ui",
            "network_security",
            "mdns",
            "feedback",
        ):
            self.assertIn(required, keys, f"TOML section '{required}' should be parsed")

    def test_doc_parser_returns_at_least_known_sections_en(self) -> None:
        keys = _doc_section_keys(DOC_PATHS["en"])
        for required in (
            "notification",
            "web_ui",
            "network_security",
            "mdns",
            "feedback",
        ):
            self.assertIn(
                required, keys, f"EN doc section '{required}' should be parsed"
            )

    def test_doc_parser_returns_at_least_known_sections_zh(self) -> None:
        keys = _doc_section_keys(DOC_PATHS["zh-CN"])
        for required in (
            "notification",
            "web_ui",
            "network_security",
            "mdns",
            "feedback",
        ):
            self.assertIn(
                required, keys, f"ZH doc section '{required}' should be parsed"
            )


if __name__ == "__main__":
    unittest.main()
