"""R840 回归护栏：插件只发布在 Open VSX，仓库里没有地方再说它在 VS Code Marketplace 上。

背景
----
插件从来没有发布到 Visual Studio Marketplace（维护者没有开通发布账号，也不打算做；Open VSX 够用）。
但仓库里一直留着这条渠道的痕迹：

* 两份 README 的安装行链到 ``marketplace.visualstudio.com`` 上的插件页。实测它返回 404，Marketplace 的
  查询接口对 ``xiadengma.ai-intervention-agent`` 返回 0 个扩展，也就是一条死链；
* ``release.yml`` 里有一个 ``vscode-marketplace`` job，没配 ``VSCE_PAT`` 时每次发布只打印一条“跳过”提示；
* SECURITY、SUPPORT、issue 模板的“安装渠道”、发布恢复文档、发布清单、tag 推送提示，都把 Marketplace
  当成真实存在的发布渠道；
* README 里“5 个 job”的数字（R233 拿它和 ``release.yml`` 的 job 数对账）把这个空转的 job 也算了进去。

现在这个 job 已删除，文字改成 Open VSX 加 GitHub Releases 里的 VSIX，README 还写明了：Microsoft 的
VS Code 自带的扩展视图搜不到它，要下载 ``.vsix`` 再用 *Extensions: Install from VSIX...* 安装。

本文件锁住：``release.yml`` 只有四个 job 且没有 Marketplace 发布步骤或 ``VSCE_PAT``；用户会读到的那些文件里
没有 “marketplace” 字样；没有任何文件链到本插件在 Marketplace 上的页面；四份 README 都写了怎么用 VSIX 安装。
检查器本身各带一个“应当报出”的坏样例和一个“应当放过”的普通文本，免得它空转。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
OPEN_VSX_PAGE = "open-vsx.org/extension/xiadengma/ai-intervention-agent"

# 这些文件里不该再出现 "marketplace"：它们是用户、贡献者和发布流程会读到的地方。
CLEAN_FILES = (
    ROOT / "README.md",
    ROOT / "README.zh-CN.md",
    ROOT / "packages" / "vscode" / "README.md",
    ROOT / "packages" / "vscode" / "README.zh-CN.md",
    ROOT / ".github" / "SECURITY.md",
    ROOT / ".github" / "SECURITY.zh-CN.md",
    ROOT / ".github" / "SUPPORT.md",
    ROOT / ".github" / "SUPPORT.zh-CN.md",
    ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml",
    RELEASE_WORKFLOW,
    ROOT / "docs" / "release-recovery.md",
    ROOT / "docs" / "release-recovery.zh-CN.md",
    ROOT / "docs" / "release-checklist.md",
    ROOT / "docs" / "workflow.md",
    ROOT / "docs" / "workflow.zh-CN.md",
    ROOT / "docs" / "troubleshooting.md",
    ROOT / "docs" / "troubleshooting.zh-CN.md",
    ROOT / "scripts" / "check_tag_push_safety.py",
)

# 这四份 README 都要告诉读者怎么用 VSIX 安装，并指向 Open VSX 上的页面。
README_FILES = (
    ROOT / "README.md",
    ROOT / "README.zh-CN.md",
    ROOT / "packages" / "vscode" / "README.md",
    ROOT / "packages" / "vscode" / "README.zh-CN.md",
)

# 链到本插件在 Marketplace 上页面的写法（别人家的扩展链接，比如 i18n-ally，不算）。
LISTING_LINK = re.compile(
    r"marketplace\.visualstudio\.com/items\?itemName=xiadengma\.", re.IGNORECASE
)
MARKETPLACE_WORD = re.compile(r"marketplace", re.IGNORECASE)
PUBLISH_TO_MARKETPLACE = re.compile(r"VSCE_PAT|vsce\s+publish", re.IGNORECASE)


def marketplace_mentions(text: str) -> list[str]:
    """文本里每一处 “marketplace” 字样（大小写不论）。"""
    return [m.group(0) for m in MARKETPLACE_WORD.finditer(text)]


def text_files_that_may_link() -> list[Path]:
    """可能放链接的文本：根目录的 md、docs、.github、两个扩展目录的 md 和 package.json、pyproject。"""
    found: list[Path] = [*ROOT.glob("*.md"), ROOT / "pyproject.toml"]
    found += list((ROOT / "docs").rglob("*.md"))
    found += [p for p in (ROOT / ".github").rglob("*") if p.is_file()]
    found += list((ROOT / "packages" / "vscode").glob("*.md"))
    found.append(ROOT / "packages" / "vscode" / "package.json")
    return sorted(set(found))


class TestTheReleaseWorkflowPublishesToOpenVsxOnly:
    def test_four_jobs_and_none_of_them_is_a_marketplace_job(self) -> None:
        jobs = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
        assert set(jobs) == {"build", "publish", "github-release", "open-vsx"}

    def test_no_step_publishes_with_vsce_or_reads_vsce_pat(self) -> None:
        text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        assert PUBLISH_TO_MARKETPLACE.findall(text) == []

    def test_open_vsx_is_still_published_to(self) -> None:
        jobs = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
        commands = "\n".join(step.get("run", "") for step in jobs["open-vsx"]["steps"])
        assert re.search(r"npx --yes ovsx@\S+ publish\b", commands)


class TestNoTextCallsTheExtensionAMarketplaceListing:
    def test_the_files_to_check_exist(self) -> None:
        missing = [str(p.relative_to(ROOT)) for p in CLEAN_FILES if not p.is_file()]
        assert missing == []

    def test_the_word_marketplace_is_not_in_them(self) -> None:
        found = {
            str(path.relative_to(ROOT)): marketplace_mentions(
                path.read_text(encoding="utf-8")
            )
            for path in CLEAN_FILES
        }
        assert {name: hits for name, hits in found.items() if hits} == {}

    def test_the_extension_changelog_header_does_not_name_it(self) -> None:
        # 版本记录里有 1.5.x 时代的历史条目，所以只检查第一个 "## " 之前的说明文字。
        text = (ROOT / "packages" / "vscode" / "CHANGELOG.md").read_text(
            encoding="utf-8"
        )
        header = text.split("\n## ", 1)[0]
        assert marketplace_mentions(header) == []

    def test_no_file_links_to_the_listing(self) -> None:
        files = text_files_that_may_link()
        assert len(files) > 100, "the scan should cover the docs and .github trees"
        linking = [
            str(p.relative_to(ROOT))
            for p in files
            if LISTING_LINK.search(p.read_text(encoding="utf-8", errors="replace"))
        ]
        assert linking == []

    def test_the_checker_finds_the_word_in_any_case(self) -> None:
        assert marketplace_mentions("VS Code Marketplace and the MARKETPLACE") == [
            "Marketplace",
            "MARKETPLACE",
        ]

    def test_the_checker_finds_a_listing_link(self) -> None:
        link = "[x](https://marketplace.visualstudio.com/items?itemName=xiadengma.ai-intervention-agent)"
        assert LISTING_LINK.search(link)

    def test_the_checker_leaves_other_extensions_and_open_vsx_alone(self) -> None:
        other = "https://marketplace.visualstudio.com/items?itemName=Lokalise.i18n-ally"
        assert LISTING_LINK.search(other) is None
        assert marketplace_mentions(f"Open VSX: https://{OPEN_VSX_PAGE}") == []


class TestEveryReadmeSaysHowToInstallTheVsix:
    def test_each_readme_links_the_open_vsx_page_and_names_the_vsix_command(
        self,
    ) -> None:
        lacking = []
        for path in README_FILES:
            text = path.read_text(encoding="utf-8")
            if OPEN_VSX_PAGE not in text or "Install from VSIX" not in text:
                lacking.append(str(path.relative_to(ROOT)))
        assert lacking == []
