"""R26.1 性能不变量：``flask_limiter`` 顶级 import 必须延迟到 ``WebUIApp.__init__``。

背景
====

``web_ui.py`` 在 R26.1 之前顶层 ``from flask_limiter import Limiter`` +
``from flask_limiter.util import get_remote_address``。``flask_limiter`` 模块本身
的 cold-start ~65 ms，但只有当 ``Limiter(...)`` 实例化（在 ``WebUIApp.__init__``
里）时才被真正使用——大量「``from web_ui import 小工具``」的单元测试（
``validate_auto_resubmit_timeout`` / ``MDNS_DEFAULT_HOSTNAME`` /
``_is_probably_virtual_interface`` 等）从来不构造 ``WebUIApp``，却被迫支付
``flask_limiter`` 的加载成本。

R26.1 把两个 import 推迟到 ``WebUIApp.__init__`` 体内（紧邻 ``self.limiter =
Limiter(...)`` 那一行），让「只取小工具」路径不再加载 ``flask_limiter``。

收益
====

- ``import web_ui`` 路径（小工具单测视角）省 ~21 ms / call（``flask_limiter``
  在 ``flask`` 已加载后增量成本约 21 ms，绝对值 65 ms 的差额是因为大量传递依
  赖如 ``werkzeug`` / ``blinker`` / ``click`` 已经被 ``flask`` 提前加载）。
- ``WebUIApp.__init__`` 路径首次构造仍付 21 ms，二次构造命中 ``sys.modules`` cache。

不变量
======

1. **静态源码不变量**（``inspect.getsource``）：
   - 模块顶层不能有 ``from flask_limiter import Limiter`` 或
     ``from flask_limiter.util import get_remote_address``（缩进 0）。
   - ``WebUIApp.__init__`` 函数体内必须有这两条 import 出现在
     ``self.limiter = Limiter(...)`` **之前**（保证 Limiter 解析时已就绪）。

2. **运行时不变量**（fresh subprocess）：
   - ``import web_ui`` 不应让 ``flask_limiter`` 进入 ``sys.modules``。
   - ``from web_ui import validate_auto_resubmit_timeout`` 同上。

3. **行为契约**：实例化 ``WebUIApp`` 后 ``self.limiter`` 必须是 ``flask_limiter.Limiter``
   实例（保留运行时正确性）。

边界
====

- 因 ``Limiter`` 在本模块只用作构造调用，没有任何模块级 ``: Limiter`` 类型注解，
  所以**不**需要 ``if TYPE_CHECKING: from flask_limiter import Limiter`` 守护块；
  下游 ``web_ui_routes/{task,feedback,static}.py`` 各自已经在自己的
  ``TYPE_CHECKING`` 块里 import ``Limiter`` 用作 ``: Limiter`` 注解，那条路径不受
  影响。
- 小工具测试场景下「不加载 flask_limiter」是必要不变量；构造 ``WebUIApp`` 才加载
  是预期行为，测试不应该断言「构造 WebUIApp 后 flask_limiter 不在 sys.modules」。
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import unittest

import web_ui


class TestWebUiLazyFlaskLimiterStatic(unittest.TestCase):
    """``web_ui.py`` 顶层不能再 ``from flask_limiter import ...``。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = inspect.getsource(web_ui)

    def test_no_top_level_flask_limiter_import(self) -> None:
        """模块顶层不能有 ``from flask_limiter ...``。"""
        for pattern_desc, pattern in (
            (
                "from flask_limiter import Limiter",
                r"^from flask_limiter import Limiter\b",
            ),
            (
                "from flask_limiter.util import get_remote_address",
                r"^from flask_limiter\.util import get_remote_address\b",
            ),
            ("import flask_limiter", r"^import flask_limiter\b"),
        ):
            with self.subTest(pattern=pattern_desc):
                self.assertIsNone(
                    re.search(pattern, self.source, re.MULTILINE),
                    f"R26.1 性能保护：web_ui 顶层禁止 ``{pattern_desc}``——"
                    "应改成 ``WebUIApp.__init__`` 内部本地 import",
                )

    def test_init_has_local_imports_before_limiter_construction(self) -> None:
        """``WebUIApp.__init__`` 体内必须本地 import 两个符号，且出现在
        ``self.limiter = Limiter(...)`` **之前**。"""
        # 用 inspect 拿 __init__ 函数体（class WebFeedbackUI 的 __init__）
        init_src = inspect.getsource(web_ui.WebFeedbackUI.__init__)

        # 1) 必须有这两条本地 import
        self.assertIn(
            "from flask_limiter import Limiter",
            init_src,
            "WebUIApp.__init__ 必须本地 ``from flask_limiter import Limiter``",
        )
        self.assertIn(
            "from flask_limiter.util import get_remote_address",
            init_src,
            "WebUIApp.__init__ 必须本地 ``from flask_limiter.util import get_remote_address``",
        )

        # 2) 必须出现在 ``self.limiter = Limiter(`` 之前
        limiter_import_pos = init_src.find("from flask_limiter import Limiter")
        get_remote_pos = init_src.find(
            "from flask_limiter.util import get_remote_address"
        )
        limiter_construct_pos = init_src.find("self.limiter = Limiter(")

        self.assertGreater(
            limiter_construct_pos,
            -1,
            "WebUIApp.__init__ 必须有 ``self.limiter = Limiter(...)`` 构造调用",
        )
        self.assertLess(
            limiter_import_pos,
            limiter_construct_pos,
            "``from flask_limiter import Limiter`` 必须在 ``self.limiter = Limiter(`` 之前",
        )
        self.assertLess(
            get_remote_pos,
            limiter_construct_pos,
            "``from flask_limiter.util import get_remote_address`` 必须在 "
            "``self.limiter = Limiter(`` 之前（``key_func=get_remote_address`` 解析依赖）",
        )


class TestWebUiLazyFlaskLimiterRuntime(unittest.TestCase):
    """``import web_ui`` 不触发 ``flask_limiter`` 加载——subprocess 隔离验证。"""

    def _run_in_subprocess(self, code: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(__import__("pathlib").Path(web_ui.__file__).parent),
            check=True,
        )
        return result.stdout

    def test_import_web_ui_does_not_load_flask_limiter(self) -> None:
        stdout = self._run_in_subprocess(
            'import sys; import web_ui; print("flask_limiter" in sys.modules)'
        )
        self.assertEqual(
            stdout.strip(),
            "False",
            "R26.1: ``import web_ui`` 不应触发 ``flask_limiter`` 加载（"
            "若失败请检查 web_ui.py 顶层是否有人重新加了 ``from flask_limiter ...``）",
        )

    def test_utility_import_does_not_load_flask_limiter(self) -> None:
        """``from web_ui import 小工具`` 同样不应触发 flask_limiter——这才是 R26.1
        实际收益的所在。"""
        stdout = self._run_in_subprocess(
            "import sys; from web_ui import validate_auto_resubmit_timeout; "
            'print("flask_limiter" in sys.modules)'
        )
        self.assertEqual(
            stdout.strip(),
            "False",
            "R26.1: ``from web_ui import validate_auto_resubmit_timeout`` 不应"
            "触发 flask_limiter 加载",
        )


class TestWebUiAppStillUsesLimiter(unittest.TestCase):
    """构造 ``WebFeedbackUI`` 后 ``self.limiter`` 必须是 ``flask_limiter.Limiter`` 实例。

    保证 R26.1 的懒加载没有破坏「rate limit 仍然生效」的运行时契约。
    """

    def test_webuiapp_self_limiter_is_real_limiter(self) -> None:
        """构造 WebFeedbackUI 后 ``self.limiter`` 必须能调用 ``.limit(...)`` 与 ``.exempt``。

        ``WebFeedbackUI.__init__`` 要求 ``prompt`` 位置参数，这里传一个最简的占位
        prompt 即可（不会触发任何 HTTP 路径，``init`` 只做对象组装）。
        """
        from flask_limiter import Limiter

        ui = web_ui.WebFeedbackUI(prompt="r26-1-test", port=0)
        self.assertIsInstance(
            ui.limiter,
            Limiter,
            "WebFeedbackUI.__init__ 必须把 self.limiter 设为 flask_limiter.Limiter 实例",
        )
        # 验证 decorator 接口存在（rate-limit 测试依赖这两个属性）
        self.assertTrue(
            callable(ui.limiter.limit),
            "self.limiter.limit 必须是可调用 decorator factory",
        )
        self.assertTrue(
            callable(ui.limiter.exempt),
            "self.limiter.exempt 必须是可调用 decorator",
        )


if __name__ == "__main__":
    unittest.main()
