"""R842 回归护栏：Dependabot 的 PR 上的 review 请求来自 CODEOWNERS，``dependabot.yml`` 里不再写 ``reviewers``。

背景
----
``dependabot.yml`` 的 ``reviewers:`` 选项已被 GitHub 移除：2025-04-29 的 changelog
"Dependabot reviewers configuration option being replaced by code owners" 宣布了这件事，理由是它和
code owners 的功能重叠、会造成 review 指派冲突，建议只用 CODEOWNERS。本仓库的三个生态以前各写了一份
``reviewers: ['xiadengma']``，早就没有任何作用：2026-10-23 推送之后 Dependabot 新开的 #127、#128、#129
上，``gh pr view --json reviewRequests`` 里的 review 请求（``XIADENGMA``）实际来自
``.github/CODEOWNERS`` 的 ``* @xiadengma``。留着一个已经失效的选项，会让人以为改它的值就能改变谁来审，
而真正起作用的 CODEOWNERS 反而没人看。

现在：

* ``dependabot.yml`` 的 ``updates`` 里不再出现 ``reviewers``；
* ``.github/CODEOWNERS`` 是唯一的来源，所以它必须有一条给所有路径指定 owner 的 ``*`` 规则，并且之后没有
  哪条规则把 owner 清空——GitHub 里后面的规则覆盖前面的，没有 owner 的规则等于让这些文件不再请求 review。

``assignees`` 仍然有效，不在这里禁止。检查器本身也各带“应当报错”的反例和“应当放过”的普通文本，免得它空转。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEPENDABOT_YML = ROOT / ".github" / "dependabot.yml"
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"

# CODEOWNERS 里 owner 的三种写法：@用户、@组织/团队、邮箱。
OWNER = re.compile(
    r"^(?:@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:/[A-Za-z0-9_.-]+)?"
    r"|[^@\s]+@[^@\s]+\.[^@\s]+)$"
)


def removed_options(text: str) -> list[str]:
    """``dependabot.yml`` 的每个生态里还在用的、GitHub 已经移除的选项；空列表表示没有。"""
    config = yaml.safe_load(text)
    problems: list[str] = []
    for update in config.get("updates", []):
        if "reviewers" in update:
            problems.append(
                f"{update.get('package-ecosystem')}: 'reviewers' was removed by GitHub; "
                "review requests come from .github/CODEOWNERS"
            )
    return problems


def codeowners_problems(text: str) -> list[str]:
    """CODEOWNERS 里会让某些路径收不到 review 请求的写法；空列表表示没问题。"""
    rules: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        rules.append((pattern, owners))

    problems: list[str] = []
    if not any(pattern == "*" and owners for pattern, owners in rules):
        problems.append("no '*' rule with an owner: some paths get no review request")
    for pattern, owners in rules:
        if not owners:
            problems.append(
                f"{pattern!r} has no owner, which switches review requests off for it"
            )
        problems.extend(
            f"{pattern!r}: {owner!r} is not an @user, an @org/team or an e-mail address"
            for owner in owners
            if not OWNER.match(owner)
        )
    return problems


class TestDependabotDoesNotUseTheRemovedOption:
    def test_the_real_file_has_none(self) -> None:
        assert removed_options(DEPENDABOT_YML.read_text(encoding="utf-8")) == []

    def test_the_three_ecosystems_are_still_there(self) -> None:
        # 防止“清掉 reviewers”顺手把整个生态条目删了。
        config = yaml.safe_load(DEPENDABOT_YML.read_text(encoding="utf-8"))
        assert [u["package-ecosystem"] for u in config["updates"]] == [
            "pip",
            "github-actions",
            "npm",
        ]

    def test_the_checker_reports_every_entry_that_has_it(self) -> None:
        bad = (
            "version: 2\nupdates:\n"
            "  - package-ecosystem: pip\n    reviewers:\n      - a\n"
            "  - package-ecosystem: npm\n    labels: [x]\n"
            "  - package-ecosystem: github-actions\n    reviewers:\n      - b\n"
        )
        assert removed_options(bad) == [
            "pip: 'reviewers' was removed by GitHub; review requests come from .github/CODEOWNERS",
            "github-actions: 'reviewers' was removed by GitHub; review requests come from .github/CODEOWNERS",
        ]

    def test_the_checker_leaves_comments_and_other_keys_alone(self) -> None:
        fine = (
            "version: 2\n# reviewers: gone, see CODEOWNERS\nupdates:\n"
            "  - package-ecosystem: pip\n    labels: [reviewers]\n    assignees:\n      - a\n"
        )
        assert removed_options(fine) == []


class TestCodeownersIsTheSourceOfReviewRequests:
    def test_the_real_file_has_no_problems(self) -> None:
        assert codeowners_problems(CODEOWNERS.read_text(encoding="utf-8")) == []

    def test_the_checker_wants_a_rule_for_every_path(self) -> None:
        assert codeowners_problems("/docs/ @a\n") == [
            "no '*' rule with an owner: some paths get no review request"
        ]

    def test_the_checker_wants_an_owner_on_the_catch_all_rule(self) -> None:
        assert codeowners_problems("*\n") == [
            "no '*' rule with an owner: some paths get no review request",
            "'*' has no owner, which switches review requests off for it",
        ]

    def test_the_checker_reports_a_later_rule_without_an_owner(self) -> None:
        assert codeowners_problems("* @a\n/docs/\n") == [
            "'/docs/' has no owner, which switches review requests off for it"
        ]

    def test_the_checker_reports_an_owner_that_is_not_one(self) -> None:
        assert codeowners_problems("* a\n") == [
            "'*': 'a' is not an @user, an @org/team or an e-mail address"
        ]

    def test_the_checker_accepts_the_ordinary_forms(self) -> None:
        fine = (
            "# a comment\n\n* @a @org/team-1 b@example.com  # trailing comment\n"
            "/docs/ @a\n"
        )
        assert codeowners_problems(fine) == []
