"""Prototype-pollution defence for ``_interpolateMustache``.

Background
----------
Snyk SNYK-JS-I18NEXT-1065979 tracked a prototype-pollution pathway in
i18next where attacker-controlled parameter names could reach
``Object.prototype``-inherited properties and leak internals into the
rendered UI. Our own ``_interpolateMustache`` accesses ``params[name]``
directly, so the same family of payloads — ``{{__proto__}}``,
``{{constructor}}``, ``{{toString}}``, ``{{hasOwnProperty}}`` — bleeds
``function Object() { [native code] }`` / ``[object Object]`` into the
translated string even when ``params`` is an empty ``{}``. Rendering
prototype-walked values into user-visible text is both a correctness
bug (localised strings shouldn't contain V8 native-function prints)
and a classic security red flag (information disclosure about the
runtime's object shape).

Fix contract
------------
For every ``{{name}}`` placeholder the renderer must:
  1. Only substitute when ``params`` owns ``name`` as its *own*
     enumerable property (``Object.prototype.hasOwnProperty.call``).
  2. Hard-reject the three canonical pollution vectors
     (``__proto__``, ``constructor``, ``prototype``) even if somehow
     set as own properties, so a future bug that merges untrusted
     JSON straight into ``params`` still can't leak.
  3. Leave the literal placeholder in place when the lookup fails
     (preserves the existing "undefined param keeps `{{x}}`" contract
     the rest of the i18n pipeline relies on).

This file pins that behaviour across both ``static/js/i18n.js`` and
``packages/vscode/i18n.js`` so a regression in one half is caught
before the other half benefits.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBUI_I18N = ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N = ROOT / "packages" / "vscode" / "i18n.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _render(i18n_path: Path, template: str, params_json: str) -> str:
    script = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: 'en' };
        require(%(path)s);
        const api = globalThis.AIIA_I18N;
        api.registerLocale('en', { greet: %(tpl)s });
        api.setLang('en');
        const params = %(params)s;
        process.stdout.write(api.t('greet', params));
        """
    ) % {
        "path": json.dumps(str(i18n_path)),
        "tpl": json.dumps(template),
        "params": params_json,
    }
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


# Every one of these MUST produce the literal template back, not any
# flavour of "[object Object]" or "function … { [native code] }".
POLLUTION_CASES = [
    ("proto_from_empty_params", "hello {{__proto__}}", "{}"),
    ("ctor_from_empty_params", "hello {{constructor}}", "{}"),
    ("proto_keyword", "hi {{prototype}}", "{}"),
    ("tostring_from_empty_params", "hello {{toString}}", "{}"),
    ("hasownprop_from_empty_params", "hello {{hasOwnProperty}}", "{}"),
    ("propertyisenumerable", "hi {{propertyIsEnumerable}}", "{}"),
    # Even non-empty params must not leak prototype methods through the
    # gaps where an "own" name collides with a dangerous reserved word.
    ("ctor_with_unrelated_own_prop", "hi {{constructor}}", '{"name":"Ada"}'),
    (
        "proto_with_unrelated_own_prop",
        "hi {{__proto__}}",
        '{"name":"Ada"}',
    ),
    # Null-prototype params shouldn't bypass either (they don't leak in
    # practice, but pin the behaviour so a future refactor can't swap
    # the guard out).
    (
        "tostring_with_null_proto_params",
        "hi {{toString}}",
        'Object.create(null, { name: { value: "Ada", enumerable: true } })',
    ),
]


class _InterpolationSecurityMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def _assert_literal_preserved(
        self, label: str, template: str, params_json: str
    ) -> None:
        out = _render(self.I18N_PATH, template, params_json)
        self.assertEqual(
            out,
            template,
            f"case={label!r} leaked prototype contents: got={out!r} expect literal={template!r}",
        )

    def test_own_properties_still_interpolate_normally(self) -> None:
        out = _render(self.I18N_PATH, "hello {{name}}", '{"name":"Ada"}')
        self.assertEqual(out, "hello Ada")

    def test_unknown_own_key_preserves_literal(self) -> None:
        out = _render(self.I18N_PATH, "hello {{name}}", "{}")
        self.assertEqual(out, "hello {{name}}")

    def test_reserved_own_key_still_blocked(self) -> None:
        # Even if a caller manages to set ``__proto__`` as a genuine own
        # property (e.g. via ``Object.defineProperty``), the renderer
        # MUST still refuse — attacker-controlled JSON merged straight
        # into params shouldn't become an exfiltration vector.
        out = _render(
            self.I18N_PATH,
            "hi {{__proto__}}",
            'Object.defineProperty({}, "__proto__", { value: "leaked", enumerable: true, writable: true })',
        )
        self.assertEqual(out, "hi {{__proto__}}")


def _make_case(label: str, template: str, params_json: str):
    def _t(self: _InterpolationSecurityMixin) -> None:
        self._assert_literal_preserved(label, template, params_json)

    _t.__name__ = f"test_{label}"
    return _t


for _label, _template, _params_json in POLLUTION_CASES:
    setattr(
        _InterpolationSecurityMixin,
        f"test_{_label}",
        _make_case(_label, _template, _params_json),
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestInterpSecurityWebUI(_InterpolationSecurityMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestInterpSecurityVSCode(_InterpolationSecurityMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


if __name__ == "__main__":
    unittest.main()
