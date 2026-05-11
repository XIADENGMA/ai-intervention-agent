# Release 恢复手册

> 关闭 CR#13 §F-1。最后修订 2026-05-12（v1.6.3 周期）。
> 英文版：[`release-recovery.md`](release-recovery.md)。

本文是 **`v*.*.*` tag 推送触发 `release.yml`、其中一个或多个 release
job 失败 / 部分发布时的人类可读 runbook**。

`release.yml` 的六个 release job（按执行顺序）：

1. **Build (sdist + wheel)** —— 跑 `scripts/ci_gate.py --ci`，再
   `uv build` + `twine check` + Node deps + VSIX build。上传
   `vsix` 与 `dist` artefact。
2. **Publish to PyPI (Trusted Publisher)** —— 将 `dist/*` 上传到
   PyPI，附带 sigstore attestations。
3. **Publish VSCode Extension to Open VSX** —— `npx --yes
   ovsx@0.10.9 publish ...`（R149 pin）。
4. **Publish VSCode Extension to VS Code Marketplace** —— 若配置
   了 `VSCE_PAT` secret 则 `vsce publish`；否则优雅 skip。
5. **Create GitHub Release** —— 把 sdist/wheel/vsix 作为 release
   asset 上传，附带从 CHANGELOG 自动生成的 release notes。

**任意 job** 失败都会留下 partial 状态。本手册按失败模式分类，给
出每种模式的恢复方法 —— 全文最重要的一条规则：

> 一旦某个 Publish job **成功**（PyPI / Open VSX / Marketplace 接
> 收了 artefact），该版本号就**永久燃烧**了。PyPI 明确拒绝同版本
> 号的重复上传，即便 `yank` 之后也不行。Open VSX 同理。**永远不
> 要复用已燃烧的版本号**，bump 到下一个 patch 即可。

## 失败模式 1 —— Build job 失败（无 Publish 跑过）

**现象**：GitHub Actions 显示 `Build (sdist + wheel)` 为 ✗，四个
Publish job 都是 `-`（依赖失败被 skip）。哪里都没上传 artefact，
GitHub Release 也没创建。

**示例**：v1.6.3 attempt #1（commit `a5c12b0`）在 "Python CI Gate"
失败，原因是 `test_housekeeping_r151` fossilisation（见 R180
commit message）。

**恢复**：clean abort + 重新打 tag **安全可行**。

```bash
# 1. 调查。本地拉失败 job 日志并复现。
gh run view <run-id> --log-failed | head -200
uv run python scripts/ci_gate.py  # 本地复现

# 2. 在 main 上修。
git checkout main
# ... commit 修复 ...
git push origin main

# 3. 删 broken tag（remote + local）。
git push --delete origin v1.6.3
git tag -d v1.6.3

# 4. 在含修复的新 HEAD 上重打 tag。
git tag -a v1.6.3 -m "release v1.6.3 (re-shot after attempt-1 CI failure)"

# 5. 推前安全检查。
uv run python scripts/check_tag_push_safety.py

# 6. push 新 tag —— 触发 release.yml。
git push origin v1.6.3
```

**为何安全**：没有任何外部镜像（PyPI / Open VSX / GitHub Release）
接收 artefact。唯一"漏出去"的就是 tag 本身，我们已经删掉。同名重打
是从消费者角度看的 tag *move*，不是 tag *rewrite*（没人消费过）。

**注意**：如果在 push 与 delete 之间任何开发者 / CI / 镜像 poll 过
tag，它们可能缓存了被抛弃的 commit hash。如果怀疑有外部消费者，在
项目的 Discussion / Issue 跟踪器里发条通告。

## 失败模式 2 —— Build ✓，部分 Publish ✗

**现象**：`Build` 成功；PyPI 上传 ✓；Open VSX 或 Marketplace ✗。
GitHub Release 取决于哪个 job 先跑，可能创建了也可能没创建。

**示例（假设）**：PyPI ✓ + Open VSX ✗，因为 Open VSX 服务器临时
返回 502。

**恢复**：**不要**用同版本号重打 tag。PyPI 已经接收了该版本，你
**不能**重新上传 `v1.6.3` 到 PyPI。选项有三：

### 选项 A —— 仅重跑失败 job（瞬时故障）

如果失败是瞬时的（网络抖动、速率限制、Open VSX 服务器临时故障），
重跑该 job：

```bash
gh run rerun <run-id> --failed
```

只重试失败的 job，**不重跑成功的**。PyPI publish 不会被重试，无
版本冲突风险。

### 选项 B —— 从已有 artefact 手动 publish

如果重跑不可用（例如 workflow 文件已改、run 太老），下载 `vsix`
artefact 手动发布：

```bash
gh run download <run-id> --name vsix
cd packages/vscode
# Open VSX：
npx --yes ovsx@0.10.9 publish *.vsix -p $OPENVSX_TOKEN
# Marketplace（如果适用）：
vsce publish --packagePath *.vsix -p $VSCE_PAT
```

### 选项 C —— Patch bump（v1.6.3 → v1.6.4）如果 artefact 自己坏了

如果失败**不是**瞬时的（例如 ovsx validator 拒绝 displayName，正如
v1.6.1 的 R149 root cause），artefact 本身需要修。PyPI 上 v1.6.3
artefact 是正常的；坏的是 VSIX。选项：

1. **可接受版本号 gap**：v1.6.3 只在 PyPI 上有；VSIX 改成 v1.6.4。
   在 CHANGELOG 注明："v1.6.3 仅在 PyPI；VSIX 用户从 v1.6.2 直接到
   v1.6.4"。
2. **VSIX 用户也急需这个修复**：bump 到 v1.6.4，修 VSIX bug，重打。
   `pip install ai-intervention-agent==1.6.4` 与 v1.6.4 VSIX 同时
   发布。v1.6.3 成为"仅 PyPI 发布"的历史 artefact。

这是一个价值判断决策。VSIX bug 微小 / 仅 cosmetic 时优先选项 1；
面向用户的明显 bug 时优先选项 2。

## 失败模式 3 —— Build ✓ + 所有 Publish ✓，但 `Create GitHub Release` ✗

**现象**：PyPI ✓ + Open VSX ✓ + Marketplace ✓ + `Create GitHub
Release` ✗（例如 `gh release create` 被限速或权限失败）。

**恢复**：三种模式里最简单的。手动创建 GitHub Release：

```bash
# 下载 Build job 的 artefact。
gh run download <run-id> --name dist
gh run download <run-id> --name vsix

# 用已有 tag 创建 GitHub Release。
gh release create v1.6.3 \
  --notes-from-tag \
  ./dist/*.tar.gz ./dist/*.whl ./packages/vscode/*.vsix
```

也可以用 `gh run rerun <run-id> --job <job-id>` 仅重跑该 job（前提
是失败原因是瞬时的）。

## R180 + R181 阻止了什么

| R180 + R181 之前                                       | R180 + R181 之后                                       |
| ------------------------------------------------------ | ------------------------------------------------------ |
| `[Unreleased]` snapshot 测试在 bump 时 fossilise       | snapshot 测试重新 anchor 在整个 CHANGELOG              |
| CHANGELOG / docs commits 静默跳过 `test.yml`           | CHANGELOG / docs commits 跑完整 `ci_gate.py` matrix    |
| 潜在 test 回退在 tag-push 才暴露                       | 潜在 test 回退在 PR-push 就暴露                        |
| 失败模式 1 是 tag-push 的**主要**危险                  | 失败模式 1 现在罕见多了                                |

本手册对失败模式 2、3 仍然适用；失败模式 1 在它**罕见**漏过的情
况下（例如 PR-merge 与 tag-push 之间上游 toolchain 变更）也仍然
适用。

## 通告模板

如果一次 release 失败 + 重打或 bump 跳过，请在项目 Discussion /
Issue 跟踪器发条简报：

> **v1.6.3 release-attempt note**：第一次 `v1.6.3` tag push
> （commit `a5c12b0`）在 Python CI Gate 失败。无 package 发布。
> tag 被删除并在 commit `72b0ae1`（含修复）上重打。外部消费者
> 从未见到失败的 attempt。已发布的 v1.6.3（PyPI / Open VSX /
> GitHub Release）就是 working bundle。

这成本约 2 分钟，防止未来 bisect 时"v1.6.3 tag 为啥跳了？"的考古
工作长达几个月。

## 相关 guard

- `tests/test_housekeeping_r151.py` —— R180 rescue 测试。
- `tests/test_workflow_paths_ignore_r181.py` —— R181 paths-ignore
  guard。
- `tests/test_release_workflow_ovsx_pinned_r149.py` —— R149 ovsx
  pin guard（相关：防止 floating-tag toolchain drift）。
- `scripts/check_tag_push_safety.py` —— push 前安全检查（一次推
  超过 3 个未推 tag 会告警）。
- `scripts/bump_version.py` —— 跨 `pyproject.toml`、`package.json`、
  `uv.lock`、`package-lock.json`、`packages/vscode/package.json`、
  `CITATION.cff`、`.github/ISSUE_TEMPLATE/bug_report.yml` 的程序化
  版本同步。
- `docs/troubleshooting.zh-CN.md` §12（R151） —— Open VSX
  displayName + ovsx pin 升级仪式。
