"""cr36 §8 #1 — CHANGELOG.md freshness invariant.

调用 ``scripts/check_changelog_freshness.py``（必须存在 + 必须报告
clean）来确保 CHANGELOG.md 永远跟 git tag 同步。

如果未来某次发版（``git tag vX.Y.Z``）后没记 CHANGELOG，此测试 fail；
如果未来某次 release branch 积压未 doc 的工作，此测试也 fail。
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_changelog_freshness.py"
# R269 / cycle-22 polish: bare ``"python"`` 在某些环境（macOS Homebrew
# 默认 / fish-shell / 用 `uv run` 跑 test）没有 PATH lookup, 找不到
# top-level binary → ``FileNotFoundError`` 让 3 个 freshness invariant
# 在本地全部 fail，但 CI（含 Linux /usr/bin/python symlink）能 pass。
# 用 ``sys.executable`` 直接指向当前解释器路径 = 无论本地还是 CI 都
# 找得到，且保证子进程和父进程跑同一个 Python 版本。
PYTHON_BIN = sys.executable


class TestScriptExists(unittest.TestCase):
    def test_script_present_and_executable(self) -> None:
        self.assertTrue(SCRIPT.exists(), f"missing {SCRIPT}")
        # 不强制 chmod +x（CI 环境差异），但 shebang 必须正确
        first_line = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(
            first_line.startswith("#!/"),
            f"script 第一行应是 shebang，实际：{first_line!r}",
        )

    def test_script_has_strict_flag(self) -> None:
        """``--strict`` 必须 expose 出来供 CI 升级使用。"""
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"--strict"', src)


class TestRunsCleanOnHead(unittest.TestCase):
    """Mutation-style invariant: this very repo必须在 HEAD 状态下
    pass check_changelog_freshness.py default mode (即不抛 issue)。
    """

    def test_head_passes_default_mode(self) -> None:
        result = subprocess.run(
            [PYTHON_BIN, str(SCRIPT)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"check exit code 应为 0, 实际 {result.returncode}\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )
        # default mode 输出必须包含 OK 标志
        self.assertIn(
            "OK",
            result.stdout,
            f"default mode 应输出 OK，实际 stdout: {result.stdout!r}",
        )

    def test_head_passes_strict_mode(self) -> None:
        """如果 default mode pass 了，strict mode 必须也 pass —— 否则
        说明 ``check_changelog_freshness.py`` 有 bug（issue 列表不为空
        但 default 仍判 OK）。
        """
        result = subprocess.run(
            [PYTHON_BIN, str(SCRIPT), "--strict"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"strict mode 应 exit 0, 实际 {result.returncode}\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}",
        )


class TestDetectsActualDrift(unittest.TestCase):
    """启发式：把 CHANGELOG.md 临时改坏，确认 script 真能检测到。
    用 git stash 方式做隔离 — 测试结束恢复。
    """

    def test_detects_missing_unreleased(self) -> None:
        """临时把 ``## [Unreleased]`` 改名 + 把最新 tag section header 也改名，
        script 必须报警（覆盖 check #1 ``CHANGELOG 缺 latest tag section``，
        不依赖 HEAD-vs-tag commit 差，避免 immediate-post-release tag-cut
        瞬态下假阴性）。
        """
        changelog = REPO_ROOT / "CHANGELOG.md"
        original = changelog.read_text(encoding="utf-8")

        # 找当前最新 git tag，rename 它的 CHANGELOG section → 必触发 check #1
        try:
            latest_tag = (
                subprocess.run(
                    ["git", "tag", "-l", "--sort=-v:refname"],
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.strip()
                .splitlines()[0]
            )
        except (subprocess.CalledProcessError, IndexError):
            self.skipTest("no git tag in repo; check #1 mutation not applicable")
            return

        latest_version = latest_tag.lstrip("v")
        broken = original.replace(
            f"## [{latest_version}]", "## [TEMP_HIDDEN_VERSION]", 1
        )
        broken = broken.replace("## [Unreleased]", "## [TEMPORARILY_BROKEN]", 1)
        if broken == original:
            self.skipTest(
                f"no [{latest_version}] or [Unreleased] section to mutate; "
                "repo state outside test design"
            )

        try:
            changelog.write_text(broken, encoding="utf-8")
            result = subprocess.run(
                [PYTHON_BIN, str(SCRIPT), "--strict"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                1,
                f"strict 应检测到 drift；stdout={result.stdout!r}",
            )
            self.assertIn("DRIFT", result.stdout)
        finally:
            changelog.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
