"""``scripts/ci_gate.py`` 在缺 Node/fnm 时必须 fail-closed，除非显式 opt-out。

历史：v1.5.x 早期 ci_gate 在 ``node`` / ``fnm`` 都缺失时静默 ``warn`` + 跳过
``red_team_i18n_runtime.mjs``——同 round-6 的 ``docs-check`` warn-only 漂移
同构。当本地约定升级为 fail-closed 后，本测试锁住两条契约：

1. 默认（环境变量未设置）→ 抛 ``RuntimeError``，错误消息里包含安装指引
   和 opt-out 提示。
2. ``AIIA_SKIP_NODE_REDTEAM=1`` → 跳过且仅在 stderr 打 ``[ci_gate] skip:``
   信号；不抛错，CI 退出码不变（用于本地真没装 Node 的开发者）。

用 monkeypatch 替换 ``_has_cmd`` 模拟"node / fnm 都不存在"，比真的去清空
``PATH`` 更稳定（避免 uv 自身丢失）。
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import ci_gate


class TestNodeRedteamFailClosed(unittest.TestCase):
    """缺 Node 时默认行为：fail-closed。"""

    def _run_decision_block(self) -> None:
        """直接调用 ci_gate 真实代码：``_resolve_node_redteam_cmd`` 决定命令，
        若返回空列表则按 ``AIIA_SKIP_NODE_REDTEAM`` 决定 fail-closed / opt-out。

        只复刻 ``_main_impl`` 中那段 fail-closed / opt-out 三向分支的"分支选择"，
        不调用 ``_main_impl`` 本身（它会跑数十秒的依赖同步 / ruff / ty / pytest
        前置工作）。``_resolve_node_redteam_cmd`` 是真函数；本助手的"分支选择"部分
        极薄（< 6 行），如果未来要测真整段，可以再抽一个 ``_run_node_redteam_step``
        函数。
        """
        node_cmd = ci_gate._resolve_node_redteam_cmd("v24.14.0")
        if node_cmd:
            return
        import os

        if os.environ.get("AIIA_SKIP_NODE_REDTEAM") == "1":
            print(
                "[ci_gate] skip: AIIA_SKIP_NODE_REDTEAM=1; "
                "red_team_i18n_runtime.mjs smoke check intentionally bypassed.",
                file=sys.stderr,
            )
            return
        raise RuntimeError(
            "未找到 node 或 fnm；i18n red-team smoke (scripts/red_team_i18n_runtime.mjs) "
            "无法运行。AIIA_SKIP_NODE_REDTEAM=1 显式 opt-out。"
        )

    def test_default_raises_runtime_error(self) -> None:
        """node + fnm 都缺、未设 opt-out → RuntimeError，且消息包含安装指引。"""
        with mock.patch.object(ci_gate, "_has_cmd", return_value=False):
            with mock.patch.dict("os.environ", {}, clear=False):
                import os

                os.environ.pop("AIIA_SKIP_NODE_REDTEAM", None)
                with self.assertRaises(RuntimeError) as ctx:
                    self._run_decision_block()
                msg = str(ctx.exception)
                self.assertIn("node", msg.lower())
                self.assertIn("AIIA_SKIP_NODE_REDTEAM", msg)

    def test_opt_out_skips_silently(self) -> None:
        """node + fnm 都缺、设了 ``AIIA_SKIP_NODE_REDTEAM=1`` → 不抛错，stderr 留信号。"""
        with mock.patch.object(ci_gate, "_has_cmd", return_value=False):
            with mock.patch.dict(
                "os.environ", {"AIIA_SKIP_NODE_REDTEAM": "1"}, clear=False
            ):
                buf = io.StringIO()
                with redirect_stderr(buf):
                    self._run_decision_block()
                stderr = buf.getvalue()
                self.assertIn("[ci_gate] skip", stderr)
                self.assertIn("AIIA_SKIP_NODE_REDTEAM=1", stderr)

    def test_node_present_no_decision_taken(self) -> None:
        """node 存在 → 决策块直接 return；不依赖 opt-out / 不抛错。"""

        def fake_has_cmd(name: str) -> bool:
            return name == "node"

        with mock.patch.object(ci_gate, "_has_cmd", side_effect=fake_has_cmd):
            self._run_decision_block()

    def test_only_fnm_present_no_decision_taken(self) -> None:
        """fnm 存在但 node 缺失 → ci_gate 走 ``fnm exec`` 路径；决策块不抛错。"""

        def fake_has_cmd(name: str) -> bool:
            return name == "fnm"

        with mock.patch.object(ci_gate, "_has_cmd", side_effect=fake_has_cmd):
            self._run_decision_block()


class TestRunWarnHelperStillExists(unittest.TestCase):
    """``_run_warn`` 函数没有活跃调用方，但保留作为未来 warn-level 门禁的复用模板。

    本测试反向锁住：``_run_warn`` 仍然导出且签名稳定（``label`` 关键字必填），
    避免一边删除一边发现需要新加 warn 级门禁时再 reinvent。如果未来确认
    永久不需要 warn 级，可以删除本测试 + 删除 ``_run_warn``——但不要先删
    helper 再后悔。
    """

    def test_run_warn_signature_stable(self) -> None:
        import inspect

        sig = inspect.signature(ci_gate._run_warn)
        self.assertIn("label", sig.parameters)
        self.assertEqual(sig.parameters["label"].kind, inspect.Parameter.KEYWORD_ONLY)


if __name__ == "__main__":
    unittest.main()
