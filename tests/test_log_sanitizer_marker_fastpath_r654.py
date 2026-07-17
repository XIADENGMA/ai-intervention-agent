"""R654 - LogSanitizer skips regex work for marker-free messages."""

from __future__ import annotations

import inspect
from typing import Any, cast

import pytest

from ai_intervention_agent.enhanced_logging import (
    _SENSITIVE_LOG_MARKERS,
    LogSanitizer,
)

REDACTED = "***REDACTED***"


class _BoomPattern:
    pattern = "boom"

    def sub(self, *_args: object, **_kwargs: object) -> str:
        raise AssertionError("marker-free log message should not run regex patterns")


def test_sanitizer_has_marker_fast_path_before_regex_loop() -> None:
    source = inspect.getsource(LogSanitizer.sanitize)

    assert "_SENSITIVE_LOG_MARKERS" in source
    assert source.index("_SENSITIVE_LOG_MARKERS") < source.index(
        "for pattern in self.sensitive_patterns:"
    )


def test_marker_free_message_returns_unchanged_without_regex_substitution() -> None:
    sanitizer = LogSanitizer()
    sanitizer.sensitive_patterns = cast(Any, [_BoomPattern()])

    message = "task r654 completed with status ok"

    assert sanitizer.sanitize(message) == message


@pytest.mark.parametrize(
    "message",
    [
        "password=super_secret_value",
        "passwd=hunter22hunter22",
        "secret_key=ABCDEFGH12345678",
        "private_key=ABCDEFGH12345678",
        "OPENAI=sk-" + "a" * 40,
        "slack=xoxb-" + "A" * 24,
        "GH=ghp_" + "A" * 36,
        "GH_FINE=github_pat_" + "A" * 80,
        "aws_access_key_id=AKIA" + "A" * 16,
        "API_KEY=AIza" + "A" * 35,
        "HF_TOKEN=hf_" + "A" * 34,
        "STRIPE_KEY=sk_live_" + "A" * 24,
        "connecting to https://alice:supersecret@example.com/path",
        "Authorization: Bearer eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20,
    ],
)
def test_marker_fast_path_preserves_representative_redaction(message: str) -> None:
    assert REDACTED in LogSanitizer().sanitize(message)


def test_marker_tuple_covers_every_representative_sensitive_prefix() -> None:
    marker_text = "\n".join(_SENSITIVE_LOG_MARKERS)

    for marker in (
        "password",
        "passwd",
        "secret",
        "private",
        "sk-",
        "xox",
        "ghp_",
        "github_pat_",
        "AKIA",
        "AIza",
        "hf_",
        "sk_live_",
        "pk_test_",
        "https://",
        "eyJ",
    ):
        assert marker in marker_text
