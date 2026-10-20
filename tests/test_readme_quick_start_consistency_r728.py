"""R728 / 增强二：README「Quick start」几处配置 + 页首导航行的一致性不变量。

背景
====

README（中英各一份）里，同一份 MCP 配置被手工抄写在好几个地方：

1. ``uvx`` JSON 片段（Quick start 里第一个 ``json`` 代码块）；
2. Cursor 一键安装徽章的 ``config=`` 参数（base64 编码的 JSON）；
3. VS Code 一键安装徽章的 ``url=`` 参数（两层 URL 编码的 JSON）；
4. 「让 AI 帮你完成配置」提示词里的 ``command / args / timeout / autoApprove`` 四行；
5. pip 备选片段（``command`` 不同，``timeout`` / ``autoApprove`` 应与 1 一致）。

改了其中一处（比如把 ``timeout`` 从 600 调到 900）却漏了别处，点徽章装出来的配置就
和文档写的不一样，而且不会有任何报错。R340 只管章节数量、图片数量和英文 markdown
语法的 ``](#anchor)``，不看这些抄写件。

同一轮还给两份 README 加了页首导航行（HTML ``<a href="#...">``）。R340 第 4 层只校验
英文版的 markdown 链接，管不到 HTML ``href`` 和中文版；GitHub 对中文标题会保留汉字
（``VS Code 插件（可选）`` → ``#vs-code-插件可选``），这里用同一条规则算出锚点再核对。

页首的徽章同样是手写的事实抄本：Python 版本徽章要和 ``requires-python`` 一致，License
徽章要和 ``pyproject.toml`` 的 ``license`` 一致，GitHub release 徽章要指向本仓库，语言
徽章要指向两份真实存在的 README 并标出当前语言。

契约
====

A. 导航行：每份 README 的页首（第一个 H2 之前）有至少 5 个页内锚点，每个都能对上同
   文档里真实存在的 H2；中英两份指向的 H2 顺序一致。
B. 配置抄写件：Cursor 徽章、VS Code 徽章、提示词四行都与 ``uvx`` 片段一致；pip 片段的
   ``timeout`` / ``autoApprove`` 与 ``uvx`` 片段一致；中英两份的 ``uvx`` 片段相同。
C. 提示词会被单独粘进聊天框，看不到这份 README，所以必须带上同语言 README 的 raw 链接。
D. pip 备选写的 Python 下限与 ``pyproject.toml`` 的 ``requires-python`` 一致。
E. 文档列表里有 SUPPORT / SECURITY 链接，目标文件存在。
F. 页首徽章：语言徽章指向两份存在的 README，图片文字与 ``alt`` 一致，当前语言用高亮色、
   另一种用灰色；Python / License / GitHub release 徽章与 ``pyproject.toml`` 对得上；
   中英两份的标签徽章（除语言徽章外）逐个相同。
"""

from __future__ import annotations

import base64
import json
import re
import tomllib
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]

LANGS = ("en", "zh-CN")
README = {"en": ROOT / "README.md", "zh-CN": ROOT / "README.zh-CN.md"}
QUICK_START_TITLE = {"en": "Quick start", "zh-CN": "快速开始"}
DOCUMENTATION_TITLE = {"en": "Documentation", "zh-CN": "文档"}
SERVER_NAME = "ai-intervention-agent"
RAW_BASE = "https://raw.githubusercontent.com/xiadengma/ai-intervention-agent/main/"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _text(lang: str) -> str:
    return README[lang].read_text(encoding="utf-8")


def _is_fence(line: str) -> bool:
    return line.lstrip().startswith("```")


def _h2_titles(text: str) -> list[str]:
    """围栏代码块外的所有 ``## `` 标题（不含 ``## `` 前缀）。"""
    titles: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _is_fence(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            titles.append(line[3:].strip())
    return titles


def _github_slug(title: str) -> str:
    """GitHub 标题锚点：转小写，去掉标点（保留字母、数字、下划线、连字符、汉字），空格换成连字符。

    与 ``github-slugger`` 对本仓库两份 README 全部 H2 的输出逐个核对过。
    """
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def _section(text: str, title_prefix: str) -> str:
    """以 ``## <title_prefix>`` 开头的章节正文（到下一个 H2 之前，围栏内容保留）。"""
    body: list[str] = []
    collecting = False
    in_fence = False
    for line in text.splitlines():
        if _is_fence(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            if collecting:
                break
            collecting = line[3:].strip().startswith(title_prefix)
            continue
        if collecting:
            body.append(line)
    assert body, f"section {title_prefix!r} not found"
    return "\n".join(body)


def _quick_start(lang: str) -> str:
    return _section(_text(lang), QUICK_START_TITLE[lang])


def _fenced_blocks(section: str, info: str) -> list[str]:
    return re.findall(rf"```{info}\n(.*?)\n```", section, flags=re.DOTALL)


def _must_match(pattern: str, text: str) -> re.Match[str]:
    match = re.search(pattern, text)
    assert match is not None, f"pattern not found: {pattern}"
    return match


def _server_entry(config_text: str) -> dict[str, Any]:
    config: dict[str, Any] = json.loads(config_text)
    servers: dict[str, Any] = config["mcpServers"]
    assert set(servers) == {SERVER_NAME}
    entry: dict[str, Any] = servers[SERVER_NAME]
    return entry


def _uvx_entry(lang: str) -> dict[str, Any]:
    return _server_entry(_fenced_blocks(_quick_start(lang), "json")[0])


def _pip_entry(lang: str) -> dict[str, Any]:
    return _server_entry(_fenced_blocks(_quick_start(lang), "json")[1])


def _cursor_payload(lang: str) -> tuple[str, dict[str, Any]]:
    match = _must_match(
        r"cursor\.com/en/install-mcp\?name=([^&\s)]+)&config=([^)\s]+)", _text(lang)
    )
    raw = base64.b64decode(urllib.parse.unquote(match.group(2)))
    payload: dict[str, Any] = json.loads(raw)
    return urllib.parse.unquote(match.group(1)), payload


def _vscode_payload(lang: str) -> dict[str, Any]:
    match = _must_match(r"vscode\.dev/redirect\?url=([^)\s]+)", _text(lang))
    decoded = urllib.parse.unquote(urllib.parse.unquote(match.group(1)))
    prefix = "vscode:mcp/install?"
    assert decoded.startswith(prefix), decoded
    payload: dict[str, Any] = json.loads(decoded[len(prefix) :])
    return payload


def _agent_prompt(lang: str) -> str:
    for block in _fenced_blocks(_quick_start(lang), "text"):
        if "autoApprove" in block:
            return block
    raise AssertionError("agent setup prompt not found in the Quick start section")


def _header(lang: str) -> str:
    """第一个 H2 之前的内容：居中的徽章区和导航行。"""
    return _text(lang).split("\n## ", 1)[0]


def _nav_anchors(lang: str) -> list[str]:
    return re.findall(r'<a href="#([^"]+)">', _header(lang))


def _pyproject() -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return data


def _python_floor() -> str:
    requires: str = _pyproject()["project"]["requires-python"]
    return _must_match(r">=\s*(\d+\.\d+)", requires).group(1)


def _shield_badges(lang: str) -> list[tuple[str, dict[str, str]]]:
    """页首所有 shields.io 徽章：``(链接, <img> 属性)``，按出现顺序。"""
    badges: list[tuple[str, dict[str, str]]] = []
    for href, attrs in re.findall(
        r'<a href="([^"]+)">\s*<img\b([^>]*?)/?>\s*</a>', _header(lang), re.DOTALL
    ):
        img = dict(re.findall(r'([\w-]+)="([^"]*)"', attrs))
        if img.get("src", "").startswith("https://img.shields.io/"):
            badges.append((href, img))
    return badges


def _badge_with(lang: str, src_fragment: str) -> tuple[str, dict[str, str]]:
    found = [b for b in _shield_badges(lang) if src_fragment in b[1]["src"]]
    assert len(found) == 1, f"[{lang}] expected one badge with {src_fragment!r}"
    return found[0]


# ---------------------------------------------------------------------------
# A. 导航行
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_nav_row_anchors_resolve_to_real_h2(lang: str) -> None:
    anchors = _nav_anchors(lang)
    assert len(anchors) >= 5, f"[{lang}] header nav row missing: {anchors}"
    assert len(set(anchors)) == len(anchors), f"[{lang}] duplicate nav anchors"
    slugs = [_github_slug(title) for title in _h2_titles(_text(lang))]
    dead = [anchor for anchor in anchors if anchor not in slugs]
    assert not dead, (
        f"[{lang}] nav anchors without a matching H2: {dead}; H2 slugs: {slugs}"
    )


def test_nav_rows_point_at_the_same_sections_in_both_languages() -> None:
    def targets(lang: str) -> list[int]:
        slugs = [_github_slug(title) for title in _h2_titles(_text(lang))]
        return [slugs.index(anchor) for anchor in _nav_anchors(lang)]

    assert targets("en") == targets("zh-CN")


# ---------------------------------------------------------------------------
# B. 配置抄写件
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_uvx_snippet_is_the_canonical_entry(lang: str) -> None:
    entry = _uvx_entry(lang)
    assert entry["command"] == "uvx"
    assert entry["args"] == [SERVER_NAME]
    assert isinstance(entry["timeout"], int)
    assert entry["autoApprove"] == ["interactive_feedback"]


def test_uvx_snippet_is_identical_in_both_languages() -> None:
    assert _uvx_entry("en") == _uvx_entry("zh-CN")


@pytest.mark.parametrize("lang", LANGS)
def test_cursor_badge_installs_the_snippet(lang: str) -> None:
    name, payload = _cursor_payload(lang)
    assert name == SERVER_NAME
    assert payload == _uvx_entry(lang)


@pytest.mark.parametrize("lang", LANGS)
def test_vscode_badge_installs_the_snippet(lang: str) -> None:
    assert _vscode_payload(lang) == {"name": SERVER_NAME, **_uvx_entry(lang)}


@pytest.mark.parametrize("lang", LANGS)
def test_pip_snippet_shares_timeout_and_auto_approve(lang: str) -> None:
    uvx, pip = _uvx_entry(lang), _pip_entry(lang)
    assert pip["command"] == SERVER_NAME
    assert pip["args"] == []
    assert pip["timeout"] == uvx["timeout"]
    assert pip["autoApprove"] == uvx["autoApprove"]


@pytest.mark.parametrize("lang", LANGS)
def test_agent_prompt_repeats_the_snippet(lang: str) -> None:
    prompt, entry = _agent_prompt(lang), _uvx_entry(lang)
    assert _must_match(r"- command: `([^`]+)`", prompt).group(1) == entry["command"]
    assert (
        json.loads(_must_match(r"- args: `([^`]+)`", prompt).group(1)) == entry["args"]
    )
    assert int(_must_match(r"- timeout: (\d+)", prompt).group(1)) == entry["timeout"]
    approved = json.loads(_must_match(r"- autoApprove: `([^`]+)`", prompt).group(1))
    assert approved == entry["autoApprove"]


# ---------------------------------------------------------------------------
# C. 提示词要带 README 链接
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_agent_prompt_links_the_readme_of_its_own_language(lang: str) -> None:
    prompt = _agent_prompt(lang)
    assert RAW_BASE + README[lang].name in prompt
    other = README["zh-CN" if lang == "en" else "en"].name
    assert RAW_BASE + other not in prompt


# ---------------------------------------------------------------------------
# D. Python 下限
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_pip_note_states_the_python_floor_from_pyproject(lang: str) -> None:
    assert f"Python {_python_floor()}" in _quick_start(lang)


# ---------------------------------------------------------------------------
# E. SUPPORT / SECURITY
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_documentation_lists_support_and_security(lang: str) -> None:
    suffix = "" if lang == "en" else ".zh-CN"
    documentation = _section(_text(lang), DOCUMENTATION_TITLE[lang])
    for stem in ("SUPPORT", "SECURITY"):
        relative = f".github/{stem}{suffix}.md"
        assert f"]({relative})" in documentation, f"[{lang}] {relative} not linked"
        assert (ROOT / relative).is_file(), f"{relative} does not exist"


# ---------------------------------------------------------------------------
# F. 页首徽章
# ---------------------------------------------------------------------------

LANGUAGE_BADGE_HREF = {"en": "./README.md", "zh-CN": "./README.zh-CN.md"}
LANGUAGE_BADGE_ALT = {"./README.md": "English", "./README.zh-CN.md": "简体中文"}
ACTIVE_COLOR, INACTIVE_COLOR = "BCDCF7", "CDCFD4"


@pytest.mark.parametrize("lang", LANGS)
def test_language_badges_link_both_readmes_and_mark_the_active_one(lang: str) -> None:
    shown = {
        href: img for href, img in _shield_badges(lang) if href in LANGUAGE_BADGE_ALT
    }
    assert set(shown) == set(LANGUAGE_BADGE_ALT), f"[{lang}] language badges missing"
    for href, img in shown.items():
        assert (ROOT / href).is_file(), f"{href} does not exist"
        assert img["alt"] == LANGUAGE_BADGE_ALT[href]
        assert img["height"] == "40"
        match = _must_match(
            r"^https://img\.shields\.io/badge/(.+)-([0-9A-Fa-f]{6})$", img["src"]
        )
        assert urllib.parse.unquote(match.group(1)) == img["alt"]
        expected = ACTIVE_COLOR if href == LANGUAGE_BADGE_HREF[lang] else INACTIVE_COLOR
        assert match.group(2).upper() == expected, f"[{lang}] wrong colour for {href}"


@pytest.mark.parametrize("lang", LANGS)
def test_python_badge_states_the_floor_from_pyproject(lang: str) -> None:
    _, img = _badge_with(lang, "/badge/Python-")
    version = urllib.parse.unquote(
        _must_match(r"/badge/Python-([^-]+)-", img["src"]).group(1)
    )
    assert version == f"{_python_floor()}+"
    assert img["alt"] == f"Python {version}"


@pytest.mark.parametrize("lang", LANGS)
def test_release_badge_points_at_this_repository(lang: str) -> None:
    urls: dict[str, str] = _pyproject()["project"]["urls"]
    repository = urls["Repository"].removeprefix("https://github.com/")
    href, img = _badge_with(lang, "/github/v/release/")
    assert f"/github/v/release/{repository}?" in img["src"]
    assert href == urls["Release notes"]


@pytest.mark.parametrize("lang", LANGS)
def test_license_badge_matches_pyproject_and_license_file(lang: str) -> None:
    license_id: str = _pyproject()["project"]["license"]
    href, img = _badge_with(lang, "/badge/License-")
    assert _must_match(r"/badge/License-([^-?]+)-", img["src"]).group(1) == license_id
    assert license_id in img["alt"]
    assert href.endswith("/blob/main/LICENSE")
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith(license_id)


def test_label_badges_are_the_same_in_both_languages() -> None:
    def labels(lang: str) -> list[tuple[str, str]]:
        return [
            (href, img["src"])
            for href, img in _shield_badges(lang)
            if href not in LANGUAGE_BADGE_ALT
        ]

    assert len(labels("en")) >= 6
    assert labels("en") == labels("zh-CN")
