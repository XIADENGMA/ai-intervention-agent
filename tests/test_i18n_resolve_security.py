"""Locale-lookup hardening: ``resolve(key, lang)`` must never walk
``Object.prototype``.

Threat model
------------
``resolve`` uses dotted-key paths like ``ui.btn.save`` to descend into
the registered locale dictionary. The descent is ``node = node[part]``,
which means a malicious or accidentally-polluted locale object could
let an attacker exfiltrate runtime internals via a key such as
``__proto__.constructor.name`` — the same family of issues Snyk has
documented against i18next's own lookup path. Even without an active
attacker, Object.prototype pollution elsewhere in the runtime (e.g. a
shared dependency) would let ``resolve`` silently return strings the
locale bundle never declared.

Fix contract
------------
For every dotted segment ``resolve`` must:
  1. Refuse to traverse the three canonical pollution names
     (``__proto__``, ``constructor``, ``prototype``). A key like
     ``ui.__proto__.leak`` MUST resolve as missing, not as whatever
     ``Object.prototype.leak`` returns.
  2. Use ``Object.prototype.hasOwnProperty.call(node, part)`` so
     values inherited through the prototype chain never count as
     "found". Previously ``locales.en.toString`` would have returned
     ``"function toString() { [native code] }"`` — which then fails
     the ``typeof === 'string'`` guard and becomes a missing-key
     miss, masking the real issue; this test asserts the stricter
     guard so the class of bug is closed at the source.
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


def _probe(i18n_path: Path, locale_expr: str, key: str) -> str:
    script = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: 'en' };
        require(%(path)s);
        const api = globalThis.AIIA_I18N;
        const data = %(locale)s;
        api.registerLocale('en', data);
        api.setLang('en');
        process.stdout.write(api.t(%(key)s));
        """
    ) % {
        "path": json.dumps(str(i18n_path)),
        "locale": locale_expr,
        "key": json.dumps(key),
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


# ``resolve('x.<pollutant>.y', 'en')`` must return the raw key (missing)
# no matter what the runtime's prototype chain looks like. We build
# fresh locale objects per case so the test is hermetic.
POLLUTION_KEYS = [
    ("proto_chain", "__proto__.toString"),
    ("ctor_chain", "constructor.name"),
    ("proto_keyword", "prototype.foo"),
    ("toString_leak", "toString"),
    ("hasOwnProperty_leak", "hasOwnProperty"),
    ("isPrototypeOf_leak", "isPrototypeOf"),
]


class _ResolveSecurityMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def _assert_missing(self, label: str, key: str) -> None:
        out = _probe(self.I18N_PATH, "{}", key)
        self.assertEqual(
            out,
            key,
            f"case={label!r} resolved a prototype-chain value: got={out!r}; "
            f"expected raw-key miss fallback {key!r}",
        )

    def test_ownership_guard_allows_normal_keys(self) -> None:
        out = _probe(self.I18N_PATH, '{ ui: { btn: { save: "Save" } } }', "ui.btn.save")
        self.assertEqual(out, "Save")

    def test_plain_missing_key_still_returns_raw_key(self) -> None:
        out = _probe(self.I18N_PATH, "{}", "ui.btn.save")
        self.assertEqual(out, "ui.btn.save")

    def test_locale_injected_proto_value_not_returned(self) -> None:
        # Simulate a hand-crafted locale where the attacker managed to
        # put a ``__proto__``-shaped dictionary entry. ``resolve`` must
        # ignore it entirely — we don't let attacker-controlled locale
        # data reach the output even via a literal ``__proto__`` key.
        locale_expr = (
            "(function(){ const o = {}; "
            'Object.defineProperty(o, "__proto__", { value: { leak: "pwn" }, enumerable: true }); '
            "return { ui: o }; })()"
        )
        out = _probe(self.I18N_PATH, locale_expr, "ui.__proto__.leak")
        self.assertEqual(out, "ui.__proto__.leak")


def _make_case(label: str, key: str):
    def _t(self: _ResolveSecurityMixin) -> None:
        self._assert_missing(label, key)

    _t.__name__ = f"test_{label}"
    return _t


for _label, _key in POLLUTION_KEYS:
    setattr(
        _ResolveSecurityMixin,
        f"test_{_label}",
        _make_case(_label, _key),
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestResolveSecurityWebUI(_ResolveSecurityMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestResolveSecurityVSCode(_ResolveSecurityMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


if __name__ == "__main__":
    unittest.main()
