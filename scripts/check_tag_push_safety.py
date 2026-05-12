"""
发布前 tag 推送安全检查工具。

## 解决的真实 bug（R19.1，2026-05-05 v1.5.24 发布期间踩到）

GitHub 平台对 ``push.tags`` 触发器有一条**未经文档化的硬限制**：

> "Events will not be created for tags when more than three tags are pushed
> at once."

来源：https://github.com/actions/runner/issues/3644 + GitHub webhook 文档。

也就是说，``git push --follow-tags origin main`` 在本地堆积了 ≥4 个未推送
``v*.*.*`` tag 时，**虽然 push 本身成功**（远端能看到所有 tag），**但 GitHub
不会为任何 tag 生成 webhook event**，导致 ``release.yml``（``on.push.tags``）
静默不触发，PyPI / GitHub Release / VSCode Marketplace / Open VSX 全线都不
会发布——**且 push 输出和 GitHub UI 都不会给开发者任何错误反馈**，唯一的现
象是 "tag 在远端但 Actions 列表里没看到 Release run"。

v1.5.24 的真实复现（2026-05-05）：本地累积了 v1.5.20 / v1.5.21 / v1.5.23 /
v1.5.24 共 4 个未推送 tag，``git push --follow-tags origin main`` 后 push
输出显示 "[new tag] v1.5.20 / v1.5.21 / v1.5.23 / v1.5.24" 全部成功，但
``gh run list --workflow=Release`` 里没有任何 v1.5.* 触发——只有 main
branch 的 Tests / VSCode Extension / CodeQL / OSSF Scorecard 跑了。修复方
法是 ``git push origin :refs/tags/v1.5.24`` 删除远端再 ``git push origin
v1.5.24`` 单独重推（一次只 push 1 个 tag，不触发限流）。

## 这个工具做什么

- 列出本地所有 ``v*.*.*`` tag（``git tag -l 'v*.*.*'``）。
- 列出远端 ``origin`` 上所有 ``v*.*.*`` tag（``git ls-remote --tags
  origin``）。
- 计算未推送 tag = 本地集合 − 远端集合。
- ``len(unpushed) == 0``：OK（exit 0），无 tag 需要 push。
- ``1 <= len(unpushed) <= 3``：OK（exit 0），可以安全 ``git push
  --follow-tags``。
- ``len(unpushed) >= 4``：**FAIL（exit 1）**，打印每个 tag 的名字和推荐的
  修复操作（按版本号升序逐个 ``git push origin <tag>``）。

## 为什么阈值是 3 而不是 5/10

GitHub 文档原文是 "more than three tags"（即 >3，所以 4+ 被屏蔽）。本工具
只在 ``>= 4`` 时报错，``<= 3`` 时放行——和官方阈值严格对齐。

## 为什么需要 ``git ls-remote`` 而不是 ``git for-each-ref refs/remotes/origin``

``git for-each-ref`` 读的是本地 ``.git/refs/remotes/origin``，依赖最近一
次 ``git fetch`` 时的快照——如果开发者忘了 fetch，就会得到过时数据。
``git ls-remote --tags origin`` 强制走网络拉取**当前**的远端 tag 列表，从
而消除"陈旧本地缓存导致虚警 / 漏警"的整类失败模式。代价是一次网络往返
（10–500 ms），对人工触发的 release-readiness 检查来说完全可接受。

## 适用场景

- 在执行 ``git push --follow-tags origin main`` 之前手动调用，作为发布前
  的最后一道闸门：``make release-check`` 或 ``uv run python
  scripts/check_tag_push_safety.py``。
- 也可以集成到本地 ``pre-push`` git hook 中（项目当前不强制，因为 hook
  是开发者机器配置，不在仓库版本控制范围内）。
- **不**集成到 ``ci_gate.py``，因为 CI 不 push tag，跑这个检查没意义。

## 退出码

- 0：安全推送（unpushed ∈ [0, 3]）。
- 1：不安全（unpushed >= 4），需要逐个推送。
- 2：环境问题（git 不可用 / 不是 git 仓库 / origin remote 不存在 / 网络
  失败）——和 git 子进程错误透传一致，不和 1（业务级失败）混淆。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_SEMVER_TAG_RE = re.compile(
    r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)

# R185：CVE gate 把 "≥ 1 个 open 的 high/critical 级 CVE" 视作
# release blocker。这条阈值是"实际可执行 + 业界主流"两条线的
# 交集——OWASP / NIST / GitHub 都把 high+ 列为 "patch immediately"
# 等级；medium/low 在 R184 cycle 里被证明常有"upstream 尚无 patch"
# 的合法长尾，硬卡 medium 会让正常发布也卡住。
_DEFAULT_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_git(args: list[str]) -> str:
    """运行 git 子命令，返回 stdout（utf-8 解码）。失败抛 ``subprocess.CalledProcessError``。"""
    result = subprocess.run(
        ["git", *args],
        cwd=_repo_root(),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _list_local_v_tags() -> set[str]:
    """返回本地所有 ``v*.*.*`` tag（严格 SemVer 形态）的集合。"""
    out = _run_git(["tag", "-l", "v*.*.*"])
    tags: set[str] = set()
    for line in out.splitlines():
        name = line.strip()
        if not name:
            continue
        if _SEMVER_TAG_RE.match(name):
            tags.add(name)
    return tags


def _list_remote_v_tags(remote: str = "origin") -> set[str]:
    """返回 ``origin`` 远端所有 ``v*.*.*`` tag（严格 SemVer 形态）的集合。

    使用 ``git ls-remote --tags`` 而不是 ``git for-each-ref refs/remotes/...``，
    后者依赖本地缓存（最后一次 ``git fetch`` 的快照）；前者强制走网络拉取
    实时数据，避免开发者忘了 fetch 时 silent 漏警/虚警。
    """
    out = _run_git(["ls-remote", "--tags", remote])
    tags: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # 行格式：``<sha>\trefs/tags/<tag>`` 或 ``<sha>\trefs/tags/<tag>^{}``
        # 后者是 annotated tag 的 dereferenced object，只关心 tag 名（去 ``^{}``）。
        parts = line.split("\t", maxsplit=1)
        if len(parts) != 2:
            continue
        ref = parts[1].strip()
        if not ref.startswith("refs/tags/"):
            continue
        name = ref[len("refs/tags/") :]
        if name.endswith("^{}"):
            name = name[: -len("^{}")]
        if _SEMVER_TAG_RE.match(name):
            tags.add(name)
    return tags


def _semver_key(tag: str) -> tuple[int, int, int, str]:
    """把 ``vMAJOR.MINOR.PATCH[-PRE]`` 拆成可排序的 key。

    pre-release 段（``-rc.1`` / ``-alpha`` 等）按字符串比较——SemVer 规范的
    pre-release 排序更复杂（数字段按数值、文本段按 ASCII），但在本工具的
    用法里（只是为了"按发布顺序逐个推送"），按字符串排已经足够稳定。
    """
    body = tag[1:]
    pre = ""
    if "-" in body:
        body, pre = body.split("-", 1)
    parts = body.split(".")
    if len(parts) != 3:
        return (0, 0, 0, pre)
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]), pre)
    except ValueError:
        return (0, 0, 0, pre)


def _parse_origin_owner_repo(remote: str = "origin") -> tuple[str, str] | None:
    """从 ``git remote get-url origin`` 反解出 ``(owner, repo)``。

    支持两种主流形态：
      * SSH: ``git@github.com:OWNER/REPO.git``
      * HTTPS: ``https://github.com/OWNER/REPO[.git]``

    不识别的（其他 host / 非 GitHub）返回 ``None``——R185 的 CVE
    gate 当前只对 GitHub 仓库有意义（GitLab / Codeberg 有不同的
    advisory API）。
    """
    try:
        out = _run_git(["remote", "get-url", remote]).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    # SSH: git@github.com:owner/repo[.git]
    ssh_m = re.match(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$", out)
    if ssh_m:
        return (ssh_m.group(1), ssh_m.group(2))

    # HTTPS: https://github.com/owner/repo[.git]
    https_m = re.match(r"^https?://github\.com/([^/]+)/(.+?)(?:\.git)?/?$", out)
    if https_m:
        return (https_m.group(1), https_m.group(2))

    return None


def _gh_available() -> bool:
    """``gh`` CLI 是否在 PATH 中。"""
    return shutil.which("gh") is not None


def _query_open_alerts(
    owner: str, repo: str, blocking_severities: frozenset[str]
) -> list[dict[str, Any]] | None:
    """通过 ``gh api`` 拉 open Dependabot alerts。

    返回值：
      * ``list[dict]``：阻断级别 CVE 列表（可能为空）；
      * ``None``：拉取失败（``gh`` 未认证、API 报错、API 不可用等）——
        调用方应根据"是否要 fail-closed"决定怎么处理。

    设计取舍：用 ``gh api`` 而不是 ``requests`` 直接打 REST，因为
    ``gh`` 自带 token 认证 + 分页 + 重试，无需在脚本里维护 GITHUB_TOKEN
    + retry-with-backoff 这套基础设施。
    """
    cmd = [
        "gh",
        "api",
        "--paginate",
        f"repos/{owner}/{repo}/dependabot/alerts",
        "--jq",
        '.[] | select(.state == "open") | {'
        "number, severity: .security_vulnerability.severity, "
        "package: .security_vulnerability.package.name, "
        "ghsa: .security_advisory.ghsa_id, "
        "summary: .security_advisory.summary"
        "}",
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return None

    alerts: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        sev = item.get("severity")
        if isinstance(sev, str) and sev.lower() in blocking_severities:
            alerts.append(item)
    return alerts


def _check_cve_gate(
    *,
    remote: str = "origin",
    blocking_severities: frozenset[str] = _DEFAULT_BLOCKING_SEVERITIES,
) -> tuple[int, list[dict[str, Any]] | None]:
    """运行 CVE gate 检查。

    返回 ``(exit_code, alerts)``：
      * ``(0, [])`` ——0 个 blocker，可以发布；
      * ``(1, [...])`` ——发现 blocker，阻止发布；
      * ``(2, None)`` ——无法判定（``gh`` 不可用 / 解析远端失败 /
        API 拉取失败），按 fail-open 策略放行但给出告警。该
        exit code 用于让 ``--strict-cve`` 模式区分"未知"和
        "已知 OK"——默认 strict 关，但用户可以显式开启。
    """
    if not _gh_available():
        print(
            "WARNING (R185): ``gh`` CLI 未安装，跳过 CVE gate。"
            "若要启用 CVE 阻断，请 `brew install gh` 或参见 "
            "https://cli.github.com/。",
            file=sys.stderr,
        )
        return 2, None

    owner_repo = _parse_origin_owner_repo(remote)
    if owner_repo is None:
        print(
            f"WARNING (R185): 无法从 remote {remote!r} 解析 owner/repo（"
            "可能是非 GitHub 仓库或 URL 形态不识别），跳过 CVE gate。",
            file=sys.stderr,
        )
        return 2, None

    owner, repo = owner_repo
    alerts = _query_open_alerts(owner, repo, blocking_severities)
    if alerts is None:
        print(
            f"WARNING (R185): 无法从 `gh api repos/{owner}/{repo}/dependabot/"
            "alerts` 拉取 Dependabot alerts（可能是 `gh auth login` 未做、"
            "网络问题或 Dependabot 未启用），跳过 CVE gate。",
            file=sys.stderr,
        )
        return 2, None

    if not alerts:
        sev_label = "/".join(sorted(blocking_severities))
        print(f"OK (R185)：0 个 open {sev_label} 级 Dependabot alert，CVE gate 通过。")
        return 0, []

    print(
        f"FAIL (R185)：发现 {len(alerts)} 个阻断级 Dependabot alert：",
        file=sys.stderr,
    )
    for alert in alerts:
        num = alert.get("number")
        sev = alert.get("severity", "?")
        pkg = alert.get("package", "?")
        ghsa = alert.get("ghsa", "?")
        summary = alert.get("summary", "")
        print(f"  - #{num} [{sev}] {pkg}: {ghsa} — {summary}", file=sys.stderr)
    print(
        "\n修复方法：\n"
        "  uv run python scripts/silent_failure_audit.py list  # 看上下文\n"
        "  uv lock --upgrade-package <pkg>                     # 升级依赖\n"
        "  uv sync --dev && uv run pytest -W error -q          # 验证\n"
        "\n或者，紧急情况下绕过该检查：--allow-cve（仅在确认 CVE 不影响"
        "本仓 exploit 路径时使用）。",
        file=sys.stderr,
    )
    return 1, alerts


def _check(threshold: int = 3, remote: str = "origin") -> int:
    """核心逻辑。返回 exit code：0=OK，1=超阈值，2=git 错误。"""
    try:
        local_tags = _list_local_v_tags()
        remote_tags = _list_remote_v_tags(remote)
    except subprocess.CalledProcessError as e:
        print(
            f"git 命令失败（exit {e.returncode}）：{' '.join(e.cmd)}\n"
            f"stderr：{(e.stderr or '').strip()}",
            file=sys.stderr,
        )
        return 2
    except FileNotFoundError:
        print("找不到 git 可执行文件（PATH 中没有 git）", file=sys.stderr)
        return 2

    unpushed = sorted(local_tags - remote_tags, key=_semver_key)

    if not unpushed:
        print("OK：本地没有未推送的 v*.*.* tag。")
        return 0

    if len(unpushed) <= threshold:
        # 1–3 个未推送 tag：``git push --follow-tags origin main`` 不会触发
        # GitHub 3-tag 限流，可以正常推。
        joined = ", ".join(unpushed)
        print(
            f"OK：本地有 {len(unpushed)} 个未推送 tag（{joined}），"
            f"≤ {threshold} 上限，可以用 `git push --follow-tags origin main` 一次推送。"
        )
        return 0

    # ≥ 4 个未推送 tag：触发 GitHub 3-tag 硬限制，Release workflow 不会触发。
    print(
        f"FAIL：本地有 {len(unpushed)} 个未推送 v*.*.* tag（> {threshold} 上限）：",
        file=sys.stderr,
    )
    for t in unpushed:
        print(f"  - {t}", file=sys.stderr)
    print(
        "\nGitHub 平台限制：单次 push >3 个 tag 时 webhook events 不会被创建，"
        "release.yml（on.push.tags）将静默不触发——PyPI / GitHub Release / "
        "VSCode Marketplace 等下游发布全部不会发生，且 push 输出和 GitHub UI "
        "都不会给出错误反馈。\n"
        "参考：https://github.com/actions/runner/issues/3644\n",
        file=sys.stderr,
    )
    print("修复方法（按版本号升序逐个推送，每次 ≤ 3 个）：", file=sys.stderr)
    print("  # 推荐：一次只推 1 个，最稳妥", file=sys.stderr)
    for t in unpushed:
        print(f"  git push origin {t}", file=sys.stderr)
    print(
        "\n或者：先 `git push origin main` 推 commit，然后逐个 push tag。",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "发布前 tag 推送安全检查：检测本地有多少 v*.*.* tag 尚未推送到 origin。"
            "若 > 3，GitHub 不会为 tag push 触发 webhook events，Release workflow 静默不触发。"
        ),
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=3,
        help=(
            "允许一次性 push 的 tag 上限（默认 3，与 GitHub 平台硬限制对齐）。"
            "超过这个数量将报错。"
        ),
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="目标 remote 名称（默认 origin）",
    )
    parser.add_argument(
        "--check-cve",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "R185：是否额外检查 Dependabot 上 open 的 high/critical CVE alert，"
            "≥ 1 时阻止 push。需要 `gh` CLI 已登录 + 仓库启用 Dependabot。"
            "默认 OFF（opt-in），开启请加 --check-cve。"
        ),
    )
    parser.add_argument(
        "--allow-cve",
        action="store_true",
        default=False,
        help=(
            "紧急绕过开关：即使 --check-cve 发现 blocker 也允许放行。"
            "仅在确认 CVE 不影响本仓 exploit 路径（如传递依赖的非利用面）时使用，"
            "应配合 commit 消息记录绕过理由。"
        ),
    )
    parser.add_argument(
        "--cve-severity",
        action="append",
        choices=["critical", "high", "medium", "low"],
        default=None,
        help=(
            "自定义 CVE blocker 严重级（可多次传入）。"
            "默认 critical + high；传 --cve-severity medium 可加严，"
            "传 --cve-severity critical 单独可放宽。"
        ),
    )
    args = parser.parse_args(argv)

    if args.threshold < 0:
        print("--threshold 不能为负数", file=sys.stderr)
        return 2

    rc = _check(threshold=args.threshold, remote=args.remote)
    if rc != 0:
        return rc

    if args.check_cve:
        sev_filter: frozenset[str] = (
            frozenset(args.cve_severity)
            if args.cve_severity
            else _DEFAULT_BLOCKING_SEVERITIES
        )
        cve_rc, _alerts = _check_cve_gate(
            remote=args.remote, blocking_severities=sev_filter
        )
        if cve_rc == 1 and not args.allow_cve:
            return 1
        if cve_rc == 1 and args.allow_cve:
            print(
                "WARNING (R185)：--allow-cve 强制放行 CVE blocker。"
                "请在 commit 消息中记录绕过理由。",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
