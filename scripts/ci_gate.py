#!/usr/bin/env python3
"""
本地/CI Gate 一键检查脚本（Python 侧）。

设计目标：
- 把“门禁命令”收敛到单一入口，减少 docs / CI / 脚本之间的漂移
- 默认适合本地开发：会自动格式化（ruff format）
- 可通过参数切换为 CI 模式：只做检查（不自动格式化源码，不重写静态构建产物；若启用 --with-vscode 仍可能产生 .vsix）
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


def _run(
    cmd: list[str],
    *,
    label: str | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """跑命令；非 0 退出码 fail-fast 抛出 ``CalledProcessError``。"""
    completed = subprocess.run(cmd, cwd=_repo_root(), check=False, env=env)
    if completed.returncode != 0:
        if label:
            print(
                f"[ci_gate] FAIL: {label} 检测到漂移 / 失败"
                f"（exit_code={completed.returncode}）。"
                "门禁已 fail-closed；请按上方提示修复后再次提交。",
                file=sys.stderr,
            )

        raise subprocess.CalledProcessError(completed.returncode, cmd)


def _run_warn(cmd: list[str], *, label: str) -> None:
    """跑命令；非 0 退出码不阻断，只打印 [ci_gate] WARN 提示到 stderr。"""
    completed = subprocess.run(cmd, cwd=_repo_root(), check=False)
    if completed.returncode != 0:
        print(
            f"[ci_gate] WARN: {label} 检测到漂移（exit_code={completed.returncode}），"
            "不阻断本次主流程。请按上方提示同步源码 / 文档后再次提交。",
            file=sys.stderr,
        )


def _resolve_node_redteam_cmd(node_version: str) -> list[str]:
    """根据 ``node`` / ``fnm`` 是否可用，返回 i18n red-team 应当执行的命令。"""
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
        "--skip-version-check",
        action="store_true",
        help=(
            "跳过内置 bump_version.py --check。仅供 workflow 已在同一 job 前置"
            "执行过该检查时使用，避免重复 gate；本地默认不要跳过。"
        ),
    )
    parser.add_argument(
        "--node-version",
        default="v24.14.0",
        help="当 npm 不可用但 fnm 可用时，使用该 Node 版本执行（默认 v24.14.0，与 CI 对齐）",
    )
    args = parser.parse_args(argv)

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

    _run(["uv", "run", "python", "scripts/check_i18n_locale_parity.py"])

    #   - 跨端 ``aiia.*`` namespace 一致：Web UI ↔ VSCode 两侧的 ``aiia.*``

    # 缺这一道时，单端补 ``aiia.*`` key、忘了同步另一端，CI 会沉默放过，

    _run(["uv", "run", "python", "scripts/check_locales.py"])
    _run(["uv", "run", "python", "scripts/check_i18n_html_coverage.py"])
    _run(["uv", "run", "python", "scripts/check_i18n_js_no_cjk.py", "--scope", "all"])
    _run(["uv", "run", "python", "scripts/check_i18n_ts_no_cjk.py"])
    _run(["uv", "run", "python", "scripts/check_i18n_duplicate_values.py"])
    _run(["uv", "run", "python", "scripts/gen_pseudo_locale.py", "--check"])

    _run(["uv", "run", "python", "scripts/check_i18n_orphan_keys.py"])

    _run(["uv", "run", "python", "scripts/gen_i18n_types.py", "--check"])

    _run(["uv", "run", "python", "scripts/check_i18n_param_signatures.py", "--strict"])

    _run(["uv", "run", "python", "scripts/check_i18n_locale_shape.py"])

    _run(["uv", "run", "python", "scripts/check_brand_color_consistency.py", "--quiet"])

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

    if not args.skip_version_check:
        _run(["uv", "run", "python", "scripts/bump_version.py", "--check"])

    minify_cmd = ["uv", "run", "python", "scripts/minify_assets.py"]
    precompress_cmd = ["uv", "run", "python", "scripts/precompress_static.py"]
    if args.ci:
        minify_cmd.append("--check")
        precompress_cmd.append("--check")
    _run(minify_cmd)
    _run(precompress_cmd)

    pytest_cmd = [
        "uv",
        "run",
        "pytest",
        "-q",
        "-o",
        "log_cli=false",
        "-n",
        "4",
        "--dist=loadfile",
    ]
    if args.with_coverage:
        pytest_cmd += [
            "--cov=src/ai_intervention_agent",
            "--cov-report=xml",
            "--cov-report=term-missing",
        ]
    pytest_env = None
    if args.with_coverage:
        pytest_env = os.environ.copy()
        pytest_env["AIIA_CI_GATE_WITH_COVERAGE"] = "1"
    _run(pytest_cmd, env=pytest_env)

    node_cmd = _resolve_node_redteam_cmd(str(args.node_version))
    if node_cmd:
        _run(node_cmd)
    elif os.environ.get("AIIA_SKIP_NODE_REDTEAM") == "1":
        print(
            "[ci_gate] skip: AIIA_SKIP_NODE_REDTEAM=1; "
            "red_team_i18n_runtime.mjs smoke check intentionally bypassed. "
            "Re-run without this flag once Node/fnm is installed.",
            file=sys.stderr,
        )
    else:
        # ``AIIA_SKIP_NODE_REDTEAM=1 make ci`` 显式 opt-out。
        raise RuntimeError(
            "未找到 node 或 fnm；i18n red-team smoke (scripts/red_team_i18n_runtime.mjs) "
            "无法运行。请安装 Node.js（推荐 v24.14.0，与 CI 对齐）或使用 fnm 管理 Node 版本。"
            "如果你确认本地 Node 缺失但仍要跑 ci_gate，可以设置环境变量 "
            "AIIA_SKIP_NODE_REDTEAM=1 显式 opt-out（CI 不会读这个变量，CI 覆盖率不会被弱化）。"
        )

    if args.with_vscode:
        _cleanup_vscode_vsix()

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
