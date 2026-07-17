from __future__ import annotations

import inspect

from ai_intervention_agent.web_ui_security import SecurityMixin


def test_parse_forwarded_for_uses_partition_fastpath() -> None:
    source = inspect.getsource(SecurityMixin._parse_forwarded_for)

    assert ".partition(" in source
    assert ".split(" not in source


def test_parse_forwarded_for_preserves_first_client_semantics() -> None:
    assert SecurityMixin._parse_forwarded_for("") == ""
    assert SecurityMixin._parse_forwarded_for("10.0.0.1") == "10.0.0.1"
    assert (
        SecurityMixin._parse_forwarded_for("10.0.0.1, 10.0.0.2, 10.0.0.3") == "10.0.0.1"
    )
    assert (
        SecurityMixin._parse_forwarded_for("  2001:db8::1  , 10.0.0.2") == "2001:db8::1"
    )
