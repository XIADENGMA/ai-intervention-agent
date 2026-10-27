"""R907: what ``BarkNotificationProvider.send`` sends, and says, step by step.

``send`` was one method of 203 lines (McCabe 42) that did everything: validate the settings, pick the
click action (a link from the event, a link rendered from the template, a text to copy, an address),
copy the allowed fields of the event, work out the timeout, post, and judge the answer. R42 added three
loopback guards to it, R706 let any ``scheme://`` through and R823 trimmed the address, each time inside
the same nest. It is now one small method per step (``send`` itself is 31 lines, McCabe 6; the largest
step is 47 lines, McCabe 7). This file is the contract that split had to keep: the same body for the same
inputs, the same log call (level and text) for the same reason.

The expectations were measured on the old method and then checked against the new one: every test here
passes on both. A differential run of the old and the new module over 54 000 random combinations of
settings, event and answer (five seeds) found no difference in the return value, the posted requests, the
log calls or the event afterwards, and those combinations reach every statement and branch of the old
method. Several rows below are behaviour that no earlier test looked at: a key of blanks, an empty
template, an unreadable timeout, the copy action without metadata, an event whose metadata is ``None``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ai_intervention_agent import notification_providers
from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationTrigger,
    NotificationType,
)
from ai_intervention_agent.notification_providers import BarkNotificationProvider


class Recorder:
    """Stands in for the module logger: every call is kept as ``(level, text, keywords)``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Any:
        def record(message: Any = "", **kwargs: Any) -> None:
            self.calls.append((level, str(message), kwargs))

        return record

    def levels(self) -> list[tuple[str, str]]:
        return [(level, text) for level, text, _ in self.calls]


class Answer:
    def __init__(
        self, status: int = 200, body: Any = None, text: str = "", json_ok: bool = True
    ) -> None:
        self.status_code = status
        self._body = {"code": status} if body is None else body
        self.text = text
        self._json_ok = json_ok

    def json(self) -> Any:
        if not self._json_ok:
            raise ValueError("not json")
        return self._body


class Session:
    """Stands in for ``provider.session``: keeps what is posted, answers as told."""

    def __init__(self, outcome: Answer | BaseException) -> None:
        self.outcome = outcome
        self.posts: list[tuple[Any, dict[str, Any], Any]] = []

    def post(self, url: Any, **kwargs: Any) -> Answer:
        self.posts.append((url, kwargs["json"], kwargs["timeout"]))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def close(self) -> None:
        return


class Config:
    def __init__(self, **overrides: Any) -> None:
        self.bark_enabled = True
        self.bark_url = "http://h.test/push"
        self.bark_device_key = "KEY"
        self.bark_icon = ""
        self.bark_action = "none"
        self.bark_url_template = "{base_url}/?task_id={task_id}"
        for name, value in overrides.items():
            if value is _MISSING:
                self.__dict__.pop(name, None)
            else:
                setattr(self, name, value)


_MISSING = object()
_KEEP = object()


class Sent:
    def __init__(self, ok: bool, session: Session, recorder: Recorder, event: Any):
        self.ok = ok
        self.posts = session.posts
        self.logs = recorder.levels()
        self.calls = recorder.calls
        self.event = event

    @property
    def body(self) -> dict[str, Any]:
        assert len(self.posts) == 1, self.posts
        return self.posts[0][1]


def send(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    metadata: Any = _KEEP,
    outcome: Answer | BaseException | None = None,
) -> Sent:
    recorder = Recorder()
    monkeypatch.setattr(notification_providers, "logger", recorder)
    provider = BarkNotificationProvider(Config(**(config or {})))
    provider.session.close()  # the real client is never used
    session = Session(outcome if outcome is not None else Answer())
    provider.session = session
    fields: dict[str, Any] = {
        "id": "ev1",
        "title": "Title",
        "message": "Message",
        "trigger": NotificationTrigger.IMMEDIATE,
        "types": [NotificationType.BARK],
        "metadata": {"task_id": "t1", "base_url": "https://h.test"},
    }
    fields.update(event or {})
    if metadata is not _KEEP:
        fields["metadata"] = metadata
    built = NotificationEvent.model_construct(**fields)
    try:
        ok = provider.send(built)
    finally:
        provider.close()
    return Sent(ok, session, recorder, built)


# ---------------------------------------------------------------------------------- nothing sent
NOTHING_SENT = {
    "disabled": (
        {"bark_enabled": False},
        {},
        ("debug", "Bark通知已禁用"),
    ),
    "no address": (
        {"bark_url": ""},
        {},
        ("warning", "Bark配置不完整，跳过发送"),
    ),
    "an address of blanks": (
        {"bark_url": "  \n"},
        {},
        ("warning", "Bark配置不完整，跳过发送"),
    ),
    "no address at all": (
        {"bark_url": None},
        {},
        ("warning", "Bark配置不完整，跳过发送"),
    ),
    "no key": (
        {"bark_device_key": ""},
        {},
        ("warning", "Bark配置不完整，跳过发送"),
    ),
    "an address that is not http": (
        {"bark_url": "ftp://h.test/push"},
        {},
        ("error", "Bark URL 格式无效: ftp://h.test/push"),
    ),
    "a key of blanks": (
        {"bark_device_key": "   "},
        {},
        ("error", "Bark device_key 为空字符串"),
    ),
    "no title": ({}, {"title": ""}, ("warning", "Bark通知标题为空，跳过发送: ev1")),
    "a title of blanks": (
        {},
        {"title": " \t "},
        ("warning", "Bark通知标题为空，跳过发送: ev1"),
    ),
    "no message": (
        {},
        {"message": ""},
        ("warning", "Bark通知消息为空，跳过发送: ev1"),
    ),
    "a message of blanks": (
        {},
        {"message": "\n \n"},
        ("warning", "Bark通知消息为空，跳过发送: ev1"),
    ),
    # the first reason wins
    "disabled and no address": (
        {"bark_enabled": False, "bark_url": ""},
        {},
        ("debug", "Bark通知已禁用"),
    ),
    "a bad address and no title": (
        {"bark_url": "ftp://h.test/push"},
        {"title": ""},
        ("error", "Bark URL 格式无效: ftp://h.test/push"),
    ),
    "a key of blanks and no title": (
        {"bark_device_key": "  "},
        {"title": ""},
        ("error", "Bark device_key 为空字符串"),
    ),
    "no title and no message": (
        {},
        {"title": "", "message": ""},
        ("warning", "Bark通知标题为空，跳过发送: ev1"),
    ),
}


class TestNothingIsSentAndOneReasonIsSaid:
    @pytest.mark.parametrize(
        ("config", "event", "expected"),
        list(NOTHING_SENT.values()),
        ids=list(NOTHING_SENT),
    )
    def test_no_request_and_one_log_call_with_the_reason(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict[str, Any],
        event: dict[str, Any],
        expected: tuple[str, str],
    ) -> None:
        sent = send(monkeypatch, config=config, event=event)
        assert sent.ok is False
        assert sent.posts == []
        assert sent.logs == [expected]


# ------------------------------------------------------------------------------------- the body
class TestTheBody:
    def test_the_smallest_body_and_the_address_it_goes_to(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(
            monkeypatch,
            config={"bark_url": " HTTPS://h.test/push\n", "bark_device_key": " KEY "},
            event={"title": " Title ", "message": "\nMessage "},
        )
        assert sent.ok is True
        assert sent.posts == [
            (
                "HTTPS://h.test/push",
                {"title": "Title", "body": "Message", "device_key": "KEY"},
                10,
            )
        ]

    @pytest.mark.parametrize(
        ("icon", "expected"),
        [
            ("http://i.test/x.png", "http://i.test/x.png"),
            (" https://i.test/y.png\n", "https://i.test/y.png"),
            ("", None),
            ("   ", None),
            (None, None),
        ],
    )
    def test_the_icon_is_trimmed_and_left_out_when_blank(
        self, monkeypatch: pytest.MonkeyPatch, icon: Any, expected: str | None
    ) -> None:
        body = send(monkeypatch, config={"bark_icon": icon}).body
        assert body.get("icon") == expected
        assert ("icon" in body) is (expected is not None)

    def test_allowed_scalars_of_the_event_are_copied_and_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        metadata = {
            "group": "g",
            "level": "active",
            "badge": 3,
            "autoCopy": True,
            "isArchive": 0,
            "sound": None,
            "event": 1.5,
            "count": 2,
            "source": "aiia",
            "task_id": "t1",  # not a Bark field
            "other": "x",  # not a Bark field
            "mixed": ["x"],  # not a Bark field
        }
        body = send(monkeypatch, metadata=metadata).body
        assert body == {
            "title": "Title",
            "body": "Message",
            "device_key": "KEY",
            "group": "g",
            "level": "active",
            "badge": 3,
            "autoCopy": True,
            "isArchive": 0,
            "sound": None,
            "event": 1.5,
            "count": 2,
            "source": "aiia",
        }

    @pytest.mark.parametrize("value", [["x"], {"a": 1}, ("t",), object()])
    def test_an_allowed_field_that_is_not_a_scalar_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch, value: Any
    ) -> None:
        body = send(monkeypatch, metadata={"group": value, "level": "active"}).body
        assert "group" not in body
        assert body["level"] == "active"

    def test_the_reserved_fields_of_the_event_never_replace_the_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reserved = {
            "title": "X",
            "body": "X",
            "device_key": "X",
            "icon": "X",
            "action": "X",
            "url": "https://z.test/",
            "copy": "X",
        }
        body = send(monkeypatch, metadata=reserved).body
        assert body == {"title": "Title", "body": "Message", "device_key": "KEY"}

    @pytest.mark.parametrize("metadata", [None, {}], ids=["None", "empty"])
    @pytest.mark.parametrize(
        ("action", "extra"),
        [
            ("none", {}),
            ("url", {}),
            ("copy", {"copy": "Message"}),
            ("https://x.test/a", {"url": "https://x.test/a"}),
        ],
    )
    def test_an_event_without_metadata_still_sends(
        self,
        monkeypatch: pytest.MonkeyPatch,
        action: str,
        extra: dict[str, str],
        metadata: Any,
    ) -> None:
        sent = send(monkeypatch, config={"bark_action": action}, metadata=metadata)
        assert sent.ok is True
        assert sent.body == {
            "title": "Title",
            "body": "Message",
            "device_key": "KEY",
            **extra,
        }

    def test_a_failed_push_of_an_event_without_metadata_is_still_said(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(
            monkeypatch,
            config={"debug": True},
            metadata=None,
            outcome=Answer(500, body="down"),
        )
        assert sent.ok is False
        assert sent.logs == [("error", "Bark通知发送失败: 500 - down")]
        assert sent.event.metadata is None

    def test_a_reserved_key_stays_out_even_if_it_were_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reserved = ("title", "body", "device_key", "icon", "action", "url", "copy")
        monkeypatch.setattr(
            BarkNotificationProvider,
            "_ALLOWED_METADATA_KEYS",
            frozenset({*reserved, "level"}),
        )
        metadata = dict.fromkeys(reserved, "X") | {"level": "active"}
        body = send(monkeypatch, metadata=metadata).body
        assert body == {
            "title": "Title",
            "body": "Message",
            "device_key": "KEY",
            "level": "active",
        }


# ----------------------------------------------------------------------------- the click action
NO_ACTION = [None, "", "   ", "none", " none "]


class TestNoClickAction:
    @pytest.mark.parametrize("action", NO_ACTION)
    def test_no_link_and_no_text_however_much_the_event_offers(
        self, monkeypatch: pytest.MonkeyPatch, action: Any
    ) -> None:
        sent = send(
            monkeypatch,
            config={"bark_action": action},
            metadata={"url": "https://a.test/", "copy": "text", "task_id": "t1"},
        )
        assert sent.body == {"title": "Title", "body": "Message", "device_key": "KEY"}
        assert sent.logs == [("info", "Bark通知发送成功: ev1 (状态码: 200)")]


LINK_KEYS = ("url", "web_ui_url", "action_url", "link")


class TestTheUrlActionTakesTheLinkOfTheEvent:
    @pytest.mark.parametrize("action", ["url", " url "])
    def test_the_link_is_trimmed_and_used(
        self, monkeypatch: pytest.MonkeyPatch, action: str
    ) -> None:
        sent = send(
            monkeypatch,
            config={"bark_action": action},
            metadata={"url": " https://a.test/x \n"},
        )
        assert sent.body["url"] == "https://a.test/x"
        assert sent.logs == [("info", "Bark通知发送成功: ev1 (状态码: 200)")]

    def test_the_keys_are_tried_in_a_fixed_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        links = {key: f"https://{key}.test/" for key in LINK_KEYS}
        for position, key in enumerate(LINK_KEYS):
            remaining = {name: links[name] for name in LINK_KEYS[position:]}
            sent = send(monkeypatch, config={"bark_action": "url"}, metadata=remaining)
            assert sent.body["url"] == links[key]

    def test_a_link_that_is_not_a_link_is_said_and_the_next_key_is_tried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(
            monkeypatch,
            config={"bark_action": "url"},
            metadata={"url": "not a link", "web_ui_url": "https://b.test/"},
        )
        assert sent.body["url"] == "https://b.test/"
        assert sent.logs[0] == (
            "warning",
            "event.metadata['url']='not a link' 不是合法跳转 URL，已忽略此候选",
        )

    @pytest.mark.parametrize(
        "loopback",
        ["http://127.0.0.1:8080/?t=1", "http://localhost/", "http://[::1]:8080/"],
    )
    def test_a_loopback_link_is_said_and_the_next_key_is_tried(
        self, monkeypatch: pytest.MonkeyPatch, loopback: str
    ) -> None:
        sent = send(
            monkeypatch,
            config={"bark_action": "url"},
            metadata={"url": loopback, "link": "https://b.test/"},
        )
        assert sent.body["url"] == "https://b.test/"
        assert sent.logs[0] == (
            "warning",
            f"event.metadata['url']={loopback!r} 是回环地址，"
            "手机端 Bark 无法跳转，已忽略此候选",
        )

    @pytest.mark.parametrize("value", ["", "   ", 5, None, ["https://a.test/"]])
    def test_a_blank_or_non_text_value_is_passed_over_without_a_word(
        self, monkeypatch: pytest.MonkeyPatch, value: Any
    ) -> None:
        sent = send(
            monkeypatch,
            config={"bark_action": "url"},
            metadata={"url": value, "link": "https://b.test/"},
        )
        assert sent.body["url"] == "https://b.test/"
        assert sent.logs == [("info", "Bark通知发送成功: ev1 (状态码: 200)")]

    @pytest.mark.parametrize(
        "link", ["ftp://f.test/x", "shortcuts://run-shortcut?name=a"]
    )
    def test_any_scheme_will_do(
        self, monkeypatch: pytest.MonkeyPatch, link: str
    ) -> None:
        sent = send(monkeypatch, config={"bark_action": "url"}, metadata={"url": link})
        assert sent.body["url"] == link

    def test_the_link_of_the_event_wins_over_the_template(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(
            monkeypatch,
            config={"bark_action": "url"},
            metadata={
                "url": "https://a.test/",
                "task_id": "t1",
                "base_url": "https://h.test",
            },
        )
        assert sent.body["url"] == "https://a.test/"


class TestTheUrlActionRendersTheTemplate:
    def _url(self, monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> Sent:
        config = {"bark_action": "url", **kwargs.pop("config", {})}
        return send(monkeypatch, config=config, **kwargs)

    def test_the_default_template(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent = self._url(monkeypatch)
        assert sent.body["url"] == "https://h.test/?task_id=t1"
        assert sent.logs == [("info", "Bark通知发送成功: ev1 (状态码: 200)")]

    def test_the_trailing_slashes_of_the_base_are_cut(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(
            monkeypatch, metadata={"task_id": "t1", "base_url": "https://h.test///"}
        )
        assert sent.body["url"] == "https://h.test/?task_id=t1"

    def test_the_task_id_is_percent_encoded_in_full(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(
            monkeypatch,
            metadata={"task_id": "a b#c&d/é", "base_url": "https://h.test"},
        )
        assert sent.body["url"] == "https://h.test/?task_id=a%20b%23c%26d%2F%C3%A9"

    def test_the_event_id_and_a_number_as_task_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(
            monkeypatch,
            config={"bark_url_template": "{base_url}/{event_id}/{task_id}"},
            metadata={"task_id": 7, "base_url": "https://h.test"},
        )
        assert sent.body["url"] == "https://h.test/ev1/7"

    @pytest.mark.parametrize("task_id", [None, ["x"], {"a": 1}])
    def test_a_task_id_that_is_not_a_scalar_is_empty(
        self, monkeypatch: pytest.MonkeyPatch, task_id: Any
    ) -> None:
        sent = self._url(
            monkeypatch, metadata={"task_id": task_id, "base_url": "https://h.test"}
        )
        assert sent.body["url"] == "https://h.test/?task_id="

    def test_a_template_without_placeholders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(
            monkeypatch,
            config={"bark_url_template": "shortcuts://run-shortcut?name=ai%20agent"},
        )
        assert sent.body["url"] == "shortcuts://run-shortcut?name=ai%20agent"

    @pytest.mark.parametrize("base", [None, 5, ["https://h.test"], {"u": 1}])
    def test_a_base_url_that_is_not_text_counts_as_missing(
        self, monkeypatch: pytest.MonkeyPatch, base: Any
    ) -> None:
        sent = self._url(monkeypatch, metadata={"task_id": "t1", "base_url": base})
        assert "url" not in sent.body
        assert sent.logs[0][1].startswith(
            "bark_url_template 渲染结果不是合法 URL，已忽略: '/?task_id=t1'；base_url 为空"
        )

    def test_without_a_base_url_the_result_is_no_link_and_the_hint_names_why(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(monkeypatch, metadata={"task_id": "t1"})
        assert "url" not in sent.body
        assert sent.logs[0][0] == "warning"
        assert sent.logs[0][1].startswith(
            "bark_url_template 渲染结果不是合法 URL，已忽略: '/?task_id=t1'；"
            "base_url 为空（监听地址 network_security.bind_interface "
        )
        assert sent.logs[1] == (
            "debug",
            "Bark 点击行为为 url，但未提供可用链接，已忽略: ev1",
        )

    def test_a_base_that_is_there_but_is_no_link_gets_no_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(monkeypatch, metadata={"task_id": "t1", "base_url": "h.test"})
        assert "url" not in sent.body
        assert sent.logs[0] == (
            "warning",
            "bark_url_template 渲染结果不是合法 URL，已忽略: 'h.test/?task_id=t1'",
        )

    def test_a_template_that_cannot_be_rendered_is_said_once_and_the_push_goes_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(monkeypatch, config={"bark_url_template": "{task.id}"})
        assert sent.ok is True
        assert "url" not in sent.body
        assert [level for level, _ in sent.logs] == ["warning", "debug", "info"]
        assert sent.logs[0][1].startswith(
            "渲染 Bark URL 模板失败: template='{task.id}'"
        )

    @pytest.mark.parametrize("template", ["{task_id}", "  {task_id}  \n"])
    def test_a_template_that_renders_to_nothing_is_not_said(
        self, monkeypatch: pytest.MonkeyPatch, template: str
    ) -> None:
        sent = self._url(
            monkeypatch,
            config={"bark_url_template": template},
            metadata={"task_id": "", "base_url": "https://h.test"},
        )
        assert "url" not in sent.body
        assert sent.logs == [
            ("debug", "Bark 点击行为为 url，但未提供可用链接，已忽略: ev1"),
            ("info", "Bark通知发送成功: ev1 (状态码: 200)"),
        ]

    def test_a_template_that_does_not_need_the_base_gets_no_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(
            monkeypatch,
            config={"bark_url_template": "not a link {task_id}"},
            metadata={"task_id": "t1"},
        )
        assert "url" not in sent.body
        assert sent.logs[0] == (
            "warning",
            "bark_url_template 渲染结果不是合法 URL，已忽略: 'not a link t1'",
        )

    def test_a_loopback_result_is_suppressed_and_said(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(
            monkeypatch,
            metadata={"task_id": "t1", "base_url": "http://127.0.0.1:8080"},
        )
        assert "url" not in sent.body
        assert sent.logs[0][0] == "warning"
        assert sent.logs[0][1].startswith(
            "bark_url_template 渲染结果命中回环地址 'http://127.0.0.1:8080/?task_id=t1'，"
            "已抑制 url 字段；"
        )
        assert sent.logs[1][0] == "debug"

    @pytest.mark.parametrize("template", ["", None, _MISSING])
    def test_no_template_means_no_link_and_a_debug_line(
        self, monkeypatch: pytest.MonkeyPatch, template: Any
    ) -> None:
        sent = self._url(monkeypatch, config={"bark_url_template": template})
        assert "url" not in sent.body
        assert sent.logs == [
            ("debug", "Bark 点击行为为 url，但未提供可用链接，已忽略: ev1"),
            ("info", "Bark通知发送成功: ev1 (状态码: 200)"),
        ]

    def test_the_template_is_not_looked_at_when_the_event_has_a_link(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(
            monkeypatch,
            config={"bark_url_template": "{task.id}"},
            metadata={"link": "https://b.test/"},
        )
        assert sent.body["url"] == "https://b.test/"
        assert sent.logs == [("info", "Bark通知发送成功: ev1 (状态码: 200)")]

    def test_every_rejected_link_is_said_before_the_template_is_tried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = self._url(
            monkeypatch,
            metadata={
                "url": "nope",
                "link": "http://localhost/",
                "task_id": "t1",
                "base_url": "https://h.test",
            },
        )
        assert sent.body["url"] == "https://h.test/?task_id=t1"
        assert [level for level, _ in sent.logs] == ["warning", "warning", "info"]
        assert "event.metadata['url']='nope'" in sent.logs[0][1]
        assert "event.metadata['link']='http://localhost/'" in sent.logs[1][1]

    def test_the_url_action_is_case_sensitive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(monkeypatch, config={"bark_action": "URL"})
        assert "url" not in sent.body
        assert sent.logs[0] == ("debug", "未知 bark_action='URL'，已忽略: ev1")


class TestTheCopyAction:
    @pytest.mark.parametrize(
        ("metadata", "expected"),
        [
            ({"copy": " text \n"}, "text"),
            ({"copy_text": "second"}, "second"),
            ({"copyContent": "third"}, "third"),
            ({"copy": "1", "copy_text": "2", "copyContent": "3"}, "1"),
            ({"copy": "   ", "copy_text": "2"}, "2"),
            ({"copy": 5, "copyContent": "3"}, "3"),
            ({"copy": "", "copy_text": "", "copyContent": ""}, "Message"),
            ({"copy": 5}, "Message"),
            ({}, "Message"),
        ],
        ids=[
            "trimmed",
            "second key",
            "third key",
            "first key wins",
            "blank first key",
            "non-text first key",
            "all blank: the message",
            "only a number: the message",
            "nothing: the message",
        ],
    )
    def test_the_text_to_copy(
        self, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, Any], expected: str
    ) -> None:
        sent = send(monkeypatch, config={"bark_action": "copy"}, metadata=metadata)
        assert sent.body["copy"] == expected
        assert "url" not in sent.body

    def test_the_message_it_falls_back_to_is_the_trimmed_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(
            monkeypatch,
            config={"bark_action": "copy"},
            event={"message": "  text of the message \n"},
            metadata={},
        )
        assert sent.body["copy"] == "text of the message"

    def test_the_copy_action_is_case_sensitive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(monkeypatch, config={"bark_action": "COPY"})
        assert "copy" not in sent.body
        assert sent.logs[0] == ("debug", "未知 bark_action='COPY'，已忽略: ev1")


class TestAnAddressAsTheAction:
    @pytest.mark.parametrize(
        ("action", "expected"),
        [
            ("http://x.test/a", "http://x.test/a"),
            (" HTTPS://x.test/b ", "HTTPS://x.test/b"),
            ("https://x.test/c?d=1#e", "https://x.test/c?d=1#e"),
        ],
    )
    def test_the_address_is_the_link(
        self, monkeypatch: pytest.MonkeyPatch, action: str, expected: str
    ) -> None:
        sent = send(monkeypatch, config={"bark_action": action}, metadata={})
        assert sent.body["url"] == expected
        assert sent.logs == [("info", "Bark通知发送成功: ev1 (状态码: 200)")]

    def test_a_loopback_address_is_suppressed_and_said(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(monkeypatch, config={"bark_action": "http://127.0.0.1:1/x"})
        assert "url" not in sent.body
        assert sent.logs[0] == (
            "warning",
            "bark_action 是回环地址 'http://127.0.0.1:1/x'，已抑制 url 字段；"
            "请改用具体的 LAN/公网 URL 或 url/copy 枚举",
        )

    @pytest.mark.parametrize("action", ["weird", "ftp://x.test/", "http", "urls"])
    def test_any_other_word_is_ignored_and_said_at_debug(
        self, monkeypatch: pytest.MonkeyPatch, action: str
    ) -> None:
        sent = send(monkeypatch, config={"bark_action": action})
        assert sent.body == {"title": "Title", "body": "Message", "device_key": "KEY"}
        assert sent.logs[0] == (
            "debug",
            f"未知 bark_action='{action}'，已忽略: ev1",
        )


# ------------------------------------------------------------------------------------ the timeout
class TestTheTimeout:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (3, 3),
            ("7", 7),
            (2.9, 2),
            (300, 300),
            (0, 1),
            (-5, 1),
            ("x", 10),
            (None, 10),
            ([3], 10),
            (_MISSING, 10),
        ],
        ids=["3", "'7'", "2.9", "300", "0", "-5", "'x'", "None", "list", "missing"],
    )
    def test_what_is_posted(
        self, monkeypatch: pytest.MonkeyPatch, value: Any, expected: int
    ) -> None:
        sent = send(monkeypatch, config={"bark_timeout": value})
        assert sent.posts[0][2] == expected


# ------------------------------------------------------------------------------------ the answer
class TestTheAnswer:
    @pytest.mark.parametrize("status", [200, 201, 204, 299])
    def test_any_2xx_is_a_success(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        sent = send(monkeypatch, outcome=Answer(status))
        assert sent.ok is True
        assert sent.logs == [("info", f"Bark通知发送成功: ev1 (状态码: {status})")]

    @pytest.mark.parametrize("status", [199, 300, 301, 400, 404, 500])
    def test_anything_else_is_a_failure_with_the_detail_in_the_log(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        sent = send(monkeypatch, outcome=Answer(status, body={"message": "no luck"}))
        assert sent.ok is False
        assert sent.logs == [
            ("error", f"Bark通知发送失败: {status} - {{'message': 'no luck'}}")
        ]

    def test_a_body_that_is_not_json_is_logged_as_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(monkeypatch, outcome=Answer(502, text="Bad Gateway", json_ok=False))
        assert sent.logs == [("error", "Bark通知发送失败: 502 - Bad Gateway")]

    def test_what_looks_like_a_secret_is_cut_out_of_the_log(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detail = (
            "device https://api.push.apple.com/3/device/"
            + "ab12" * 8
            + " key "
            + "a" * 40
            + " token [ABCDEFGHIJKLMNOP1234]"
        )
        sent = send(monkeypatch, outcome=Answer(400, body=detail))
        assert len(sent.logs) == 1
        text = sent.logs[0][1]
        assert "ab12" * 8 not in text
        assert "a" * 40 not in text
        assert "ABCDEFGHIJKLMNOP1234" not in text
        assert "<redacted>" in text
        assert "<redacted_hex>" in text
        assert "[<redacted_key>]" in text

    def test_the_log_keeps_800_characters_of_the_detail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(monkeypatch, outcome=Answer(500, text="x" * 2000, json_ok=False))
        assert sent.logs == [("error", "Bark通知发送失败: 500 - " + "x" * 800)]

    @pytest.mark.parametrize(
        ("config", "metadata", "kept"),
        [
            ({}, {"test": True}, True),
            ({"debug": True}, {}, True),
            ({"debug": True}, {"test": True}, True),
            ({"debug": False}, {"test": False}, False),
            ({}, {}, False),
            ({"debug": True}, {"test": 0}, True),
        ],
        ids=[
            "test event",
            "debug",
            "both",
            "neither (explicit)",
            "neither",
            "debug only",
        ],
    )
    def test_the_detail_is_kept_on_the_event_for_a_test_or_a_debug_run_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict[str, Any],
        metadata: dict[str, Any],
        kept: bool,
    ) -> None:
        sent = send(
            monkeypatch,
            config=config,
            metadata=metadata,
            outcome=Answer(403, body={"message": "denied " + "y" * 900}),
        )
        stored = sent.event.metadata.get("bark_error")
        if not kept:
            assert stored is None
            return
        assert stored["status_code"] == 403
        assert stored["detail"].startswith("{'message': 'denied yyy")
        assert len(stored["detail"]) == 800

    def test_the_detail_kept_on_the_event_is_made_safe_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detail = (
            "device https://api.push.apple.com/3/device/"
            + "ab12" * 8
            + " [ABCDEFGHIJKLMNOP1234]"
        )
        sent = send(
            monkeypatch, config={"debug": True}, outcome=Answer(400, body=detail)
        )
        assert sent.event.metadata["bark_error"]["detail"] == (
            "device https://api.push.apple.com/3/device/<redacted> [<redacted_key>]"
        )

    def test_a_success_leaves_the_event_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(monkeypatch, config={"debug": True}, metadata={"test": True})
        assert sent.event.metadata == {"test": True}


class TestWhatGoesWrongOnTheWay:
    def test_a_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent = send(monkeypatch, outcome=httpx.ReadTimeout("slow"))
        assert sent.ok is False
        assert sent.logs == [("error", "Bark通知发送超时: ev1")]
        assert sent.calls[0][2] == {"exc_info": True}

    def test_a_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent = send(monkeypatch, outcome=httpx.ConnectError("refused"))
        assert sent.ok is False
        assert sent.logs == [("error", "Bark通知发送网络错误: refused")]
        assert sent.calls[0][2] == {"exc_info": True}

    def test_anything_else(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent = send(monkeypatch, outcome=RuntimeError("boom"))
        assert sent.ok is False
        assert sent.logs == [("error", "Bark通知发送失败: boom")]
        assert sent.calls[0][2] == {"exc_info": True}

    def test_a_setting_that_is_not_text_is_a_failure_and_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent = send(monkeypatch, config={"bark_url": 123})
        assert sent.ok is False
        assert sent.posts == []
        assert sent.logs == [
            ("error", "Bark通知发送失败: 'int' object has no attribute 'lower'")
        ]

    def test_an_interrupt_is_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(KeyboardInterrupt):
            send(monkeypatch, outcome=KeyboardInterrupt())
