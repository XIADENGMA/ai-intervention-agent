# Implementation Plan: GitHub Actions CI/CD 流水线

**Branch**: `001-github-actions-cicd` | **Date**: 2025-12-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-github-actions-cicd/spec.md`

## Summary

为 AI Intervention Agent 项目实现完整的 GitHub Actions CI/CD 流水线，包括：

1. 自动化测试（Push/PR 触发，Python 3.11/3.12 矩阵，pytest + coverage + ruff）
2. 自动发布到 PyPI（Tag 触发，Trusted Publisher，GitHub Release 创建）
3. 依赖自动更新（Dependabot 配置，每周检查）

## Technical Context

**Language/Version**: Python 3.11, 3.12
**Primary Dependencies**: pytest, pytest-cov, ruff, hatchling (build)
**Storage**: N/A
**Testing**: pytest + pytest-cov
**Target Platform**: GitHub Actions (ubuntu-latest)
**Project Type**: Single Python package
**Performance Goals**: 测试工作流 ≤10 分钟，发布工作流 ≤5 分钟
**Constraints**: 使用 Trusted Publisher，不存储 PyPI Token
**Scale/Scope**: 单仓库 CI/CD

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

| 原则                | 合规状态 | 说明                                |
| ------------------- | -------- | ----------------------------------- |
| I. 代码质量         | ✅       | YAML 配置使用中文注释，结构清晰     |
| II. 测试标准        | ✅       | 实现 pytest + coverage，覆盖率 ≥80% |
| III. 用户体验一致性 | ✅       | 工作流状态在 GitHub UI 清晰显示     |
| IV. 性能要求        | ✅       | 设置超时限制，缓存依赖加速          |
| V. 交互优先         | ✅       | 通过 MCP 工具确认配置细节           |

## Project Structure

### Documentation (this feature)

```text
specs/001-github-actions-cicd/
├── spec.md              # 功能规格说明
├── plan.md              # 本文件 - 实现计划
└── tasks.md             # 任务清单（待创建）
```

### Source Code (repository root)

```text
.github/
├── workflows/
│   ├── test.yml              # 测试工作流 (P1)
│   └── release.yml           # 发布工作流 (P2)
├── dependabot.yml            # 依赖更新配置 (P3)
└── assets/                   # 现有截图资源
    ├── desktop_screenshot.png
    └── mobile_screenshot.png
```

**Structure Decision**: GitHub Actions 标准目录结构，工作流文件按功能分离

## Implementation Phases

### Phase 1: 测试工作流 (P1) 🎯 MVP

**目标**: 实现完整的自动化测试流程

**工作流配置**: `.github/workflows/test.yml`

```yaml
# 触发条件
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

# 任务
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11', '3.12']
    steps:
      - 检出代码
      - 设置 Python 环境
      - 安装 uv
      - 安装依赖 (使用缓存)
      - 运行 ruff 检查
      - 运行 pytest 测试
      - 上传覆盖率报告
```

**关键特性**:

- Python 版本矩阵测试 (3.11, 3.12)
- 依赖缓存加速构建
- 覆盖率报告上传到 Codecov（可选）

### Phase 2: 发布工作流 (P2)

**目标**: 实现自动化发布到 PyPI

**工作流配置**: `.github/workflows/release.yml`

```yaml
# 触发条件
on:
  push:
    tags:
      - 'v*.*.*'

# 任务
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - 检出代码
      - 设置 Python 环境
      - 安装构建工具
      - 构建 wheel 和 sdist
      - 上传构建产物

  publish:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      id-token: write # Trusted Publisher
    steps:
      - 下载构建产物
      - 发布到 PyPI (Trusted Publisher)

  release:
    needs: publish
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - 创建 GitHub Release
      - 上传构建产物到 Release
```

**关键特性**:

- Trusted Publisher 安全发布（无需存储 Token）
- 构建与发布分离（失败可重试）
- 自动创建 GitHub Release

### Phase 3: 依赖自动更新 (P3)

**目标**: 配置 Dependabot 自动管理依赖

**配置文件**: `.github/dependabot.yml`

```yaml
version: 2
updates:
  # Python 依赖
  - package-ecosystem: 'pip'
    directory: '/'
    schedule:
      interval: 'weekly'
    reviewers:
      - 'xiadengma'
    labels:
      - 'dependencies'
      - 'python'

  # GitHub Actions 版本
  - package-ecosystem: 'github-actions'
    directory: '/'
    schedule:
      interval: 'weekly'
    labels:
      - 'dependencies'
      - 'github-actions'
```

**关键特性**:

- Python 依赖每周检查
- GitHub Actions 版本每周检查
- 自动添加标签和 Reviewer

## Pre-requisites

在实现前需要完成：

1. **PyPI Trusted Publisher 配置**

   - 在 PyPI 项目设置中添加 Trusted Publisher
   - 配置：仓库 `xiadengma/ai-intervention-agent`，工作流 `release.yml`

2. **GitHub Repository 设置**
   - 启用 Actions（已默认启用）
   - 配置分支保护规则（可选）

## Complexity Tracking

| 潜在复杂性                 | 是否需要 | 简单替代方案               |
| -------------------------- | -------- | -------------------------- |
| 多平台测试 (Windows/macOS) | ❌       | 仅 Linux 满足需求          |
| 发布前自动版本号           | ❌       | 手动在 pyproject.toml 更新 |
| 私有 PyPI 源               | ❌       | 仅发布到公共 PyPI          |

## Estimated Timeline

| Phase    | 任务            | 预计时间      |
| -------- | --------------- | ------------- |
| Phase 1  | 测试工作流      | 30 分钟       |
| Phase 2  | 发布工作流      | 30 分钟       |
| Phase 3  | Dependabot 配置 | 10 分钟       |
| 验证     | 端到端测试      | 30 分钟       |
| **总计** |                 | **~1.5 小时** |
