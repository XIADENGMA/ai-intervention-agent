"""locale 查找加固（Batch-1.5 H3）：``resolve(key, lang)`` 绝不能遍历
``Object.prototype``。

威胁：``resolve`` 按 dotted-key 下潜（``node = node[part]``）。恶意或被污染
的 locale 对象可以让 ``ui.__proto__.constructor.name`` 泄出 runtime 内部
（Snyk 对 i18next 有同类 CVE）。即便没有主动攻击，任何 shared dep 污染
``Object.prototype`` 也会让 ``resolve`` 返回 locale 从未声明的字符串。

合约（每段必须）：
  1. 拒绝 ``__proto__`` / ``constructor`` / ``prototype`` 三个关键字；
  2. 用 ``Object.prototype.hasOwnProperty.call`` 判断，原型链继承属性
     （如 ``toString``）不算命中，避免 ``typeof === 'string'`` 兜底把问题
     降级成 missing-key 掩盖。
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


# ``resolve('x.<pollutant>.y', 'en')`` 必须返回原始 key（miss）；每 case 用
# 全新 locale 对象，测试保持 hermetic（不受 runtime 原型链状态影响）
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
            f"case={label!r} 泄漏了原型链值: got={out!r}; 期望退化为原始 key {key!r}",
        )

    def test_ownership_guard_allows_normal_keys(self) -> None:
        out = _probe(self.I18N_PATH, '{ ui: { btn: { save: "Save" } } }', "ui.btn.save")
        self.assertEqual(out, "Save")

    def test_plain_missing_key_still_returns_raw_key(self) -> None:
        out = _probe(self.I18N_PATH, "{}", "ui.btn.save")
        self.assertEqual(out, "ui.btn.save")

    def test_locale_injected_proto_value_not_returned(self) -> None:
        # locale 里塞 ``__proto__`` own property 也必须拒绝，不让攻击者可控数据走字面 key 漏出
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
