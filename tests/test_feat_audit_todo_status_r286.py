"""R286 / cycle-26 t26-3: TODO 状态审计工具 invariant — 保证
``scripts/audit_todo_status.py`` 长期可用 (TODO.md gitignored 的特殊性
让本工具是 process-level invariant)。

Background
==========

cr54 §5 + cr55 §3.4 持续指出 process gap: TODO.md 是用户的本地 gitignored
scratchpad，cycle 完成对应功能时 commit 中往往没有显式标记 "Closes TODO
#X"，user 重新打开 TODO.md 时看不到状态变化。

R286 创建审计工具 ``scripts/audit_todo_status.py`` —— 扫描 TODO.md +
CHANGELOG.md，输出 TODO 项 → addressing commit 映射表。本测试锁定工具
的 API/CLI 契约。

Invariant
---------

1. 脚本可以从 CLI 执行不抛 exception
2. 脚本支持 ``--md`` flag 输出 markdown 表格
3. 脚本支持 ``--strict`` flag (有 open 未追踪 TODO 时 exit 1)
4. 脚本不会 commit / 修改任何文件 (只读取 + stdout 输出)
5. 脚本对 TODO.md 不存在的情况优雅 fallback (warn + exit 0)
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "audit_todo_status.py"


class TestAuditTodoStatusScriptR286(unittest.TestCase):
    """R286 #1: 脚本 CLI 契约。"""

    def setUp(self) -> None:
        # 用 sys.executable 而非 'python3'，避免环境差异
        self.python = sys.executable

    def test_script_exists_and_executable(self) -> None:
        """脚本必须存在 + 可执行 bit 已设置。"""
        self.assertTrue(
            AUDIT_SCRIPT.exists(),
            f"R286: ``{AUDIT_SCRIPT}`` 必须存在",
        )
        self.assertTrue(
            AUDIT_SCRIPT.stat().st_mode & 0o100,
            f"R286: ``{AUDIT_SCRIPT}`` 必须有 owner-execute bit (chmod +x)",
        )

    def test_script_has_module_docstring(self) -> None:
        """脚本 module docstring 必须解释 why + how (R286 anchor)。"""
        src = AUDIT_SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "R286",
            "TODO.md",
            "CHANGELOG.md",
            "gitignored",
        ):
            self.assertIn(
                marker,
                src,
                f"R286: 脚本 module docstring 必须提到 ``{marker}``",
            )

    def test_script_help_works(self) -> None:
        """``--help`` 必须正常工作不抛异常。"""
        result = subprocess.run(
            [self.python, str(AUDIT_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"R286: ``--help`` 必须 exit 0 (got {result.returncode})。"
            f" stderr={result.stderr[:300]}",
        )
        self.assertIn(
            "--md",
            result.stdout,
            "R286: ``--help`` 输出必须列出 ``--md`` flag",
        )
        self.assertIn(
            "--strict",
            result.stdout,
            "R286: ``--help`` 输出必须列出 ``--strict`` flag",
        )

    def test_script_runs_clean_no_exception(self) -> None:
        """主路径必须 exit 0 (默认行为，非 strict)。"""
        result = subprocess.run(
            [self.python, str(AUDIT_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"R286: 默认执行必须 exit 0 (got {result.returncode})。"
            f" stderr={result.stderr[:300]}",
        )

    def test_script_md_flag_renders_table(self) -> None:
        """``--md`` 必须输出 markdown 表格 (含 ``|`` 分隔符与 header 行)。"""
        result = subprocess.run(
            [self.python, str(AUDIT_SCRIPT), "--md"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        out = result.stdout
        # 如果 TODO.md 不存在 → fallback warn，跳过本断言
        if "TODO.md 不存在" not in result.stderr:
            self.assertIn(
                "|",
                out,
                "R286: ``--md`` 输出必须有 ``|`` 分隔符",
            )
            self.assertIn(
                "TODO snippet",
                out,
                "R286: ``--md`` 输出必须有 ``TODO snippet`` 表头",
            )

    def test_script_summary_line_present(self) -> None:
        """主路径 stdout 必须以 ``# Summary:`` 行结尾。"""
        result = subprocess.run(
            [self.python, str(AUDIT_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if "TODO.md 不存在" in result.stderr:
            self.skipTest("TODO.md 不存在，跳过 summary 断言")
        self.assertIn(
            "# Summary:",
            result.stdout,
            "R286: 主输出必须含 ``# Summary:`` 行",
        )


class TestAuditScriptReadOnlyR286(unittest.TestCase):
    """R286 #2: 脚本必须严格 read-only (不写任何文件)。"""

    def test_script_does_not_import_write_apis(self) -> None:
        """脚本不能 import 任何明显的写文件 / git 操作 API。"""
        src = AUDIT_SCRIPT.read_text(encoding="utf-8")
        # 反向 invariant: 不能出现 .write(/.write_text(/git.* import
        forbidden = [
            r"\.write\(",
            r"\.write_text\(",
            r"\.write_bytes\(",
            r"shutil\.copy",
            r"os\.remove",
            r"os\.unlink",
            r"subprocess.*git\s+(add|commit|push)",
        ]
        import re

        for pat in forbidden:
            matches = re.findall(pat, src)
            self.assertEqual(
                len(matches),
                0,
                f"R286: 脚本必须 read-only，不能含 ``{pat}``（找到 {len(matches)} 处）",
            )


if __name__ == "__main__":
    unittest.main()
