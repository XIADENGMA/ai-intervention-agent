"""R873: the tool definition tells the model how to use the tool, not how the server is built.

FastMCP serves the docstring of ``interactive_feedback`` as the tool description and every
``Field(description=...)`` as the description of a parameter, and an MCP client puts the whole
definition in front of the model on every request it makes.  The docstring had grown three
maintainer notes the model cannot use: a line about which module registers the tool, and two
paragraphs of Chinese about a lazy ``import httpx`` (R25.2) and the ``ctx`` argument (R44) that
named a private helper and the test runner.  Four parameter texts also ended in the note of the
round or the research cycle that added them (``R166``, ``R167``, ``mining-cycle-3 §2.1``).
That is about 1.2 KB of every request spent on text that cannot help the model, in the middle of
the one English description it reads.

This module reads the definition the way a client receives it (``tool.to_mcp_tool()``) and holds
every description in it to four rules: English prose, no development-tracking id, no source file
of this package, no private helper.  The maintainer notes live in comments inside the function
body, where they are still next to the code they explain.

The title (``Interactive Feedback (人机协作反馈)``) is for the person looking at the client's
tool list, not for the model, so only ``description`` texts are held to the rules.
"""

from __future__ import annotations

import asyncio
import pkgutil
import re
from typing import Any

import pytest

import ai_intervention_agent
from ai_intervention_agent.server import mcp

TOOL = "interactive_feedback"

# Kana, CJK symbols and punctuation, the ideographs and their extension A, Hangul, full-width
# forms: what the maintainers' notes are written in.  The em dash and curly quotes of English
# prose are not in these ranges.
CJK_RUN = re.compile(
    "[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]+"
)

# ``R166``, ``R25.2``: the round that added the text.  One digit (``R2``) is left alone.
ROUND_ID = re.compile(r"\bR\d{2,4}(?:\.\d+)?\b")
# The research cycle a feature was borrowed in (``mining-cycle-3 §2.1``).  The section sign alone
# is not a mark of it: a text may point at ``RFC 9110 §15``.
CYCLE_NOTE = re.compile(r"mining-cycle")
# ``_emit_ctx_info``: a private helper, a snake_case name with a leading underscore.  Markdown
# emphasis (``_sparingly_``, ``_two_words_``), a single word (``_meta``), ``__init__`` and
# ``obj._private_attr`` are not it.
PRIVATE_NAME = re.compile(r"(?<![\w.])_[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?!\w)")
# ``server.py``, ``web_ui.py``: only this package's own modules, so an example path such as
# ``auth/session.py`` in a parameter text stays legal.  ``mcp.tool`` is how ``server.py``
# registers the function.
PACKAGE_MODULES = "|".join(
    re.escape(module.name)
    for module in pkgutil.iter_modules(ai_intervention_agent.__path__)
)
PACKAGE_FILE = re.compile(rf"\b(?:{PACKAGE_MODULES})\.py\b|\bmcp\.tool\b")

RULES: dict[str, re.Pattern[str]] = {
    "not English": CJK_RUN,
    "development-tracking id": re.compile(f"{ROUND_ID.pattern}|{CYCLE_NOTE.pattern}"),
    "the server's own source": re.compile(
        f"{PACKAGE_FILE.pattern}|{PRIVATE_NAME.pattern}"
    ),
}


def leaks(text: str, rule: str) -> list[str]:
    """What in ``text`` breaks ``rule`` (a key of ``RULES``), as short snippets."""
    return [match.group(0) for match in RULES[rule].finditer(text)]


def descriptions(node: Any, path: str = "") -> dict[str, str]:
    """Every ``description`` text under ``node``, keyed by where it is.

    A parameter that is itself named ``description`` is a dict, not a text, so it is walked into
    rather than taken for the text of its parent.
    """
    found: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if key == "description" and isinstance(value, str):
                found[here] = value
            else:
                found.update(descriptions(value, here))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.update(descriptions(value, f"{path}[{index}]"))
    return found


def offenders(texts: dict[str, str], rule: str) -> dict[str, list[str]]:
    return {
        label: found for label, text in texts.items() if (found := leaks(text, rule))
    }


def undescribed(definition: dict[str, Any]) -> list[str]:
    """The tool (as ``"(the tool)"``) and each parameter that has no description text."""
    texts = descriptions(definition)
    missing = [] if texts.get("description", "").strip() else ["(the tool)"]
    for name in definition["inputSchema"]["properties"]:
        label = f"inputSchema.properties.{name}.description"
        if not texts.get(label, "").strip():
            missing.append(name)
    return missing


@pytest.fixture(scope="module")
def definition() -> dict[str, Any]:
    tool = asyncio.run(mcp.get_tool(TOOL))
    assert tool is not None, "interactive_feedback is not registered on the server"
    return tool.to_mcp_tool().model_dump(mode="json", exclude_none=True, by_alias=True)


class TestTheDefinitionAsAClientReceivesIt:
    def test_the_tool_and_every_parameter_have_a_description(
        self, definition: dict[str, Any]
    ) -> None:
        assert undescribed(definition) == []

    def test_nothing_in_it_is_written_in_the_maintainers_language(
        self, definition: dict[str, Any]
    ) -> None:
        found = offenders(descriptions(definition), "not English")

        assert not found, f"text for the model in another language: {found}"

    def test_nothing_in_it_names_a_development_tracking_id(
        self, definition: dict[str, Any]
    ) -> None:
        found = offenders(descriptions(definition), "development-tracking id")

        assert not found, f"round / cycle notes in the text for the model: {found}"

    def test_nothing_in_it_names_the_servers_own_source(
        self, definition: dict[str, Any]
    ) -> None:
        found = offenders(descriptions(definition), "the server's own source")

        assert not found, f"source references in the text for the model: {found}"


class TestTheRulesCannotGoSilentlyBlind:
    """Synthetic texts: each rule finds what R873 found, and nothing an English description needs."""

    def test_chinese_prose_is_found_as_runs(self) -> None:
        text = "Ask the user. 函数体首行 import httpx 让下面（运行时）解析符号。"

        assert leaks(text, "not English") == [
            "函数体首行",
            "让下面（运行时）解析符号。",
        ]

    @pytest.mark.parametrize("text", ["かな", "カナ", "한글", "ＡＢＣ", "、"])
    def test_other_east_asian_scripts_and_full_width_forms_are_found(
        self, text: str
    ) -> None:
        assert leaks(f"see {text} here", "not English") == [text]

    def test_english_punctuation_is_not_mistaken_for_it(self) -> None:
        text = "Recommended — 1-2000 characters; “quoted”, ‘single’, café, ½, … done."

        assert leaks(text, "not English") == []

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("(~1 MB UTF-8, R166)", ["R166"]),
            ("removed in R167;", ["R167"]),
            ("R25.2: lazy import", ["R25.2"]),
            ("R44 best practice", ["R44"]),
            ("R84720 is not a round id", []),
            ("mining-cycle-3 §2.1 — borrowed", ["mining-cycle"]),
            ("see mining-cycle-12 for why", ["mining-cycle"]),
        ],
    )
    def test_round_and_cycle_notes_are_found(
        self, text: str, expected: list[str]
    ) -> None:
        assert leaks(text, "development-tracking id") == expected

    @pytest.mark.parametrize(
        "text",
        [
            "R2 and R2D2",
            "CAR12 and PAR44",
            "see RFC 9110 §15 and ISO 8601 §4.3",
            "an R-rated film",
            "iter-3 or attempt-2",
            "ISO 8601, UTF-8, RFC 9110",
            "version 1.6.0",
        ],
    )
    def test_ordinary_english_is_not_a_tracking_id(self, text: str) -> None:
        assert leaks(text, "development-tracking id") == []

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("`server.py` wraps it", ["server.py"]),
            ("see web_ui.py and task_queue.py", ["web_ui.py", "task_queue.py"]),
            ("wraps it with `mcp.tool()` to expose it", ["mcp.tool"]),
            ("see ``_emit_ctx_info`` for details", ["_emit_ctx_info"]),
            ("calls _private_helper first", ["_private_helper"]),
            ("`_make_resubmit_response()` runs", ["_make_resubmit_response"]),
        ],
    )
    def test_references_to_the_servers_own_source_are_found(
        self, text: str, expected: list[str]
    ) -> None:
        assert leaks(text, "the server's own source") == expected

    @pytest.mark.parametrize(
        "text",
        [
            "Migrate auth/session.py to PyJWT 2.x",
            "pytest all green + no new ruff warnings",
            "the `i18n` placeholder and `task_id`",
            "keyword-only, __init__ and obj._private_attr stay as they are",
            "use it _sparingly_, or _two_words_, or _very important_ ones, and _meta",
            "a snake_case_name and a_b_c",
        ],
    )
    def test_examples_and_ordinary_identifiers_are_not_source_references(
        self, text: str
    ) -> None:
        assert leaks(text, "the server's own source") == []

    def test_the_package_file_rule_knows_the_modules_it_is_about(self) -> None:
        names = {
            module.name
            for module in pkgutil.iter_modules(ai_intervention_agent.__path__)
        }

        assert {"server", "server_feedback", "web_ui", "task_queue"} <= names
        for name in ("server", "server_feedback"):
            assert leaks(f"in {name}.py", "the server's own source") == [f"{name}.py"]


class TestTheWalkCannotGoSilentlyBlind:
    def test_the_description_of_the_tool_and_of_each_parameter_is_found(self) -> None:
        definition = {
            "name": "t",
            "title": "T (标题)",
            "description": "top",
            "inputSchema": {
                "properties": {
                    "a": {"type": "string", "description": "first"},
                    "b": {"type": "integer"},
                }
            },
        }

        assert descriptions(definition) == {
            "description": "top",
            "inputSchema.properties.a.description": "first",
        }

    def test_nested_and_listed_descriptions_are_found(self) -> None:
        schema = {
            "properties": {
                "a": {
                    "anyOf": [
                        {"type": "array", "items": {"description": "item text"}},
                        {"type": "null", "description": "null text"},
                    ]
                }
            },
            "$defs": {"X": {"description": "def text"}},
        }

        assert descriptions(schema) == {
            "properties.a.anyOf[0].items.description": "item text",
            "properties.a.anyOf[1].description": "null text",
            "$defs.X.description": "def text",
        }

    def test_a_parameter_named_description_is_walked_into(self) -> None:
        schema = {
            "properties": {
                "description": {"type": "string", "description": "what the thing is"}
            }
        }

        assert descriptions(schema) == {
            "properties.description.description": "what the thing is"
        }

    def test_a_title_is_not_a_description(self) -> None:
        assert (
            descriptions({"title": "人机协作反馈", "annotations": {"title": "標題"}})
            == {}
        )

    def test_a_missing_or_blank_description_is_reported_by_name(self) -> None:
        definition = {
            "description": "the tool",
            "inputSchema": {
                "properties": {
                    "a": {"description": "described"},
                    "b": {"type": "string"},
                    "c": {"description": "   \n"},
                }
            },
        }

        assert undescribed(definition) == ["b", "c"]

    def test_a_tool_without_a_description_is_reported(self) -> None:
        definition = {
            "description": " ",
            "inputSchema": {"properties": {"a": {"description": "described"}}},
        }

        assert undescribed(definition) == ["(the tool)"]

    def test_offenders_names_where_the_text_is(self) -> None:
        texts = {"a": "fine", "b": "see R166", "c": "also R44 and R25.2"}

        assert offenders(texts, "development-tracking id") == {
            "b": ["R166"],
            "c": ["R44", "R25.2"],
        }
