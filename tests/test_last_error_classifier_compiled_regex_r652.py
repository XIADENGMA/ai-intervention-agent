"""R652 - last-error classification reuses compiled regex patterns."""

from __future__ import annotations

import inspect

from ai_intervention_agent.web_ui_routes import system as system_module


def test_last_error_classifier_uses_module_level_compiled_patterns() -> None:
    source = inspect.getsource(system_module._classify_last_error)

    assert "import re" not in source
    assert "_LAST_ERROR_STATUS_RE.search(s_lower)" in source
    assert "_LAST_ERROR_PREFIX_STATUS_RE.match(s_lower)" in source
    assert "_LAST_ERROR_NETWORK_KEYWORDS" in source


def test_last_error_classifier_runtime_contract_is_preserved() -> None:
    cases = {
        None: None,
        "": None,
        "{'status_code': 401, 'detail': 'Bark API returned 401'}": "client_error",
        "HTTP/1.1 503 Service Unavailable": "server_error",
        "500 Internal Server Error from upstream": "server_error",
        "Request timed out after 30 seconds": "timeout",
        "Connection refused on port 443": "network_error",
        "provider_not_registered": "not_registered",
        "Some unstructured error msg": "unknown",
    }

    for raw, expected in cases.items():
        assert system_module._classify_last_error(raw) == expected
