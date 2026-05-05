"""
``scripts/check_tag_push_safety.py`` 的单元测试。

锁定 R19.1 的 GitHub 3-tag 硬限制防护逻辑。这些测试故意 mock 掉
``_run_git`` 而不调用真实 git——本工具的行为完全由 git 输出决定，把
git 隔离掉之后我们可以稳定地复现 0/1/2/3/4/5/N tag 的边界场景，避
免依赖 CI runner 当前 git 仓库的实际 tag 状态。

锁定的不变量：
- 本地 == 远端：exit 0，不打印 unpushed 列表
- 本地有 1–threshold 个未推送：exit 0，提示但不报错
- 本地有 threshold+1 及以上：exit 1，stderr 列出每个 tag + 修复建议
- git 不可用：exit 2（与业务级 fail exit=1 区分开）
- 远端 ``ls-remote`` 返回 ``^{}`` dereference 行：去重后只算一次（不
  会因为 annotated tag 多算一次而虚标"已推送"或"未推送"）
- 非 SemVer 形态（``v1.5``、``foo``、``1.5.0`` 缺 ``v`` 前缀等）：被
  正则过滤掉，不会污染 ``unpushed`` 集合
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from scripts import check_tag_push_safety as mod


def _make_git_output(
    local: list[str], remote_with_dereferences: list[str]
) -> mock.Mock:
    """构造一个能根据 git 子命令返回不同 stdout 的 ``_run_git`` mock。"""

    def _side_effect(args: list[str]) -> str:
        if args[:2] == ["tag", "-l"]:
            return "\n".join(local) + ("\n" if local else "")
        if args[:2] == ["ls-remote", "--tags"]:
            lines = []
            for ref in remote_with_dereferences:
                # 用真实的 SHA 占位（40 hex），格式严格按 git ls-remote 输出
                sha = "0" * 40
                lines.append(f"{sha}\trefs/tags/{ref}")
            return "\n".join(lines) + ("\n" if lines else "")
        raise AssertionError(f"unexpected git args: {args}")

    return mock.Mock(side_effect=_side_effect)


class TestCheckBehaviour:
    def test_no_unpushed_tags_returns_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """本地 == 远端时 exit 0，不打 unpushed 列表。"""
        with mock.patch.object(
            mod,
            "_run_git",
            _make_git_output(
                local=["v1.5.20", "v1.5.21"],
                remote_with_dereferences=[
                    "v1.5.20",
                    "v1.5.20^{}",
                    "v1.5.21",
                    "v1.5.21^{}",
                ],
            ),
        ):
            rc = mod._check()
        assert rc == 0
        captured = capsys.readouterr()
        assert "OK" in captured.out
        assert "未推送" not in captured.err

    def test_three_unpushed_tags_passes_at_threshold(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """正好 3 个未推送（阈值边界）：exit 0，提示但不报错。"""
        with mock.patch.object(
            mod,
            "_run_git",
            _make_git_output(
                local=["v1.5.20", "v1.5.21", "v1.5.22", "v1.5.23"],
                remote_with_dereferences=["v1.5.20"],
            ),
        ):
            rc = mod._check()
        assert rc == 0
        captured = capsys.readouterr()
        assert "OK" in captured.out
        assert "v1.5.21" in captured.out
        assert "v1.5.23" in captured.out

    def test_four_unpushed_tags_fails_above_threshold(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """4 个未推送：exit 1，stderr 列出 tag + 修复建议。

        锁定：这是 v1.5.24 真实复现的场景（v1.5.20 / v1.5.21 / v1.5.23 /
        v1.5.24 同时未推送，触发 GitHub 3-tag 硬限制，Release workflow
        静默不触发）。
        """
        with mock.patch.object(
            mod,
            "_run_git",
            _make_git_output(
                local=["v1.5.20", "v1.5.21", "v1.5.23", "v1.5.24"],
                remote_with_dereferences=[],
            ),
        ):
            rc = mod._check()
        assert rc == 1
        captured = capsys.readouterr()
        # stderr 必须列出每个未推送 tag
        for tag in ("v1.5.20", "v1.5.21", "v1.5.23", "v1.5.24"):
            assert tag in captured.err
        # 必须包含 GitHub 限制说明 + 修复命令模板
        assert "webhook" in captured.err.lower() or "限制" in captured.err
        assert "git push origin v1.5.20" in captured.err

    def test_custom_threshold_zero_fails_on_any_unpushed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--threshold 0`` 时任何未推送 tag 都报错（用于严格 release gate）。"""
        with mock.patch.object(
            mod,
            "_run_git",
            _make_git_output(
                local=["v1.5.20"],
                remote_with_dereferences=[],
            ),
        ):
            rc = mod._check(threshold=0)
        assert rc == 1
        captured = capsys.readouterr()
        assert "v1.5.20" in captured.err

    def test_dereferenced_remote_refs_deduplicated(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """远端 ``ls-remote`` 输出含 ``^{}`` dereference 行：去重，不重复计数。

        Annotated tag 在 ``git ls-remote --tags`` 中会出现两行（一行是
        tag object 本身，一行是 ``<tag>^{}`` 指向 commit），如果工具把
        ``^{}`` 也当成独立 tag，集合差集会出错。锁定去 ``^{}`` 后缀逻辑。
        """
        with mock.patch.object(
            mod,
            "_run_git",
            _make_git_output(
                local=["v1.5.24"],
                remote_with_dereferences=["v1.5.24", "v1.5.24^{}"],
            ),
        ):
            rc = mod._check()
        assert rc == 0
        captured = capsys.readouterr()
        assert "OK" in captured.out
        assert "未推送" not in captured.err

    def test_non_semver_tags_filtered_from_local_and_remote(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """非 SemVer 形态（``v1.5``、``foo``、``1.5.0``）被正则过滤掉。

        锁定：``_SEMVER_TAG_RE`` 的过滤面足够窄，不会把 lightweight 历史
        tag 或开发者打的 wip tag 计入 unpushed。
        """
        with mock.patch.object(
            mod,
            "_run_git",
            _make_git_output(
                local=["v1.5.24", "v1.5", "foo", "1.5.0", "wip-feature"],
                remote_with_dereferences=["v1.5.24"],
            ),
        ):
            rc = mod._check()
        assert rc == 0
        captured = capsys.readouterr()
        assert "OK" in captured.out
        # 确保非 SemVer tag 不出现在任何输出中
        assert "v1.5\n" not in captured.out
        assert "foo" not in captured.out

    def test_pre_release_tags_accepted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``v1.5.24-rc.1`` 等 pre-release 形态被识别（与 ``bump_version.py`` 接受的
        SemVer 集合保持一致）。"""
        with mock.patch.object(
            mod,
            "_run_git",
            _make_git_output(
                local=["v1.5.24-rc.1", "v1.5.24"],
                remote_with_dereferences=["v1.5.24"],
            ),
        ):
            rc = mod._check()
        assert rc == 0
        captured = capsys.readouterr()
        assert "v1.5.24-rc.1" in captured.out


class TestEnvironmentErrors:
    def test_git_not_installed_returns_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``FileNotFoundError`` → exit 2（与业务级 1 区分）。"""
        with mock.patch.object(mod, "_run_git", side_effect=FileNotFoundError("git")):
            rc = mod._check()
        assert rc == 2
        captured = capsys.readouterr()
        assert "git" in captured.err.lower()

    def test_git_subprocess_error_returns_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``subprocess.CalledProcessError`` → exit 2（git 仓库不存在 / origin
        不可达 / 网络错等都归这一类）。"""
        err = subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "ls-remote", "--tags", "origin"],
            output="",
            stderr="fatal: 'origin' does not appear to be a git repository\n",
        )
        with mock.patch.object(mod, "_run_git", side_effect=err):
            rc = mod._check()
        assert rc == 2
        captured = capsys.readouterr()
        assert "exit 128" in captured.err
        assert "origin" in captured.err


class TestSemverSortKey:
    def test_sort_orders_by_numeric_components(self) -> None:
        """排序 key：按 MAJOR.MINOR.PATCH 数值排，非按字典序。

        关键防回归：字典序会把 ``v1.5.10`` 排在 ``v1.5.2`` 之前——这会让
        修复建议的 "逐个 push" 顺序错乱（跳号 push 不影响功能但不符合
        "按版本顺序发布" 的人类预期）。
        """
        tags = ["v1.5.2", "v1.5.10", "v1.5.1", "v1.4.20"]
        sorted_tags = sorted(tags, key=mod._semver_key)
        assert sorted_tags == ["v1.4.20", "v1.5.1", "v1.5.2", "v1.5.10"]

    def test_pre_release_sorts_after_release_in_strict_string_compare(self) -> None:
        """``v1.5.24-rc.1`` 与 ``v1.5.24``：按 (1, 5, 24, "rc.1") vs
        (1, 5, 24, "")，元组比较 "" < "rc.1"，所以 release 排在 pre 前面。

        SemVer 规范实际是 pre-release < release（``-rc.1`` 应该排在 ``-`` 前），
        本工具按字符串 ``""`` < ``"rc.1"`` 反向排——但这只影响 "修复建议
        的 push 顺序"，不影响发布正确性。锁定当前行为，未来若改成严格
        SemVer 排序时这个测试会失败提醒。
        """
        tags = ["v1.5.24-rc.1", "v1.5.24"]
        sorted_tags = sorted(tags, key=mod._semver_key)
        assert sorted_tags == ["v1.5.24", "v1.5.24-rc.1"]


class TestMainCli:
    def test_main_passes_threshold_to_check(self) -> None:
        """``--threshold N`` 必须传给 ``_check``。"""
        with mock.patch.object(mod, "_check", return_value=0) as m:
            rc = mod.main(["--threshold", "5"])
        assert rc == 0
        m.assert_called_once_with(threshold=5, remote="origin")

    def test_main_passes_remote_to_check(self) -> None:
        """``--remote NAME`` 必须传给 ``_check``。"""
        with mock.patch.object(mod, "_check", return_value=0) as m:
            rc = mod.main(["--remote", "upstream"])
        assert rc == 0
        m.assert_called_once_with(threshold=3, remote="upstream")

    def test_main_rejects_negative_threshold(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--threshold -1`` → exit 2（业务校验失败）。"""
        rc = mod.main(["--threshold", "-1"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "负数" in captured.err
