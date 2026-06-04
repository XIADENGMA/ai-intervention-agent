"""cr36 §8 #1 — CHANGELOG.md freshness invariant.

调用 ``scripts/check_changelog_freshness.py``（必须存在 + 必须报告
clean）来确保 CHANGELOG.md 永远跟 git tag 同步。

如果未来某次发版（``git tag vX.Y.Z``）后没记 CHANGELOG，此测试 fail；
如果未来某次 release branch 积压未 doc 的工作，此测试也 fail。
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_changelog_freshness.py"


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
            ["python", str(SCRIPT)],
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
            ["python", str(SCRIPT), "--strict"],
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
        """临时把 ``## [Unreleased]`` 改名为 ``## [Foo]``，script 必须报警。"""
        changelog = REPO_ROOT / "CHANGELOG.md"
        original = changelog.read_text(encoding="utf-8")
        broken = original.replace("## [Unreleased]", "## [TEMPORARILY_BROKEN]", 1)
        if broken == original:
            # 没找到 Unreleased，跳过 — repo 状态非测试所设计的标准形态
            self.skipTest("no [Unreleased] section in CHANGELOG; skip drift sim")

        try:
            changelog.write_text(broken, encoding="utf-8")
            result = subprocess.run(
                ["python", str(SCRIPT), "--strict"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            # strict + drift → exit 1
            self.assertEqual(
                result.returncode, 1, f"strict 应检测到 drift；stdout={result.stdout!r}"
            )
            self.assertIn("DRIFT", result.stdout)
        finally:
            changelog.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
