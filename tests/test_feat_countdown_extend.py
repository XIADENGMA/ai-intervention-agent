"""feat-countdown-extend (§3.2) 回归契约

对标 mcp-feedback-enhanced v2.6.0 的 "Auto-commit pause/resume" 控制：
用户写长反馈时倒计时一直滴答压力大；现在可以点 +60s 按钮把单个 task
的 auto-resubmit deadline 往后推 60 秒（每个 task 最多 3 次）。

设计原则
--------
1. **最小可用 (MVP)**：单向 extend（只增不减），不实现 pause/resume。
   用户真要"无限暂停"应该走全局禁用 auto_resubmit_timeout 路径。
2. **per-task 限额防滥用**：每个 task 最多 3 次延长 + 单次 [10, 300]s，
   避免绕开 auto-resubmit 永久挂住任务。
3. **零 SSE schema 改动**：不新增 SSE 事件类型，前端用 fetch response
   立即更新本地状态，其他 client 通过下一次 5s 轮询同步。
4. **后端为 source-of-truth**：``extends_used`` 写在 Task model，
   API 响应返回 ``extends_used + extends_max`` 让前端 stateless 计算
   按钮 disabled 状态。
5. **i18n + a11y**：5 个翻译 key + title/aria-label + disabled 状态切换。

锁定的不变量
------------
A. 后端 Task model：``extends_used`` 字段 + ``extend_deadline`` 方法
B. 后端 endpoint：路由注册 + 速率限制 + 4 种错误码 + 422 上限保护
C. 后端业务规则：completed task / disabled auto-resubmit / 超出 [10,300] /
   达到 max_extends 全部拒绝
D. 前端 HTML：按钮元素 + i18n 属性 + initial disabled + hidden 状态
E. 前端 CSS：按钮样式 + hover/focus/disabled state + .hidden 隐藏
F. 前端 JS：updateCountdownExtendButton + handleExtendCountdownClick +
   one-time DOMContentLoaded binding
G. i18n：5 keys × 2 locale，中文 distinct
H. 字段透传：GET /api/tasks 和 GET /api/tasks/export 都返回 extends_used
   和 extends_max（前端 backward-compat 依赖）
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_QUEUE_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "task_queue.py"
TASK_ROUTE_PY = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
)
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
EN_JSON = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
ZH_JSON = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ============================================================
# A. Task model: extends_used + extend_deadline
# ============================================================
class TestTaskModelExtendsUsed(unittest.TestCase):
    def setUp(self) -> None:
        self.src = TASK_QUEUE_PY.read_text(encoding="utf-8")

    def test_extends_used_field_declared(self) -> None:
        self.assertRegex(
            self.src,
            r"extends_used:\s*int\s*=\s*0",
            "Task model 必须有 extends_used: int = 0 字段",
        )

    def test_extend_deadline_method_defined(self) -> None:
        self.assertIn(
            "def extend_deadline",
            self.src,
            "Task 必须有 extend_deadline 方法",
        )

    def test_extend_returns_tuple_success_error(self) -> None:
        """方法签名必须是 ``-> tuple[bool, str | None]``，让 caller
        能区分"被拒绝的原因"。"""
        m = re.search(
            r"def extend_deadline\([^)]+\)\s*->\s*([^:]+):",
            self.src,
        )
        self.assertIsNotNone(m, "未找到 extend_deadline 签名")
        assert m is not None
        return_type = m.group(1).strip()
        self.assertIn("tuple", return_type.lower())
        self.assertIn("bool", return_type.lower())
        # str 或 None
        self.assertTrue(
            "str" in return_type or "None" in return_type,
            f"返回类型必须含 str/None 用于错误码：实际 {return_type}",
        )


# ============================================================
# A2. Task.extend_deadline 行为契约（直接调用 + 状态）
# ============================================================
class TestTaskExtendBehavior(unittest.TestCase):
    """直接 import Task 模块跑业务逻辑，端到端验证四种拒绝路径。"""

    def setUp(self) -> None:
        from ai_intervention_agent.task_queue import Task

        self.Task = Task

    # cr32 §3.3 low fix：所有调用强制传 max_extends/min/max；这里集中给
    # 测试用一份默认 keyword，避免每个 case 重复书写。
    EXT_KW = {"max_extends": 3, "min_seconds": 10, "max_seconds": 300}

    def test_extend_increases_timeout_and_used(self) -> None:
        t = self.Task(task_id="t1", prompt="hello", auto_resubmit_timeout=120)
        self.assertEqual(t.extends_used, 0)
        ok, err = t.extend_deadline(60, **self.EXT_KW)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(t.auto_resubmit_timeout, 180)
        self.assertEqual(t.extends_used, 1)

    def test_extend_respects_max_extends(self) -> None:
        t = self.Task(task_id="t1", prompt="hi", auto_resubmit_timeout=120)
        for _ in range(3):
            ok, _err = t.extend_deadline(60, **self.EXT_KW)
            self.assertTrue(ok)
        # 第 4 次应该被拒
        ok, err = t.extend_deadline(60, **self.EXT_KW)
        self.assertFalse(ok)
        self.assertEqual(err, "extends_limit_reached")
        self.assertEqual(t.extends_used, 3, "上限后 extends_used 不应再 +1")

    def test_extend_rejects_completed_task(self) -> None:
        from ai_intervention_agent.task_queue import TaskStatus

        t = self.Task(
            task_id="t1",
            prompt="hi",
            auto_resubmit_timeout=120,
            status=TaskStatus.COMPLETED,
        )
        ok, err = t.extend_deadline(60, **self.EXT_KW)
        self.assertFalse(ok)
        self.assertEqual(err, "task_completed")

    def test_extend_rejects_disabled_auto_resubmit(self) -> None:
        t = self.Task(task_id="t1", prompt="hi", auto_resubmit_timeout=0)
        ok, err = t.extend_deadline(60, **self.EXT_KW)
        self.assertFalse(ok)
        self.assertEqual(err, "auto_resubmit_disabled")

    def test_extend_rejects_seconds_out_of_range(self) -> None:
        t = self.Task(task_id="t1", prompt="hi", auto_resubmit_timeout=120)
        for bad in (5, 301, 0, -10):
            ok, err = t.extend_deadline(bad, **self.EXT_KW)
            self.assertFalse(ok, f"seconds={bad} 应被拒")
            self.assertEqual(err, "invalid_seconds")

    def test_extend_remaining_time_increases(self) -> None:
        """``get_remaining_time`` 应反映新的 auto_resubmit_timeout。"""
        t = self.Task(task_id="t1", prompt="hi", auto_resubmit_timeout=120)
        before = t.get_remaining_time()
        ok, _err = t.extend_deadline(60, **self.EXT_KW)
        self.assertTrue(ok)
        after = t.get_remaining_time()
        # 时间精度可能差 ±1s，所以用 >= before + 59 防止 race
        self.assertGreaterEqual(after, before + 59)

    def test_extend_keyword_only_enforced(self) -> None:
        """cr32 §3.3 low fix invariant：max_extends/min_seconds/max_seconds
        是 keyword-only **且必填**，不能用 positional 也不能省略 → 让
        ``server_config.COUNTDOWN_*`` 调整后不会出现"路由侧改了但有遗漏
        的调用点仍用旧默认值 3 / 10 / 300"漂移。

        故意走 ``cast(Any, ...)`` 让 ty/mypy 不在 IDE / pre-commit 阶段
        拦截 — 我们就是要测**运行时** ``TypeError``。
        """
        from typing import Any, cast

        t = self.Task(task_id="t1", prompt="hi", auto_resubmit_timeout=120)
        with self.assertRaises(TypeError):
            cast(Any, t).extend_deadline(60)
        with self.assertRaises(TypeError):
            cast(Any, t).extend_deadline(60, max_extends=3, min_seconds=10)


# ============================================================
# B. Backend endpoint registration + constants
# ============================================================
class TestBackendEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.src = TASK_ROUTE_PY.read_text(encoding="utf-8")

    def test_constants_defined(self) -> None:
        for const, expected in (
            ("COUNTDOWN_EXTENDS_MAX", 3),
            ("COUNTDOWN_EXTEND_DEFAULT_SECONDS", 60),
            ("COUNTDOWN_EXTEND_SECONDS_MIN", 10),
            ("COUNTDOWN_EXTEND_SECONDS_MAX", 300),
        ):
            self.assertRegex(
                self.src,
                rf"{const}:\s*int\s*=\s*{expected}",
                f"必须有模块常量 {const} = {expected}",
            )

    def test_extend_route_registered(self) -> None:
        self.assertIn(
            '@self.app.route("/api/tasks/<task_id>/extend", methods=["POST"])',
            self.src,
            "必须注册 POST /api/tasks/<task_id>/extend 路由",
        )

    def test_extend_route_has_rate_limit(self) -> None:
        """速率限制必须存在，防止恶意 spam。"""
        m = re.search(
            r'@self\.app\.route\("/api/tasks/<task_id>/extend".*?\n'
            r'\s*@self\.limiter\.limit\("([^"]+)"\)',
            self.src,
        )
        self.assertIsNotNone(
            m,
            "extend 路由必须紧跟 @self.limiter.limit(...) 速率限制装饰器",
        )
        assert m is not None
        # 必须是合理范围（不能 1000/min spammable，不能 1/hour 限制日常使用）
        self.assertRegex(
            m.group(1),
            r"\d+ per minute",
            "速率限制单位应是 per minute",
        )

    def test_extend_view_function_defined(self) -> None:
        self.assertIn(
            "def extend_task_deadline(task_id: str)",
            self.src,
            "必须有 extend_task_deadline 视图函数",
        )

    def test_extend_handles_404_for_unknown_task(self) -> None:
        m = re.search(
            r"def extend_task_deadline.*?(?=def \w|\Z)",
            self.src,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        # cr32 §3.1 fix 之后改走 ``TaskQueue.extend_task_deadline`` facade，
        # task 不存在时 facade 返回 ``error_code == "task_not_found"``，
        # route 据此返回 404。``re.DOTALL`` 让 ``.`` 跨换行；视图函数里
        # ``"task_not_found"`` → ``404`` 之间可能因为换行/缩进而距离很大。
        self.assertRegex(
            body,
            r'"task_not_found"[\s\S]*?404',
            "task 不存在时（facade 返回 task_not_found）必须返回 404",
        )

    def test_extend_handles_422_for_limit_reached(self) -> None:
        m = re.search(
            r"def extend_task_deadline.*?(?=def \w|\Z)",
            self.src,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        self.assertIn(
            "extends_limit_reached",
            body,
            "上限路径必须返回 extends_limit_reached error code",
        )
        self.assertIn(
            "422",
            body,
            "上限路径必须返回 422 状态码（区别于 400 的请求错误）",
        )

    def test_extend_rejects_bool_seconds(self) -> None:
        """bool 是 int 的子类，必须显式排除（防 ``True == 1`` 通过校验）。"""
        m = re.search(
            r"def extend_task_deadline.*?(?=def \w|\Z)",
            self.src,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        # 容忍 Black/ruff 格式化把 ``isinstance(requested_seconds, bool)``
        # 拆成 ``isinstance(\n   requested_seconds,\n   bool)`` 跨行的情况
        self.assertRegex(
            body,
            r"isinstance\(\s*requested_seconds\s*,\s*bool\s*\)",
            "必须显式 isinstance check bool（不能让 True 通过 int 校验）",
        )

    def test_list_tasks_exposes_extends_fields(self) -> None:
        """GET /api/tasks 必须返回 extends_used + extends_max，前端依赖。"""
        m = re.search(
            r'"task_id":\s*task\.task_id,(.*?)\}',
            self.src,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(1)
        self.assertIn(
            '"extends_used": task.extends_used',
            body,
            "GET /api/tasks 响应里必须有 extends_used 字段",
        )
        self.assertIn(
            '"extends_max": COUNTDOWN_EXTENDS_MAX',
            body,
            "GET /api/tasks 响应里必须有 extends_max 字段",
        )


# ============================================================
# C. HTML
# ============================================================
class TestHtmlButton(unittest.TestCase):
    def setUp(self) -> None:
        self.html = WEB_UI_HTML.read_text(encoding="utf-8")

    def test_button_present_in_countdown_container(self) -> None:
        """按钮必须放在 #countdown-container 内部（不能游离）。"""
        m = re.search(
            r'id="countdown-container"(.*?)</div>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 #countdown-container")
        assert m is not None
        self.assertIn(
            'id="countdown-extend-btn"',
            m.group(1),
            "+60s 按钮必须在 #countdown-container 内（视觉上同一控件组）",
        )

    def test_button_has_class_hidden_disabled_initially(self) -> None:
        """初始 hidden + disabled，等 JS hydrate 后才显示。"""
        m = re.search(
            r'id="countdown-extend-btn"([^>]*)>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        attrs = m.group(1)
        self.assertIn("hidden", attrs, "必须初始 .hidden")
        self.assertIn("disabled", attrs, "必须初始 disabled")

    def test_button_has_i18n_attributes(self) -> None:
        m = re.search(
            r'id="countdown-extend-btn"([^>]*)>',
            self.html,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        attrs = m.group(1)
        self.assertIn(
            'data-i18n-title="page.extendCountdown.title"',
            attrs,
        )
        self.assertIn(
            'data-i18n-aria-label="page.extendCountdown.ariaLabel"',
            attrs,
        )


# ============================================================
# D. CSS
# ============================================================
class TestCss(unittest.TestCase):
    def setUp(self) -> None:
        self.css = MAIN_CSS.read_text(encoding="utf-8")

    def test_base_class_defined(self) -> None:
        self.assertIn(".countdown-extend-btn {", self.css)

    def test_hidden_class_defined(self) -> None:
        self.assertIn(".countdown-extend-btn.hidden {", self.css)
        m = re.search(
            r"\.countdown-extend-btn\.hidden\s*\{([^}]+)\}",
            self.css,
        )
        self.assertIsNotNone(m)
        assert m is not None
        self.assertIn("display: none", m.group(1))

    def test_disabled_state_no_pointer(self) -> None:
        m = re.search(
            r"\.countdown-extend-btn:disabled\s*\{([^}]+)\}",
            self.css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "必须定义 :disabled 状态",
        )
        assert m is not None
        self.assertIn(
            "cursor: not-allowed",
            m.group(1),
            ":disabled 必须 cursor: not-allowed (a11y + UX hint)",
        )

    def test_focus_visible_outline_present(self) -> None:
        self.assertRegex(
            self.css,
            r"\.countdown-extend-btn:focus-visible\s*\{[^}]*outline:",
            "必须有 :focus-visible outline (键盘可访问性)",
        )

    def test_light_theme_override_present(self) -> None:
        self.assertRegex(
            self.css,
            r'\[data-theme="light"\]\s+\.countdown-extend-btn\s*\{',
            "必须有浅色主题 override (color contrast)",
        )


# ============================================================
# E. JS
# ============================================================
class TestJsLogic(unittest.TestCase):
    def setUp(self) -> None:
        self.full = MULTI_TASK_JS.read_text(encoding="utf-8")
        self.code = _strip_js_comments(self.full)

    def test_update_function_defined(self) -> None:
        self.assertIn(
            "function updateCountdownExtendButton",
            self.code,
            "必须定义 updateCountdownExtendButton(task)",
        )

    def test_click_handler_defined(self) -> None:
        self.assertIn(
            "function handleExtendCountdownClick",
            self.code,
            "必须定义 handleExtendCountdownClick()",
        )

    def test_update_function_called_in_updateTasksList(self) -> None:
        """updateTasksList 必须在每次任务列表刷新时同步按钮状态。"""
        m = re.search(
            r"function updateTasksList\([^)]+\)\s*\{(.*?)\n\}",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 updateTasksList 函数体")
        assert m is not None
        self.assertIn(
            "updateCountdownExtendButton",
            m.group(1),
            "updateTasksList 必须调用 updateCountdownExtendButton 同步按钮",
        )

    def test_click_handler_posts_to_correct_endpoint(self) -> None:
        m = re.search(
            r"function handleExtendCountdownClick.*?\n\}",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        self.assertIn(
            '"/api/tasks/"',
            body,
            "必须 POST 到 /api/tasks/<id>/extend",
        )
        self.assertIn(
            '"/extend"',
            body,
            "URL 必须以 /extend 结尾",
        )
        self.assertIn(
            '"POST"',
            body,
            "必须用 POST method",
        )

    def test_idempotent_click_binding(self) -> None:
        """重复加载本脚本不应重复绑 click handler。"""
        self.assertIn(
            "__aiiaExtendBtnBound",
            self.code,
            "必须有 window.__aiiaExtendBtnBound 标志做 idempotent binding",
        )

    def test_respects_disabled_state(self) -> None:
        """click handler 必须在 btn.disabled === true 时早 return。"""
        m = re.search(
            r"function handleExtendCountdownClick.*?\n\}",
            self.code,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(0)
        self.assertIn(
            "btn.disabled",
            body,
            "必须检查 btn.disabled 早 return",
        )


# ============================================================
# F. i18n
# ============================================================
class TestI18n(unittest.TestCase):
    REQUIRED_KEYS = ["label", "title", "ariaLabel", "limitReached", "networkError"]

    def _load(self, p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    def test_en_has_all_keys(self) -> None:
        ec = self._load(EN_JSON).get("page", {}).get("extendCountdown")
        self.assertIsInstance(ec, dict, "en.json 必须有 page.extendCountdown")
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, ec, f"en.json 缺 {key}")
            self.assertIsInstance(ec[key], str)
            self.assertGreater(len(ec[key].strip()), 0)

    def test_zh_has_all_keys(self) -> None:
        ec = self._load(ZH_JSON).get("page", {}).get("extendCountdown")
        self.assertIsInstance(ec, dict, "zh-CN.json 必须有 page.extendCountdown")
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, ec, f"zh-CN.json 缺 {key}")
            self.assertIsInstance(ec[key], str)
            self.assertGreater(len(ec[key].strip()), 0)

    def test_zh_distinct_from_en(self) -> None:
        en = self._load(EN_JSON).get("page", {}).get("extendCountdown", {})
        zh = self._load(ZH_JSON).get("page", {}).get("extendCountdown", {})
        for key in self.REQUIRED_KEYS:
            self.assertNotEqual(
                en.get(key),
                zh.get(key),
                f"page.extendCountdown.{key} 中英必须不同（防漏译）",
            )


# ============================================================
# G. 设计锚点
# ============================================================
class TestDesignAnchors(unittest.TestCase):
    def test_task_queue_has_anchor(self) -> None:
        self.assertIn(
            "feat-countdown-extend",
            TASK_QUEUE_PY.read_text(encoding="utf-8"),
            "task_queue.py 必须有 feat-countdown-extend 锚点",
        )

    def test_route_has_anchor(self) -> None:
        self.assertIn(
            "feat-countdown-extend",
            TASK_ROUTE_PY.read_text(encoding="utf-8"),
            "task.py 必须有 feat-countdown-extend 锚点",
        )

    def test_html_has_anchor(self) -> None:
        self.assertIn(
            "feat-countdown-extend",
            WEB_UI_HTML.read_text(encoding="utf-8"),
            "web_ui.html 必须有 feat-countdown-extend 锚点",
        )

    def test_css_has_anchor(self) -> None:
        self.assertIn(
            "feat-countdown-extend",
            MAIN_CSS.read_text(encoding="utf-8"),
            "main.css 必须有 feat-countdown-extend 锚点",
        )

    def test_js_has_anchor(self) -> None:
        self.assertIn(
            "feat-countdown-extend",
            MULTI_TASK_JS.read_text(encoding="utf-8"),
            "multi_task.js 必须有 feat-countdown-extend 锚点",
        )


if __name__ == "__main__":
    unittest.main()
