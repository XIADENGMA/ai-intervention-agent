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
import re
import subprocess
import sys
from pathlib import Path

_SEMVER_TAG_RE = re.compile(
    r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


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
    args = parser.parse_args(argv)

    if args.threshold < 0:
        print("--threshold 不能为负数", file=sys.stderr)
        return 2

    return _check(threshold=args.threshold, remote=args.remote)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
