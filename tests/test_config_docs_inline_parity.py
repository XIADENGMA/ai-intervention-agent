"""防回归：``docs/*.md`` 散文里 inline 提到的 ``<section>.<key>`` 必须真在
``config.toml.default`` 中存在 —— 否则用户照做去改 ``config.toml`` 不生效。

历史背景（R94）
---------------
2026-05-09 巡检发现 ``docs/troubleshooting.{md,zh-CN.md}`` 的"手机访问 mDNS"
小节告诉用户：

>   Set ``web_ui.bind_interface`` to your LAN IP …

但 ``bind_interface`` 配置项实际上在 ``[network_security]`` section
（``config.toml.default`` line 92-93），不在 ``[web_ui]``。用户照 docs 改
``[web_ui] bind_interface = "..."`` **毫无效果** —— 这是经典 docs-to-code 漂移
（与 ``test_config_docs_parity.py`` 守的"表格 vs TOML"是不同维度：那份只看
``configuration{,.zh-CN}.md`` 的表格，不看其他 docs 散文里 inline 的引用）。

设计原则
--------
- **限定 section 名白名单** = 当前 ``config.toml.default`` 真实顶层 section
  集合。这样新增 section 时本测试自动跟着扩面，不会有"section 名变了忘改测试"
  的二级漂移。
- **限定 key 形态**：``<section>.<snake_case_key>``（小写 + 下划线），并显式排除
  常见文件后缀（``.py`` / ``.js`` / ``.md`` / ``.toml`` / ``.json`` / …），
  否则 ``server.py`` / ``web_ui.py`` 这种 lessons-learned 里的文件名引用会被
  误判成 config key。
- **排除已被 ``test_config_docs_parity`` 覆盖的文件**（``configuration.md``
  / ``configuration.zh-CN.md``）和 ``CHANGELOG.md``（历史记录里的旧名属于
  迁移说明，不应触发回归），以及 ``docs/api*/`` 自动生成的 API docs（噪声大且
  内容受 docstring 控制，``scripts/generate_docs.py`` 自管 drift）。
- **失败信息要"指出正确 section"**：用户最常踩的是"section 名错位"（如本案
  bind_interface 在 network_security 不在 web_ui），所以失败时同时打印
  "你写错了 ``X.Y``，正确写法是 ``Z.Y``"，比单纯 "Y not found" 友好。

测试覆盖
--------
- ``test_no_undeclared_inline_refs``: 主断言。
- ``test_section_set_matches_toml_top_level``: 元测试，确保 ``KNOWN_SECTIONS``
  与 ``config.toml.default`` 真实顶层 section 集合一致 —— 项目新增
  ``[security]`` 之类 section 时本测试会先挂，提醒同步白名单。
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOML_TEMPLATE = REPO_ROOT / "config.toml.default"
DOCS_DIR = REPO_ROOT / "docs"

# 排除：已被 ``test_config_docs_parity`` 覆盖的两份配置主文档；CHANGELOG 是
# 历史，里面的 ``feedback.auto_resubmit_timeout`` 是 v1.4 → v1.5 的迁移记录，
# 属于"故意保留旧名说明"，本测试不该触发。
_EXCLUDED_NAMES = frozenset(
    {
        "configuration.md",
        "configuration.zh-CN.md",
        "CHANGELOG.md",
    }
)

# 排除：API docs 是 ``scripts/generate_docs.py`` 自动生成的 docstring 抄录，
# 内容受源码 docstring 控制；如果源码 docstring 里写错 section.key，
# ``test_config_defaults_consistency`` / ``test_config_docs_parity`` 都不会
# 抓到，但那是 ``test_docstring_validity`` 的事，不归本测试管（避免抓到
# ``feedback.auto_resubmit_timeout`` 类参数名 → 文件名混淆的噪声）。
_EXCLUDED_DIR_FRAGMENTS = ("/api/", "/api.zh-CN/")

# 文件后缀白名单：``server.py`` / ``static/js/app.js`` / ``locales/en.json``
# 这种引用经常出现在 lessons-learned 里，得排除否则会被当成 ``server.py``
# config key（py / js / json 不可能是 toml key）。同时也覆盖
# ``ai_intervention_agent.py`` / ``i18n-keys.d.ts`` 等。
_FILE_EXT_LIKE_KEYS = frozenset(
    {
        "py",
        "js",
        "ts",
        "tsx",
        "jsx",
        "mjs",
        "cjs",
        "md",
        "rst",
        "txt",
        "json",
        "toml",
        "yaml",
        "yml",
        "ini",
        "cfg",
        "html",
        "htm",
        "css",
        "scss",
        "svg",
        "lock",
        "log",
        "tmp",
        "bak",
        "d",  # ``.d.ts`` 类型声明的中段
        "sh",
        "zsh",
        "bash",
        "fish",
    }
)


def _load_toml_sections() -> dict[str, set[str]]:
    """``{section: {key, …}}`` 全集，来自 ``config.toml.default``。"""
    data = tomllib.loads(TOML_TEMPLATE.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for sec, body in data.items():
        if isinstance(body, dict):
            out[sec] = set(body.keys())  # ty: ignore[invalid-assignment]
    return out


def _iter_docs() -> list[Path]:
    """所有需要扫的 ``docs/**/*.md``。"""
    out: list[Path] = []
    for p in DOCS_DIR.rglob("*.md"):
        sp = str(p).replace("\\", "/")
        if any(frag in sp for frag in _EXCLUDED_DIR_FRAGMENTS):
            continue
        if p.name in _EXCLUDED_NAMES:
            continue
        out.append(p)
    return out


class TestConfigDocsInlineParity(unittest.TestCase):
    def setUp(self) -> None:
        self.toml_sections = _load_toml_sections()
        sections_re = "|".join(re.escape(s) for s in self.toml_sections)
        # 反引号包裹的 ``<section>.<key>``。section 限定为 TOML 模板真实
        # 顶层名，key 是小写 snake_case。
        self.inline_re = re.compile(r"`(" + sections_re + r")\.([a-z_][a-z0-9_]*)`")
        # ``<section>`` 任意小写 snake_case 名，用于"section 名错"反查：
        # 出现 ``web_ui.bind_interface`` 时，我们要能定位到 ``bind_interface``
        # 真实属于哪个 section（network_security）。
        self.key_to_section: dict[str, str] = {}
        for sec, keys in self.toml_sections.items():
            for k in keys:
                # 同名 key 出现在多个 section 是合法的（罕见），保留任一即可——
                # 失败信息会列举所有可能 section。
                self.key_to_section.setdefault(k, sec)

    def _sections_owning_key(self, key: str) -> list[str]:
        """返回真正声明 ``key`` 的 section 列表，用于在失败信息里建议正确写法。"""
        return sorted(sec for sec, keys in self.toml_sections.items() if key in keys)

    def test_section_set_matches_toml_top_level(self) -> None:
        """元测试：测试代码用到的 ``self.toml_sections`` 不是空且与 TOML 一致。

        这个测试看似 trivial，实际防的是"项目新增 ``[security]`` 之类
        section、但 ``config.toml.default`` 没真实声明（只在 docstring 里讨论）"
        这种二级漂移。
        """
        self.assertGreater(
            len(self.toml_sections),
            0,
            "config.toml.default 必须至少声明 1 个 [section]，否则本测试覆盖空集",
        )
        # 至少要包含核心 5 大 section（核心契约）
        for required in ("web_ui", "feedback", "notification"):
            self.assertIn(
                required,
                self.toml_sections,
                f"核心 section [{required}] 在 config.toml.default 中缺失",
            )

    def test_no_undeclared_inline_refs(self) -> None:
        """主断言：``docs/*.md`` 反引号 inline 写的每个 ``<section>.<key>`` 都必须
        真在 ``config.toml.default`` 里声明。"""
        drifts: dict[str, list[tuple[str, int, str]]] = {}
        for path in _iter_docs():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for m in self.inline_re.finditer(line):
                    sec, key = m.group(1), m.group(2)
                    # 排除文件后缀类（``web_ui.py`` / ``server.py`` 类引用）
                    if key in _FILE_EXT_LIKE_KEYS:
                        continue
                    if key not in self.toml_sections.get(sec, set()):
                        ref = f"{sec}.{key}"
                        drifts.setdefault(ref, []).append(
                            (str(path.relative_to(REPO_ROOT)), lineno, line.strip())
                        )

        if drifts:
            lines = ["docs 散文中提到了 config.toml.default 未声明的 `section.key`："]
            for ref, locs in sorted(drifts.items()):
                sec, key = ref.split(".", 1)
                owners = self._sections_owning_key(key)
                if owners:
                    suggestion = (
                        f"  └─ `{key}` 实际声明在 [{', '.join(owners)}]，"
                        f"docs 应改写为 `{owners[0]}.{key}`"
                    )
                else:
                    suggestion = f"  └─ `{key}` 在所有 section 中均未声明 —— 可能是错别字 / 已删除"
                lines.append(f"\n• `{ref}`")
                lines.append(suggestion)
                for fp, ln, snippet in locs[:5]:
                    lines.append(f"     @ {fp}:{ln}: {snippet[:120]}")
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
