#!/usr/bin/env python3
"""
本地/CI Gate 一键检查脚本（Python 侧）。

设计目标：
- 把“门禁命令”收敛到单一入口，减少 docs / CI / 脚本之间的漂移
- 默认适合本地开发：会自动格式化（ruff format）
- 可通过参数切换为 CI 模式：只做检查、不改动文件
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


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=_repo_root(), check=True)


def main(argv: list[str]) -> int:
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

    pytest_cmd = ["uv", "run", "pytest", "-q"]
    if args.with_coverage:
        pytest_cmd += ["--cov=.", "--cov-report=xml", "--cov-report=term-missing"]
    _run(pytest_cmd)

    # 生成静态资源压缩文件（.min）；该类文件默认 gitignore
    _run(["uv", "run", "python", "scripts/minify_assets.py"])

    if args.with_vscode:
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

        _run(cmd)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
