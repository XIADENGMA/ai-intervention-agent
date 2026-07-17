# 贡献者指南 —— 不变量测试

> **本文是什么。** 仓库里 `tests/test_*_invariant_*.py` 这一大类测试
> 的设计模式手册。下列场景之前先读本文：
> 添加一个需要长期防护、抵抗静默腐烂的新功能；
> _删除_ 一个不变量测试（这样你知道自己放弃了什么保护）；
> CI 突然在一个"看似什么都没测"的测试上 fail。

> **本文不是什么。** 通用的测试入门教程。经典的 unit /
> integration / end-to-end 测试纪律请看
> [`docs/lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md)
> 与现有测试文件。

> **English version**: [`contributor-guide-invariant-tests.md`](contributor-guide-invariant-tests.md).

## 1. 什么是不变量测试

**不变量测试**断言代码库或其产物的某个结构性属性，**这个属性必须
在任何重构后依然成立**。它不是行为测试（行为测试断言代码在
运行时**做了什么**），而是针对代码库形态本身的契约测试。

本仓库当前锁定的三个示例不变量：

- **R220 / R224**: `docs/observability/grafana-dashboard*.json` 中
  引用的每一个 `aiia_*` 指标名都必须以子串形式出现在
  `src/ai_intervention_agent/web_ui_routes/system.py` 里。否则在
  `system.py` 里改个指标名，导入的 Grafana 仪表盘会悄悄废掉，运维
  要等到面板变空白才发现。
- **R217**: `src/ai_intervention_agent/static/js/state.js` 与
  `packages/vscode/webview-state.js` 必须**字节完全一致**。否则在
  其中一个文件里修了 bug，另一个文件还在带着原 bug 运行。
- **R215**: `scripts/smoke_test_r50.py` 的 `needed` 元组必须列出
  `task.py` 里 `SSEBusStatsSnapshot` TypedDict 中的每一个标量字段。
  否则新加一个 SSE 可观测性字段时，生产烟雾测试会悄悄漏掉验证。

不变量测试**很便宜**（多数毫秒级），但每次重构、每次代码评审、
每次新贡献者上手都能拿到回报。

## 2. 何时该写一个 —— 决策树

加新功能前，问自己：

1. **此功能的正确性是否依赖多个文件保持同步？**
   - 是 → 几乎一定要写不变量测试。
   - 否 → 也许不需要；行为测试够用。
2. **同步规则是不是代码评审能可靠抓到的那种？**
   - "仪表盘 JSON 与 Python 源里的指标名必须匹配" —— 评审 10 次
     有 1 次会漏。**写不变量。**
   - "`max_attempts` 必须是正整数" —— 评审 100% 抓住。算了。
3. **此功能会不会比当前作者活得更久？**
   - 会（任何健康项目都会）→ 写不变量，避免下一个贡献者意外
     拆掉原设计决策。
4. **失败模式是不是静默的？**
   - "Grafana 面板渲染空白" —— 静默。**写不变量。**
   - "应用启动立即崩溃" —— 喧嚣。算了；普通 CI 自然抓到。
5. **失败的代价是否高于写测试的代价？**
   - 测试写 + 维护 ~30 分钟。
   - 失败要小时到几天的 debug + 用户可见的故障。**几乎总是：
     写不变量。**

## 3. 五种常见模式

本仓库已经在 **12+ 个 R-cycle 累积了 12+ 个不变量测试**
(R212、R213、R215、R216、R217、R219、R220、R221、R222、R223、R225、
R226)。它们聚集在五类可复用的模式上。

### 模式 A —— 静态源字符串存在性检查

**用例**: 锁定一段代码"绝不包含 X"或"必须包含 X"。

**例子**: `tests/test_notification_manager_console_noise_invariant_r216.py`
断言 `src/ai_intervention_agent/static/js/notification-manager.js`
中 `console.log(` 出现次数为**零**（生产环境为了让控制台安静，
应该用 `console.debug(`)。

**配方**:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "src" / "..." / "your_file.js"


def test_no_console_log_calls() -> None:
    source = TARGET.read_text(encoding="utf-8")
    count = source.count("console.log(")
    assert count == 0, (
        f"{TARGET.name} 包含 {count} 次 console.log(...) 调用; "
        "生产环境应使用 console.debug(...) 保持控制台安静。"
    )
```

**何时升级到 AST 扫描 (模式 B)**:

- 字符串同时出现在不相关的注释 / docstring 里，会产生误报。
- 需要精确计数调用点（字符串字面量里的 `console.log(` 否则也会被算上）。
- 需要强制"每次调用 X 都对应一次调用 Y"这种跨调用不变量。

### 模式 B —— 基于 AST 的调用点枚举

**用例**: 在结构层面计数或约束函数调用 / 类引用。

**例子**: `tests/test_sse_event_schemas_r198.py` 走 `src/` 下
每个 `*.py` 文件，用 `ast.parse` 解析，找出每个
`_sse_bus.emit("<literal>", ...)` 调用，断言每个 literal 事件
类型都出现在 `sse_event_schemas.py` 的 `KNOWN_SSE_EVENTS` 注册表里。

**配方**:

```python
import ast
from pathlib import Path

def _emit_event_types(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "emit"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.add(node.args[0].value)
    return found
```

**为何用 AST 而非正则**: 正则会匹配到注释、docstring、其他叫
`emit` 的函数里的 `"emit"` 字符串。AST 只看见真正的方法调用。

### 模式 C —— JSON / YAML 结构化检查

**用例**: 锁定项目发布的配置 / 数据文件的结构。

**例子**: `tests/test_grafana_dashboard_invariant_r220.py` 解析
`docs/observability/grafana-dashboard.json`，断言：

- `schemaVersion` 在 Grafana 10–11 支持范围内
- `uid` 保持稳定值 `aiia-overview-r220`
- `panels` 数量严格为 7（布局调整是刻意编辑，不是事故）
- 每个面板有非空且唯一的标题
- 面板 targets 里每个 `aiia_*` 指标都在 `system.py` 中存在

**配方**:

```python
import json
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "docs" / "..."


def test_dashboard_structure() -> None:
    data = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    panels = data.get("panels") or []
    assert len(panels) == 7, (
        f"面板数量发生漂移: 期望 7, 实际 {len(panels)}。"
        "如果是有意增删面板, 请同步更新此测试的期望计数。"
    )
    titles = [p.get("title") for p in panels]
    assert len(titles) == len(set(titles)), "重复的面板标题"
```

**小贴士**: 锁定数量（面板数、字段数、选项数）时，在测试里加一
条注释"如果你是有意改动这个数, 请同步更新期望值"。否则下一个加
面板的贡献者会花 10 分钟纠结 CI 为什么挂了。

### 模式 D —— 双语 locale 平价

**用例**: 项目同时发 `en.json` + `zh-CN.json`；新 key 必须两边
都有，消息长度必须在合理比例范围内（捕获意外的空翻译）。

**例子**: `tests/test_notification_fallback_toast_invariant_r214.py`
断言 `en.json` 里每个 `status.notifFallback*` key 在 `zh-CN.json`
中都有对应项，且中文长度在英文长度的 [0.4, 2.5]× 区间内（同时
捕获截断的翻译与冗长跑题的翻译）。

**配方**:

```python
import json
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "src" / "..." / "static" / "locales"


def test_bilingual_key_parity() -> None:
    en = json.loads((LOCALES / "en.json").read_text())
    zh = json.loads((LOCALES / "zh-CN.json").read_text())

    def flatten(prefix: str, obj: dict) -> dict[str, str]:
        result: dict[str, str] = {}
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(flatten(full_key, v))
            elif isinstance(v, str):
                result[full_key] = v
        return result

    en_keys = flatten("", en)
    zh_keys = flatten("", zh)
    missing_in_zh = set(en_keys) - set(zh_keys)
    assert not missing_in_zh, f"zh-CN 缺失 keys: {sorted(missing_in_zh)}"
```

**别忘了**: 加新 i18n key 之后跑一下
`uv run python scripts/gen_pseudo_locale.py` 重新生成
`_pseudo/pseudo.json` 伪语言，其他测试会检查它。

### 模式 E —— 跨工具 / 跨文件字节平价

**用例**: 两个文件必须**字节完全一致**，因为它们是同一段代码在
不同分发上下文里的拷贝（例如 Web UI 与 VS Code webview 共享逻辑）。

**例子**: `tests/test_state_machine.py::TestJsSync::test_two_js_files_are_byte_identical`
断言 `src/ai_intervention_agent/static/js/state.js` 与
`packages/vscode/webview-state.js` 字节完全一致。这两个文件刻意
重复，没用 import，是因为 VS Code webview 无法访问 `packages/vscode`
之外的文件（否则 .vsix 体积会膨胀）。

**配方**:

```python
import hashlib
from pathlib import Path

TWIN_A = Path(__file__).resolve().parent.parent / "src" / "..."
TWIN_B = Path(__file__).resolve().parent.parent / "packages" / "..."


def test_twins_are_byte_identical() -> None:
    a_hash = hashlib.sha256(TWIN_A.read_bytes()).hexdigest()
    b_hash = hashlib.sha256(TWIN_B.read_bytes()).hexdigest()
    assert a_hash == b_hash, (
        f"{TWIN_A.relative_to(TWIN_A.parents[3])} 与 "
        f"{TWIN_B.relative_to(TWIN_A.parents[3])} 已经字节不一致。"
        "如果你在其中一个里修了 bug, 请把同样的修复 copy 到另一个;"
        "重复是刻意的, 因为 VS Code webview 无法 import "
        "packages/vscode 之外的文件。"
    )
```

**R217 中途抓到的漂移**: 在 `state.js` 里把 `console.log` 降级
到 `console.debug`，但忘了在 `webview-state.js` 同步同样的改动，
该测试中途打挂；当场 1 分钟修好，比之后 "为什么浏览器能跑 VS
Code 跑不了？" 几小时的 debug 节约多了。

## 4. 应该回避的反模式

- **不要写一个与行为测试重复的不变量**。
  如果 `test_handler_returns_200_on_valid_input` 在 handler 正常时
  本来就过，那就不需要再加一个
  `test_handler_function_exists`。

- **不要锁一个本就该自然增长的计数**。
  `assert len(items) == 7` 适合 "已完成的仪表盘的面板数"。
  `assert len(items) == 7` **不适合** "支持的 MCP 工具数量" ——
  这种会涨。改用 `assert len(items) >= 7` 表示 "单调增长"，或
  `assert 7 <= len(items) <= 50` 表示 "保持在合理区间内"。

- **不要在三个测试里把同一个文件读三遍**。
  把解析结果缓存到模块级常量或 `setUpModule()`，免得 30 个不变量
  叠加做 30 次 AST 解析。

- **不要写不在 docstring 里说 WHY 的不变量测试**。
  6 个月后未来的你不会记得 "指标名平价" 为什么重要。把 docstring
  写得像是在向"刚 onboarding、问我能不能删掉这个测试它让我 PR 挂
  了"的贡献者解释。

- **不要让不变量测试依赖仓库里不存在的 ground-truth 数据**。
  如果你的测试需要生产 Prometheus 实例去 scrape 指标，那它是
  生产烟雾测试，不是不变量测试。把它挪到 `scripts/smoke_test_*.py`
  并配单独的 CI job 跑。

## 5. 工作流

1. 判断是否需要写不变量（用 §2 决策树）。
2. 从 §3 挑最贴切的模式。
3. 创建 `tests/test_<feature>_invariant_r<NNN>.py`，文件名取
   引入该不变量的 R-cycle 编号。
4. 开头写多行模块 docstring 说清楚：
   - 哪个 R-cycle 加的、为什么加
   - 测试防的具体是什么漂移
   - 链接到 CR / CHANGELOG 的来源
   - 测试覆盖的 case 列表（编号）
5. 用上面的配方写测试。优先继承 `unittest.TestCase`（与仓库其余
   测试风格一致）。
6. 跑 `uv run pytest tests/test_<feature>_invariant_r<NNN>.py`
   确认当前 tree 通过。
7. 在 dev branch 里**故意打破**这个不变量（比如改个指标名、漏个
   key），确认测试**报错**且报错信息可操作。**如果信息不可操作，
   就改写它**。
8. 恢复工作树，把测试和它保护的功能一起 commit，并在 CHANGELOG
   里加一条引用该 R-cycle 编号的条目。

## 6. 仓库不变量测试总览

下列 R-cycle 引入了覆盖对应表面的不变量测试。新加的不变量请用
同样的命名模式（`tests/test_<topic>_invariant_r<NNN>.py`）与同样
的 docstring 模板。

| R-cycle | 测试文件                                                                | 不变量类型                       | 锁定内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------- | ----------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| R212    | `tests/test_sse_schema_validate_contract_r212.py`                       | 跨模块                           | R205 schema 校验开关 ↔ R210 stats snapshot 一致性                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| R213    | `tests/test_static_precompress_production_invariant_r213.py`            | 文件系统                         | 生产静态资源都有对应的 `.gz` + `.br` 副本                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| R215    | `tests/test_smoke_test_r50_field_drift_invariant_r215.py`               | 跨文件                           | `smoke_test_r50.py` `needed` 元组 ↔ `SSEBusStatsSnapshot` TypedDict                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| R216    | `tests/test_notification_manager_console_noise_invariant_r216.py`       | 模式 A                           | `notification-manager.js` 中 `console.log(` 数量为 0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| R217    | `tests/test_static_js_console_log_demotion_invariant_r217.py`           | 模式 A                           | 9 个项目自有 JS 文件中 `console.log(` 数量为 0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| R219    | `tests/test_changelog_inline_code_lint_r219.py`                         | 模式 A                           | CHANGELOG.md 使用 Markdown 单反引号（非 RST 双反引号）的 inline code 风格                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| R220    | `tests/test_grafana_dashboard_invariant_r220.py`                        | 模式 C                           | Grafana 概览仪表盘 ↔ `system.py` `/metrics` 名称平价                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| R221    | `tests/test_vscode_webview_console_noise_invariant_r221.py`             | 模式 A                           | `packages/vscode/` 项目自有 JS 中 `console.log(` 数量为 0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| R222    | `tests/test_readme_related_projects_invariant_r222.py`                  | 模式 D                           | 双语 README 的 "Related projects" 表保持同步                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| R223    | `tests/test_settings_shortcuts_full_help_hint_invariant_r223.py`        | 模式 D                           | 设置面板键盘快捷键提示的 i18n 平价                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| R224    | `tests/test_grafana_dashboard_notif_providers_invariant_r224.py`        | 模式 B                           | 每个 provider 的通知 dashboard JSON 与 `system.py` 暴露的 metric 对齐                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| R225    | `tests/test_remote_environment_detector_r225.py`                        | 混合 (A+D)                       | SSH/WSL 探测器契约 + `web_ui.py` 集成守门                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| R226    | `tests/test_precompress_pre_commit_hook_invariant_r226.py`              | 模式 C                           | `.pre-commit-config.yaml` 中预压缩新鲜度 hook 已注册且配置正确                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| R227    | `tests/test_invariant_test_guide_catalogue_r227.py`                     | 模式 C + D                       | 本目录引用的测试文件都真实存在 + 双语平价                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| R228    | `tests/test_shortcuts_notification_body_completeness_invariant_r228.py` | 模式 D + 跨文件                  | `Ctrl+/` 通知 body 列出每一个快捷键 + 交叉校验 `keyboard-shortcuts.js`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| R229    | `tests/test_submit_btn_disabled_visible_invariant_r229.py`              | 模式 A + 模式 C                  | 深浅两套主题的 `:disabled` CSS 规则存在 + JS 不再给 submit 按钮写 inline 颜色                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| R230    | `tests/test_decorative_svgs_aria_hidden_invariant_r230.py`              | 模式 A                           | `web_ui.html` 每一个 `<svg>` 都有 `aria-hidden="true"` + `focusable="false"` (a11y / WCAG 1.1.1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| R232    | `tests/test_icon_only_buttons_aria_label_invariant_r232.py`             | 模式 A                           | 每个 icon-only `<button>` / `<a role=button>` 必须有非空 `aria-label` / `aria-labelledby` (a11y / WCAG 4.1.2, R230 后续锁定)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| R233    | `tests/test_readme_factual_claims_invariant_r233.py`                    | 模式 B + 模式 D                  | README 量化 claim（测试数、subtest 数、release pipeline job 数）保持在与正典源（`release.yml` / `pytest --collect-only`）的容差范围内                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| R234    | `tests/test_feedback_textarea_disabled_css_invariant_r234.py`           | 模式 A                           | `.feedback-textarea:disabled` 在深/浅两个主题都存在, 都声明 4 个视觉提示 (background/color/cursor/border-color), 浅色用 `!important`; JS 不写 inline 的伴随断言放在 R229 测试文件                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| R235    | `tests/test_form_inputs_accessible_name_invariant_r235.py`              | 模式 A                           | 每个 `<input>`（非 hidden/submit/button/reset/image）+ 每个 `<textarea>` 必须有 accessible name（包裹 `<label>` / `<label for>` / `aria-label` / `aria-labelledby` / `aria-hidden=true + tabindex=-1`）(a11y / WCAG 4.1.2, R230/R232 后续锁定)                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| R236    | `tests/test_ty_precommit_hook_invariant_r236.py`                        | 模式 B + 模式 A                  | `.pre-commit-config.yaml` 必须保留 `ty-check` hook（默认 `[pre-commit]` 阶段、运行 `ty check`、filter `*.py`），`ci_gate.py` 仍要调用 `ty`（pre-commit 是 fast shadow，CI 是契约）。防止 v1.7.5-style 废弃 release。                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| R237    | `tests/test_dialog_aria_compliance_invariant_r237.py`                   | 模式 A                           | 每个 `role="dialog"` 元素必须有 `aria-modal="true"` + (`aria-labelledby` 指向真实存在的 id 或 `aria-label`) + 默认隐藏 (class `hidden` 或 `[hidden]` 属性)。WAI-ARIA 1.2 + WCAG 4.1.2 锁定。Cycle 14 a11y 第 4 波（R230→R232→R235 是控件，R237 是模态层）。                                                                                                                                                                                                                                                                                                                                                                                                                                |
| R238    | `tests/test_modal_focus_trap_invariant_r238.py`                         | 模式 B                           | 两个模态对话框（`#code-paste-panel` + `#settings-panel`）实现 Tab / Shift-Tab 焦点陷阱（`app.js` 的 `_modalFocusTrap` + `settings-manager.js` 的 `_settingsFocusTrap`），使用 W3C 标准的可聚焦选择器 + `offsetParent !== null` 可见性过滤；关闭处理把焦点还给打开者（`#feedback-text` / `#settings-btn`）。是 R237 声明性 ARIA 契约的命令式焦点管理伙伴。                                                                                                                                                                                                                                                                                                                                  |
| R239    | `tests/test_star_counts_freshness_invariant_r239.py`                    | 模式 D                           | README "Related projects" 表的 star 数快照日期（"last reviewed YYYY-MM" / "最近核对：YYYY-MM"）必须可解析、不在未来、距今 ≤ 12 个月（可通过环境变量 `R239_STAR_COUNT_MAX_AGE_MONTHS` 覆盖），并且 EN + ZH 两份 README 日期一致。模式 D 漂移检测。                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| R240    | `tests/test_modal_inert_background_invariant_r240.py`                   | 模式 B                           | 两个模态打开函数（`showSettings`、`openCodePasteModal`）必须把 `.container`（`role="main"` 容器）标为 `inert`，对应关闭函数清除；两处都用 `try { el.inert = … } catch { setAttribute("inert", …) }` 防御性写法。与 R237 (ARIA) + R238 (焦点陷阱) 组成 a11y 第 4 波三件套：模态打开时鼠标、键盘、AT 都不能再到达背景。                                                                                                                                                                                                                                                                                                                                                                      |
| R241    | `tests/test_inert_helper_dry_invariant_r241.py`                         | 模式 B                           | `_safelySetInert(el, value)` DRY 辅助函数在 `app.js`（top-level 函数）和 `settings-manager.js`（class method）都存在并具备相同分支行为；调用点必须用 helper —— helper 定义外不能再有 `container.inert = …` inline 赋值。关闭 CR#28 的 F-cycle15-2（抽取 R240 的 4× 重复 try/catch）。                                                                                                                                                                                                                                                                                                                                                                                                      |
| R242    | `tests/test_minify_precommit_hook_invariant_r242.py`                    | 模式 B                           | `check-static-minified-fresh` pre-commit hook 必须存在，entry 真正调用 `scripts/minify_assets.py --check`，files filter 匹配 `static/(css\|js)`，hook 不被流放到 `manual`/`pre-push`，配套脚本依然存在并保留 `--check` 旗标。R242 关闭 R234/R238/R240/R241 暴露出的"修改 .js/.css 后 Flask 仍 serve 旧 .min 文件"沉默 bug —— 与 R226（precompress 新鲜度）同构问题，在第二条构建产物链上补齐。                                                                                                                                                                                                                                                                                             |
| R243    | `tests/test_get_minified_file_freshness_r243.py`                        | 模式 A（运行时）                 | `_get_minified_file()` 在请求时拒绝 stale `.min`（mtime < source → fallback 到 source 并 WARN 每文件一次）。端到端行为测试，用真实 tempdir 文件：fresh-min 仍选用、stale-min 被拒、WARN 按文件名独立 dedup（不同文件互不影响）、显式请求 `.min` 仍直通、缺失 `.min` 仍 fallback、`stat()` 抛 `OSError` 时 static 端点不崩。R243 是 R242 commit-time 防御的运行时配套层，覆盖 `--no-verify` 与 hook 未触及的 pre-existing stale 文件。                                                                                                                                                                                                                                                      |
| R244    | `tests/test_modal_not_self_inert_invariant_r244.py`                     | 模式 B                           | 修复 R240 cascade self-inert bug：两个 modal 都在 `.container` 内，旧版 `container.inert = true` 让 modal 自己也变 inert（沉默地破坏点击/焦点）。新 helper `_setContainerSiblingsInert(openModalEl, value)` 在 `app.js`（top-level fn）和 `settings-manager.js`（class method）都存在；它遍历 `container.children` 并跳过 `openModalEl`。四个 modal 开/关路径（`openCodePasteModal`/`closeCodePasteModal`/`showSettings`/`hideSettings`）必须调用新 helper 并传 panel 元素；回归守卫禁止任何 modal 路径出现 `container.inert = …` / `_safelySetInert(document.querySelector(".container"), …)`。关闭 R240 引入但被静默隐藏 4 个 cycle 的 UX 杀手 —— R240 当时只有 Pattern B 测试因此漏检。 |
| R245    | `tests/test_dialog_not_in_inert_subtree_invariant_r245.py`              | 模式 A++（HTML 层 cascade 模型） | Cascade-aware 结构性 invariant，把 R244 的具体修复推广到所有未来 modal 添加。解析 `web_ui.html` 收集每个 `role="dialog"` 元素及其到 `<body>` 的祖先链；解析 `app.js` + `settings-manager.js` 抽取 DANGEROUS 直接 inert selector（如 `.container`）；如果某个 dialog 的祖先链包含 dangerous selector 就 fail（除非 JS 用了 R244 sibling 遍历 helper 明确 skip 当前 dialog）。已确认能捕获 R240 原始 bug 模式（见 test docstring）。局限：纯静态，不模拟 JS 在运行时 `createElement` 注入的 modal —— 那种动态场景仍依赖 F-cycle16-playwright。                                                                                                                                               |
| R246    | `tests/test_build_artifact_freshness_matrix_invariant_r246.py`          | 模式 B                           | 补齐 R226（precompress）+ R242（minify）开启的「build-artifact 新鲜度 pre-commit 矩阵」。把剩余 4 个 generator（`gen_i18n_types`、`gen_pseudo_locale`、`generate_docs` × 2 语言、`generate_pwa_icons`）从只在 CI 跑提升到 pre-commit hook。5 个 hook id 必须满足：存在性 + 正确 `--check` 调用 + 限定 `files` filter + 不被流放到 manual/pre-push + 配套脚本 + 仍支持 `--check` flag + ci_gate.py 仍调用非 PWA 的脚本（`--no-verify` 旁路的纵深防御）。R246 之后，6 条 build-artifact 链全部具备 pre-commit fail-fast + ci_gate canonical-truth 双层守护，矩阵统一。                                                                                                                       |
| R412    | `tests/test_feat_openapi_property_description_completeness_r412.py`     | 模式 A + ratchet                  | **v3.10.2 OpenAPI 文档质量矩阵第二个 sub-pattern**。API contract 第 9 应用。静态扫描 `web_ui_routes/*.py` 所有 OpenAPI YAML properties；ratchet 策略锁非 envelope property 的 description 覆盖率 ≥ 70%（R418 ratchet from 45%）；envelope 字段（`status` / `success` / `message` / `error`）显式 whitelist（REST 通用响应包装含义全球一致）。future cycle 可加 description 推 coverage 至 80%+，然后 ratchet 上调 `MIN_NON_ENVELOPE_DESC_COVERAGE`。ratchet 设计 = 持续改进 + 强制单调递增。 |
| R414    | `tests/test_feat_routes_mixin_matrix_negative_validation_r414.py`       | 模式 B + meta-invariant           | **第 14 维度（Mixin route registration matrix）第 2 应用 + 项目首个 meta-invariant**。R406 是 positive-only test（只验证当前状态 OK），R414 通过 synthetic 输入验证 R406 的辅助函数在真实漂移场景下会正确 fire（覆盖 layer 2/3/4/naming 4 个 negative 场景）。meta-invariant 价值：保证 R406 在 future 真实漂移时仍然 fire，而不是因为某次 refactor 把 R406 静默 ignored。self-validation pattern 可扩展到 R404/R412/R408 等其他 invariant；累计 3+ 应用可提升为 v3.11 系列命名（meta-invariants）。              |
| R416    | `tests/test_feat_version_quintet_sync_invariant_r416.py`                | 模式 A + Release 基础设施         | **release 基础设施强化 — 防 v1.7.5-style 多源 version drift release**。锁 5 个版本来源严格相等：`pyproject.toml` / `CITATION.cff` / `package.json` / `packages/vscode/package.json` / `package-lock.json`（root + packages.""）。结构化 invariant 不锁具体版本号，每次 release 不需修改（与 R341/R382/R410 等具体版本锁互补形成「release 时做对 + release 间不退」双层保护）。历史失败模式：v1.7.5 release 因 `pyproject.toml` 已 bump 但 `package.json` 未同步 → release 失败（`docs/release-checklist.md:71`）。            |
| R418    | `tests/test_feat_openapi_property_description_ratchet_r418.py`          | 模式 B + meta-invariant           | **R412 ratchet uplift + real improvement + self-validation 第 2 应用**。R412 启动 v3.10.2 锁 baseline 45%，R418 在同 cycle 实施 real improvement：（1）加 25 个 description 到 task.py + feedback.py 高频字段（task_id / created_at / auto_resubmit_timeout / remaining_time / server_time 等），（2）ratchet up `MIN_NON_ENVELOPE_DESC_COVERAGE`：0.45 → 0.70（实际 coverage 50% → 75%）。项目第一个 **invariant + 实施改进 + ratchet up** 三位一体 commit。ratchet 模式可扩展到 doc-parity / i18n / security header 等其他 ratchet 型 invariant。              |
| R422    | `tests/test_feat_openapi_error_response_schema_parity_r422.py`          | 模式 A + ratchet                  | **v3.10.3 OpenAPI 文档质量矩阵第 3 sub-pattern — error path 完整性**。API contract 第 11 应用（含 v3.10.1 endpoint summary R404 + v3.10.2 property description R412/R418）。静态扫描 `web_ui_routes/*.py` OpenAPI YAML 所有 4xx/5xx response（status code 400-599），统计有 `schema:` 字段的比例；ratchet 锁 `MIN_ERROR_RESPONSE_SCHEMA_COVERAGE` ≥ 0.05（当前 3/51 = 5.88%）。业务价值：当前 51 个 error response 仅 3 个（5.88%）有 schema，客户端无法静态消费错误响应结构，大量 retry 逻辑靠 try-catch；future cycle 加 schema 推 coverage → ratchet 上调 baseline（推荐节奏 0.05→0.15→0.30→0.50→0.70→0.90）。ratchet 模式第 3 应用（R412/R418/R422）。           |
| R424    | `tests/test_feat_doc_parity_negative_validation_r424.py`                | 模式 B + meta-invariant           | **meta-invariant 第 3 应用 — 元方法学层（维度 15）工业化里程碑**。R414（Mixin matrix negative）→ R418（R412 ratchet uplift validation）→ **R424（doc-parity R400 negative）** 形成 3 应用工业化，元方法学层（v3.11 候选）正式从孵化进入稳定 pattern。通过 synthetic drift 输入（H2 count mismatch / unmapped H2 / code block 不平衡 / link 差异 > 3）反向验证 R400 的辅助函数（`_extract_h2_headings`、`SECTION_MAPPING`、`_count_code_blocks`、`_count_external_links`）在真实漂移场景下能正确 fire，防止 R400 silently broken（positive-only test 的盲点）。doc-parity invariant 的 invariant，守护方法学入口文档不被静默双语漂移。                              |
| R426    | `tests/test_feat_openapi_property_description_ratchet_r426.py`          | 模式 B + meta-invariant           | **R412 ratchet uplift 第 2 次 + meta-invariant 第 4 应用 + 实施改进 + ratchet up 三位一体 第 2 次**。R412（cycle-47 #A1 baseline 45%）→ R418（cycle-47 #D1，+25 descriptions，coverage 50% → 75%，ratchet 45% → 70%）→ **R426（cycle-48 #D1，+14 descriptions，coverage 70% → 85%，ratchet 70% → 80%）**。cycle-48 内为 `notification.py`（bark / *Enabled / *Volume 通知配置字段）+ `feedback.py`（predefined_options / task_id）+ `system.py`（token rotation/status 元数据）添加 14 个 description，把非 envelope coverage 从 70.15% 推到 85.07%，然后 ratchet `MIN_NON_ENVELOPE_DESC_COVERAGE` 至 0.80。元方法学层应用累计 4（R414 / R418 / R424 / R426）进入超稳定阶段。                                            |
| R428    | `tests/test_feat_openapi_error_response_schema_ratchet_r428.py`         | 模式 B + meta-invariant           | **R422 ratchet uplift 第 1 次 + meta-invariant 第 5 应用 + 实施改进 + ratchet up 三位一体 第 3 次**。R422（cycle-48 #B1 baseline 5%）→ **R428（cycle-49 #A1，+8 schemas，coverage 5.88% → 21.57%，ratchet 0.05 → 0.15）**。cycle-49 内为 `feedback.py`（POST /api/update-feedback 400/500）+ `task.py`（GET /api/tasks 500，GET /api/tasks/download 400/500，POST /api/tasks 400/409/500）添加 8 个 schema，把 4xx/5xx schema coverage 从 5.88% 推到 21.57%，然后 ratchet `MIN_ERROR_RESPONSE_SCHEMA_COVERAGE` 至 0.15。ratchet 模式累计应用 R412/R418/R422/R426/R428（**5 应用 = 工业化巩固期**）。元方法学层（维度 15）应用累计 5（R414/R418/R424/R426/R428）进入超稳定 + 与老牌方法学维度并肩。               |
| R430    | `tests/test_feat_endpoint_summary_negative_validation_r430.py`          | 模式 B + meta-invariant           | **meta-invariant 第 6 应用 — 元方法学层超巩固期 + API contract meta-invariant 子模式 1st app**。R414 → R418 → R424 → R426 → R428 → **R430** = 6 应用进入超巩固期，与 doc-parity（6 应用）并列成熟方法学维度。同时是 API contract pattern 第一次得到元保护层 — 把 meta-invariant 模式从 doc-parity / ratchet 扩展到 API contract 维度。通过 5 种 synthetic OpenAPI docstring drift（空 first-line / < 5 chars / > 200 chars / TODO marker / 待定 中文 marker）反向验证 R404 的 `_extract_endpoint_summaries` / `FIRST_LINE_MIN_LEN` / `FIRST_LINE_MAX_LEN` / `PLACEHOLDER_MARKERS` 辅助函数能正确 fire，防止 R404 silently broken。                  |
| R432    | `tests/test_feat_openapi_error_schema_ratchet_2nd_r432.py`              | 模式 B + meta-invariant           | **R422 ratchet uplift 第 2 次 + meta-invariant 第 7 应用 + 实施改进 + ratchet up 三位一体 第 4 次 — notification.py 焦点**。R422（cycle-48 #B1 baseline 5%）→ R428（cycle-49 #A1，+8 schemas，coverage → 21.57%，ratchet → 0.15）→ **R432（cycle-49 #C1，+8 schemas，coverage → 37.25%，ratchet → 0.30）**。cycle-49 内为 `notification.py`（test-bark-notification 400/500 + trigger-task-notification 500 + notification-config 500 + GET /api/notification-config 500 + GET /api/get-feedback-config 500 + POST /api/update-feedback-config 400/500）添加 8 个 schema，把 4xx/5xx schema coverage 推到 37.25%，然后 ratchet 至 0.30。ratchet 模式累计应用 6（R412/R418/R422/R426/R428/R432），元方法学层 7 应用进入超巩固期 + 1。 |
| R436    | `tests/test_feat_openapi_error_schema_ratchet_3rd_r436.py`              | 模式 B + meta-invariant           | **R422 ratchet uplift 第 3 次 + meta-invariant 第 8 应用 + 实施改进 + ratchet up 三位一体 第 5 次 — system.py admin endpoints 焦点**。R422 → R428 → R432 → **R436（cycle-50 #A1，+8 schemas，coverage → 52.94%，ratchet → 0.50）**。cycle-50 内为 `system.py` admin endpoints（open-config-file 400/403/500 + healthz 503 + set-log-level 400/403）+ `task.py` GET /api/tasks/<id> 404/500 添加 8 个 schema，把 4xx/5xx schema coverage 推到 52.94%，然后 ratchet 至 0.50。**ratchet 模式累计应用 7（R412/R418/R422/R426/R428/R432/R436）→ 巩固期完全成熟**，「实施改进 + ratchet up 三位一体」累计 5 应用 → pattern 完全工业化，元方法学层 8 应用进入深化期。 |                                                                                                                       |
| R438    | `tests/test_feat_i18n_untranslated_negative_validation_r438.py`         | 模式 B + meta-invariant           | **R350（i18n untranslated keys audit）负面自验证 — i18n meta-invariant 子模式第 1 次应用 + 元方法学层第 9 应用 → 完全工业化阈值达成**。cycle-50 #B1。合成 4 种 i18n drift 场景（100% 未翻译 / 50% 未翻译 / 平衡翻译 / _meta 元数据过滤），反向验证 R350 的 `_flatten_strings` helper + 比例上限算法在 locale 漂移场景能正确 fire。**元方法学层（维度 15）累计应用 9（R414/R418/R424/R426/R428/R430/R432/R436/R438）→ 完全工业化阈值达成**，形成 3 个 meta-invariant 子模式：doc-parity（R424）/ API contract（R430）/ **i18n（R438 首发，守护 R350+R353+R366+R374 共 4 个 i18n invariants）**。i18n 是 user-facing 体验最关键的维度之一（主 app + VS Code 共 4 locales），R350 静默失效 = 漏译可能不被发现伤中文用户。 |                                                                                                                       |
| R440    | `tests/test_feat_openapi_error_schema_ratchet_4th_r440.py`              | 模式 B + meta-invariant           | **R422 ratchet uplift 第 4 次 + meta-invariant 第 10 应用 + 7 成决胜 threshold 突破 — task.py countdown ops + feedback.py 429 焦点**。R422 → R428 → R432 → R436 → **R440（cycle-51 #A1，+9 schemas，coverage → 70.59%，ratchet → 0.70）**。cycle-51 内为 `task.py` POST /api/tasks/<id>/extend（400/404/422/500）+ POST /api/tasks/<id>/freeze（400/404/409/500）+ `feedback.py` POST /api/submit 429（含 retry_after hint）添加 9 个 schema，把 4xx/5xx schema coverage 推到 70.59%，然后 ratchet 至 0.70。**ratchet 模式累计应用 8（R412/R418/R422/R426/R428/R432/R436/R440）→ 巩固期持续深化**，「实施改进 + ratchet up 三位一体」累计 6 应用 → pattern 工业化深化期，元方法学层 10 应用进入完全工业化深化期。 |                                                                                                                       |
| R442    | `tests/test_feat_vscode_i18n_untranslated_negative_validation_r442.py`  | 模式 B + meta-invariant           | **R353（VS Code i18n untranslated audit）负面自验证 — i18n meta-invariant 子模式第 2 次应用 + 元方法学层第 11 应用 → 完全工业化深化期**。cycle-51 #B1。合成 5 种 VS Code locale drift 场景（100%/50%/balanced/near-ceiling 7%/_meta 元数据过滤），反向验证 R353 的 `_flatten_strings` helper + 8% ceiling 算法在 VS Code locale 漂移场景能正确 fire。**i18n meta-invariant 子模式从 1 应用（R438）→ 2 应用（R442）进入巩固期**（与 doc-parity / API contract 子模式形成可比的演化节奏）。VS Code extension 是 IDE 集成用户群入口，R353 静默失效 = 漏译可能直接 ship 到 marketplace 伤中文 IDE 用户群。 |                                                                                                                       |
| R444    | `tests/test_feat_methodology_evolution_doc_parity_r444.py`              | 模式 B + meta-invariant           | **v3.11 系列正式启动 + methodology evolution doc structure invariant + doc-parity 子模式第 7 应用 → 完全工业化深化期**。cycle-51 #C1。创建 `docs/methodology-evolution.{md,zh-CN.md}` 作为 v3.0 → v3.11 方法学维度的 *single source of truth*，并锁定其结构（4 layer：bilingual SSoT 存在性 + structural parity heading/table 行 + v3.11 anchor 关键信息 + lineage marker）。**v3.11 系列正式命名** — 元方法学层（从 R414 cycle-47 1st 应用到 R442 cycle-51 11th 应用 历经 5 cycle）正式作为方法学维度命名为 v3.11，与 doc-parity（v3.5）/ perf-baseline（v3.6）等老牌维度同级。**doc-parity 子模式累计应用 7**（R335 → R340 → R346 → R394 → R400 → R408 → R444）→ 完全工业化深化期。任何新贡献者（人 / agent）想了解 invariant 测试方法学时，现有 *单一权威来源* 可快速理解全部维度。 |                                                                                                                       |
| R446    | `tests/test_feat_openapi_error_schema_ratchet_5th_r446.py`              | 模式 B + meta-invariant           | **R422 ratchet uplift 第 5 次 + meta-invariant 第 12 应用 + production-quality threshold 突破 — notification.py reset + bark-test + system.py rotate-token 焦点**。R422 → R428 → R432 → R436 → R440 → **R446（cycle-52 #A1，+6 schemas，coverage → 82.35%，ratchet → 0.80）**。cycle-52 内为 `notification.py` POST /api/reset-feedback-config 500 + POST /api/test-bark-notification 400/500 + `system.py` POST /api/rotate-token 403/500/429（含 retry_after）添加 6 个 schema，把 4xx/5xx schema coverage 推到 82.35%（production-quality threshold），然后 ratchet 至 0.80。**ratchet 模式累计应用 9（R412/R418/R422/R426/R428/R432/R436/R440/R446）→ 完全工业化深化期**，「实施改进 + ratchet up 三位一体」累计 7 应用 → pattern 工业化深化期，元方法学层 12 应用进入完全工业化深化期 + 1。 |                                                                                                                       |
| R448    | `tests/test_feat_i18n_zh_tw_untranslated_negative_validation_r448.py`   | 模式 B + meta-invariant           | **R366（main app zh-TW untranslated audit）负面自验证 — i18n meta-invariant 子模式第 3 次应用 + 元方法学层第 13 应用 → 完全工业化深化期 + 2**。cycle-52 #B1。合成 5 种 zh-TW locale drift 场景（100%/50%/balanced/near-ceiling 7%/_meta 元数据过滤），反向验证 R366 的 `_flatten_strings` helper + 8% ceiling 算法在 zh-TW locale 漂移场景能正确 fire。**i18n meta-invariant 子模式从 2 应用（R442）→ 3 应用（R448）进入工业化阈值**（与 doc-parity 6 应用 / API contract 1 应用形成可比演化节奏）。zh-TW（繁体中文）是台湾/香港 IDE 用户群关键 locale，R366 静默失效 = 漏译可能直接 ship 到 marketplace 伤台港用户。R448 完全复用 R442 模板 + zh-TW 适配，证明 i18n 子模式有 *机械化复用* 能力。 |                                                                                                                       |
| R452    | `tests/test_task_queue_counter_decision_r452.py`                        | 模式 C + 性能决策                 | **TaskQueue 计数器决策 invariant**。锁定当前经测量后的取舍：默认 `max_tasks=10` 时继续使用 `get_task_count()` 快照统计；维护型 counters 只有在更大队列规模的 benchmark 证明 stats 成为瓶颈后才引入，避免把未验证的共享状态复杂度放进热路径。 |                                                                                                                       |
| R457    | `tests/test_mcp_dynamic_tools_spike_r457.py`                            | 模式 A + spike contract           | **FastMCP 动态工具注册 spike**。在未来加入可选/条件式诊断工具前，锁住本地 FastMCP 3.2.4 行为：稳定核心工具 `interactive_feedback` 必须始终静态可发现，动态 `add_tool` 必须保留 metadata 与 annotations，`on_duplicate="error"` 下重复 name/version 必须报错，并且当前 SDK API shape 使用 `on_duplicate` 与 callable/preconstructed tool 输入。 |                                                                                                                       |
| R457    | `tests/test_predefined_options_defaults_ui_r457.py`                     | 模式 A + regression               | **预设选项默认值前端传播回归保护**。覆盖 VS Code webview fallback、首次渲染的本地状态优先级、legacy single-task Web UI 三条用户路径；只有后端显式 `true` 默认值才会预选选项，避免陈旧本地状态或 falsey 值静默覆盖配置默认值。 |                                                                                                                       |
| R673    | `tests/test_strip_images_result_copy_r673.py`                           | 模式 B + regression               | **strip-images 结果拷贝回归保护**。锁定图片剥离后的结果拷贝路径，确保文本 payload 保持预期且不会传播陈旧图片数据。 |
| R674    | `tests/test_task_queue_watchdog_record_copy_r674.py`                    | 模式 B + 并发                     | **TaskQueue watchdog 记录拷贝保护**。确保 watchdog 诊断对任务记录取快照，而不是把可变队列内部状态暴露给监控路径。 |
| R675    | `tests/test_import_config_single_snapshot_r675.py`                      | 模式 C + 配置                     | **导入配置单一快照保护**。锁定配置导入使用同一份一致快照，避免并发变化时校验与应用看到不同数据。 |
| R676    | `tests/test_network_security_update_copy_r676.py`                       | 模式 B + 安全                     | **网络安全更新拷贝保护**。确保网络安全更新在修改前拷贝输入结构，避免调用方持有的状态泄漏进运行时策略。 |
| R677    | `tests/test_config_validate_section_copy_r677.py`                       | 模式 B + 配置                     | **配置 section 校验拷贝保护**。保持 section validation 无副作用：校验拷贝后的数据，而不是修改共享配置字典。 |
| R678    | `tests/test_restore_config_copy_r678.py`                                | 模式 B + 配置                     | **恢复配置拷贝保护**。确保恢复配置在边界处拷贝状态，避免 rollback 路径保留可变别名。 |
| R679    | `tests/test_state_machine_transitions_copy_r679.py`                     | 模式 B + 状态机                   | **状态机 transition 拷贝保护**。锁定 transition 元数据拷贝，避免调用方在注册后继续修改已存储的 transition state。 |
| R680    | `tests/test_notification_routes_get_section_direct_r680.py`             | 模式 C + 路由契约                 | **通知路由 section 直取保护**。确保通知路由保持优化后配置流期望的 direct section access 路径。 |
| R681    | `tests/test_server_print_config_web_ui_copy_r681.py`                    | 模式 B + CLI/Web UI               | **server print-config Web UI 拷贝保护**。确保展示前拷贝 Web UI 配置数据，避免展示 helper 修改 live config。 |
| R682    | `tests/test_notification_cleanup_tuple_snapshots_r682.py`               | 模式 B + cleanup                  | **通知清理 tuple 快照保护**。锁定清理快照为 tuple 型不可变记录，避免并发修改导致 cleanup 迭代失效。 |
| R685    | `tests/test_wait_completion_survives_client_close_r685.py`              | 模式 C + 回归                     | **等待完成 client 关闭存活保护**。锁定 `wait_for_task_completion` 每个请求点即时获取池化 client，配置热更新关闭 httpx client 后等待中的会话不再卡死、用户反馈不丢失。 |
| R687    | `tests/test_multi_task_render_idempotent_skip_r687.py`                  | 模式 C + 前端                     | **多任务渲染幂等短路保护**。锁定描述/选项渲染的 dataset 签名短路：轮询/SSE 刷新内容未变化时不重建 DOM，消除 MathJax/Prism 闪烁与选区丢失。 |
| R688    | `tests/test_vscode_marked_renderer_merge_r688.py`                       | 模式 C + webview                  | **VSCode marked renderer 合并保护**。锁定 webview 用 `marked.use({renderer})` 部分合并；`setOptions({renderer})` 会整体替换 Renderer，在 marked v15 下标题/列表/表格解析必炸。 |
| R689    | `tests/test_wait_completion_deadline_extension_r689.py`                 | 模式 C + 超时                     | **后端截止时间延长感知保护**。锁定后端等待循环在超时前探测 `remaining_time`，用户手动延长 / 输入自动延长不再触发过早 ghost-close。 |
| R689    | `tests/test_typing_hold_and_autosubmit_content_r689.py`                 | 模式 C + 前端                     | **输入保持倒计时与归零提交内容保护**。锁定 web + webview 倒计时在用户输入时自动延长，归零时优先提交已输入文本/选项而不是 resubmit 提示语。 |
| R690    | `tests/test_vscode_countdown_controls_parity_r690.py`                   | 模式 C + webview                  | **VSCode 倒计时控制对齐保护**。锁定 webview 的 +60s/冻结 DOM 与 extend/freeze 端点接线保持存在，同时（R700 起）控制行有意 `display: none`——typing-hold 自动延长取代手动按钮；并锁定归零 tick 输入守卫与任务标签 header_label 优先。 |
| R691    | `tests/test_webview_task_fields_parity_r691.py`                         | 模式 C + API 契约                 | **任务级字段跨端对齐保护**。锁定 `/api/config` 返回 `feedback_placeholder` / `question_type` / `header_label` 且 webview 消费它们（chip、占位覆盖、Yes/No 按钮组），与 web 页面一致。 |
| R692    | `tests/test_submit_focus_and_notify_deeplink_r692.py`                   | 模式 C + UX 流程                  | **提交聚焦与通知直达保护**。锁定提交后自动聚焦的登记/消费流程（web + webview，带时间窗、yesno 感知）及隐藏态通知在面板重新可见时直达对应任务的深链。 |
| R695    | `tests/test_web_countdown_header_visibility_r695.py`                     | 模式 C + CSS/JS                   | **Web 倒计时冻结语义保护**。锁定冻结成功路径整体注销倒计时条目、重建倒计时前必须带显式禁用守卫——确保冻结不会触发自动提交。R700 起 `.header-info-container` 整行有意隐藏（标签页圆环是倒计时唯一展示位），测试同步锁定该下线决策。 |
| R696    | `tests/test_lottie_eager_countdown_icon_r696.py`                          | 模式 C + 模板/CSS                 | **Lottie 直出与倒计时图标主题化保护**。锁定 lottie.min.js 随首屏 `<script defer>` 预加载且排在 app.js 之前（空态动画从第一帧即为 Lottie，无降级动画热切换；降级仅限 reduced-motion / 加载失败），倒计时标签为 `currentColor` 内联 SVG 时钟而非 ⏰ emoji。 |
| R702    | `tests/test_task_timeout_explicit_guard_r702.py`                          | 模式 A + 源码契约                 | **显式 per-task 超时的热更新保护（幽灵提交根因）**。锁定 `Task.auto_resubmit_timeout_explicit`：API 调用方显式传入 timeout 的任务永不被 `frontend_countdown` 配置热更新同步覆盖；回调注册路径只记录基准、不执行同步（注册不等于配置变更）。 |

## 7. 进一步阅读

- [`docs/lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md)
  —— 为什么静默腐烂能绕过普通评审的根因分析。
- [`docs/code-reviews/`](code-reviews/) —— 每份 CR 都记录了驱动下
  一批不变量的 follow-up backlog。
- [`docs/release-recovery.md`](release-recovery.md) —— 13 步发布
  清单；很多不变量就是为了把其中某一步自动化。
