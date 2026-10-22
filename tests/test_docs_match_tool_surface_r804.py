"""R804: the docs describe the tool and the HTTP API the server really has.

``docs/mcp_tools.md`` (and zh-CN) documented a per-call ``auto_resubmit_timeout``
parameter of ``interactive_feedback`` and ended with a complete example that passes it.
``docs/architecture.md`` (and zh-CN) drew it into two sequence diagrams and the
parameter table.  The tool has no such parameter and its schema is strict
(``additionalProperties: false``), so an agent that copied the documented example got
``MCPError: Unexpected keyword argument`` and *no task at all* (measured through the
real stdio server).  The same diagrams named two endpoints that do not exist
(``POST /api/tasks/{id}/complete``, ``POST /api/tasks/{id}/auto-resubmit``), called the
SSE event ``task.created`` (it is ``task_changed``; ``task.created`` is a ``ctx.info``
label) and polled "every 5 s" (2 s, backing off to 30 s).  The ``feedback_placeholder``
description promised ``placeholder_truncated`` "in the response", but the MCP tool result
never carries it - only the internal ``POST /api/tasks`` reply does.

Why the existing guards let it through:

* R287 checked "the documented parameter exists in the source" with
  ``__code__.co_varnames``, which also lists *local variables*, and
  ``interactive_feedback`` has a local called ``auto_resubmit_timeout``;
* R288 / R311 pinned the *shape* of the diagrams (participants, three notes, keywords)
  and used ``assertIn(name, whole_section)``, never the endpoints or parameters.

These tests compare the docs with the running thing: the live tool schema
(``tools/list``) and the live Flask URL map.  Every guard has a self-test on a
synthetic document, so a scanner that silently stops matching cannot go green.
"""

from __future__ import annotations

import ast
import asyncio
import os
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ai_intervention_agent.server import mcp
from ai_intervention_agent.web_ui import WebFeedbackUI

REPO = Path(__file__).resolve().parent.parent

_PRUNED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
}

# Generated, historical or private files: they quote old states on purpose.
_NOT_USER_FACING = (
    "CHANGELOG.md",
    "packages/vscode/CHANGELOG.md",
    "TODO.md",
    "docs/api/",
    "docs/api.zh-CN/",
    "docs/code-reviews/",
    "docs/a11y-audit-",
    "docs/feature-mining-",
    "docs/perf-",
    "docs/lessons-learned-",
    "docs/methodology-evolution",
    "docs/contributor-guide-",
    "docs/zhconv-eval",
    "docs/loop-engineering-design-notes",
)

MCP_TOOLS_DOCS = ("docs/mcp_tools.md", "docs/mcp_tools.zh-CN.md")
ARCHITECTURE_DOCS = ("docs/architecture.md", "docs/architecture.zh-CN.md")

# What every reader needs to find in the parameter list of ``interactive_feedback``.
DOCUMENTED_AS_BULLETS = {
    "message",
    "predefined_options",
    "header_label",
    "feedback_placeholder",
    "loop_id",
    "loop_objective",
    "loop_phase",
    "success_criteria",
    "iteration_label",
}

MAX_CALL_CHARS = 8000


def _user_facing_markdown() -> list[Path]:
    found: list[Path] = []
    for base, dirs, files in os.walk(REPO):
        dirs[:] = [name for name in dirs if name not in _PRUNED_DIRS]
        for name in files:
            if not name.endswith(".md"):
                continue
            path = Path(base) / name
            if path.relative_to(REPO).as_posix().startswith(_NOT_USER_FACING):
                continue
            found.append(path)
    return sorted(found)


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


# --------------------------------------------------------------------------- calls


_CALL = re.compile(r"interactive_feedback(?:<br\s*/?>)?\(")
_KEYWORD = re.compile(r"\s*([A-Za-z_]\w*)\s*=(?!=)\s*(.*)", re.DOTALL)
_STRING = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")
_JSON_WORDS = {"true": "True", "false": "False", "null": "None"}


def _scan_call(text: str, open_index: int) -> str | None:
    """The parenthesised argument list that starts at ``text[open_index]``."""
    depth = 0
    quote = ""
    index = open_index
    stop = min(len(text), open_index + MAX_CALL_CHARS)
    while index < stop:
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char == "#":
            newline = text.find("\n", index)
            index = stop if newline == -1 else newline
            continue
        elif char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_index : index + 1]
        index += 1
    return None


def _top_level_segments(inner: str) -> list[str]:
    segments: list[str] = []
    buffer: list[str] = []
    depth = 0
    quote = ""
    index = 0
    while index < len(inner):
        char = inner[index]
        if quote:
            buffer.append(char)
            if char == "\\" and index + 1 < len(inner):
                buffer.append(inner[index + 1])
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char == "#":
            newline = inner.find("\n", index)
            index = len(inner) if newline == -1 else newline
            continue
        elif char in "\"'":
            quote = char
            buffer.append(char)
        elif char in "([{":
            depth += 1
            buffer.append(char)
        elif char in ")]}":
            depth -= 1
            buffer.append(char)
        elif char == "," and depth == 0:
            segments.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
        index += 1
    segments.append("".join(buffer))
    return segments


def _keyword_arguments(call: str) -> dict[str, str]:
    """``name -> source text of its value`` for every ``name=value`` argument."""
    inner = re.sub(r"<br\s*/?>", " ", call)[1:-1]
    found: dict[str, str] = {}
    for segment in _top_level_segments(inner):
        match = _KEYWORD.fullmatch(segment)
        if match:
            found[match.group(1)] = match.group(2).strip()
    return found


def _python_literal(source: str) -> tuple[bool, Any]:
    """Evaluate a documented value; JSON spellings (``true``/``null``) are accepted."""

    def words(chunk: str) -> str:
        return re.sub(
            r"\b(true|false|null)\b", lambda hit: _JSON_WORDS[hit.group(1)], chunk
        )

    pieces: list[str] = []
    last = 0
    for string in _STRING.finditer(source):
        pieces.append(words(source[last : string.start()]))
        pieces.append(string.group(0))
        last = string.end()
    pieces.append(words(source[last:]))
    try:
        value = ast.literal_eval("".join(pieces).strip())
    except (ValueError, SyntaxError):
        return False, None
    if value is Ellipsis:
        return False, None
    return True, value


def _documented_calls() -> list[tuple[str, int, str | None]]:
    found: list[tuple[str, int, str | None]] = []
    for path in _user_facing_markdown():
        text = path.read_text(encoding="utf-8")
        for match in _CALL.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append((_rel(path), line, _scan_call(text, match.end() - 1)))
    return found


# --------------------------------------------------------------------- doc sections


def _tool_section(text: str) -> str:
    """Everything under ``### `interactive_feedback` `` up to the next h3."""
    start = text.index("### `interactive_feedback`")
    following = re.search(r"^### ", text[start + 4 :], re.MULTILINE)
    return (
        text[start:]
        if following is None
        else text[start : start + 4 + following.start()]
    )


_PARAMETER_BULLET = re.compile(r"^- `([a-z_][a-z0-9_]*)`\s*[（(]", re.MULTILINE)


def _architecture_parameter_rows(text: str) -> list[list[str]]:
    """Backticked identifiers of the first cell of each row of the agent-side table."""
    start = re.search(
        r"^### (?:Agent-side parameters|Agent 端参数)", text, re.MULTILINE
    )
    assert start is not None, "the agent-side parameter table moved"
    following = re.search(r"^### ", text[start.end() :], re.MULTILINE)
    section = (
        text[start.start() :]
        if following is None
        else text[start.start() : start.end() + following.start()]
    )
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        first_cell = line.strip().strip("|").split("|")[0]
        names = re.findall(r"`([a-z_][a-z0-9_]*)`", first_cell)
        if names:
            rows.append(names)
    return rows


# ------------------------------------------------------------------------ endpoints


_ENDPOINT = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\s+`?(/api/[A-Za-z0-9_\-./{}<>:]+)"
)


def _documented_endpoints(text: str) -> list[tuple[int, str, str]]:
    text = re.sub(r"<br\s*/?>", " ", text)
    found: list[tuple[int, str, str]] = []
    for match in _ENDPOINT.finditer(text):
        path = match.group(2).rstrip(".,;:)]`")
        path = re.sub(r"\{[^}]*\}|<[^>]*>", "X", path).rstrip("/")
        line = text.count("\n", 0, match.start()) + 1
        found.append((line, match.group(1), path))
    return found


def _route_table(ui: WebFeedbackUI) -> list[tuple[re.Pattern[str], set[str]]]:
    table = []
    for rule in ui.app.url_map.iter_rules():
        parts = re.split(r"(<[^>]+>)", rule.rule)
        pattern = "".join(
            "[^/]+" if part.startswith("<") else re.escape(part) for part in parts
        )
        table.append(
            (re.compile(pattern), set(rule.methods or ()) - {"HEAD", "OPTIONS"})
        )
    return table


def _is_a_route(
    table: list[tuple[re.Pattern[str], set[str]]], method: str, path: str
) -> bool:
    return any(
        method in methods and pattern.fullmatch(path) for pattern, methods in table
    )


# ---------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def tool_schema() -> dict[str, Any]:
    tool = asyncio.run(mcp.get_tool("interactive_feedback"))
    assert tool is not None, "interactive_feedback is not registered on the server"
    return tool.parameters


@pytest.fixture(scope="module")
def route_table() -> list[tuple[re.Pattern[str], set[str]]]:
    return _route_table(WebFeedbackUI(prompt="r804", port=19804))


# ------------------------------------------------------------------ scanner self-tests


class TestTheScannersCannotGoSilentlyBlind:
    """Synthetic documents: each scanner finds what R804 found, and nothing else."""

    def test_a_call_with_comments_and_nested_values_is_parsed(self) -> None:
        text = (
            "intro\ninteractive_feedback(\n"
            '  message=("a (b" "c"),  # a comment with ( and \' in it\n'
            '  predefined_options=[{"label": "x", "default": true}],\n'
            "  auto_resubmit_timeout=120,\n)\ntrailer"
        )
        call = _scan_call(text, text.index("("))
        assert call is not None and call.endswith(")")
        arguments = _keyword_arguments(call)
        assert list(arguments) == [
            "message",
            "predefined_options",
            "auto_resubmit_timeout",
        ]
        assert _python_literal(arguments["message"]) == (True, "a (bc")
        assert _python_literal(arguments["predefined_options"]) == (
            True,
            [{"label": "x", "default": True}],
        )
        assert _python_literal(arguments["auto_resubmit_timeout"]) == (True, 120)

    def test_a_diagram_label_is_a_call_too(self) -> None:
        label = "Agent->>AIIA: interactive_feedback<br/>(auto_resubmit_timeout=120)"
        match = _CALL.search(label)
        assert match is not None
        call = _scan_call(label, match.end() - 1)
        assert call is not None
        assert _keyword_arguments(call) == {"auto_resubmit_timeout": "120"}

    def test_positional_names_and_ellipsis_are_not_keyword_arguments(self) -> None:
        call = "(message,<br/>header_label, predefined_options, ...)"
        assert _keyword_arguments(call) == {}
        assert _python_literal("...") == (False, None)

    def test_an_unclosed_call_is_reported_not_skipped(self) -> None:
        text = 'interactive_feedback(message="never closes'
        assert _scan_call(text, text.index("(")) is None

    def test_endpoint_scanner_reads_placeholders_and_trailing_punctuation(self) -> None:
        text = (
            "UI->>AIIA: POST /api/tasks/{id}/auto-resubmit\n"
            "see `GET /api/tasks/<task_id>`, then POST /api/tasks/{id}/submit.\n"
            "the /api/index.md link has no method\n"
            "UI->>AIIA: POST /api/tasks/{id}/submit<br/>(typed text)"
        )
        assert _documented_endpoints(text) == [
            (1, "POST", "/api/tasks/X/auto-resubmit"),
            (2, "GET", "/api/tasks/X"),
            (2, "POST", "/api/tasks/X/submit"),
            (4, "POST", "/api/tasks/X/submit"),
        ]

    def test_route_matching_checks_the_method_as_well_as_the_path(
        self, route_table: list[tuple[re.Pattern[str], set[str]]]
    ) -> None:
        assert _is_a_route(route_table, "POST", "/api/tasks/X/submit")
        assert _is_a_route(route_table, "GET", "/api/tasks/X")
        assert not _is_a_route(route_table, "POST", "/api/tasks/X/auto-resubmit")
        assert not _is_a_route(route_table, "POST", "/api/tasks/X/complete")
        assert not _is_a_route(route_table, "GET", "/api/tasks/X/submit")

    def test_architecture_table_parser_reads_the_first_cell_only(self) -> None:
        text = (
            "### Agent-side parameters (LLM passes these via MCP)\n\n"
            "| Parameter | Purpose |\n|---|---|\n"
            "| `header_label` | mentions `nothing_else` |\n"
            "| `loop_id` + 4 loop fields | group |\n\n### next\n"
        )
        assert _architecture_parameter_rows(text) == [["header_label"], ["loop_id"]]


# ----------------------------------------------------------------- the tool's own schema


class TestToolSchemaIsStrict:
    """The premise of the whole module: an unknown argument is an error, not ignored."""

    def test_schema_rejects_arguments_it_does_not_list(
        self, tool_schema: dict[str, Any]
    ) -> None:
        assert tool_schema.get("additionalProperties") is False
        assert "auto_resubmit_timeout" not in tool_schema["properties"]
        validator = jsonschema.validators.validator_for(tool_schema)(tool_schema)
        assert list(validator.iter_errors({"message": "hi"})) == []
        errors = list(
            validator.iter_errors({"message": "hi", "auto_resubmit_timeout": 120})
        )
        assert errors, "the documented example would have been accepted"


# ------------------------------------------------------------------ calls in the docs


class TestEveryDocumentedCallWorks:
    def test_the_scan_finds_the_examples_it_should(self) -> None:
        calls = _documented_calls()
        assert len(calls) >= 8, f"only {len(calls)} calls found - did the docs move?"
        unclosed = [(rel, line) for rel, line, call in calls if call is None]
        assert not unclosed, f"calls whose parentheses never close: {unclosed}"
        names = {
            name
            for _, _, call in calls
            if call is not None
            for name in _keyword_arguments(call)
        }
        assert {"message", "predefined_options", "header_label"} <= names
        assert {rel for rel, _, _ in calls} >= set(MCP_TOOLS_DOCS + ARCHITECTURE_DOCS)

    def test_calls_name_only_parameters_the_tool_has(
        self, tool_schema: dict[str, Any]
    ) -> None:
        known = set(tool_schema["properties"])
        unknown = [
            f"{rel}:{line}: {name}"
            for rel, line, call in _documented_calls()
            if call is not None
            for name in _keyword_arguments(call)
            if name not in known
        ]
        assert not unknown, (
            "documented calls pass arguments the strict schema rejects "
            f"(the agent gets a validation error and no task): {unknown}"
        )

    def test_calls_validate_against_the_tools_json_schema(
        self, tool_schema: dict[str, Any]
    ) -> None:
        validator = jsonschema.validators.validator_for(tool_schema)(tool_schema)
        checked = 0
        problems: list[str] = []
        for rel, line, call in _documented_calls():
            if call is None:
                continue
            arguments = {}
            for name, source in _keyword_arguments(call).items():
                parsed, value = _python_literal(source)
                if parsed:
                    arguments[name] = value
            if not arguments:
                continue
            checked += 1
            problems += [
                f"{rel}:{line}: {error.message[:160]}"
                for error in validator.iter_errors(arguments)
            ]
        assert checked >= 5, f"only {checked} calls had literal arguments"
        assert not problems, problems


# -------------------------------------------------------------- parameters in the docs


class TestParameterReferenceMatchesTheSchema:
    @pytest.mark.parametrize("doc", MCP_TOOLS_DOCS)
    def test_bullets_name_real_parameters(
        self, doc: str, tool_schema: dict[str, Any]
    ) -> None:
        section = _tool_section((REPO / doc).read_text(encoding="utf-8"))
        bullets = set(_PARAMETER_BULLET.findall(section))
        assert bullets >= DOCUMENTED_AS_BULLETS, (
            f"{doc}: parameter bullets missing {sorted(DOCUMENTED_AS_BULLETS - bullets)}"
        )
        invented = bullets - set(tool_schema["properties"])
        assert not invented, (
            f"{doc} documents parameters the tool does not have: {sorted(invented)}"
        )

    @pytest.mark.parametrize("doc", MCP_TOOLS_DOCS)
    def test_every_parameter_of_the_tool_is_mentioned(
        self, doc: str, tool_schema: dict[str, Any]
    ) -> None:
        section = _tool_section((REPO / doc).read_text(encoding="utf-8"))
        missing = [
            name for name in tool_schema["properties"] if f"`{name}`" not in section
        ]
        assert not missing, (
            f"{doc}: parameters the schema accepts but the reference never "
            f"mentions: {missing} (a name outside the schema is a hard error, so "
            "the accepted ones must be listed - compatibility aliases included)"
        )

    @pytest.mark.parametrize("doc", ARCHITECTURE_DOCS)
    def test_architecture_table_lists_each_real_parameter_once(
        self, doc: str, tool_schema: dict[str, Any]
    ) -> None:
        rows = _architecture_parameter_rows((REPO / doc).read_text(encoding="utf-8"))
        names = [name for row in rows for name in row]
        assert {"header_label", "predefined_options", "feedback_placeholder"} <= set(
            names
        )
        assert not set(names) - set(tool_schema["properties"]), (
            f"{doc}: table rows for parameters the tool does not have: "
            f"{sorted(set(names) - set(tool_schema['properties']))}"
        )
        duplicated = sorted({name for name in names if names.count(name) > 1})
        assert not duplicated, f"{doc}: parameter listed twice: {duplicated}"

    @pytest.mark.parametrize(
        ("doc", "heading"),
        [
            ("docs/mcp_tools.md", r"#### Agent-mode parameters"),
            ("docs/mcp_tools.zh-CN.md", r"#### Agent 模式专用参数"),
        ],
    )
    def test_the_countdown_is_documented_as_global_configuration(
        self, doc: str, heading: str
    ) -> None:
        """No per-call countdown: the agent-mode section names the global setting and why."""
        text = (REPO / doc).read_text(encoding="utf-8")
        match = re.search(heading + r".*?(?=^#### )", text, re.MULTILINE | re.DOTALL)
        assert match is not None, f"{doc}: agent-mode section not found"
        assert "feedback.frontend_countdown" in match.group(0), doc
        assert "additionalProperties" in match.group(0), doc

    @pytest.mark.parametrize("doc", ARCHITECTURE_DOCS)
    def test_diagrams_do_not_show_the_countdown_as_an_argument(self, doc: str) -> None:
        text = (REPO / doc).read_text(encoding="utf-8")
        assert "auto_resubmit_timeout" not in text, (
            f"{doc} shows the countdown as something the agent passes"
        )

    def test_placeholder_truncation_is_not_promised_in_the_tool_result(
        self, tool_schema: dict[str, Any]
    ) -> None:
        """Only ``POST /api/tasks`` reports ``placeholder_truncated``; the MCP result never does."""
        description = tool_schema["properties"]["feedback_placeholder"]["description"]
        assert "placeholder_truncated" not in description
        for doc in MCP_TOOLS_DOCS:
            section = _tool_section((REPO / doc).read_text(encoding="utf-8"))
            assert "placeholder_truncated" not in section, doc


# ------------------------------------------------------------------ endpoints in docs


class TestEveryDocumentedEndpointExists:
    def test_the_scan_finds_the_endpoints_it_should(self) -> None:
        endpoints = [
            (_rel(path), line, method, route)
            for path in _user_facing_markdown()
            for line, method, route in _documented_endpoints(
                path.read_text(encoding="utf-8")
            )
        ]
        assert len(endpoints) >= 20, f"only {len(endpoints)} endpoints found"
        files = {rel for rel, *_ in endpoints}
        assert set(ARCHITECTURE_DOCS) <= files

    def test_method_and_path_match_a_real_route(
        self, route_table: list[tuple[re.Pattern[str], set[str]]]
    ) -> None:
        missing = [
            f"{_rel(path)}:{line}: {method} {route}"
            for path in _user_facing_markdown()
            for line, method, route in _documented_endpoints(
                path.read_text(encoding="utf-8")
            )
            if not _is_a_route(route_table, method, route)
        ]
        assert not missing, (
            "documented endpoints no route answers (GET/POST pairs are checked "
            f"against the live URL map): {missing}"
        )

    def test_diagrams_name_the_real_sse_event(self) -> None:
        """``task.created`` / ``task.completed`` are ``ctx.info`` labels, not SSE events."""
        for doc in ARCHITECTURE_DOCS:
            text = (REPO / doc).read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if "SSE task." in line:
                    pytest.fail(f"{doc}:{line_no} calls an SSE event {line.strip()!r}")
            assert "task_changed" in text, f"{doc} never names the SSE event"

    def test_diagrams_do_not_claim_a_five_second_poll(self) -> None:
        """The browser poll starts at 2 s and backs off to 30 s (``TASKS_POLL_*_MS``)."""
        for doc in ARCHITECTURE_DOCS:
            text = (REPO / doc).read_text(encoding="utf-8")
            assert not re.search(r"every 5\s?s|每 5\s?s", text), doc
