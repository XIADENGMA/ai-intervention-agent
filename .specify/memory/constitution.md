<!--
Sync Impact Report
==================
Version: N/A → 1.0.0 (Initial creation)

Modified Principles: N/A (Initial creation)

Added Sections:
- Core Principles (5): Code Quality, Testing Standards, UX Consistency, Performance Requirements, Interactive-First
- Development Workflow Constraints
- Technical Decision Governance
- Full Governance Rules

Templates Status:
- .specify/templates/plan-template.md: ⚠️ Pending - Constitution Check section needs alignment
- .specify/templates/spec-template.md: ✅ Compatible
- .specify/templates/tasks-template.md: ✅ Compatible

Follow-up TODOs: None
-->

# AI Intervention Agent Constitution

## Core Principles

### I. 代码质量 (Code Quality)

让用户实时控制 AI 执行过程的 MCP 工具必须遵循最高的代码质量标准：

- **简洁性**: 代码必须简洁明了，避免过度抽象和不必要的复杂性。每个函数/方法应专注于单一职责。
- **可读性**: 使用中文注释说明复杂逻辑，采用清晰的命名规范（Python snake_case）。代码应自文档化。
- **可维护性**: 模块化设计，单一职责原则，低耦合高内聚。避免循环依赖。
- **类型安全**: 必须使用 Python 类型提示（Type Hints），所有公共接口必须有完整的类型定义。
- **文档规范**: 公共 API 必须有 docstring，重要业务逻辑必须有注释说明。中文优先。

**验证方式**: 代码审查、静态分析工具（mypy/ruff）

### II. 测试标准 (Testing Standards)

确保软件质量的测试规范：

- **覆盖率要求**: 核心模块（server.py, web_ui.py, config_manager.py）测试覆盖率 ≥80%
- **测试类型**:
  - 单元测试：函数级别的独立测试
  - 集成测试：MCP 协议交互、Web UI 流程、配置加载
  - E2E 测试：完整用户反馈流程
- **回归测试**: 每个 Bug 修复必须附带测试用例，防止问题复发
- **测试优先**: 重要功能采用 TDD（测试驱动开发），先写测试后实现
- **CI 集成**: 所有 PR 必须通过自动化测试才能合并

**验证方式**: pytest 测试套件、GitHub Actions CI

### III. 用户体验一致性 (UX Consistency)

为用户提供一致、流畅的交互体验：

- **响应式设计**: Web UI 必须适配桌面浏览器和移动设备
- **交互反馈**: 每个用户操作必须有明确的视觉反馈（状态变化）和/或声音反馈（通知音）
- **错误处理**: 用户友好的错误消息，使用简洁中文描述，避免暴露技术细节和堆栈信息
- **加载状态**: 长时间操作必须显示进度指示（倒计时圆环、加载动画）
- **一致性**: UI 组件、颜色方案、字体、间距保持统一的视觉风格

**验证方式**: 手动 UI 测试、响应式布局检查

### IV. 性能要求 (Performance Requirements)

确保系统高效运行的性能标准：

- **响应时间**:
  - Web API 响应时间 ≤200ms（p95）
  - 页面首次加载时间 ≤3s
- **资源效率**:
  - 内存占用 ≤200MB（稳态运行）
  - CPU 空闲时占用 ≤5%
- **并发支持**: 支持多任务并发处理，无资源竞争和死锁
- **超时处理**: 所有网络请求必须设置合理超时（默认 5s），避免无限等待
- **优雅降级**: 服务不可用时提供明确的降级策略和错误提示

**验证方式**: 性能测试、资源监控

### V. 交互优先 (Interactive-First)

AI 与用户交互的核心原则：

- **MCP 工具交互**: AI 必须通过 `interactive_feedback` MCP 工具与用户进行所有沟通，禁止直接询问
- **用户确认**: 关键决策、多方案选择、任务完成必须通过工具获得用户明确确认
- **预定义选项**: 提供选项列表方便用户快速选择，减少输入成本
- **会话活跃**: 通过自动重调机制（可配置倒计时）保持会话连续性
- **禁止擅自结束**: 未经用户通过 MCP 工具明确同意，禁止主动结束任务或对话

**验证方式**: 交互流程审查、MCP 调用日志

## Development Workflow Constraints

开发工作流的约束和规范：

- **配置管理**: 使用 JSONC 格式支持注释，配置文件必须有完整的字段说明
- **依赖管理**: 使用 uv 管理 Python 依赖，依赖版本锁定在 pyproject.toml
- **日志规范**: 结构化日志输出，关键操作（启动、请求、错误）必须有日志记录
- **版本控制**: 遵循 Git Flow，功能分支命名 `feature/xxx`，修复分支 `fix/xxx`

## Technical Decision Governance

技术决策的治理流程：

- **架构变更**: 涉及核心架构的变更必须在宪法框架内评估对各原则的影响
- **新增依赖**: 引入新依赖前必须评估：必要性、维护活跃度、安全性、许可证兼容性
- **API 变更**: 公共 API 变更必须遵循语义化版本规范，评估向后兼容性影响
- **性能权衡**: 性能优化与代码可读性产生冲突时，优先保证可读性，除非有明确的性能瓶颈证据

## Governance

宪法的治理和修订规则：

- **最高优先级**: 本宪法中的原则是项目开发的最高准则，所有技术决策必须符合这些原则
- **修订流程**: 修订宪法必须：
  1. 通过 `interactive_feedback` 工具与用户讨论变更内容
  2. 说明修订原因和影响范围
  3. 更新版本号（遵循语义化版本）
  4. 同步更新所有受影响的模板和文档
- **合规检查**: 所有代码审查必须验证是否符合宪法原则
- **复杂性论证**: 引入复杂性必须提供充分的理由说明为何简单方案不可行
- **运行时指导**: 具体的开发指导请参考 `CLAUDE.md`

**Version**: 1.0.0 | **Ratified**: 2025-12-09 | **Last Amended**: 2025-12-09
