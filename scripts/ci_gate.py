#!/usr/bin/env python3
"""
本地/CI Gate 一键检查脚本（Python 侧）。

设计目标：
- 把“门禁命令”收敛到单一入口，减少 docs / CI / 脚本之间的漂移
- 默认适合本地开发：会自动格式化（ruff format）
- 可通过参数切换为 CI 模式：只做检查（不自动格式化源码），但可能生成 gitignore 的构建产物（如 .min；若启用 --with-vscode 还会产生 .vsix）
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _run(cmd: list[str], *, label: str | None = None) -> None:
    """跑命令；非 0 退出码 fail-fast 抛出 ``CalledProcessError``。

    可选 ``label``：在 ``subprocess.run(check=True)`` 抛错前先打印
    ``[ci_gate] FAIL: <label>...`` 到 stderr，方便快速定位是哪一道
    门禁失败（避免 traceback 里只看到 ``Command '[...]' returned
    non-zero exit status N`` 这种通用消息）。``_run_warn`` 已经在
    warn 级用了同名参数；这里复用以保持上下层调用接口一致。
    """
    completed = subprocess.run(cmd, cwd=_repo_root(), check=False)
    if completed.returncode != 0:
        if label:
            print(
                f"[ci_gate] FAIL: {label} 检测到漂移 / 失败"
                f"（exit_code={completed.returncode}）。"
                "门禁已 fail-closed；请按上方提示修复后再次提交。",
                file=sys.stderr,
            )
        # 与之前 ``check=True`` 的语义对齐：抛 ``CalledProcessError`` 由
        # 上层 ``_main_impl`` 捕获并以非 0 退出，保留与既有调用方的兼容
        raise subprocess.CalledProcessError(completed.returncode, cmd)


def _run_warn(cmd: list[str], *, label: str) -> None:
    """跑命令；非 0 退出码不阻断，只打印 [ci_gate] WARN 提示到 stderr。

    用于"漂移检测但不阻塞主名项"的 warn 级门禁——在维护者尚未把
    drift 修复纳入提交流程时，给一条人类可读的提醒，而不是直接 fail
    一个绿色 CI。当本地约定开始严格执行后，把对应调用从 `_run_warn`
    切到 `_run` 即可升级为硬门禁。
    """
    completed = subprocess.run(cmd, cwd=_repo_root(), check=False)
    if completed.returncode != 0:
        print(
            f"[ci_gate] WARN: {label} 检测到漂移（exit_code={completed.returncode}），"
            "不阻断本次主流程。请按上方提示同步源码 / 文档后再次提交。",
            file=sys.stderr,
        )


def _resolve_node_redteam_cmd(node_version: str) -> list[str]:
    """根据 ``node`` / ``fnm`` 是否可用，返回 i18n red-team 应当执行的命令。

    返回空列表表示"两者都不可用"——上层 caller 必须按 ``AIIA_SKIP_NODE_REDTEAM``
    环境变量决定 fail-closed 还是 graceful skip（见 ``_main_impl``）。

    单独抽出函数是为了让 ``tests/test_ci_gate_node_redteam.py`` 直接调用真实
    决策代码，而不是复刻一份测试用的二份逻辑（容易漂移）。
    """
    if _has_cmd("node"):
        return ["node", "scripts/red_team_i18n_runtime.mjs", "--quiet"]
    if _has_cmd("fnm"):
        return [
            "fnm",
            "exec",
            "--using",
            node_version,
            "--",
            "node",
            "scripts/red_team_i18n_runtime.mjs",
            "--quiet",
        ]
    return []


def _cleanup_vscode_vsix() -> int:
    """清理 VSCode 插件打包产物（避免 .vsix 污染 CI/工作区）"""
    vs_dir = _repo_root() / "packages" / "vscode"
    if not vs_dir.exists():
        return 0
    removed = 0
    for p in vs_dir.glob("*.vsix"):
        try:
            p.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    return removed


def _main_impl(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Python CI Gate：uv/ruff/ty/pytest/minify 一键执行",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI 模式：使用 --frozen，并且 ruff format 只做 --check（不改动文件）",
    )
    parser.add_argument(
        "--with-coverage",
        action="store_true",
        help="pytest 生成覆盖率（--cov=. --cov-report=xml --cov-report=term-missing）",
    )
    parser.add_argument(
        "--with-vscode",
        action="store_true",
        help="额外运行 VSCode 插件门禁：npm run vscode:check（需要 npm；或在 fnm 环境下自动尝试 fnm exec）",
    )
    parser.add_argument(
        "--node-version",
        default="v24.14.0",
        help="当 npm 不可用但 fnm 可用时，使用该 Node 版本执行（默认 v24.14.0，与 CI 对齐）",
    )
    args = parser.parse_args(argv)

    # 依赖同步
    sync_cmd = ["uv", "sync", "--all-groups"]
    if args.ci:
        sync_cmd.append("--frozen")
    _run(sync_cmd)

    # ruff：本地默认 format（修复），CI 默认 check-only
    if args.ci:
        _run(["uv", "run", "ruff", "format", "--check", "."])
    else:
        _run(["uv", "run", "ruff", "format", "."])

    _run(["uv", "run", "ruff", "check", "."])
    _run(["uv", "run", "ty", "check", "."])

    # i18n 静态门禁（Web UI + VSCode webview + VSCode extension host）：
    #   1. locale JSON key/type/占位符跨 locale 一致
    #   2. HTML 模板零硬编码 CJK
    #   3. JS 源文件零硬编码 CJK 字符串字面量（--scope all 覆盖 static/js 和
    #      packages/vscode，P8 之后两侧都必须干净）
    #   4. TS 源文件零硬编码 CJK 字符串字面量（packages/vscode/*.ts；
    #      L2·G6 之后 extension host 全部走 vscode.l10n.t）
    #   5. locale 重复值检测（warn 级；I18n 维护性信号，不阻断 CI）
    #   6. pseudo locale 与 en.json 同步（P9·L2·G4：QA 可切到 pseudo 看
    #      硬编码泄漏 / 布局溢出 / Unicode 断裂）
    _run(["uv", "run", "python", "scripts/check_i18n_locale_parity.py"])
    # check_locales.py 与 check_i18n_locale_parity.py 互补，独占两块覆盖：
    #   - VS Code manifest 翻译：``package.nls.json`` / ``package.nls.zh-CN.json``
    #     （parity 脚本只看 ``locales/*.json``，不看 manifest 翻译；遗漏会让
    #     扩展上架时某种语言下 commands/views 标题缺失）
    #   - 跨端 ``aiia.*`` namespace 一致：Web UI ↔ VSCode 两侧的 ``aiia.*``
    #     keys 必须一字不差（为未来抽取共享 locale 模块铺路）
    # 缺这一道时，单端补 ``aiia.*`` key、忘了同步另一端，CI 会沉默放过，
    # 直到运行时 i18n 回退到原始 key 才暴露。
    _run(["uv", "run", "python", "scripts/check_locales.py"])
    _run(["uv", "run", "python", "scripts/check_i18n_html_coverage.py"])
    _run(["uv", "run", "python", "scripts/check_i18n_js_no_cjk.py", "--scope", "all"])
    _run(["uv", "run", "python", "scripts/check_i18n_ts_no_cjk.py"])
    _run(["uv", "run", "python", "scripts/check_i18n_duplicate_values.py"])
    _run(["uv", "run", "python", "scripts/gen_pseudo_locale.py", "--check"])
    # Warn-level：orphan key 扫描 — 默认不 block 流水线（见脚本 docstring）。
    _run(["uv", "run", "python", "scripts/check_i18n_orphan_keys.py"])
    # P9·L8：i18n-keys.d.ts 与 packages/vscode/locales/en.json 同步
    #   （TypeScript `hostT(key: I18nKey)` 依赖该 .d.ts 捕获拼写错误）。
    _run(["uv", "run", "python", "scripts/gen_i18n_types.py", "--check"])
    # P9·L9·G1：t(key, { params }) 与 locale 值占位符签名一致。strict
    #   模式直接阻断 —— pytest 侧已经对 scan() 做硬断言，这里再打一道
    #   人类可读报告方便 PR 作者本地预览。
    _run(["uv", "run", "python", "scripts/check_i18n_param_signatures.py", "--strict"])
    # P10·B3·H13：locale JSON 形状校验（tree-of-objects + string leaves）。
    #   比 Batch-2 H11 的 runtime warn-once 更早，lint 时就挡回 PR。
    _run(["uv", "run", "python", "scripts/check_i18n_locale_shape.py"])

    # docs/api(.zh-CN)/* 漂移检测 — fail-closed 硬门禁（自 v1.5.23 起）。
    # `generate_docs.py --check` 已经支持双语言、幂等、报告漂移文件路径。
    # 一旦改动 Python 源码的 docstring / 签名而忘了重生 docs，CI 会
    # 直接 fail，且错误消息里给出可立即复制的修复命令。修复方法：
    #   `uv run python scripts/generate_docs.py --lang en`
    #   `uv run python scripts/generate_docs.py --lang zh-CN`
    # 升级历史：v1.5.x 早期是 ``_run_warn`` warn 级（不阻断）；事实证明
    # warn 容易被忽视——v1.5.23 圈子审计发现 docs/api/task_queue.md
    # 与中文镜像的 ``add_task`` 签名 drift 了一个 round（DRY refactor 之后
    # 只 regen 了中文，英文被悄悄落下，warn-level CI 跑了几十次也没人
    # 改）。升级为 ``_run``（fail-closed）后，这种 silent drift 不可能
    # 再合入 main。
    _run(
        ["uv", "run", "python", "scripts/generate_docs.py", "--lang", "en", "--check"],
        label="docs/api/ (English)",
    )
    _run(
        [
            "uv",
            "run",
            "python",
            "scripts/generate_docs.py",
            "--lang",
            "zh-CN",
            "--check",
        ],
        label="docs/api.zh-CN/ (Chinese)",
    )

    # 版本一致性 fail-closed 门禁：``bump_version.py --check`` 验证
    # ``pyproject.toml``、``uv.lock``、根/插件 ``package.json`` /
    # ``package-lock.json``、``.github/ISSUE_TEMPLATE/bug_report.yml``、
    # ``CITATION.cff`` 全部对齐。历史上 ``test.yml`` 独占这一步，本地
    # ``make ci`` / ``make pre-commit`` 跑不到，只有 push 之后 CI 才报
    # 红——一次往返浪费 5–10 分钟。挪进 ci_gate 后本地预检和远端 CI 的
    # 信号面完全一致（local-CI parity），``test.yml`` 那一步保留作为
    # 防御性兜底，不构成重复执行成本（同一进程，跑两次还是 < 0.1s）。
    _run(["uv", "run", "python", "scripts/bump_version.py", "--check"])

    # 先生成 .min / 预压缩副本，再跑 pytest。
    # pytest 会校验预压缩 .gz/.br 解压后与原文 byte-identical；如果只更新
    # .min 而不重生预压缩副本，CI 会在 static compression 集成测试中选到
    # stale .gz 并失败。
    _run(["uv", "run", "python", "scripts/minify_assets.py"])
    _run(["uv", "run", "python", "scripts/precompress_static.py"])

    # 测试集中包含大量“故意喂坏配置”的用例；这些用例会产生日志级
    # WARNING/ERROR，但断言本身期望通过。门禁输出保持干净，只让真实失败
    # 通过 pytest 退出码和失败摘要体现。
    pytest_cmd = ["uv", "run", "pytest", "-q", "-o", "log_cli=false"]
    if args.with_coverage:
        pytest_cmd += ["--cov=.", "--cov-report=xml", "--cov-report=term-missing"]
    _run(pytest_cmd)

    # P10·B1.5·H7：两份 i18n.js 的跨特性 red-team smoke。pytest 已覆盖
    # 单特性断言，这里补一遍完整集成面（ICU/apostrophe/嵌套 # / LRU /
    # miss-key / prototype-pollution / byte-parity），catch 两半漂移。
    # Node 运行环境沿用 --with-vscode 的解析规则。
    node_cmd = _resolve_node_redteam_cmd(str(args.node_version))
    if node_cmd:
        _run(node_cmd)
    elif os.environ.get("AIIA_SKIP_NODE_REDTEAM") == "1":
        # 显式 opt-out 路径：本地开发者没装 Node 时仍想跑 ci_gate，可以
        # 设环境变量绕过。CI 不会设置此变量（GitHub Actions 镜像自带
        # Node），所以 CI 上的覆盖率不会被弱化。
        print(
            "[ci_gate] skip: AIIA_SKIP_NODE_REDTEAM=1; "
            "red_team_i18n_runtime.mjs smoke check intentionally bypassed. "
            "Re-run without this flag once Node/fnm is installed.",
            file=sys.stderr,
        )
    else:
        # fail-closed：与 round-6 docs/api drift 升级同 spirit。silent skip
        # 一个 smoke check 让 CI 看起来绿但实际没跑过，比直接 fail 更糟糕。
        # 历史教训：v1.5.x 早期 docs-check 用 warn 级，warn 输出谁都不看，
        # 跑了几十次才发现 task_queue.md 漂移了一整轮。i18n red-team 的失败
        # 模式更严重（ICU 解析、apostrophe 转义、LRU 等多个 batch 的回归
        # smoke），所以这里直接 fail-closed；本地开发者真没 Node 时
        # ``AIIA_SKIP_NODE_REDTEAM=1 make ci`` 显式 opt-out。
        raise RuntimeError(
            "未找到 node 或 fnm；i18n red-team smoke (scripts/red_team_i18n_runtime.mjs) "
            "无法运行。请安装 Node.js（推荐 v24.14.0，与 CI 对齐）或使用 fnm 管理 Node 版本。"
            "如果你确认本地 Node 缺失但仍要跑 ci_gate，可以设置环境变量 "
            "AIIA_SKIP_NODE_REDTEAM=1 显式 opt-out（CI 不会读这个变量，CI 覆盖率不会被弱化）。"
        )

    if args.with_vscode:
        # 运行前先清理一次，避免误用上次残留产物
        _cleanup_vscode_vsix()

        # 优先使用系统 npm；若不可用且存在 fnm，则尝试 fnm exec
        cmd: list[str]
        if _has_cmd("npm"):
            cmd = ["npm", "run", "vscode:check"]
        elif _has_cmd("fnm"):
            cmd = [
                "fnm",
                "exec",
                "--using",
                str(args.node_version),
                "--",
                "npm",
                "run",
                "vscode:check",
            ]
        else:
            raise RuntimeError(
                "未找到 npm（也未找到 fnm）。请先安装 Node.js/npm，或使用 fnm 管理 Node。"
            )

        # Linux/headless 下若无 DISPLAY，尽量自动使用 xvfb-run
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            if _has_cmd("xvfb-run"):
                cmd = ["xvfb-run", "-a", *cmd]
            else:
                raise RuntimeError(
                    "检测到无 DISPLAY 的 headless 环境，但未安装 xvfb-run。请先安装 xvfb，或手动使用 xvfb-run 执行 vscode:check。"
                )

        try:
            _run(cmd)
        finally:
            # 无论成功失败都尽量清理，避免污染后续步骤/缓存
            _cleanup_vscode_vsix()

    return 0


def main(argv: list[str]) -> int:
    """入口包装：将常见失败转换为清晰的退出码（避免大段 traceback 噪声）。"""
    try:
        return _main_impl(argv)
    except subprocess.CalledProcessError as e:
        print(
            f"命令执行失败：{e.cmd}（exit_code={e.returncode}）",
            file=sys.stderr,
        )
        return int(e.returncode or 1)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
