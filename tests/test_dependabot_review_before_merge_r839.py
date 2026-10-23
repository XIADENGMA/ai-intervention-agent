"""R839 回归护栏：Dependabot 的 PR 只由人合并，版本更新每月检查一次。

背景
----
以前 ``.github/workflows/dependabot-auto-merge.yml`` 对 patch / minor 的 Dependabot PR 执行
``gh pr merge --auto --squash``。仓库没有开 "Allow auto-merge"，``main`` 的 ruleset 也没有必需检查，
所以这条命令是**立刻合并**，不等 CI：#113 到 #126 这 8 个 Dependabot PR（2026-09-28 至 2026-10-19）
都在开出 17–24 秒后就被合并，而一轮 ``Tests`` 要跑好几分钟；跑完时这 8 个的 Python 3.11 全是红的，
#123 和 #126 的 3.12、3.13 也是红的。结果是 ``origin/main`` 每周凭空多 1–3 个本地没有的提交，
本地有未推送提交的人必须先 ``git pull --rebase``。

现在：

* 删掉自动合并的 workflow，Dependabot 开出来的 PR 由人看过 CI 再合并；
* ``dependabot.yml`` 的三个生态（pip、github-actions、npm）都改成 ``monthly``（每月 1 日）；
  ``schedule.day`` 只对 ``weekly`` 有效，GitHub 的校验器会拒绝 monthly + day（Zcash Foundation 的
  zebra#10014 就是为这个报错删的 ``day``），所以 ``day`` 必须一起删；
* 安全更新不受 ``schedule`` 管，漏洞公布时照旧立刻开 PR。

本文件锁住：每个生态是 monthly 且没有 ``day``；没有任何 workflow 自己合并 PR；仓库里没有文字还在指向
已删除的 workflow。检查器本身也各带一个“应当报错”的反例，免得它空转。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEPENDABOT_YML = ROOT / ".github" / "dependabot.yml"
WORKFLOWS = ROOT / ".github" / "workflows"
REMOVED_WORKFLOW = "dependabot-auto-merge"

# 能让一个 workflow 自己合并 PR 的写法：gh CLI、REST、GraphQL 和两个常见的第三方 action。
MERGE_PATTERNS = (
    re.compile(r"\bgh\s+pr\s+merge\b"),
    re.compile(r"/pulls/[^\s\"']*/merge\b"),
    re.compile(r"\benablePullRequestAutoMerge\b"),
    re.compile(r"\bpullRequest\.merge\b|\bpulls\.merge\b"),
    re.compile(r"peter-evans/enable-pull-request-automerge"),
    re.compile(r"pascalgn/automerge-action"),
)

# 出现被删 workflow 的名字也算问题的地方：.github 下的文本，和两份发布恢复文档。
TEXT_PLACES = (
    *sorted((ROOT / ".github").rglob("*.yml")),
    *sorted((ROOT / ".github").rglob("*.md")),
    ROOT / "docs" / "release-recovery.md",
    ROOT / "docs" / "release-recovery.zh-CN.md",
)


def schedule_problems(text: str) -> list[str]:
    """``dependabot.yml`` 里每个生态的 schedule 有哪些问题；空列表表示没问题。"""
    config = yaml.safe_load(text)
    problems: list[str] = []
    for update in config.get("updates", []):
        ecosystem = update.get("package-ecosystem")
        schedule = update.get("schedule") or {}
        if schedule.get("interval") != "monthly":
            problems.append(
                f"{ecosystem}: interval is {schedule.get('interval')!r}, not 'monthly'"
            )
        if "day" in schedule:
            problems.append(f"{ecosystem}: 'day' is only valid for a weekly interval")
    return problems


def merge_commands(text: str) -> list[str]:
    """文本里能让 workflow 自己合并 PR 的写法。"""
    return [m.group(0) for pattern in MERGE_PATTERNS for m in pattern.finditer(text)]


class TestEveryEcosystemIsCheckedMonthly:
    def test_the_real_file_has_no_problems(self) -> None:
        assert schedule_problems(DEPENDABOT_YML.read_text(encoding="utf-8")) == []

    def test_the_three_ecosystems_are_still_there(self) -> None:
        config = yaml.safe_load(DEPENDABOT_YML.read_text(encoding="utf-8"))
        assert [u["package-ecosystem"] for u in config["updates"]] == [
            "pip",
            "github-actions",
            "npm",
        ]

    def test_the_time_of_day_is_kept(self) -> None:
        # monthly 仍然可以带 time / timezone；去掉它们会让 Dependabot 随机挑一个时间。
        config = yaml.safe_load(DEPENDABOT_YML.read_text(encoding="utf-8"))
        for update in config["updates"]:
            assert update["schedule"].get("time") == "09:00"
            assert update["schedule"].get("timezone") == "Asia/Shanghai"

    def test_the_checker_reports_a_weekly_schedule(self) -> None:
        bad = (
            "version: 2\nupdates:\n"
            "  - package-ecosystem: pip\n    schedule:\n      interval: weekly\n      day: monday\n"
        )
        assert schedule_problems(bad) == [
            "pip: interval is 'weekly', not 'monthly'",
            "pip: 'day' is only valid for a weekly interval",
        ]

    def test_the_checker_reports_a_day_on_a_monthly_schedule(self) -> None:
        bad = (
            "version: 2\nupdates:\n"
            "  - package-ecosystem: npm\n    schedule:\n      interval: monthly\n      day: monday\n"
        )
        assert schedule_problems(bad) == [
            "npm: 'day' is only valid for a weekly interval"
        ]


class TestNothingMergesAPullRequestOnItsOwn:
    def test_the_auto_merge_workflow_is_gone(self) -> None:
        assert not (WORKFLOWS / f"{REMOVED_WORKFLOW}.yml").exists()

    def test_no_workflow_has_a_way_to_merge(self) -> None:
        workflows = sorted(WORKFLOWS.glob("*.yml"))
        assert len(workflows) >= 8, "the workflows directory should not look empty"
        found = {
            path.name: merge_commands(path.read_text(encoding="utf-8"))
            for path in workflows
            if merge_commands(path.read_text(encoding="utf-8"))
        }
        assert found == {}

    def test_the_checker_finds_the_old_command(self) -> None:
        old = 'run: gh pr merge --auto --squash "$PR_URL"'
        assert merge_commands(old) == ["gh pr merge"]

    def test_the_checker_finds_the_other_ways(self) -> None:
        assert merge_commands("curl -X PUT /repos/o/r/pulls/7/merge") == [
            "/pulls/7/merge"
        ]
        assert merge_commands("mutation { enablePullRequestAutoMerge(input: {}) }") == [
            "enablePullRequestAutoMerge"
        ]
        assert merge_commands("uses: pascalgn/automerge-action@v0.16") == [
            "pascalgn/automerge-action"
        ]

    def test_the_checker_leaves_ordinary_text_alone(self) -> None:
        assert merge_commands("git merge --no-ff feature  # merge the branch") == []


class TestNothingPointsAtTheRemovedWorkflow:
    def test_the_places_to_look_exist(self) -> None:
        assert len(TEXT_PLACES) >= 10
        assert all(path.is_file() for path in TEXT_PLACES)

    def test_no_text_names_it(self) -> None:
        naming = [
            str(path.relative_to(ROOT))
            for path in TEXT_PLACES
            if REMOVED_WORKFLOW in path.read_text(encoding="utf-8")
        ]
        assert naming == []
