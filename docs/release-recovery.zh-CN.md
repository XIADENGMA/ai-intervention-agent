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

# 5. 推前安全检查。（加 --check-cve 启用 R185 Dependabot CVE 闸门；
#    需要 `gh auth login` + 仓库已启用 Dependabot。或用快捷目标
#    `make release-check-cve`。）
uv run python scripts/check_tag_push_safety.py

# 6. push 新 tag —— 触发 release.yml。
git push origin v1.6.3
```

**为何安全**：没有任何外部镜像（PyPI / Open VSX / GitHub Release）
接收 artefact。唯一"漏出去"的就是 tag 本身，我们已经删掉。同名重打
是从消费者角度看的 tag _move_，不是 tag _rewrite_（没人消费过）。

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

| R180 + R181 之前                                 | R180 + R181 之后                                    |
| ------------------------------------------------ | --------------------------------------------------- |
| `[Unreleased]` snapshot 测试在 bump 时 fossilise | snapshot 测试重新 anchor 在整个 CHANGELOG           |
| CHANGELOG / docs commits 静默跳过 `test.yml`     | CHANGELOG / docs commits 跑完整 `ci_gate.py` matrix |
| 潜在 test 回退在 tag-push 才暴露                 | 潜在 test 回退在 PR-push 就暴露                     |
| 失败模式 1 是 tag-push 的**主要**危险            | 失败模式 1 现在罕见多了                             |

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
  超过 3 个未推 tag 会告警）。**R185 扩展**：`--check-cve` 标志在
  仓库存在 ≥ 1 个 `critical`/`high` 级 Dependabot 开放告警时阻止
  发布；opt-in，默认 OFF。`make release-check-cve` 是便利目标。
- `scripts/bump_version.py` —— 跨 `pyproject.toml`、`package.json`、
  `uv.lock`、`package-lock.json`、`packages/vscode/package.json`、
  `CITATION.cff`、`.github/ISSUE_TEMPLATE/bug_report.yml` 的程序化
  版本同步。**R183**：bump 时若 `CHANGELOG.md [Unreleased]` 看起来
  为空会打 WARNING（`--warn-empty-unreleased` 默认开启；
  `--no-warn-empty-unreleased` 抑制）。
- `docs/troubleshooting.zh-CN.md` §12（R151） —— Open VSX
  displayName + ovsx pin 升级仪式。
- `.github/dependabot.yml` + `automated-security-fixes`
  （仓库级开关，**R184** 已启用）—— CVE 披露后 Dependabot 自动
  开 PR。配合 `dependabot-auto-merge.yml` 的链路是：CVE 落地 →
  Dependabot 开 patch-bump PR → patch/minor 自动合并 → 下个发布
  自动带上修复。主版本仍走人工审阅（见
  `dependabot-auto-merge.yml`）。

## Tag 推送前清单（R206 / Cycle 9 · F-release-1）

> **本节存在的理由**：除了上面六种 `release.yml` 失败模式（都在
> `git push v*.*.*` **之后** 触发），`main` 上的 `Tests` workflow
> 在 tag-push 时也会跑——它失败会让 tag 停在 **CI 红的 commit**
> 上，而 Publish job 一个都不跑。v1.7.2 正好踩中：初始 tag commit
> （`36222a3`）漏了 `docs/api/enhanced_logging.md` 的 regen，`Tests`
> workflow 里的 docs-parity gate 标红，v1.7.2 tag 不得不在 5 分钟
> 后 force-retag 到 docs-sync commit（`35f9671`）。

下面的清单是 **push 任何 `v*.*.*` tag 之前本地要跑的步骤**。配合
现有的 `scripts/check_tag_push_safety.py`（见上文「相关守护」）
与 `Tests` workflow 的 CHANGELOG-非-Unreleased pre-commit guard
（R180 + R181），这是接 tag-push-time 失误的 **三层保险**。

> **R209（cycle 10 · F-release-2）自动化**：下面第 6 步
> （`check_tag_push_safety.py`）现已通过 pre-commit framework
> 接入 Git `pre-push` hook。一次性安装：`make install-hooks`
> （或 `pre-commit install --hook-type pre-commit --hook-type
> pre-push`），之后 ≥ 4 个 `v*.*.*` tag 未推送时 hook 会
> 拒绝 push（防 R19.1 GitHub webhook 屏蔽）。该 hook 与人工
> 清单是**互补关系**——只拦截最危险的单一失败模式，不是全
> 13 步。绕过开关：`git push --no-verify`。

1. **本地预飞行**（本清单）—— 在 `git push --follow-tags` **之前**
   抓失误。
2. **`main` 上的 `Tests` workflow**（R180 + R181 + CHANGELOG drift
   守护）—— 在 tag-push **之后**、`release.yml` Publish job **之前**
   抓失误。
3. **`release.yml` 六个 job 流水线**（上面失败模式 1-3）—— 抓单 job
   artefact / publish 级失败。

```bash
# === Tag 推送前清单（cycle 9 / F-release-1） ===========================

# 1. 与远端 main 同步，保持 linear history。
git fetch --all --tags --prune
git checkout main
git pull --ff-only origin main
git status --short                          # 必须为空

# 2. 静态检查（ruff + ty）—— 硬 gate。
uv run ruff check .
uv run ruff format --check .
uv run ty check .                           # All checks passed!

# 3. API docs parity —— 两份语言。v1.7.2 漏了这个 CI 才挂。
uv run python scripts/generate_docs.py --lang en --check
uv run python scripts/generate_docs.py --lang zh-CN --check

# 4. 完整 pytest。case 总数与上一个 release 相比若有下降是可疑的。
uv run pytest -q                            # 预期 5xxx passed

# 5. Lockfile 一致性。
uv lock --check                             # Resolved N packages in Xs
npm install --prefer-offline --no-audit > /dev/null  # 若动了 package.json

# 6. Release 安全检查（已有，R185）。
uv run python scripts/check_tag_push_safety.py
# （R185 严格模式想用 CVE gate）
make release-check-cve

# 7. CHANGELOG sanity：[Unreleased] **不能** 是空的（否则你在发空
#    release）。
rg -n -A1 '^## \[Unreleased\]' CHANGELOG.md | head -5

# 8. Bump 版本 + 同步所有 version-bearing 文件（R183）。
uv run python scripts/bump_version.py X.Y.Z

# 9. 最后一道 pre-commit gate（让 pre-commit hooks 在 bump-commit
#    落盘前 normalise EOL / trim whitespace）。
git add -A
pre-commit run --all-files
git commit -m ":bookmark: chore(release): vX.Y.Z"
# （或在 hooks 改了文件时 amend 上一个 bump-commit —— 仅限尚未 push。）

# 10. 打 annotated tag。**不要用 lightweight tag**（不带 `-a` 的
#     `git tag X`）—— release.yml 期望 annotated tag，lightweight
#     tag 的 body 自动汇总会被跳过。
git tag -a vX.Y.Z -m "vX.Y.Z: <一行总结>

<每个 CR review 2-4 个 bullet 细节>"

# 11. push 前最后 dry-run —— 现在抓拼错的 tag 名。
git log --oneline -1 vX.Y.Z
git show vX.Y.Z --stat | head -30

# 12. branch + tag 一次性 push。
git push --follow-tags origin main

# 13. 看 CI live。在 Tests + release.yml 都绿之前别走。
gh run watch  # 或：gh run list --branch main --limit 5
```

### Retag 安全窗口（v1.7.2 经验）

如果 `Tests` workflow 在 tag commit 上失败、**而且** `release.yml`
Publish job 还没启动（或者因为 `Tests` 是必需依赖被 skip 了），
force-retag 到修复 commit 在**短窗口内是安全的**。v1.7.2 在初始
push 5 分钟后 retag `36222a3` → `35f9671`。

**安全 retag 条件**（全部满足）：

- PyPI / Open VSX / Marketplace 没有任何 publish 成功（查
  `release.yml` run page 或直接看 PyPI 页面）；
- GitHub Release 还没创建（或者你能删掉它）；
- 距离失败的 tag push < 30 分钟（统计上典型 fork/clone 延迟窗口
  —— 超过这个时间，要假设有人有 frozen reference 了）。

**Retag 步骤**（镜像 v1.7.2 的恢复）：

```bash
# A. 先在 main 上落修复。
git checkout main
# ... 修 docs / test / lockfile / 啥的 ...
git commit -m ":memo: docs(api): regenerate XXX for return-type widen in vX.Y.Z"
git push origin main

# B. 两边删坏 tag。
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z

# C. 在修复 commit 上重打 tag，annotation **明确说明** retag 这件事
#    （CR#21 §3.2：未来的维护者必须知道）。
git tag -a vX.Y.Z <fix-commit-sha> -m "vX.Y.Z: <summary>

Note: tag was force-retagged from <broken-sha> to <fix-sha> within
5 minutes of initial push due to <reason>. No external consumers
saw the broken tag. The CHANGELOG [vX.Y.Z] entry documents this
recovery."

# D. 再 push。
git push origin vX.Y.Z

# E. 看 release.yml 在新 tag 上跑起来。
gh run watch
```

### 超过 retag 窗口之后

如果 tag 已经出去 > 30 分钟，或者任何一个 Publish job 已经成功，
该版本就**已经燃烧**了。Bump 到下一个 patch（如 v1.7.2 → v1.7.3）
在新版本里 ship 修复。在 `CHANGELOG.md` 里记录被燃烧的版本：

```markdown
## [1.7.3] — YYYY-MM-DD

### Fixed

- v1.7.2 was tagged with [...broken thing...]; v1.7.3 ships the fix.
  Users on v1.7.2 should upgrade.
```

见上面「Communication template」section —— 同样的原则，scale 到燃
烧版本的 disclosure。

### Tag-was-moved 历史

本清单旨在防止的历史性 tag retag：

| Tag    | 旧 SHA    | 新 SHA    | 原因                                                                 |
| ------ | --------- | --------- | -------------------------------------------------------------------- |
| v1.6.3 | `a5c12b0` | `72b0ae1` | R180 R151 fossilisation 让 Python CI Gate 在 tag-commit 失败         |
| v1.7.2 | `36222a3` | `35f9671` | docs/api parity drift 漏了 `enhanced_logging.md` regen（R204 时期）  |

两次事故 → CHANGELOG entry + tag annotation 都明确写明 retag，
遵循上面「Communication template」。**如果你的 retag 次数超过
一年 3-4 次，pre-flight 清单需要加新 gate**：起一个 F-release-2
follow-up，识别最近一次 miss 漏了哪一步。

## 安全发布捷径（R184）

Dependabot 在运行时依赖上报 CVE 时，发布流程就是常规流程的
压缩版：

```bash
# 1. 识别（Dependabot UI 或 `gh api`）：
gh api repos/$OWNER/$REPO/dependabot/alerts --jq \
  '.[] | select(.state == "open") | {pkg: .security_vulnerability.package.name, severity: .security_vulnerability.severity, ghsa: .security_advisory.ghsa_id}'

# 2. 升依赖：
uv lock --upgrade-package <pkg>
# 直接依赖的话先改 pyproject.toml：
# "foo>=X.Y.Z"  # security: GHSA-...

# 3. 验证：
uv sync --dev
uv run pytest -W error -q
uv run python scripts/ci_gate.py

# 4. 落地 + bump：
git commit -m ":lock: security(deps-rNNN): bump <pkg> ..."
git push origin main
uv run python scripts/bump_version.py X.Y.<Z+1>
```

🔒 emoji + `security(deps-...)` commit 前缀让 CVE patch 在
`git log` 里可 grep。CHANGELOG 里的 `### Security` 区段（Keep-a-
Changelog 约定）也让披露对下游消费者可发现。
