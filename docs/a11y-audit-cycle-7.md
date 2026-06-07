# a11y-audit-cycle-7

> Status: **track-a-closed**, Track B/C `pending`
> Started: 2026-06-05
> Methodology: v3.2 + Track F + filename convention
> WCAG focus: SC 4.1.2 (Name, Role, Value)
> Source: cr49 §5 follow-up #6 (aria-label completeness audit)
> Cycle kind: `a11y-audit` (第 4 个 a11y cycle，承接 cycle-1/2/3/5)

## §1 范围

cycles 1-5 重点：focus 管理 + WCAG 1.4.3/1.4.11 contrast。cycle-7 转向
**WCAG 4.1.2 Name, Role, Value** — 让所有交互元素有 accessible name，
让 screen reader 用户能识别 button 用途。

## §2 Tracks

### Track A: icon-only `<button>` aria-label audit (R260) — closed

#### §2.A.1 调研

- `<button>` 总数: 31
- 含 icon-only class (`btn-icon-only` / `close-btn` / `tab-close` /
  `btn-circle`) 的 button: 4
- 其中**仅有 `title` 无 `aria-label`** 的：1 个
  - `#open-config-file-btn` (settings 页 IDE 打开按钮)

#### §2.A.2 决策依据

WCAG 4.1.2 (Name, Role, Value)：所有交互元素必须有 accessible name。
``<button>`` 的优先级：``aria-labelledby`` > ``aria-label`` > inner
text > ``title``。

`title` 单独 NOT 充分：
- Screen reader 支持不一致（NVDA 朗读、VoiceOver 仅 hover 时朗读）
- 移动端/键盘用户根本看不到 tooltip
- ARIA Authoring Practices 把 ``title`` 列为"最后兜底"

#### §2.A.3 实施

```html
<button
  id="open-config-file-btn"
  class="btn btn-secondary btn-icon-only config-path-open-btn"
  data-i18n-title="settings.openConfigInIde"
  data-i18n-aria-label="settings.openConfigInIde"  ← 新增
  title="Open the config file..."
  aria-label="Open the config file..."  ← 新增
  disabled
>
```

复用现有 i18n key `settings.openConfigInIde` (3 locales 已存在)，无新
key 引入。

#### §2.A.4 invariant (R260, 2 tests)

`tests/test_feat_a11y_cycle7_icon_button_aria_label.py`：

1. **TestIconButtonsHaveAriaLabel**: 全 template 扫描，发现 `class*=
   btn-icon-only|close-btn|tab-close|btn-circle` 的 button 必有
   `aria-label` 或 `aria-labelledby`
2. **TestOpenConfigButtonI18nAriaLabel**: `#open-config-file-btn` 必有
   `data-i18n-aria-label` (确保 aria-label 随语言切换)

### Track B: modal/dialog `aria-modal` + `role` 一致性 (pending)

cycles 1 推进了 kshelp overlay focus + inert，但还没系统检查 modal
的 `role="dialog"` + `aria-modal="true"` 是否成对出现。

待办：

- 扫描所有 `class*=modal|panel|overlay` 容器
- 验证 ARIA Authoring Practices Dialog Pattern 合规
- focus management 已 cycle-1 cover

### Track C: form input `aria-describedby` for error messages (pending)

设置页 input 验证错误（cycle-2 系列）当前用 inline DOM 显示，但是
否绑 `aria-describedby` 让 screen reader 关联？待 audit。

## §3 saturation 信号

cycle-7 是第 4 个 a11y-audit cycle。Track A 只发现 1 个 violation，
信号密度比 cycle-1/2/3 低，但**单点修复价值高**（settings 页是高频
入口）。

a11y-audit cycle 信号密度演进：
- cycle-1 Track A: 1 个 kshelp focus 完整重写（高密度）
- cycle-2 Track A+B: 12 个 token 重做 (高密度)
- cycle-3 Track A: 1 个 focus-ring token + 多处 cascading 更新 (中密度)
- cycle-5 Track A-D: 4 个独立 tracks (中密度)
- cycle-7 Track A: 1 个 button 修复 (低密度)

**cycle-7 启示**：随 a11y 成熟，单 cycle Track 数量会减少但 Track 内
的"深度"应增加（即 invariant 应当 generalize，cycle-7 Track A 的
invariant 就是"通用扫所有 icon-only button"，不是"专扫这一个 button"）。

## §4 cycle-8 candidates

- Track B 延期：modal/dialog aria 一致性
- Track C 延期：form aria-describedby
- 新增: `<a>` tag 缺 link text (aria-label) audit
- 新增: image (`<img>` / `<svg>`) alt/aria-label audit (R260 同源)

## §5 closeout (Track A)

Track A 单独 ship。Track B/C 进 cycle-8 backlog。
