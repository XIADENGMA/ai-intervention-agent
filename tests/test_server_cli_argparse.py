"""CLI · ``ai-intervention-agent --version`` / ``--help`` 回归测试。

设计目标
========

PyPI 工具的事实标准（pip / ruff / uv / black / fastmcp 自己）都支持
``--version`` 和 ``--help``。本项目在 v1.6.4 之前没有这层 CLI——用户输入
``uvx ai-intervention-agent --version`` 会被 ``mcp.run(transport="stdio")``
当作纯 MCP server 启动，永远 hang 在 stdin EOF 上，得 Ctrl+C 才能退。

本测试守护四条 invariant：

1. ``--version`` / ``-V``：``sys.exit(0)``，stdout 包含 ``ai-intervention-agent`` +
   版本号；
2. ``--help`` / ``-h``：``sys.exit(0)``，stdout 含 ``usage:`` 段；
3. 未知 flag：``sys.exit(2)``（argparse 默认），stderr 含 ``unrecognized
   arguments``；
4. 无参数（MCP client 调起的默认调用形态）：fall through 到 stdio loop——
   测试时 mock ``mcp.run`` 验证它**确实**被调用一次，且 argv 解析不抛
   ``SystemExit``。

这四条守护"CLI 改造没有破坏 MCP client 调用契约"——任何后续修改
（加新 flag、改 help 文本）都必须先过这四条 invariant，避免悄悄回归到
"--version hang 永远"的旧 bug。
"""

from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from ai_intervention_agent import server


class TestBuildArgParser(unittest.TestCase):
    """``_build_arg_parser()`` 直接函数测试：纯构造行为，无副作用。"""

    def test_returns_argparse_parser(self) -> None:
        parser = server._build_arg_parser()
        self.assertIsInstance(parser, argparse.ArgumentParser)

    def test_prog_name_is_pypi_console_script_name(self) -> None:
        """parser.prog 必须与 [project.scripts] 注册名一致。

        否则 ``--help`` 显示的 prog 与用户实际敲的命令对不上，UX 受损。
        """
        parser = server._build_arg_parser()
        self.assertEqual(parser.prog, "ai-intervention-agent")

    def test_version_action_is_registered(self) -> None:
        """``--version`` 必须存在且 ``action == "version"``。

        避免后续重构误改成 ``store_true`` 之类需要手工 print + sys.exit
        的形态——argparse 自带的 ``action="version"`` 是唯一不会留 bug
        余地的实现。
        """
        parser = server._build_arg_parser()
        actions = {a.option_strings[0]: a for a in parser._actions}
        self.assertIn("--version", actions)
        # argparse 内部 _VersionAction class name；用 string 比较更稳健
        self.assertEqual(type(actions["--version"]).__name__, "_VersionAction")

    def test_version_short_flag_is_capital_V(self) -> None:
        """``-V``（大写）是 PyPI CLI 惯例（pip / ruff / uv 都用 ``-V``）。

        ``-v`` 通常留给 ``--verbose``，避免日后扩展冲突。
        """
        parser = server._build_arg_parser()
        version_action = next(
            a for a in parser._actions if "--version" in a.option_strings
        )
        self.assertIn("-V", version_action.option_strings)


class TestMainCliVersionFlag(unittest.TestCase):
    """``main(["--version"])`` 端到端：argparse ``action="version"`` 触发
    ``sys.exit(0)`` + 把 version string 写 stdout。"""

    def _run_main_capture(self, argv: list[str]) -> tuple[int, str, str]:
        """运行 ``server.main(argv)``，捕获 (exit_code, stdout, stderr)。

        ``main`` 的 stdio loop 路径不会触发——argparse ``--version`` 在
        ``sys.exit(0)`` 之前已经退出。但万一以后有 regression，``mcp.run``
        被 patch 成 no-op，避免测试 hang。
        """
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(server.mcp, "run", lambda *a, **kw: None),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            try:
                server.main(argv)
                # 没有抛 SystemExit：意味着 fall through 到 stdio loop（已被 patch）
                return 0, stdout.getvalue(), stderr.getvalue()
            except SystemExit as exc:
                code = (
                    exc.code
                    if isinstance(exc.code, int)
                    else (1 if exc.code is not None else 0)
                )
                return code, stdout.getvalue(), stderr.getvalue()

    def test_version_flag_exits_zero(self) -> None:
        code, _, _ = self._run_main_capture(["--version"])
        self.assertEqual(code, 0)

    def test_version_flag_prints_to_stdout(self) -> None:
        """``--version`` 输出走 stdout（不是 stderr），方便 ``$(...)``
        命令替换 / pipe。argparse 行为，但加测试守这条契约。"""
        _, out, _ = self._run_main_capture(["--version"])
        self.assertIn("ai-intervention-agent", out)

    def test_version_short_flag_works(self) -> None:
        """``-V`` 等价于 ``--version``。"""
        code, out, _ = self._run_main_capture(["-V"])
        self.assertEqual(code, 0)
        self.assertIn("ai-intervention-agent", out)

    def test_version_output_matches_resolve_server_version(self) -> None:
        """打印的版本号必须与 ``_resolve_server_version()`` 一致——避免
        两条版本号路径漂移（一条进 MCP initialize，一条进 CLI）。"""
        _, out, _ = self._run_main_capture(["--version"])
        expected = server._resolve_server_version()
        self.assertIn(expected, out)


class TestMainCliHelpFlag(unittest.TestCase):
    """``main(["--help"])`` 端到端：argparse 自动 ``sys.exit(0)`` + 把 help
    写 stdout。"""

    def _run_main_capture(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(server.mcp, "run", lambda *a, **kw: None),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            try:
                server.main(argv)
                return 0, stdout.getvalue(), stderr.getvalue()
            except SystemExit as exc:
                code = (
                    exc.code
                    if isinstance(exc.code, int)
                    else (1 if exc.code is not None else 0)
                )
                return code, stdout.getvalue(), stderr.getvalue()

    def test_help_flag_exits_zero(self) -> None:
        code, _, _ = self._run_main_capture(["--help"])
        self.assertEqual(code, 0)

    def test_help_short_flag_works(self) -> None:
        code, _, _ = self._run_main_capture(["-h"])
        self.assertEqual(code, 0)

    def test_help_contains_usage_line(self) -> None:
        """help 文本必须含 ``usage:`` 行（argparse 默认行为，但锁死）。"""
        _, out, _ = self._run_main_capture(["--help"])
        self.assertIn("usage:", out.lower())

    def test_help_mentions_version_flag(self) -> None:
        """help 必须自我描述 ``--version`` 选项，让用户知道存在。"""
        _, out, _ = self._run_main_capture(["--help"])
        self.assertIn("--version", out)

    def test_help_mentions_mcp_or_stdio_context(self) -> None:
        """help 应当让"不知道这是个 MCP server"的新用户也能搞清楚——
        epilog 里有 stdio / MCP 提示。"""
        _, out, _ = self._run_main_capture(["--help"])
        out_lower = out.lower()
        self.assertTrue(
            "mcp" in out_lower or "stdio" in out_lower,
            f"help 文本应包含 MCP 或 stdio 上下文，实际：{out!r}",
        )


class TestMainCliUnknownFlag(unittest.TestCase):
    """``main(["--unknown"])`` 端到端：argparse 默认 ``sys.exit(2)``。"""

    def _run_main_capture(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(server.mcp, "run", lambda *a, **kw: None),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            try:
                server.main(argv)
                return 0, stdout.getvalue(), stderr.getvalue()
            except SystemExit as exc:
                code = (
                    exc.code
                    if isinstance(exc.code, int)
                    else (1 if exc.code is not None else 0)
                )
                return code, stdout.getvalue(), stderr.getvalue()

    def test_unknown_flag_exits_two(self) -> None:
        code, _, _ = self._run_main_capture(["--unknown-flag"])
        self.assertEqual(code, 2)

    def test_unknown_flag_error_goes_to_stderr(self) -> None:
        _, _, err = self._run_main_capture(["--unknown-flag"])
        self.assertIn("unrecognized", err.lower())


class TestMainCliBackwardCompat(unittest.TestCase):
    """无参数调用：必须 fall through 到 ``mcp.run``，保持 MCP client 契约。

    这是最关键的契约——Cursor / Claude Desktop / mcp-cli 默认调起本 binary
    时 ``sys.argv[1:] == []``。本类守护此路径**不**被 argparse 截掉。
    """

    def test_no_args_falls_through_to_mcp_run(self) -> None:
        """无参数时，``mcp.run`` 必须被调用至少 1 次。"""
        called = []

        def _fake_run(*args, **kwargs):
            called.append((args, kwargs))

        with (
            patch.object(server.mcp, "run", side_effect=_fake_run),
            patch.object(server, "_stdlib_logging", server._stdlib_logging),
        ):
            server.main([])

        self.assertGreaterEqual(
            len(called),
            1,
            "无参数调用时 mcp.run 必须被调用，否则 MCP client 调用契约破坏",
        )

    def test_no_args_uses_stdio_transport(self) -> None:
        """``mcp.run`` 必须以 ``transport='stdio'`` 调起——MCP 协议契约。"""
        called = []

        def _fake_run(*args, **kwargs):
            called.append(kwargs)

        with patch.object(server.mcp, "run", side_effect=_fake_run):
            server.main([])

        self.assertTrue(
            any(kw.get("transport") == "stdio" for kw in called),
            f"mcp.run 必须以 transport='stdio' 调起，实际 kwargs：{called!r}",
        )

    def test_none_argv_skips_argparse(self) -> None:
        """``main(None)`` 必须**跳过** argparse 直接走 stdio loop——这是
        保护历史测试套件的关键契约。

        否则 pytest 自己的 sys.argv（带 ``-v`` / ``-q`` / 路径等 flag）会被
        argparse 当成 server CLI flag，整套 ``test_server_functions::TestMain``
        / ``test_server_main_retry_backoff`` / ``test_diagnostic_event_log_r40``
        都会炸 ``argparse.SystemExit(2)``。
        """
        called = []

        def _fake_run(*args, **kwargs):
            called.append((args, kwargs))

        # 故意把 sys.argv 设置成一个"如果误用 argparse 一定炸"的值
        # （含 argparse 看不懂的 flag）。如果 main(None) 错误地 fallback
        # 到 sys.argv[1:]，会触发 SystemExit(2)；正确实现下应忽略它。
        with (
            patch.object(server.sys, "argv", ["pytest", "--unknown-pytest-flag"]),
            patch.object(server.mcp, "run", side_effect=_fake_run),
        ):
            try:
                server.main(None)
            except SystemExit as exc:
                self.fail(
                    f"main(None) 应跳过 argparse，不应抛 SystemExit。"
                    f"实际 exit_code={exc.code!r}"
                )

        self.assertGreaterEqual(
            len(called),
            1,
            "``main(None)`` 应直接走 stdio loop（mcp.run 被调用）",
        )


class TestCliMainConsoleScriptEntry(unittest.TestCase):
    """``_cli_main()``：PyPA console_script 入口，显式读 sys.argv[1:] 后调
    ``main(argv)``。"""

    def test_cli_main_with_version_flag_in_sys_argv(self) -> None:
        """模拟 ``ai-intervention-agent --version`` 调用：sys.argv 含
        ``--version``，``_cli_main()`` 应触发 argparse 解析 + ``sys.exit(0)``。"""
        stdout = io.StringIO()
        with (
            patch.object(server.sys, "argv", ["ai-intervention-agent", "--version"]),
            patch.object(server.mcp, "run", lambda *a, **kw: None),
            redirect_stdout(stdout),
        ):
            with self.assertRaises(SystemExit) as ctx:
                server._cli_main()

        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("ai-intervention-agent", stdout.getvalue())

    def test_cli_main_no_flag_falls_through_to_stdio(self) -> None:
        """模拟 MCP client 调起：sys.argv 只有 prog name，无 flag。
        ``_cli_main()`` 必须 fall through 到 stdio loop（mcp.run 被调用）。"""
        called = []

        def _fake_run(*args, **kwargs):
            called.append((args, kwargs))

        with (
            patch.object(server.sys, "argv", ["ai-intervention-agent"]),
            patch.object(server.mcp, "run", side_effect=_fake_run),
        ):
            server._cli_main()

        self.assertGreaterEqual(
            len(called),
            1,
            "无 flag 时 _cli_main 必须走 stdio loop，否则 MCP client 调用契约破坏",
        )


if __name__ == "__main__":
    unittest.main()
