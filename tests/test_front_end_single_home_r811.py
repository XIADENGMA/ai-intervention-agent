"""R811: two blocks of the front end that existed twice now have one home each.

The "thermo-nuclear" review listed them as the cheapest wins; each of them had already
cost two rounds, because a fix to one copy had to be found, repeated and tested in the
other:

* **The Tab focus trap of the modal dialogs.**  ``app.js`` (code-paste dialog,
  ``_modalFocusTrap``) and ``settings-manager.js`` (settings panel,
  ``_settingsFocusTrap``) carried the same ~25 lines, and R586 and R587 are the same bug
  in the two copies.  The loop lives once, in ``DOMSecurity.trapTabFocus``
  (``dom-security.js``, loaded before both dialogs); the dialogs only decide when to call
  it.  The behaviour is proved in ``test_app_modal_focus_trap_loop_r586.py`` and
  ``test_settings_focus_trap_loop_r587.py``; this file guards that no third copy grows
  back and that the helper is loaded before the scripts that call it.
* **The "feedback was submitted" tail of the VS Code webview.**  ``submitWithData`` was a
  253-line function whose success branch (log line, clearing the form of the *submitted*
  task, dropping that task's cached draft, toast, refresh) sat in the middle of the
  network and error handling.  It is ``finishSuccessfulSubmit`` now, reached from exactly
  one place.  R716 (form reset), R809 (another task on screen) and R452 (timeout path)
  read the two functions together.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
WEBVIEW_UI_JS = VSCODE_DIR / "webview-ui.js"

# Third-party bundles that are not ours to restructure.
VENDORED_WEB_UI = {"tex-mml-chtml.js", "prism.js", "marked.js"}


def _first_party_scripts(directory: Path, *, vendored: set[str]) -> list[Path]:
    return sorted(
        path
        for path in directory.glob("*.js")
        if not path.name.endswith(".min.js") and path.name not in vendored
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _body(source: str, header_pattern: str) -> str:
    """Body of a 2-space-indented function of ``webview-ui.js`` (up to its own ``  }``)."""
    match = re.search(
        r"\n  " + header_pattern + r"\([^)]*\) \{\n(.*?)\n  \}\n", source, re.DOTALL
    )
    assert match is not None, f"missing {header_pattern!r}"
    return match.group(1)


class TestTabFocusTrapHasOneHome(unittest.TestCase):
    def test_only_dom_security_walks_the_controls_of_a_panel(self) -> None:
        """The visibility test of the trap (``offsetParent === null``) exists once."""
        holders = [
            path.relative_to(REPO_ROOT).as_posix()
            for directory, vendored in (
                (STATIC_JS, VENDORED_WEB_UI),
                (VSCODE_DIR, set()),
            )
            for path in _first_party_scripts(directory, vendored=vendored)
            if re.search(r"offsetParent\s*===\s*null", _read(path))
        ]
        self.assertEqual(
            holders,
            ["src/ai_intervention_agent/static/js/dom-security.js"],
            msg=(
                "R811 invariant: Tab-trap loop 只允许存在于 DOMSecurity.trapTabFocus。"
                "出现第二份拷贝意味着下一个修复要做两遍 (R586/R587 的教训)。"
            ),
        )

    def test_both_dialogs_call_the_shared_trap_and_have_no_private_one(self) -> None:
        app = _read(STATIC_JS / "app.js")
        settings = _read(STATIC_JS / "settings-manager.js")

        self.assertIn("window.DOMSecurity.trapTabFocus(panel, event)", app)
        self.assertIn("window.DOMSecurity.trapTabFocus(panel, e)", settings)
        for name in ("_modalFocusTrap", "_settingsFocusTrap"):
            self.assertNotIn(name, app)
            self.assertNotIn(name, settings)

    def test_helper_is_loaded_before_the_scripts_that_call_it(self) -> None:
        order = re.findall(r'src="/static/js/([\w.-]+?)\.js\?v=', _read(TEMPLATE))
        for later in ("settings-manager", "app"):
            self.assertIn("dom-security", order)
            self.assertIn(later, order)
            self.assertLess(
                order.index("dom-security"),
                order.index(later),
                msg=(
                    f"R811 invariant: dom-security.js 必须先于 {later}.js 加载, "
                    "否则对话框的 Tab 焦点陷阱不可用。"
                ),
            )


class TestWebviewSubmitSuccessTailHasOneHome(unittest.TestCase):
    def test_success_tail_is_one_function_reached_from_one_place(self) -> None:
        source = _read(WEBVIEW_UI_JS)

        self.assertEqual(source.count("function finishSuccessfulSubmit("), 1)
        self.assertEqual(
            source.count("finishSuccessfulSubmit("), 2
        )  # definition + call
        self.assertEqual(source.count("Feedback submitted successfully"), 1)

        submit = _body(source, r"async function submitWithData")
        self.assertIn(
            "return finishSuccessfulSubmit(taskIdToSubmit, responsePath)", submit
        )

        finish = _body(source, r"function finishSuccessfulSubmit")
        self.assertIn("Feedback submitted successfully", finish)
        self.assertIn("isSubmitTargetStillCurrent(taskIdToSubmit)", finish)
        self.assertIn("showToast(t('ui.submit.success')", finish)

    def test_submit_with_data_no_longer_resets_the_form_itself(self) -> None:
        submit = _body(_read(WEBVIEW_UI_JS), r"async function submitWithData")

        for fragment in (
            "textarea.value = ''",
            "uploadedImages = []",
            "checkbox.checked = false",
            "delete taskTextareaContents",
            "delete taskOptionsStates",
            "delete taskImages",
        ):
            self.assertNotIn(fragment, submit, msg=fragment)


if __name__ == "__main__":
    unittest.main()
