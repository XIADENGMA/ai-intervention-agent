"""R832: a log line says how long the AI's message, the user's answer or an option was, not what it said.

The project's own convention is already "lengths, not content" (``task.created ... message_len=22``,
``prompt_len: 320`` in ``service_manager``), and ``LogSanitizer`` plus R826 (no variable values in
a traceback) keep secrets out of what a log carries. Five call sites still wrote the first
characters of a text a person typed or an AI wrote into the line, at ``INFO`` or ``WARNING``:

* ``WebFeedbackUI.update_content``: ``内容已更新: <first 50 characters of the prompt>... (task_id: ...)``
  at ``INFO``, in ``web_ui.log`` (on disk, 5 MB) every time the page's content changes;
* ``POST /api/tasks/<id>/submit``: ``任务 <id> 反馈已提交 | ... text[:60]="<first 60 characters of
  the user's own answer>" ua=... referer=...`` at ``INFO``: the answer is the one text the user
  typed for the AI, and it is the one that may hold a password or a token the AI asked for;
* ``interactive_feedback``: ``收到反馈请求: <first 50 characters>... `` and the deprecated
  ``launch_feedback_ui``: ``启动反馈界面: <first 100 characters>... ``: both call ``logger.info``, and
  ``EnhancedLogger`` maps these two phrases to ``DEBUG``, so the text shows up as soon as someone
  turns debug logging on to file an issue, which is when logs get pasted;
* ``validate_input``: ``选项过长被截断: <first 50 characters of the option>...`` at ``WARNING``.

Those lines now carry the length (``prompt_len``, ``text_len``, the option's length) and nothing of
the text; every other part of them is what it was (task id, option and image counts, user agent,
referer, the 10 000-character limit). The phrases the level mapping looks for stay in place, so the
lines keep their effective level.

What this module runs: each call site for real (the Web UI object, the MCP tool with its harness, the
deprecated launcher, the per-task submit route through Flask's test client, ``validate_input``), with every log
call recorded before the logger's level filter and mapping, so a ``DEBUG``-mapped line is seen too;
the level mapping of the three phrases; a scan of the whole package for a slice of a prompt, summary,
message, option or answer (or a ``..._preview`` variable) inside an f-string of a logger call at ``INFO``
or above, with a self-check of the rule.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

import ai_intervention_agent.server_feedback as server
from ai_intervention_agent import server_config
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.server_config import MAX_OPTION_LENGTH, WebUIConfig
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI
from tests.test_notification_off_event_loop_r776 import _Harness
from tests.test_server_functions import _mock_arun_closing

PACKAGE = Path(server.__file__).resolve().parent
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

# The text of each secret starts with a marker, so a cut of its first characters carries it, and
# mixes ASCII, CJK and an emoji, so that a length in bytes would be told apart from one in characters.
PROMPT = "R832-PRIVATE-PROMPT 提示词😀 " + "p" * 300
ANSWER = "R832-PRIVATE-ANSWER the password is hunter2 密码😀 " + "a" * 200
OPTION = "R832-PRIVATE-OPTION 选项😀 " + "o" * (MAX_OPTION_LENGTH + 50)
MARKERS = ("R832-PRIVATE", "hunter2", "提示词", "密码", "选项😀")

Line = tuple[int, str]


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> list[Line]:
    """Every log call of the process, as ``(level, text)``, before the level filter and mapping."""
    seen: list[Line] = []
    lock = threading.Lock()

    def record(
        self: EnhancedLogger, level: int, message: str, *args: Any, **_kwargs: Any
    ) -> None:
        text = EnhancedLogger._render(message, args)
        with lock:
            seen.append((level, text))

    monkeypatch.setattr(EnhancedLogger, "log", record)
    return seen


def _with(lines: list[Line], phrase: str) -> list[Line]:
    return [(level, text) for level, text in lines if phrase in text]


def _assert_nothing_private(lines: list[Line]) -> None:
    assert lines, "nothing was logged: the check would pass for the wrong reason"
    for level, text in lines:
        for marker in MARKERS:
            assert marker not in text, f"{logging.getLevelName(level)}: {text}"


def _the_one(lines: list[Line], phrase: str) -> Line:
    found = _with(lines, phrase)
    assert len(found) == 1, (phrase, [text for _, text in lines])
    return found[0]


# --------------------------------------------------------------------------------------
# A. Each call site, run for real
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r832", task_id="r832-initial", auto_resubmit_timeout=0, port=19832
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    queue = get_task_queue()
    queue.clear_all_tasks()
    queue.add_task(
        task_id="r832-task",
        prompt="p",
        predefined_options=["x"],
        auto_resubmit_timeout=300,
    )
    ui.feedback_result = None
    try:
        yield ui.app.test_client()
    finally:
        queue.clear_all_tasks()


class TestTheWebUiContentUpdate:
    def test_the_line_has_the_length_and_not_the_text(
        self, ui: WebFeedbackUI, lines: list[Line]
    ) -> None:
        ui.update_content(PROMPT, ["a"], "r832-update")
        _assert_nothing_private(lines)
        level, text = _the_one(lines, "内容已更新")
        assert level == logging.INFO
        assert f"prompt_len: {len(PROMPT)}" in text
        assert "task_id: r832-update" in text

    def test_the_content_is_updated_as_before(
        self, ui: WebFeedbackUI, lines: list[Line]
    ) -> None:
        ui.update_content(PROMPT, ["a"], "r832-update")
        assert ui.current_prompt == PROMPT
        assert ui.current_options == ["a"]
        assert ui.current_task_id == "r832-update"
        assert ui.has_content is True

    def test_clearing_the_content_is_still_said_in_words(
        self, ui: WebFeedbackUI, lines: list[Line]
    ) -> None:
        ui.update_content("")
        assert [text for _, text in lines] == ["内容已清空，显示无有效内容页面"]


class TestTheSubmitRoute:
    def _submit(self, client: FlaskClient, text: str = ANSWER) -> Any:
        return client.post(
            "/api/tasks/r832-task/submit",
            data={"feedback_text": text, "selected_options": '["x"]'},
            environ_base=LOOPBACK,
        )

    def test_the_line_has_the_length_and_not_the_answer(
        self, client: FlaskClient, lines: list[Line]
    ) -> None:
        assert self._submit(client).status_code == 200
        level, text = _the_one(lines, "反馈已提交")
        assert level == logging.INFO
        assert f"text_len={len(ANSWER)}" in text
        for marker in MARKERS:
            assert marker not in text, text

    def test_nothing_the_route_logs_has_the_answer(
        self, client: FlaskClient, lines: list[Line]
    ) -> None:
        self._submit(client)
        _assert_nothing_private(lines)

    def test_the_rest_of_the_line_is_what_it_was(
        self, client: FlaskClient, lines: list[Line]
    ) -> None:
        self._submit(client)
        _, text = _the_one(lines, "反馈已提交")
        assert text.startswith("任务 r832-task 反馈已提交 | ")
        assert "opts=1 imgs=0 " in text
        assert ' ua="' in text
        assert ' referer="' in text

    def test_the_answer_still_reaches_the_task(
        self, client: FlaskClient, lines: list[Line]
    ) -> None:
        assert self._submit(client).get_json()["success"] is True
        task = get_task_queue().get_task("r832-task")
        assert task is not None and task.result is not None
        assert task.result["user_input"] == ANSWER
        assert task.result["selected_options"] == ["x"]

    def test_an_empty_answer_has_length_zero(
        self, client: FlaskClient, lines: list[Line]
    ) -> None:
        self._submit(client, "")
        _, text = _the_one(lines, "反馈已提交")
        assert "text_len=0" in text


class TestTheMcpTool:
    def _ask(self, monkeypatch: pytest.MonkeyPatch, message: str) -> None:
        _Harness(monkeypatch)  # patches the Web UI, the notifier and the task id

        async def go() -> None:
            await server.interactive_feedback(
                message=message,
                predefined_options=None,
                feedback_placeholder=None,
                header_label=None,
                loop_id=None,
                loop_objective=None,
                loop_phase=None,
                success_criteria=None,
                iteration_label=None,
                ctx=None,
            )

        asyncio.run(go())

    def test_the_line_has_the_length_and_not_the_text(
        self, monkeypatch: pytest.MonkeyPatch, lines: list[Line]
    ) -> None:
        self._ask(monkeypatch, PROMPT)
        _assert_nothing_private(lines)
        _, text = _the_one(lines, "收到反馈请求")
        assert f"prompt_len={len(PROMPT)}" in text
        assert "(自动生成task_id: " in text

    def test_the_diagnostic_event_is_untouched(
        self, monkeypatch: pytest.MonkeyPatch, lines: list[Line]
    ) -> None:
        self._ask(monkeypatch, PROMPT)
        created = _with(lines, "event=task.created")
        assert created and f"message_len={len(PROMPT)}" in created[0][1]


class TestTheDeprecatedLauncher:
    def _launch(self, summary: str) -> dict[str, Any]:
        notifier = MagicMock()
        notifier.send_notification.return_value = "event-1"
        response = MagicMock()
        response.status_code = 200
        http = MagicMock()
        http.post.return_value = response
        config = WebUIConfig(host="127.0.0.1", port=18998)
        with (
            patch.object(server, "NOTIFICATION_AVAILABLE", True),
            patch.object(server, "notification_manager", notifier),
            patch.object(
                server.service_manager, "get_web_ui_config", return_value=(config, 120)
            ),
            patch.object(server.service_manager, "get_sync_client", return_value=http),
            patch.object(
                server.server_config, "_generate_task_id", return_value="task-r832"
            ),
            patch.object(
                server.asyncio,
                "run",
                side_effect=_mock_arun_closing(
                    None, {"user_input": "done", "selected_options": []}
                ),
            ),
        ):
            return server.launch_feedback_ui(summary)

    def test_the_line_has_the_length_and_not_the_text(self, lines: list[Line]) -> None:
        result = self._launch(PROMPT)
        assert result["user_input"] == "done"
        _assert_nothing_private(lines)
        _, text = _the_one(lines, "启动反馈界面")
        assert f"prompt_len={len(PROMPT)}" in text
        assert "(自动生成task_id: task-r832)" in text


class TestAnOptionThatIsTooLong:
    def test_the_warning_has_the_length_and_not_the_text(
        self, lines: list[Line]
    ) -> None:
        cleaned_prompt, cleaned_options = server_config.validate_input(
            "hello", [OPTION]
        )
        _assert_nothing_private(lines)
        level, text = _the_one(lines, "选项过长")
        assert level == logging.WARNING
        assert f"{len(OPTION)} 字符" in text
        assert f"{MAX_OPTION_LENGTH}" in text
        assert cleaned_prompt == "hello"

    def test_the_option_is_cut_as_before(self, lines: list[Line]) -> None:
        _, cleaned_options = server_config.validate_input("hello", [OPTION])
        assert cleaned_options == [OPTION[:MAX_OPTION_LENGTH] + "..."]

    def test_an_option_within_the_limit_logs_nothing(self, lines: list[Line]) -> None:
        _, cleaned_options = server_config.validate_input("hello", ["short"])
        assert cleaned_options == ["short"]
        assert lines == []


# --------------------------------------------------------------------------------------
# B. The phrases the level mapping looks for are still there
# --------------------------------------------------------------------------------------


class TestTheLinesKeepTheirLevel:
    """``EnhancedLogger`` maps three of the phrases to a level of its own, whatever level the call asks for."""

    def test_the_mapping_still_recognises_the_three_lines(
        self,
        ui: WebFeedbackUI,
        monkeypatch: pytest.MonkeyPatch,
        lines: list[Line],
    ) -> None:
        ui.update_content(PROMPT, [], "r832-update")
        TestTheMcpTool()._ask(monkeypatch, PROMPT)
        TestTheDeprecatedLauncher()._launch(PROMPT)
        logger = EnhancedLogger("r832.mapping")
        expected = {
            "内容已更新": logging.INFO,
            "收到反馈请求": logging.DEBUG,
            "启动反馈界面": logging.DEBUG,
        }
        for phrase, level in expected.items():
            _, text = _the_one(lines, phrase)
            assert logger._get_effective_level(text, logging.INFO) == level, text


# --------------------------------------------------------------------------------------
# C. No logger call at INFO or above cuts a prefix off a text a person wrote
# --------------------------------------------------------------------------------------

LOG_METHODS = {"info", "warning", "error", "critical", "exception"}
LOGGER_NAMES = {"logger", "log", "_logger"}
PRIVATE_NAME = re.compile(
    r"prompt|summary|message|option|feedback|user_input|answer", re.I
)


def _is_logger(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in LOGGER_NAMES
    return isinstance(node, ast.Attribute) and node.attr in LOGGER_NAMES


def _is_cut_of_private_text(value: ast.expr) -> bool:
    """``prompt[:50]``, ``answer[-20:]``, ``message[10:40]``: part of a text, not its length."""
    return (
        isinstance(value, ast.Subscript)
        and isinstance(value.slice, ast.Slice)
        and PRIVATE_NAME.search(ast.unparse(value.value)) is not None
    )


def _is_preview_variable(value: ast.expr) -> bool:
    return isinstance(value, ast.Name) and "preview" in value.id.lower()


def _cuts_in_logger_calls(tree: ast.AST) -> tuple[int, list[tuple[int, str]]]:
    """``(logger calls at INFO or above, [(line, source of the offending value)])``."""
    calls = 0
    flagged: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOG_METHODS
            and _is_logger(node.func.value)
        ):
            continue
        calls += 1
        for part in ast.walk(node):
            if isinstance(part, ast.FormattedValue) and (
                _is_cut_of_private_text(part.value) or _is_preview_variable(part.value)
            ):
                flagged.append((node.lineno, ast.unparse(part.value)))
    return calls, flagged


class TestNoLoggerCallCutsAPrefixOffAText:
    def test_the_package(self) -> None:
        total = 0
        found: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            calls, flagged = _cuts_in_logger_calls(ast.parse(path.read_text("utf-8")))
            total += calls
            found.extend(
                f"{path.relative_to(PACKAGE)}:{line}: {source}"
                for line, source in flagged
            )
        assert total > 100, (
            f"the scan saw only {total} logger calls: it is not scanning"
        )
        assert found == []

    @pytest.mark.parametrize(
        "source",
        [
            'logger.info(f"updated: {new_prompt[:50]}...")',
            'logger.warning(f"too long: {cleaned_option[:50]}...")',
            'logger.info(f"start: {cleaned_summary[:100]}")',
            'logger.error(f"got {user_message[:20]}")',
            'self.logger.info(f"answer {feedback_text[:60]}")',
            'logger.info(f"sent {_preview}")',
            'logger.critical(f"sent {text_preview}")',
            'logger.info(f"tail {new_prompt[-50:]}")',
            'logger.warning(f"middle {cleaned_option[10:40]}")',
        ],
    )
    def test_the_rule_flags_the_old_patterns(self, source: str) -> None:
        _, flagged = _cuts_in_logger_calls(ast.parse(source))
        assert len(flagged) == 1, source

    @pytest.mark.parametrize(
        "source",
        [
            'logger.info(f"updated: {len(new_prompt)}")',
            'logger.error(f"server said {err_text[:500]}")',
            'logger.info(f"body {response.text[:200]}")',
            'logger.info(f"agent {user_agent[:80]}")',
            'logger.debug(f"final {item.text[:100]}")',
            'print(f"{new_prompt[:50]}")',
            'other.info(f"{new_prompt[:50]}")',
            'logger.info(f"first {names[0]} of {len(new_prompt)} in {options[1]}")',
        ],
    )
    def test_the_rule_leaves_the_rest_alone(self, source: str) -> None:
        _, flagged = _cuts_in_logger_calls(ast.parse(source))
        assert flagged == [], source
