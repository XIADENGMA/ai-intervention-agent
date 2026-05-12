"""R185：``scripts/check_tag_push_safety.py`` 的 CVE gate 契约。

闭合 CR#14 §F-4：在 tag push 前提供 local pre-push CVE 检查
（不放进 release.yml，因为 GitHub Actions 的 ``vulnerability-
alerts: read`` 权限是 2026-04 新加的、feature-flagged、runner
端尚未广泛 enable；本地 ``gh`` 用 user PAT 没有这个 gate）。

本套件覆盖五层：

1. **URL parsing 边界**：``_parse_origin_owner_repo`` 在 SSH /
   HTTPS / 带与不带 ``.git`` 后缀 / 非 GitHub host / 完全错乱
   的输入下都按合约返回。
2. **CVE 查询**：``_query_open_alerts`` 在 ``gh`` 不存在 /
   subprocess 失败 / JSON 解析失败 / 严重级过滤 等场景的行为。
3. **CVE gate 主流程**：``_check_cve_gate`` 在 ``gh`` 缺失 /
   远端不识别 / 拉取失败 / 0 alert / 1+ blocker 五个分支返回
   正确 exit code + alert 列表。
4. **CLI flags**：``--check-cve`` / ``--no-check-cve`` /
   ``--allow-cve`` / ``--cve-severity`` 的解析和默认值。
5. **端到端 ``main()``**：在 mock gh 的前提下跑真实 CLI，验证
   exit code、stderr 包含 "R185"、阻断/放行行为对齐。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module() -> ModuleType:
    """Load ``scripts/check_tag_push_safety.py`` by absolute path.

    与 R183 测试同款 ``importlib.util`` 加载，避开 ``sys.path``
    注入（``ty`` 无法静态识别 sys.path mutation）。
    """
    path = REPO_ROOT / "scripts" / "check_tag_push_safety.py"
    spec = importlib.util.spec_from_file_location("check_tag_push_safety_uut", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _load_module()


class TestR185ParseOriginOwnerRepo(unittest.TestCase):
    """``_parse_origin_owner_repo`` URL parsing 边界。"""

    def _patch_git(self, stdout: str) -> mock._patch[mock.MagicMock]:
        return mock.patch.object(M, "_run_git", return_value=stdout + "\n")

    def test_ssh_form_with_git_suffix(self) -> None:
        with self._patch_git("git@github.com:xiadengma/ai-intervention-agent.git"):
            self.assertEqual(
                M._parse_origin_owner_repo(), ("xiadengma", "ai-intervention-agent")
            )

    def test_ssh_form_without_git_suffix(self) -> None:
        with self._patch_git("git@github.com:xiadengma/repo"):
            self.assertEqual(M._parse_origin_owner_repo(), ("xiadengma", "repo"))

    def test_https_form_with_git_suffix(self) -> None:
        with self._patch_git("https://github.com/xiadengma/ai-intervention-agent.git"):
            self.assertEqual(
                M._parse_origin_owner_repo(), ("xiadengma", "ai-intervention-agent")
            )

    def test_https_form_without_git_suffix(self) -> None:
        with self._patch_git("https://github.com/xiadengma/repo"):
            self.assertEqual(M._parse_origin_owner_repo(), ("xiadengma", "repo"))

    def test_https_with_trailing_slash(self) -> None:
        with self._patch_git("https://github.com/xiadengma/repo/"):
            self.assertEqual(M._parse_origin_owner_repo(), ("xiadengma", "repo"))

    def test_http_scheme_also_recognised(self) -> None:
        with self._patch_git("http://github.com/xiadengma/repo.git"):
            self.assertEqual(M._parse_origin_owner_repo(), ("xiadengma", "repo"))

    def test_non_github_host_returns_none(self) -> None:
        with self._patch_git("git@gitlab.com:xiadengma/repo.git"):
            self.assertIsNone(M._parse_origin_owner_repo())

    def test_codeberg_host_returns_none(self) -> None:
        with self._patch_git("https://codeberg.org/xiadengma/repo"):
            self.assertIsNone(M._parse_origin_owner_repo())

    def test_garbage_input_returns_none(self) -> None:
        with self._patch_git("not even a url"):
            self.assertIsNone(M._parse_origin_owner_repo())

    def test_git_command_failure_returns_none(self) -> None:
        with mock.patch.object(
            M, "_run_git", side_effect=subprocess.CalledProcessError(1, "git")
        ):
            self.assertIsNone(M._parse_origin_owner_repo())

    def test_git_not_installed_returns_none(self) -> None:
        with mock.patch.object(M, "_run_git", side_effect=FileNotFoundError):
            self.assertIsNone(M._parse_origin_owner_repo())


class TestR185QueryOpenAlerts(unittest.TestCase):
    """``_query_open_alerts`` 行为。"""

    def _patch_subprocess(
        self,
        *,
        stdout: str = "",
        returncode: int = 0,
        side_effect: Exception | None = None,
    ) -> mock._patch[mock.MagicMock]:
        if side_effect is not None:
            return mock.patch("subprocess.run", side_effect=side_effect)
        result = mock.MagicMock()
        result.stdout = stdout
        result.returncode = returncode
        return mock.patch("subprocess.run", return_value=result)

    def test_zero_alerts_returns_empty_list(self) -> None:
        with self._patch_subprocess(stdout=""):
            alerts = M._query_open_alerts("owner", "repo", frozenset({"high"}))
            self.assertEqual(alerts, [])

    def test_filters_by_severity(self) -> None:
        out = (
            json.dumps({"number": 1, "severity": "high", "package": "p"})
            + "\n"
            + json.dumps({"number": 2, "severity": "low", "package": "p"})
            + "\n"
            + json.dumps({"number": 3, "severity": "critical", "package": "p"})
        )
        with self._patch_subprocess(stdout=out):
            alerts = M._query_open_alerts(
                "owner", "repo", frozenset({"high", "critical"})
            )
            self.assertIsNotNone(alerts)
            assert alerts is not None
            nums = sorted([a["number"] for a in alerts])
            self.assertEqual(nums, [1, 3])  # low (number 2) excluded

    def test_case_insensitive_severity(self) -> None:
        out = json.dumps({"number": 1, "severity": "HIGH", "package": "p"})
        with self._patch_subprocess(stdout=out):
            alerts = M._query_open_alerts("owner", "repo", frozenset({"high"}))
            self.assertEqual(len(alerts or []), 1)

    def test_subprocess_failure_returns_none(self) -> None:
        with self._patch_subprocess(side_effect=subprocess.CalledProcessError(1, "gh")):
            self.assertIsNone(
                M._query_open_alerts("owner", "repo", frozenset({"high"}))
            )

    def test_gh_api_rate_limit_returns_none(self) -> None:
        """CR#16 F-2：``gh api`` 命中 GitHub API rate-limit 时 (HTTP 403,
        ``X-RateLimit-Remaining: 0``) 返回非 0 退出码，subprocess.run 抛
        ``CalledProcessError``——本测试 documents 这条 path 也走 fail-safe
        return None，让 main() 把 "未知" 当 ``(2, None)`` 处理，输出
        WARNING 后 fail-open 放行。

        Rationale: 我们刻意**不**区分 "rate-limit / 网络 / gh 未登录 /
        Dependabot 关闭" 这几种 None-return 子情况——所有"无法判断" 都
        归一处理成 "warn + pass"，让 CI 不因为外部依赖抖动而误阻发布。
        """
        # gh CLI 在 rate-limit 时 stderr 含 "API rate limit exceeded" + 退出 1
        rate_limit_err = subprocess.CalledProcessError(
            returncode=1,
            cmd="gh",
            stderr="HTTP 403: API rate limit exceeded for installation ID 12345",
        )
        with self._patch_subprocess(side_effect=rate_limit_err):
            result = M._query_open_alerts(
                "owner", "repo", frozenset({"high", "critical"})
            )
            self.assertIsNone(
                result,
                "rate-limit 必须走 fail-safe None return（与其它 gh 失败"
                "情况共享 path），让上层 fail-open 输出 WARNING 后放行",
            )

    def test_gh_api_unauthorized_returns_none(self) -> None:
        """CR#16 F-2 续：``gh`` 未 ``gh auth login`` 时 401/403，同样走
        None return path——不阻断发布，仅 WARN。
        """
        not_logged_in_err = subprocess.CalledProcessError(
            returncode=1,
            cmd="gh",
            stderr=(
                "gh: To use GitHub CLI in a GitHub Actions workflow, "
                "set the GH_TOKEN environment variable."
            ),
        )
        with self._patch_subprocess(side_effect=not_logged_in_err):
            self.assertIsNone(
                M._query_open_alerts("owner", "repo", frozenset({"high"}))
            )

    def test_timeout_returns_none(self) -> None:
        with self._patch_subprocess(side_effect=subprocess.TimeoutExpired("gh", 30)):
            self.assertIsNone(
                M._query_open_alerts("owner", "repo", frozenset({"high"}))
            )

    def test_gh_not_installed_returns_none(self) -> None:
        with self._patch_subprocess(side_effect=FileNotFoundError):
            self.assertIsNone(
                M._query_open_alerts("owner", "repo", frozenset({"high"}))
            )

    def test_malformed_json_lines_are_skipped(self) -> None:
        """JSON 解析失败的行应被静默跳过，不影响正常项。"""
        out = (
            "this is not json\n"
            + json.dumps({"number": 7, "severity": "high"})
            + "\n"
            + "}{"
        )
        with self._patch_subprocess(stdout=out):
            alerts = M._query_open_alerts("owner", "repo", frozenset({"high"}))
            self.assertEqual(len(alerts or []), 1)
            assert alerts is not None
            self.assertEqual(alerts[0]["number"], 7)

    def test_missing_severity_field_is_skipped(self) -> None:
        """``severity`` 字段缺失的告警不应被误算入 blocker。"""
        out = (
            json.dumps({"number": 1})  # no severity
            + "\n"
            + json.dumps({"number": 2, "severity": "high"})
        )
        with self._patch_subprocess(stdout=out):
            alerts = M._query_open_alerts("owner", "repo", frozenset({"high"}))
            self.assertEqual(len(alerts or []), 1)
            assert alerts is not None
            self.assertEqual(alerts[0]["number"], 2)


class TestR185CheckCveGate(unittest.TestCase):
    """``_check_cve_gate`` 五个分支。"""

    def test_gh_not_available_returns_unknown(self) -> None:
        with mock.patch.object(M, "_gh_available", return_value=False):
            rc, alerts = M._check_cve_gate()
            self.assertEqual(rc, 2)
            self.assertIsNone(alerts)

    def test_unparseable_remote_returns_unknown(self) -> None:
        with (
            mock.patch.object(M, "_gh_available", return_value=True),
            mock.patch.object(M, "_parse_origin_owner_repo", return_value=None),
        ):
            rc, alerts = M._check_cve_gate()
            self.assertEqual(rc, 2)
            self.assertIsNone(alerts)

    def test_query_failure_returns_unknown(self) -> None:
        with (
            mock.patch.object(M, "_gh_available", return_value=True),
            mock.patch.object(M, "_parse_origin_owner_repo", return_value=("o", "r")),
            mock.patch.object(M, "_query_open_alerts", return_value=None),
        ):
            rc, alerts = M._check_cve_gate()
            self.assertEqual(rc, 2)
            self.assertIsNone(alerts)

    def test_zero_alerts_returns_ok(self) -> None:
        with (
            mock.patch.object(M, "_gh_available", return_value=True),
            mock.patch.object(M, "_parse_origin_owner_repo", return_value=("o", "r")),
            mock.patch.object(M, "_query_open_alerts", return_value=[]),
        ):
            rc, alerts = M._check_cve_gate()
            self.assertEqual(rc, 0)
            self.assertEqual(alerts, [])

    def test_blockers_present_returns_fail(self) -> None:
        sample = [
            {
                "number": 1,
                "severity": "high",
                "package": "p",
                "ghsa": "g",
                "summary": "s",
            }
        ]
        with (
            mock.patch.object(M, "_gh_available", return_value=True),
            mock.patch.object(M, "_parse_origin_owner_repo", return_value=("o", "r")),
            mock.patch.object(M, "_query_open_alerts", return_value=sample),
        ):
            rc, alerts = M._check_cve_gate()
            self.assertEqual(rc, 1)
            self.assertEqual(alerts, sample)


class TestR185CliFlags(unittest.TestCase):
    """``--check-cve`` / ``--allow-cve`` / ``--cve-severity`` 解析。"""

    def test_check_cve_default_off(self) -> None:
        """默认 OFF——保留旧行为，opt-in 时才跑 CVE gate。"""
        from io import StringIO

        with (
            mock.patch.object(M, "_check", return_value=0),
            mock.patch.object(M, "_check_cve_gate") as gate,
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = M.main([])
            self.assertEqual(rc, 0)
            gate.assert_not_called()

    def test_check_cve_flag_triggers_gate(self) -> None:
        from io import StringIO

        with (
            mock.patch.object(M, "_check", return_value=0),
            mock.patch.object(M, "_check_cve_gate", return_value=(0, [])) as gate,
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = M.main(["--check-cve"])
            self.assertEqual(rc, 0)
            gate.assert_called_once()

    def test_no_check_cve_explicit_off(self) -> None:
        """``BooleanOptionalAction`` 的 ``--no-`` 反义。"""
        from io import StringIO

        with (
            mock.patch.object(M, "_check", return_value=0),
            mock.patch.object(M, "_check_cve_gate") as gate,
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = M.main(["--no-check-cve"])
            self.assertEqual(rc, 0)
            gate.assert_not_called()

    def test_allow_cve_overrides_blocker(self) -> None:
        """``--allow-cve`` 在 gate fail 时仍让 main() 返回 0。"""
        from io import StringIO

        sample = [{"number": 1, "severity": "high", "package": "p"}]
        with (
            mock.patch.object(M, "_check", return_value=0),
            mock.patch.object(M, "_check_cve_gate", return_value=(1, sample)),
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()) as stderr,
        ):
            rc = M.main(["--check-cve", "--allow-cve"])
            self.assertEqual(rc, 0)
            self.assertIn("--allow-cve", stderr.getvalue())
            self.assertIn("R185", stderr.getvalue())

    def test_blocker_without_allow_cve_fails(self) -> None:
        from io import StringIO

        sample = [{"number": 1, "severity": "high", "package": "p"}]
        with (
            mock.patch.object(M, "_check", return_value=0),
            mock.patch.object(M, "_check_cve_gate", return_value=(1, sample)),
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = M.main(["--check-cve"])
            self.assertEqual(rc, 1)

    def test_unknown_state_does_not_block(self) -> None:
        """gate 返回 ``(2, None)``（gh 未装等）应放行——fail-open。"""
        from io import StringIO

        with (
            mock.patch.object(M, "_check", return_value=0),
            mock.patch.object(M, "_check_cve_gate", return_value=(2, None)),
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = M.main(["--check-cve"])
            self.assertEqual(rc, 0)

    def test_tag_check_failure_skips_cve_gate(self) -> None:
        """tag-count 检查失败时应直接 return 不再跑 CVE gate。"""
        from io import StringIO

        with (
            mock.patch.object(M, "_check", return_value=1),
            mock.patch.object(M, "_check_cve_gate") as gate,
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = M.main(["--check-cve"])
            self.assertEqual(rc, 1)
            gate.assert_not_called()

    def test_custom_severity_filter(self) -> None:
        from io import StringIO

        with (
            mock.patch.object(M, "_check", return_value=0),
            mock.patch.object(M, "_check_cve_gate", return_value=(0, [])) as gate,
            mock.patch("sys.stdout", StringIO()),
            mock.patch("sys.stderr", StringIO()),
        ):
            rc = M.main(["--check-cve", "--cve-severity", "critical"])
            self.assertEqual(rc, 0)
            gate.assert_called_once()
            kwargs = gate.call_args.kwargs
            self.assertEqual(kwargs["blocking_severities"], frozenset({"critical"}))


if __name__ == "__main__":
    unittest.main()
