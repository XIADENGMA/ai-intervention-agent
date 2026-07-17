from __future__ import annotations

import inspect
from typing import Any

from ai_intervention_agent.web_ui_rate_limiter import WebUiRateLimiter
from ai_intervention_agent.web_ui_security import SecurityMixin


class _TrackingEnviron(dict[str, Any]):
    def __init__(self, *, remote_addr: str, forwarded_for: str = "") -> None:
        super().__init__(
            {
                "REMOTE_ADDR": remote_addr,
                "HTTP_X_FORWARDED_FOR": forwarded_for,
            }
        )
        self.forwarded_for_reads = 0

    def get(self, key: str, default: Any = None) -> Any:
        if key == "HTTP_X_FORWARDED_FOR":
            self.forwarded_for_reads += 1
        return super().get(key, default)


class _SecurityProbe(SecurityMixin):
    pass


def test_untrusted_remote_does_not_read_forwarded_for_header() -> None:
    probe = _SecurityProbe()
    environ = _TrackingEnviron(
        remote_addr="8.8.8.8",
        forwarded_for="127.0.0.1, 10.0.0.1, 10.0.0.2",
    )

    assert probe._get_request_client_ip(environ) == "8.8.8.8"
    assert environ.forwarded_for_reads == 0


def test_trusted_loopback_still_reads_forwarded_for_header() -> None:
    probe = _SecurityProbe()
    environ = _TrackingEnviron(
        remote_addr="127.0.0.1",
        forwarded_for="10.0.0.9, 127.0.0.1",
    )

    assert probe._get_request_client_ip(environ) == "10.0.0.9"
    assert environ.forwarded_for_reads == 1


def test_limiter_client_key_reads_forwarded_for_after_trust_check() -> None:
    source = inspect.getsource(WebUiRateLimiter._client_key)

    trust_check = source.index("_should_trust_forwarded_for(remote_addr)")
    header_read = source.index('request.headers.get("X-Forwarded-For", "")')
    assert trust_check < header_read
