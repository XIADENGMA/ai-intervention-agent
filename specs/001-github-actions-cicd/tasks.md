# Tasks: GitHub Actions CI/CD 流水线

**Input**: Design documents from `/specs/001-github-actions-cicd/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 创建 GitHub Actions 目录结构

- [ ] T001 创建 `.github/workflows/` 目录结构

**Checkpoint**: 目录结构就绪

---

## Phase 2: User Story 1 - 自动化测试 (Priority: P1) 🎯 MVP

**Goal**: 实现完整的自动化测试工作流，在 Push/PR 时自动运行测试和代码检查

**Independent Test**: 创建测试 PR，验证工作流自动执行并报告结果

### Implementation for User Story 1

- [ ] T002 [US1] 创建完整的测试工作流文件 `.github/workflows/test.yml`
  - 配置触发条件 (push to main/develop, pull_request to main)
  - 设置 Python 版本矩阵 (3.11, 3.12)
  - 配置 ubuntu-latest 运行环境
  - 使用 uv 安装依赖（含缓存配置）
  - 运行 ruff check 和 ruff format --check
  - 运行 pytest 并生成覆盖率报告
  - 上传覆盖率报告 artifact

**Checkpoint**: 测试工作流可独立运行，PR 创建后自动执行测试

---

## Phase 3: User Story 2 - 自动发布到 PyPI (Priority: P2)

**Goal**: 实现 Tag 触发的自动发布流程，使用 Trusted Publisher 安全发布

**Independent Test**: 推送测试 tag (v0.0.0-test)，验证构建流程（跳过实际发布）

### Implementation for User Story 2

- [ ] T003 [P] [US2] 创建完整的发布工作流文件 `.github/workflows/release.yml`
  - 配置 tag 触发条件 (v*.*.\*)
  - 设置 permissions (id-token: write, contents: write)
  - 实现 build job：构建 wheel 和 sdist，上传 artifact
  - 实现 publish job：使用 PyPI Trusted Publisher 发布
  - 实现 release job：创建 GitHub Release 并上传产物

**Checkpoint**: Tag 推送后自动构建并发布到 PyPI

---

## Phase 4: User Story 3 - 依赖自动更新 (Priority: P3)

**Goal**: 配置 Dependabot 自动检测依赖更新并创建 PR

**Independent Test**: 检查 Dependabot 页面是否显示配置生效

### Implementation for User Story 3

- [ ] T004 [P] [US3] 创建 Dependabot 配置文件 `.github/dependabot.yml`
  - 配置 Python (pip) 依赖检查（每周）
  - 配置 GitHub Actions 版本检查（每周）
  - 设置 labels 和 reviewers

**Checkpoint**: Dependabot 配置完成，可检测依赖更新

---

## Phase 5: Validation & Polish

**Purpose**: 验证和完善 CI/CD 流程

- [ ] T005 验证工作流 YAML 语法
  - 使用 GitHub Actions 在线验证器或本地 yamllint
  - 确认所有工作流语法正确
- [ ] T006 验证测试工作流
  - 创建测试 PR 触发工作流
  - 确认测试和代码检查正常运行
  - 确认覆盖率报告生成
- [ ] T007 验证发布工作流准备（可选 - 需先配置 PyPI）
  - 在 PyPI 配置 Trusted Publisher
  - 文档说明配置步骤
- [ ] T008 更新项目文档
  - 在 README.md 添加 CI 徽章
  - 记录 CI/CD 流程说明

**Checkpoint**: 完整 CI/CD 流程验证通过

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
    │
    ├─→ Phase 2 (US1: 测试工作流)
    │
    ├─→ Phase 3 (US2: 发布工作流) [P] 与 Phase 2 并行
    │
    └─→ Phase 4 (US3: Dependabot) [P] 与 Phase 2/3 并行
         │
         └─→ Phase 5 (Validation) - 依赖所有 User Stories
```

### Parallel Opportunities

| 任务组         | 任务             | 可并行                      |
| -------------- | ---------------- | --------------------------- |
| Phase 1 完成后 | T002, T003, T004 | ✅ 三个工作流文件互不依赖   |
| Phase 5        | T005, T008       | ✅ 语法验证与文档更新可并行 |

---

## Task Summary

| ID   | 任务         | 文件                 | 优先级     |
| ---- | ------------ | -------------------- | ---------- |
| T001 | 创建目录结构 | `.github/workflows/` | Setup      |
| T002 | 测试工作流   | `test.yml`           | P1 MVP     |
| T003 | 发布工作流   | `release.yml`        | P2         |
| T004 | Dependabot   | `dependabot.yml`     | P3         |
| T005 | YAML 验证    | -                    | Validation |
| T006 | 测试验证     | -                    | Validation |
| T007 | 发布验证     | -                    | Validation |
| T008 | 文档更新     | `README.md`          | Polish     |

**总计**: 8 个任务（优化前 14 个）

---

## Notes

- [P] 标记的任务 = 不同文件，无依赖关系，可并行执行
- 每个 User Story 可独立完成和测试
- 发布工作流需要先在 PyPI 配置 Trusted Publisher 才能实际发布
- 建议按 MVP 策略：先完成 T002 测试工作流，验证后再实现其他功能
- 使用 ruff 替代 flake8/black/isort 组合，简化工具链
