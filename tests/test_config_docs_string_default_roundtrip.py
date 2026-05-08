r"""防回归：``docs/configuration{,.zh-CN}.md`` 表格里给出的 string 默认值必须能
被用户**原样复制粘贴**到 ``config.toml`` 并解析回 ``config.toml.default`` 的真实
默认值。

历史背景（R95）
---------------
2026-05-09 巡检 ``[feedback]::prompt_suffix`` 时发现：

  - ``config.toml.default`` line 140 写：
    ``prompt_suffix = "\n请积极调用 interactive_feedback 工具"``
    （TOML 双引号串里的 ``\n`` 是 escape sequence，解析为真换行 ``0x0A``）。
  - ``docs/configuration.md`` line 207 写表格 Default 列为：
    `` `"\\n请积极调用 interactive_feedback 工具"` ``。
  - Markdown 反引号内 inline code 不解析反斜杠转义，所以 GitHub 渲染显示
    ``"\\n请积极调用 interactive_feedback 工具"``（**两**反斜杠 + ``n``）。
  - 用户照渲染结果原样复制到 ``config.toml`` 得到：
    ``prompt_suffix = "\\n请积极..."``。TOML 把 ``\\`` 解析为字面反斜杠 ``\``，
    ``n`` 字面 ``n`` —— 解析后字符串首字符 = 字面 ``\n`` 两字符（**不是换行**）。

==> 用户"恢复默认值"会得到字面反斜杠开头的字符串，AI 提示语就和反馈正文
紧贴在一起没换行。无报错、无警告，纯 silent breakage（v1.5.x 起一直存在
直到 R95 才发现）。

设计原则
--------
- **唯一可靠对齐方式 = TOML 双向解析**：把 doc 表格 Default 列的字面字符串
  当作 ``key = <Default>`` 拼出一行临时 TOML，``tomllib.loads`` 解析；
  与 ``config.toml.default`` 的同 key 对比。两边都过 TOML 解析器，自动正确
  处理任何 escape 形态差异。
- **只校验 string 字段**：bool / int / float 在 doc 表格里通常写
  ``true`` / ``600`` / ``1.0``，可以用 ``test_config_defaults_consistency``
  / ``test_config_docs_range_parity`` 守住。本测试只关心带 ``"..."`` 包裹
  的字符串默认值——这正是 escape-sequence 误用的高发区。
- **逐项跳过非字面**：表格里的占位符（``""`` 空串、``"see notes"``、``—``、
  ``\`null\`` 等）只对 doc 表格写法是否能 roundtrip 解析做判断；解析失败的
  跳过（既然 doc 写的不是合法 TOML 字面，就不该用 toml roundtrip 校验它）。
- **English & Chinese both checked**：两份配置 doc 都参与，避免一份修对了
  另一份还错（之前 R94 / R93 都是双语同错）。

附加证明：单元测试 ``test_prompt_suffix_doc_roundtrips_to_real_newline``
直接用 ``\n`` 默认值这个具体字段作 byte-equal 锁，下次有人不小心把
``\n`` 改回 ``\\n``，本测试会精确指出。
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

# ``### `name``` 或 ``### `name`（说明）`` 都接受。
SECTION_HEADING_RE = re.compile(
    r"^###\s+`([a-z_]+)`(?:\s*[（(].*?[）)])?\s*$", re.MULTILINE
)
# 表格行：``| `key` | type | default | notes |``，要求 default 列是带反引号的字符串字面。
ROW_WITH_STRING_DEFAULT_RE = re.compile(
    r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|\s*string[^|]*\|\s*`(\"[^`]*\")`",
    re.MULTILINE,
)


def _toml_section_keys() -> dict[tuple[str, str], object]:
    """``{(section, key): default_value}`` 来自 ``config.toml.default``。"""
    data = tomllib.loads(TOML_TEMPLATE.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], object] = {}
    for sec, body in data.items():
        if isinstance(body, dict):
            for k, v in body.items():
                out[(sec, k)] = v
    return out


def _parse_doc_string_defaults(doc_path: Path) -> dict[tuple[str, str], str]:
    """从配置 doc 的表格抓 string 默认值字面（含两侧的 ``"..."``）。

    返回 ``{(section, key): doc_default_literal}``——只收集类型列写 ``string``
    且 default 列为反引号包裹双引号字面的行。
    """
    text = doc_path.read_text(encoding="utf-8")
    out: dict[tuple[str, str], str] = {}
    cur_sec: str | None = None
    for line in text.splitlines():
        m = SECTION_HEADING_RE.match(line)
        if m:
            cur_sec = m.group(1)
            continue
        if cur_sec is None:
            continue
        rm = ROW_WITH_STRING_DEFAULT_RE.match(line)
        if rm:
            out[(cur_sec, rm.group(1))] = rm.group(2)
    return out


class TestConfigDocsStringDefaultRoundtrip(unittest.TestCase):
    """主断言：doc 表格写的 string 默认值用户原样复制粘贴到 ``config.toml``
    解析后必须等于 ``config.toml.default`` 真实默认值。"""

    def setUp(self) -> None:
        self.toml_defaults = _toml_section_keys()

    def _roundtrip(self, doc_literal: str) -> tuple[bool, object]:
        """模拟用户把 doc 表格 Default 列字面贴到 ``config.toml``：``key = <literal>``。

        返回 (parsed_ok, parsed_value)。解析失败返回 (False, error_str)。
        """
        try:
            parsed = tomllib.loads(f"k = {doc_literal}")
            return True, parsed["k"]
        except Exception as e:
            return False, str(e)

    def test_doc_string_defaults_roundtrip_to_template(self) -> None:
        drifts: list[str] = []
        for lang, doc_path in DOC_PATHS.items():
            doc_defaults = _parse_doc_string_defaults(doc_path)
            for (sec, key), doc_lit in doc_defaults.items():
                if (sec, key) not in self.toml_defaults:
                    # ``test_config_docs_parity`` 已经守 key 集合一致，这里
                    # 跳过避免重复抛错制造噪声。
                    continue
                tval = self.toml_defaults[(sec, key)]
                if not isinstance(tval, str):
                    # 模板里不是字符串（被人改过类型？），交给
                    # ``test_config_defaults_consistency`` / pydantic 报。
                    continue
                ok, parsed = self._roundtrip(doc_lit)
                if not ok:
                    drifts.append(
                        f"  [{lang}] {sec}.{key}: doc Default 写的 {doc_lit!r} 不是合法 TOML 字面 (err: {parsed})"
                    )
                    continue
                if parsed != tval:
                    drifts.append(
                        f"  [{lang}] {sec}.{key}:\n"
                        f"     doc Default = {doc_lit} → parsed {parsed!r}\n"
                        f"     toml 实际值 = {tval!r}\n"
                        f"     用户照 doc 复制粘贴会得到错误默认值"
                    )
        if drifts:
            lines = [
                "docs/configuration*.md 表格 Default 列字符串值与 config.toml.default "
                "TOML-roundtrip 不一致（用户照 doc 复制粘贴会改变行为）：",
                *drifts,
            ]
            self.fail("\n".join(lines))

    def test_prompt_suffix_doc_roundtrips_to_real_newline(self) -> None:
        """精确锁住 R95 的具体修复点：``feedback.prompt_suffix`` 默认值
        必须以**真实换行符** ``0x0A`` 开头，而不是字面 ``\\n``。

        之前 R95 修复前，doc 写 ``"\\\\n请积极..."`` 用户复制粘贴到 toml 会得到
        字面反斜杠 ``\\n请积极...``（首字符 = 反斜杠 ``\\`` + 字母 ``n``）。
        修复后 doc 写 ``"\\n请积极..."``，复制粘贴解析后 = 真换行 + ``请积极...``。
        """
        tval = self.toml_defaults.get(("feedback", "prompt_suffix"))
        self.assertIsNotNone(
            tval, "config.toml.default 缺少 feedback.prompt_suffix 默认值"
        )
        assert isinstance(tval, str)
        self.assertTrue(
            tval.startswith("\n"),
            f"feedback.prompt_suffix 默认值首字符应为换行符 0x0A，实际首字符 ord={ord(tval[0])}",
        )
        # 双语 doc 表格里的 Default 列字面（带 ``"..."`` 包裹）解析后必须等于 tval
        for lang, doc_path in DOC_PATHS.items():
            doc_defaults = _parse_doc_string_defaults(doc_path)
            doc_lit = doc_defaults.get(("feedback", "prompt_suffix"))
            self.assertIsNotNone(
                doc_lit,
                f"[{lang}] {doc_path.name} 缺少 feedback.prompt_suffix 表格行",
            )
            assert doc_lit is not None
            parsed = tomllib.loads(f"k = {doc_lit}")["k"]
            self.assertEqual(
                parsed,
                tval,
                f"[{lang}] {doc_path.name} 中 feedback.prompt_suffix 的 doc Default "
                f"({doc_lit}) 解析后 = {parsed!r}，与 toml 实际值 {tval!r} 不一致",
            )


if __name__ == "__main__":
    unittest.main()
