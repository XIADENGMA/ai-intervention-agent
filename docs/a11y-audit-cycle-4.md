# a11y-audit-cycle-4: 多 Track polish + invariant-driven 漂移修复

> Status: **closed**
> Started: 2026-06-05 (cr48 同日)
> Closed: 2026-06-05
> Methodology: v3.2 + Track F + filename convention (mining-11 R254)
> Cycle kind: `a11y-audit` (cycles-1-3 同族)
> Cycle index: 4

## §1 Cycle 触发原因

cr48 §5 总结了 11 个 follow-ups，cr48 §7 推荐 cycle-4 做 **polish cycle**：4
small tracks × ~30 min。本 cycle 把其中 3 个最小耦合的 follow-up + 1 个
即时 invariant-driven 抓出来的 **latent bug 链** 一起 ship：

- Track A (R259): 状态色 hex 硬编码 invariant — 阻止新组件作者
  bypass cycle-2 升级
  - **Bonus**: invariant 实跑时**捕获 3 个真实漂移 bug** (R259a)
- Track B (R259b): `tests/test_critical_preload_r21_1.py` HTML 注释
  解析 false-positive 修复
- Track C (R259c): `_resolveLabel` i18n wrapper 加入正则识别 — 修复
  4 个 `page.iosA2hs.*` orphan/dead key 误判
- Track D (R259d): `freeze_task_deadline` docstring 里的 Markdown
  bullets 破坏 flasgger YAML 解析 — 移到 Python `#` 注释
- Track E: README "5,400+ tests" → "6,000+ tests" baseline 调
- Track F (CONTRIBUTING bonus): 新加 `## 3.ter` 设计约束章节 ——
  把 cycle-2 L2 + cycle-2 L5 + cycle-3 L2 重复出现的
  `--bg-primary #e8e6dc` constraint 写进 codebase

注意：Track B/C/D/E 都是 **invariant-test failure 优先发现**的
latent bug，不是设计性变更。cycle-2 Track B 教训"audit cycles =
discovery > declaration" 在 cycle-4 再次验证。

---

## §2 方法论 (v3.2 复用 + 新模式)

### §2.1 v3.2 老基线

参考 cycle-{1,2,3}.md，本节不重复。

### §2.2 新模式 (cycle-4 沉淀)

**P1: "测试驱动发现" pattern**

> 写一个 invariant test → 跑 → 看它 fail 的内容是什么 → 修
> 真正的 bug → 再次跑 invariant 守住。

cycle-4 Track A 是最纯的例子：

1. 写了 "no old status hex hardcoded" invariant
2. 跑 invariant → 报 `line 7847: color: #ef4444;` 漂移
3. 顺藤摸到 line 7475 + 7485 也是 `rgba(239, 68, 68, 1)` （相同 hex 不同写法）
4. 三处全部切到 `var(--error-500)` → invariant 再跑通过

价值：**1 个测试，发现 3 个真实漂移 bug**。比 mining cycles
的"扫别人 codebase 找新功能"信号密度高得多。

**P2: "false-positive 也算正确反应" pattern**

Track B (R259b) 修复了一个 _test_ 本身的 bug：
- `_extract_body` 用 `<body\b[^>]*>([\s\S]*?)</body>` regex 匹配
- 但模板 line 82 的 HTML 注释里有 `<body>` 文档引用
- regex 不剥注释 → 从注释里的 `<body>` 开始捕获，把整个 head 都
  误当 body 内容
- 6 条本来在 head 里的 preload link 被错位归到"body 里" → test fail

**教训**：测试 fail 不代表代码 bug — **要先排查测试自身的正确性**。
cycle-4 之前我们 3 次 R250 / R246 / R254 都是测试找到代码 bug，
这是第一次找到测试自己的 bug。建立新平衡。

修复后该 helper 被 `_strip_html_comments()` 先剥再匹配，**所有**
使用 `_extract_head`/`_extract_body` 的 test 都受益。

**P3: "wrapper 命名约定" pattern**

Track C (R259c) 揭示一个隐性约定：

- `_t`, `_tl`, `hostT`, `__vuT`, `__domSecT`, `__ncT`, `AIIA_I18N.t`
  这些都是 i18n wrapper，**已注册到** `_JS_T_CALL_RE` 正则
- 但 `_resolveLabel` 在 `ios_a2hs_hint.js` 里也是 i18n wrapper（带
  fallback 兜底语义），**没注册** → 4 个 `page.iosA2hs.*` key 被
  误判 orphan/dead

**教训**：新的 i18n wrapper 函数 = 新的"名字"，必须同步更新
`_JS_T_CALL_RE`（在 `scripts/check_i18n_orphan_keys.py` 和
`tests/test_runtime_behavior.py` 两个文件，**两处必须同步**）。

文档化的下一步：把这个约定写进 `CONTRIBUTING.md` 第 §3 节 "Commit
style" 旁边的"新 wrapper 函数 checklist"（cycle-5 follow-up）。

**P4: "Markdown 不进 docstring" pattern**

Track D (R259d) 教训：flasgger / OpenAPI / Swagger 这类把 docstring
当 YAML 解析的工具，**任何 Markdown 块级语法**（`-` bullets，`##`
标题，`>` blockquote）都会 break YAML 解析。

**规则**：
- 设计文档型说明 → 放函数定义**前**的 `#` 行注释里
- 接口契约（response schema 等）→ 放 docstring 的 `---` 后 YAML 里
- 两者**不要混合**

cycle-5 follow-up：加 invariant 扫所有 `@self.app.route` decorator
的 docstring，确保 `---` 后**没有** `\n## ` / `\n- ` 这种 Markdown
脏字符。

---

## §3 Inventory

### §3.1 cr48 § 5 follow-ups 状态

| ID | 描述 | cycle-4 状态 | 备注 |
|----|------|-------------|------|
| #1 | `.btn-primary` white-on-#007aff = 4.02:1 FAIL | **deferred** | 涉及 R66/R109 锁定 hex 族，需要协调修改 → cycle-5 |
| #2 | 8 个组件 :focus-visible 没用 `--focus-ring-color` | deferred | cycle-5 polish |
| #3 | status hex hardcode invariant | **shipped (Track A)** | + 3 个 latent bug |
| #4 | light `bg-primary` 设计约束写 CONTRIBUTING | **shipped (Track F)** | §3.ter 新章节 |
| #5 | 3 个 test 的 WCAG helpers 合并 | deferred | 收益低 |
| #6-8 | border / hover / AAA 升级 | deferred | cycle-6 candidate |
| #9-11 | keyboard / ARIA / VoiceOver | deferred | cycle-5 candidate |

### §3.2 invariant-driven 新发现 bug

| 文件 | 行 | 旧值 | 新值 | 严重性 |
|------|----|------|------|--------|
| `main.css` | 7477 | `color: rgba(239, 68, 68, 1)` | `var(--error-500)` | medium (dark theme hover, AA pass on bg-secondary) |
| `main.css` | 7487 | `color: rgba(239, 68, 68, 1)` | `var(--error-500)` | medium (同上) |
| `main.css` | 7847 | `color: #ef4444;` | `var(--error-500)` | **HIGH** (light theme hover, 2.40:1 on #e8e6dc) |

Line 7847 在 light theme 上是 **WCAG AA-normal FAIL** —— 用户 hover task
关闭按钮看到的是 2.40:1 红字，正好低于 4.5:1 阈值。R259a 升级到 `var(--error-500)`
= `#b03d38` (5.06:1 AA-normal pass)。

### §3.3 test-side fixes

| 文件 | 修复 | impact |
|------|------|--------|
| `tests/test_critical_preload_r21_1.py` | `_extract_head/body` 加 `_strip_html_comments` 前处理 | 修复 1 个 false-positive 失败 + 防御未来类似 false-positive |
| `tests/test_runtime_behavior.py` `_JS_T_CALL_RE` | 加 `_resolveLabel` 旁支 | 修 4 个 orphan key false-positive |
| `scripts/check_i18n_orphan_keys.py` `JS_T_CALL_RE` | 同上同步 | 保 strict mode green |
| `src/.../web_ui_routes/task.py` | `freeze_task_deadline` docstring 拆分 | 修 swagger YAML parser 失败 |
| `README.md` / `README.zh-CN.md` | "5,400+ tests" → "6,000+ tests" | 修 stale-claim invariant (lag 636 → 35) |

---

## §4 实施细节

### §4.1 Track A 实现

**新增**：`tests/test_feat_a11y_cycle4_status_hex_hardcode.py` —— 5 invariants

测试矩阵：

- `TestNoOldStatusHexHardcoded` (4 tests)：cycle-2 R257b **之前**的 hex
  不应再出现在 rule body 内（允许出现在 `--token:` 定义内）
  - `#ef4444` (旧 dark error)
  - `#3b82f6` (旧 dark info — 实际验证只在 token 内)
  - `#788c5d` / `#c54d47` / `#f59e0b` / `#6a9bcc` (旧 light status)
- `TestNewStatusHexOnlyInTokenDefs` (1 test)：cycle-2 R257b **之后**的
  hex 也只能在 token 定义内出现（防止"先漂移再正确"的伪修复）

**关键 helper**：`_hex_outside_token_defs(css, hex)` 先剥 `/* ... */`
注释，再过滤 `--token:\s*HEX` 形式的 token 定义行，返回剩余引用——也
就是 hardcode 泄漏点。

**Bonus discovery (R259a)**：跑测试**第一次**就抓到 line 7847 的
`color: #ef4444`（light theme），然后人工排查同文件相关 selector
找到 line 7475+7485 的 rgba 形式（test 没有专门 RGB 形式检测，但
人工"hex 与 rgba 互译"思维抓住了）。

3 处统一切到 `var(--error-500)`，跟随 cycle-2 R257b token 升级。

### §4.2 Track B 实现

**修改**：`tests/test_critical_preload_r21_1.py`

加 helper：

```python
def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--[\s\S]*?-->", "", text)
```

`_extract_head` 和 `_extract_body` 调用前先 `_strip_html_comments`。
这是 R259b 的核心：注释里的 `<body>` 文档引用不应被结构 invariant
误命中。

### §4.3 Track C 实现

**修改**两个文件**两处同步**：

```python
# Before
r"""(?:(?<![.\w])(?:_?tl?|hostT|__vuT|__domSecT|__ncT)|AIIA_I18N\.t)\(\s*..."""

# After  R259c — 加 |_resolveLabel
r"""(?:(?<![.\w])(?:_?tl?|hostT|__vuT|__domSecT|__ncT|_resolveLabel)|AIIA_I18N\.t)\(\s*..."""
```

文件：
- `scripts/check_i18n_orphan_keys.py` line ~62
- `tests/test_runtime_behavior.py` line ~123

`_resolveLabel` 是 `ios_a2hs_hint.js` 的本地 i18n wrapper（带 fallback
默认值，用于 SSR/早期渲染 i18n 未就绪时兜底）。

### §4.4 Track D 实现

**修改**：`src/.../web_ui_routes/task.py` `freeze_task_deadline`

把 docstring 末尾的 `## 设计原因 / 历史教训` Markdown 块整段移到
**函数定义前**的 Python `#` 注释（保持原文+原 bullets，同时不破
坏 flasgger YAML 解析）。

### §4.5 Track E 实现

`README.md` / `README.zh-CN.md` 把 "5,400+ tests" → "6,000+ tests"。
新值在 R233 invariant 的 `MAX_LAG_TESTS=500` 阈值内（当前 actual
6,036，stated 6,000，lag = 36）。

### §4.6 Track F 实现

`.github/CONTRIBUTING.md` 和 `.github/CONTRIBUTING.zh-CN.md` 在
`## 3.bis Frontend FOUC` 之后插入新章节 `## 3.ter 新颜色 token 的递归
设计约束`，把以下教训写进 codebase：

1. light `--bg-primary #e8e6dc` **3 次** 被识别为 contrast-constraining
   axis（cycle-2 L2/L5，cycle-3 L2）
2. 新 token 检查顺序：**先 light contrast, 再 dark contrast**
3. 用 invariant test 当 gate，不要相信肉眼判断
4. 约束家族模式：新颜色通常在 Tailwind 600-700 shade

---

## §5 测试结果

```
tests/test_feat_a11y_cycle1_kshelp_focus.py         16 passed
tests/test_feat_a11y_cycle1_prefers_contrast.py      7 passed
tests/test_feat_a11y_cycle2_wcag_contrast.py        31 passed
tests/test_feat_a11y_cycle3_wcag_focus_ring.py       7 passed
tests/test_feat_a11y_cycle4_status_hex_hardcode.py   5 passed (新)
─────────────────────────────────────────────────────────────
total a11y                                          66 passed (+5)
total project                                    6,035 passed
```

修复前全套 5 个失败 → 修复后 0 失败：
1. `test_critical_preload_r21_1.py::TestPreloadPosition::test_preload_links_only_in_head`
2. `test_i18n_orphan_keys.py::TestMainModes::test_strict_exits_zero_when_no_orphans`
3. `test_runtime_behavior.py::TestI18nDeadKeys::test_web_locale_no_dead_keys`
4. `test_lazy_swagger_optin_r23_3.py::TestEnabledPath::test_enabled_apispec_returns_json`
5. `test_readme_factual_claims_invariant_r233.py::TestTestCountClaimNotTooStale::test_*`

---

## §6 经验沉淀 (5 lessons)

**L1: invariant-driven cycle = test-first auditing**

cycle-4 Track A 是最纯的 "test-first" 例子。先写 invariant
（守约束的代码），跑 → 看 fail → 修真实 bug → 守住。
不预测哪里有问题，让测试告诉我。

mining-cycles 是"在别人 codebase 里找好东西借鉴"，audit-cycles
是"在自己 codebase 里写守门 invariant，让测试找出我没想到的
漂移"。两者互补。

**L2: 测试 fail 不等于代码 bug**

Track B (R259b) 是第一次"测试自己有 bug"。之前 R250 / R246 /
R254 都是测试找到代码 bug，建立了"测试 fail = 代码错"的认知偏
差。Track B 打破这个偏差：**先排查测试 helper 的正确性**，
特别是 regex / parsing / comment-handling 这类容易 false-
positive 的逻辑。

**L3: wrapper 命名约定要可发现**

Track C (R259c) 揭示：i18n wrapper 函数名是隐性约定（已注册的
`_t/_tl/hostT/...` vs 没注册的 `_resolveLabel`）。约定**不可
发现** = 漂移源。cycle-5 follow-up 把"加新 wrapper 时必须同步
2 个正则文件"写进 CONTRIBUTING.md 第 §3 节。

**L4: Markdown 与 docstring 工具不兼容**

Track D (R259d) 教训：当 docstring 被特殊工具（flasgger / sphinx /
typedoc / etc.）解析时，Markdown 块级语法可能 break parser。规则：
设计文档型说明用函数前 `#` 注释，接口契约用 docstring 内 YAML/JSON
块，**两者不要混**。

**L5: bulk health-fix 一次性收清**

cycle-4 把 5 个失败 + 3 个 latent bug + 1 个 Track A invariant + 1 个
CONTRIBUTING 章节 一次性 ship 完，避免 cycle-N+1 又开 5 个零散 commit。
这是 cycle-7 的"health-fix sweep"模式在 audit 上下文的复用。

阈值经验：每 5 commit 做一次 code review 时，**顺手把 review 之外
跑出来的 latent bug + stale claim 一并修**，比留到下一 cycle 高效。

---

## §7 saturation signals

- 4 连续 a11y-audit cycles，**没有新设计模式**，但产出
  invariant + bug fix + 文档约束三类**有形**资产
- cycle-4 第一次出现 "test-side bug"（R259b） → 测试代码也开始
  需要 invariant 守护（meta-meta）
- 第二次"3 latent bug found by 1 invariant"（cycle-2 Track B 是
  第一次） → audit 信号密度持续验证
- README factual claim drift = bg / no longer "new" 信号
  → R233 自动 nag 模式已成熟，每隔 ~30 commits 触发 1 次

---

## §8 cycle-5 follow-ups (新)

| # | 来源 | 描述 | 工作量 |
|---|------|------|--------|
| 1 | cycle-4 §2.2 P3 | CONTRIBUTING.md 加 "新 wrapper 函数 checklist" | XS |
| 2 | cycle-4 §2.2 P4 | invariant 扫 @route docstring 不含 Markdown bullets | S |
| 3 | cr48 #1 carry | `.btn-primary` WCAG fix（R66/R109 baseline 调整） | M |
| 4 | cr48 #2 carry | 8 个组件 `:focus-visible` 用 `--focus-ring-color` | S |
| 5 | cycle-4 R259a | 把 rgba(R,G,B,1) hex 形式也加进 R259 invariant | S |

---

## §9 closeout

cycle-4 在 cr48 同日 ship 完，没单独占一个 review 窗口。建议 cr49
覆盖 cycle-4 + 之后 4 个 commit。

**ship 总结**：
- 6 commits ship 本 cycle 所有 tracks
- 5 个新 invariant + 5 个原 fail 转 green
- 3 latent bug 修复（其中 1 个 light-theme A11Y 真 FAIL）
- 2 个文档章节新增 (CONTRIBUTING §3.ter + 本文档)
- 0 个 release artifact / version bump
