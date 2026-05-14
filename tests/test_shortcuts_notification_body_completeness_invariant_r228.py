"""R228 / Cycle 13: Ctrl+/ shortcut notification body lists every
registered shortcut.

Background
----------
`src/ai_intervention_agent/static/js/keyboard-shortcuts.js`
`showHelp()` is invoked when the user presses `Ctrl+/` (or `Cmd+/`
on macOS). It writes a full 8-line table to the browser console AND
sends a web notification with body text `shortcuts.notifyBody`. The
notification body is the **only** visible cue for users who have
notifications enabled but DevTools closed.

Before R228, the body covered only 3 of the 7 registered shortcuts
(`Enter`, `T`, `Esc`) and gave the misleading impression those were
the only shortcuts available. R223 partially mitigated this with a
settings-panel hint pointing users at the console for the full
reference, but the notification itself still lied by omission.

R228 expands the body to cover every shortcut in compact form and
appends an explicit pointer at the DevTools console for the full
table. This invariant locks both improvements so a future
"shortening" of the body cannot silently regress the discoverability.

Cases (8 total):

1. Both locales declare a non-empty `shortcuts.notifyBody`.
2. EN body mentions every shortcut binding registered in
   `keyboard-shortcuts.js` (`Enter`, `,`, `/`, `T`, `Tab`, `Esc`).
3. zh-CN body mentions every shortcut binding (same set).
4. EN body mentions "console" (sets expectation about where the
   full reference lives).
5. zh-CN body mentions "控制台" or "console" equivalent.
6. Bodies stay under a reasonable upper bound (~250 chars) so they
   render in OS notification widgets without truncation.
7. Both bodies still reference the `{{mod}}` ICU placeholder
   (otherwise the `mod` parameter passed by `showHelp()` is wasted
   and the message reads weirdly on macOS / Windows).
8. The `showHelp()` source still calls `sendNotification` with
   `t('shortcuts.notifyBody', { mod })` — otherwise the body
   changes here aren't actually rendered.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
KEYBOARD_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard-shortcuts.js"
)


def _load_locale(name: str) -> dict:
    return json.loads((LOCALES_DIR / name).read_text(encoding="utf-8"))


def _get_notify_body(locale: dict) -> str:
    shortcuts = locale.get("shortcuts") or {}
    value = shortcuts.get("notifyBody", "")
    return str(value) if isinstance(value, str) else ""


# All seven shortcut bindings registered in keyboard-shortcuts.js.
# Each tuple is (substring_to_check, friendly_name_for_error_message).
# The substring is a fragment the body MUST contain in order to be
# considered "this binding is mentioned" — chosen to match both EN
# and zh-CN bodies (the bindings themselves are language-neutral).
_REQUIRED_BINDINGS = (
    ("Enter", "submit / Ctrl+Enter"),
    (",", "settings / Ctrl+,"),
    ("/", "help / Ctrl+/"),
    ("T", "toggle theme / T"),
    ("Tab", "task switch / Tab"),
    ("Esc", "close modal / Esc"),
)

# Reasonable upper bound for notification body length. Most modern
# notification widgets render up to ~250–500 chars but truncate
# anything longer. Keep well under to leave room for the `{{mod}}`
# substitution (≤ 4 chars for "Ctrl" / "⌘").
_MAX_BODY_LENGTH = 250


class TestBodyExists(unittest.TestCase):
    def test_en_body_non_empty(self) -> None:
        body = _get_notify_body(_load_locale("en.json"))
        self.assertTrue(
            body.strip(),
            "en.json shortcuts.notifyBody is empty — R228 expects the body to be the only visible cue for users with notifications on but DevTools closed.",
        )

    def test_zh_body_non_empty(self) -> None:
        body = _get_notify_body(_load_locale("zh-CN.json"))
        self.assertTrue(body.strip(), "zh-CN.json shortcuts.notifyBody is empty.")


class TestBodyMentionsEveryBinding(unittest.TestCase):
    def test_en_body_covers_all_bindings(self) -> None:
        body = _get_notify_body(_load_locale("en.json"))
        missing = [name for substr, name in _REQUIRED_BINDINGS if substr not in body]
        self.assertEqual(
            missing,
            [],
            (
                "en.json shortcuts.notifyBody does not mention "
                f"these registered bindings: {missing}. The "
                "previous 3-shortcut body was the documented R228 "
                "regression we are guarding against."
            ),
        )

    def test_zh_body_covers_all_bindings(self) -> None:
        body = _get_notify_body(_load_locale("zh-CN.json"))
        missing = [name for substr, name in _REQUIRED_BINDINGS if substr not in body]
        self.assertEqual(missing, [])


class TestBodyMentionsConsole(unittest.TestCase):
    def test_en_body_mentions_console(self) -> None:
        body = _get_notify_body(_load_locale("en.json")).lower()
        self.assertIn(
            "console",
            body,
            (
                "en.json shortcuts.notifyBody should mention "
                "'console' so users know where the full 8-line "
                "help table is — without this the notification "
                "feels like 'these are the only shortcuts'."
            ),
        )

    def test_zh_body_mentions_console_or_devtools(self) -> None:
        body = _get_notify_body(_load_locale("zh-CN.json"))
        self.assertTrue(
            "控制台" in body or "console" in body.lower(),
            (
                "zh-CN.json shortcuts.notifyBody should mention "
                "'控制台' or 'console' so users know where the full help "
                "table is."
            ),
        )


class TestBodyLengthSane(unittest.TestCase):
    def test_en_body_under_max_length(self) -> None:
        body = _get_notify_body(_load_locale("en.json"))
        self.assertLessEqual(
            len(body),
            _MAX_BODY_LENGTH,
            (
                f"en.json shortcuts.notifyBody length {len(body)} "
                f"exceeds {_MAX_BODY_LENGTH} chars — many OS "
                "notification widgets truncate beyond that point."
            ),
        )

    def test_zh_body_under_max_length(self) -> None:
        body = _get_notify_body(_load_locale("zh-CN.json"))
        self.assertLessEqual(len(body), _MAX_BODY_LENGTH)


class TestModPlaceholderPreserved(unittest.TestCase):
    def test_en_body_keeps_mod_placeholder(self) -> None:
        body = _get_notify_body(_load_locale("en.json"))
        self.assertIn(
            "{{mod}}",
            body,
            (
                "en.json shortcuts.notifyBody must keep the "
                "`{{mod}}` placeholder — keyboard-shortcuts.js "
                "passes `mod` ('Ctrl' / '⌘') as the substitution "
                "parameter, and a hardcoded 'Ctrl' would read "
                "weirdly on macOS."
            ),
        )

    def test_zh_body_keeps_mod_placeholder(self) -> None:
        body = _get_notify_body(_load_locale("zh-CN.json"))
        self.assertIn("{{mod}}", body)


class TestKeyboardJsStillCallsSendNotification(unittest.TestCase):
    """Without this, the body changes here would be invisible
    because showHelp() stopped invoking the notification path."""

    def test_show_help_invokes_send_notification_with_notify_body(self) -> None:
        source = KEYBOARD_JS.read_text(encoding="utf-8")
        self.assertIn(
            "sendNotification(",
            source,
            "keyboard-shortcuts.js showHelp() no longer calls sendNotification.",
        )
        self.assertIn(
            "shortcuts.notifyBody",
            source,
            "keyboard-shortcuts.js showHelp() no longer references shortcuts.notifyBody.",
        )
        self.assertIn(
            "showHelp",
            source,
            "keyboard-shortcuts.js no longer defines showHelp().",
        )


if __name__ == "__main__":
    unittest.main()
