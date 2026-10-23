from __future__ import annotations

import inspect

from ai_intervention_agent.web_ui_security import SecurityMixin


def test_parse_forwarded_for_cuts_from_the_right_at_most_hops_times() -> None:
    # R660 kept the cut cheap; R849 moved it to the right-hand end. The header is as
    # long as the visitor makes it, so the cut count is bounded by the hop count.
    source = inspect.getsource(SecurityMixin._parse_forwarded_for)

    assert '.rsplit(",", hops)' in source
    assert ".split(" not in source


def test_parse_forwarded_for_preserves_the_proxy_written_client_semantics() -> None:
    assert SecurityMixin._parse_forwarded_for("") == ""
    assert SecurityMixin._parse_forwarded_for("10.0.0.1") == "10.0.0.1"
    assert (
        SecurityMixin._parse_forwarded_for("10.0.0.1, 10.0.0.2, 10.0.0.3") == "10.0.0.3"
    )
    assert (
        SecurityMixin._parse_forwarded_for("10.0.0.2,  2001:db8::1  ") == "2001:db8::1"
    )
