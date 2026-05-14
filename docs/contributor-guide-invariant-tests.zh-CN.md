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

| R-cycle | 测试文件                                                      | 不变量类型 | 锁定内容                                                                       |
| ------- | ------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------ |
| R212    | `tests/test_sse_schema_validate_contract_r212.py`             | 跨模块      | R205 schema 校验开关 ↔ R210 stats snapshot 一致性                              |
| R213    | `tests/test_static_precompress_production_invariant_r213.py`  | 文件系统    | 生产静态资源都有对应的 `.gz` + `.br` 副本                                       |
| R215    | `tests/test_smoke_test_r50_field_drift_invariant_r215.py`     | 跨文件      | `smoke_test_r50.py` `needed` 元组 ↔ `SSEBusStatsSnapshot` TypedDict           |
| R216    | `tests/test_notification_manager_console_noise_invariant_r216.py` | 模式 A | `notification-manager.js` 中 `console.log(` 数量为 0                            |
| R217    | `tests/test_static_js_console_log_demotion_invariant_r217.py` | 模式 A      | 9 个项目自有 JS 文件中 `console.log(` 数量为 0                                 |
| R219    | `tests/test_changelog_inline_code_lint_r219.py`               | 模式 A      | CHANGELOG.md 使用 Markdown 单反引号（非 RST 双反引号）的 inline code 风格      |
| R220    | `tests/test_grafana_dashboard_invariant_r220.py`              | 模式 C      | Grafana 概览仪表盘 ↔ `system.py` `/metrics` 名称平价                          |
| R221    | `tests/test_vscode_webview_console_noise_invariant_r221.py`   | 模式 A      | `packages/vscode/` 项目自有 JS 中 `console.log(` 数量为 0                      |
| R222    | `tests/test_readme_related_projects_invariant_r222.py`        | 模式 D      | 双语 README 的 "Related projects" 表保持同步                                  |
| R223    | `tests/test_settings_shortcuts_full_help_hint_invariant_r223.py` | 模式 D   | 设置面板键盘快捷键提示的 i18n 平价                                            |
| R224    | `tests/test_grafana_dashboard_notif_providers_invariant_r224.py` | 模式 B    | 每个 provider 的通知 dashboard JSON 与 `system.py` 暴露的 metric 对齐         |
| R225    | `tests/test_remote_environment_detector_r225.py`              | 混合 (A+D)  | SSH/WSL 探测器契约 + `web_ui.py` 集成守门                                     |
| R226    | `tests/test_precompress_pre_commit_hook_invariant_r226.py`    | 模式 C      | `.pre-commit-config.yaml` 中预压缩新鲜度 hook 已注册且配置正确                |
| R227    | `tests/test_invariant_test_guide_catalogue_r227.py`           | 模式 C + D  | 本目录引用的测试文件都真实存在 + 双语平价                                     |
| R228    | `tests/test_shortcuts_notification_body_completeness_invariant_r228.py` | 模式 D + 跨文件 | `Ctrl+/` 通知 body 列出每一个快捷键 + 交叉校验 `keyboard-shortcuts.js`     |
| R229    | `tests/test_submit_btn_disabled_visible_invariant_r229.py`             | 模式 A + 模式 C | 深浅两套主题的 `:disabled` CSS 规则存在 + JS 不再给 submit 按钮写 inline 颜色 |
| R230    | `tests/test_decorative_svgs_aria_hidden_invariant_r230.py`             | 模式 A          | `web_ui.html` 每一个 `<svg>` 都有 `aria-hidden="true"` + `focusable="false"` (a11y / WCAG 1.1.1) |
| R232    | `tests/test_icon_only_buttons_aria_label_invariant_r232.py`            | 模式 A          | 每个 icon-only `<button>` / `<a role=button>` 必须有非空 `aria-label` / `aria-labelledby` (a11y / WCAG 4.1.2, R230 后续锁定) |
| R233    | `tests/test_readme_factual_claims_invariant_r233.py`                   | 模式 B + 模式 D | README 量化 claim（测试数、subtest 数、release pipeline job 数）保持在与正典源（`release.yml` / `pytest --collect-only`）的容差范围内 |
| R234    | `tests/test_feedback_textarea_disabled_css_invariant_r234.py`          | 模式 A          | `.feedback-textarea:disabled` 在深/浅两个主题都存在, 都声明 4 个视觉提示 (background/color/cursor/border-color), 浅色用 `!important`; JS 不写 inline 的伴随断言放在 R229 测试文件 |
| R235    | `tests/test_form_inputs_accessible_name_invariant_r235.py`             | 模式 A          | 每个 `<input>`（非 hidden/submit/button/reset/image）+ 每个 `<textarea>` 必须有 accessible name（包裹 `<label>` / `<label for>` / `aria-label` / `aria-labelledby` / `aria-hidden=true + tabindex=-1`）(a11y / WCAG 4.1.2, R230/R232 后续锁定) |
| R236    | `tests/test_ty_precommit_hook_invariant_r236.py`                       | 模式 B + 模式 A | `.pre-commit-config.yaml` 必须保留 `ty-check` hook（默认 `[pre-commit]` 阶段、运行 `ty check`、filter `*.py`），`ci_gate.py` 仍要调用 `ty`（pre-commit 是 fast shadow，CI 是契约）。防止 v1.7.5-style 废弃 release。 |
| R237    | `tests/test_dialog_aria_compliance_invariant_r237.py`                  | 模式 A          | 每个 `role="dialog"` 元素必须有 `aria-modal="true"` + (`aria-labelledby` 指向真实存在的 id 或 `aria-label`) + 默认隐藏 (class `hidden` 或 `[hidden]` 属性)。WAI-ARIA 1.2 + WCAG 4.1.2 锁定。Cycle 14 a11y 第 4 波（R230→R232→R235 是控件，R237 是模态层）。 |
| R238    | `tests/test_modal_focus_trap_invariant_r238.py`                        | 模式 B          | 两个模态对话框（`#code-paste-panel` + `#settings-panel`）实现 Tab / Shift-Tab 焦点陷阱（`app.js` 的 `_modalFocusTrap` + `settings-manager.js` 的 `_settingsFocusTrap`），使用 W3C 标准的可聚焦选择器 + `offsetParent !== null` 可见性过滤；关闭处理把焦点还给打开者（`#feedback-text` / `#settings-btn`）。是 R237 声明性 ARIA 契约的命令式焦点管理伙伴。 |
| R239    | `tests/test_star_counts_freshness_invariant_r239.py`                   | 模式 D          | README "Related projects" 表的 star 数快照日期（"last reviewed YYYY-MM" / "最近核对：YYYY-MM"）必须可解析、不在未来、距今 ≤ 12 个月（可通过环境变量 `R239_STAR_COUNT_MAX_AGE_MONTHS` 覆盖），并且 EN + ZH 两份 README 日期一致。模式 D 漂移检测。 |
| R240    | `tests/test_modal_inert_background_invariant_r240.py`                  | 模式 B          | 两个模态打开函数（`showSettings`、`openCodePasteModal`）必须把 `.container`（`role="main"` 容器）标为 `inert`，对应关闭函数清除；两处都用 `try { el.inert = … } catch { setAttribute("inert", …) }` 防御性写法。与 R237 (ARIA) + R238 (焦点陷阱) 组成 a11y 第 4 波三件套：模态打开时鼠标、键盘、AT 都不能再到达背景。 |
| R241    | `tests/test_inert_helper_dry_invariant_r241.py`                        | 模式 B          | `_safelySetInert(el, value)` DRY 辅助函数在 `app.js`（top-level 函数）和 `settings-manager.js`（class method）都存在并具备相同分支行为；调用点必须用 helper —— helper 定义外不能再有 `container.inert = …` inline 赋值。关闭 CR#28 的 F-cycle15-2（抽取 R240 的 4× 重复 try/catch）。 |
| R242    | `tests/test_minify_precommit_hook_invariant_r242.py`                   | 模式 B          | `check-static-minified-fresh` pre-commit hook 必须存在，entry 真正调用 `scripts/minify_assets.py --check`，files filter 匹配 `static/(css\|js)`，hook 不被流放到 `manual`/`pre-push`，配套脚本依然存在并保留 `--check` 旗标。R242 关闭 R234/R238/R240/R241 暴露出的"修改 .js/.css 后 Flask 仍 serve 旧 .min 文件"沉默 bug —— 与 R226（precompress 新鲜度）同构问题，在第二条构建产物链上补齐。 |
| R243    | `tests/test_get_minified_file_freshness_r243.py`                       | 模式 A（运行时） | `_get_minified_file()` 在请求时拒绝 stale `.min`（mtime < source → fallback 到 source 并 WARN 每文件一次）。端到端行为测试，用真实 tempdir 文件：fresh-min 仍选用、stale-min 被拒、WARN 按文件名独立 dedup（不同文件互不影响）、显式请求 `.min` 仍直通、缺失 `.min` 仍 fallback、`stat()` 抛 `OSError` 时 static 端点不崩。R243 是 R242 commit-time 防御的运行时配套层，覆盖 `--no-verify` 与 hook 未触及的 pre-existing stale 文件。 |
| R244    | `tests/test_modal_not_self_inert_invariant_r244.py`                    | 模式 B          | 修复 R240 cascade self-inert bug：两个 modal 都在 `.container` 内，旧版 `container.inert = true` 让 modal 自己也变 inert（沉默地破坏点击/焦点）。新 helper `_setContainerSiblingsInert(openModalEl, value)` 在 `app.js`（top-level fn）和 `settings-manager.js`（class method）都存在；它遍历 `container.children` 并跳过 `openModalEl`。四个 modal 开/关路径（`openCodePasteModal`/`closeCodePasteModal`/`showSettings`/`hideSettings`）必须调用新 helper 并传 panel 元素；回归守卫禁止任何 modal 路径出现 `container.inert = …` / `_safelySetInert(document.querySelector(".container"), …)`。关闭 R240 引入但被静默隐藏 4 个 cycle 的 UX 杀手 —— R240 当时只有 Pattern B 测试因此漏检。 |

## 7. 进一步阅读

- [`docs/lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md)
  —— 为什么静默腐烂能绕过普通评审的根因分析。
- [`docs/code-reviews/`](code-reviews/) —— 每份 CR 都记录了驱动下
  一批不变量的 follow-up backlog。
- [`docs/release-recovery.md`](release-recovery.md) —— 13 步发布
  清单；很多不变量就是为了把其中某一步自动化。
