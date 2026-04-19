"""``_interpolateMustache`` 的原型污染加固（Batch-1.5 H4）。

Snyk SNYK-JS-I18NEXT-1065979 记录过 i18next 的原型污染路径——可控参数名
命中 ``Object.prototype`` 继承属性就把 runtime 内部漏到 UI。本仓
``_interpolateMustache`` 直接走 ``params[name]``，同类 payload
（``{{__proto__}}`` / ``{{constructor}}`` / ``{{toString}}`` / ``{{hasOwnProperty}}``）
即便 ``params = {}`` 也会把 ``function Object() { [native code] }`` /
``[object Object]`` 渲染出去：既是正确性 bug，也是信息泄漏红线。

合约（每处 ``{{name}}``）：
  1. 仅当 ``params`` 自有 own 属性命中时替换（``hasOwnProperty.call``）；
  2. 即便 own 属性里塞了 ``__proto__`` / ``constructor`` / ``prototype``
     也硬拒，给未来合并不受信 JSON 的场景留后手；
  3. 命不中保留字面 ``{{x}}``，维持「缺参保占位」既有合约。

两份 i18n.js 都要通过；任一回归必须立刻挂测试，避免一半先沾上 bug。
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


# 每条 case 必须原样返回模板字面，绝不能冒出 ``[object Object]`` / ``function … [native code]``
POLLUTION_CASES = [
    ("proto_from_empty_params", "hello {{__proto__}}", "{}"),
    ("ctor_from_empty_params", "hello {{constructor}}", "{}"),
    ("proto_keyword", "hi {{prototype}}", "{}"),
    ("tostring_from_empty_params", "hello {{toString}}", "{}"),
    ("hasownprop_from_empty_params", "hello {{hasOwnProperty}}", "{}"),
    ("propertyisenumerable", "hi {{propertyIsEnumerable}}", "{}"),
    # 非空 params 也不能因「own 名与保留名冲突」的缝隙漏出原型方法
    ("ctor_with_unrelated_own_prop", "hi {{constructor}}", '{"name":"Ada"}'),
    (
        "proto_with_unrelated_own_prop",
        "hi {{__proto__}}",
        '{"name":"Ada"}',
    ),
    # null-prototype params 也不得绕过（实测不泄，但钉住行为防将来重构退防线）
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
            f"case={label!r} 漏出原型内容: got={out!r} 期望字面 {template!r}",
        )

    def test_own_properties_still_interpolate_normally(self) -> None:
        out = _render(self.I18N_PATH, "hello {{name}}", '{"name":"Ada"}')
        self.assertEqual(out, "hello Ada")

    def test_unknown_own_key_preserves_literal(self) -> None:
        out = _render(self.I18N_PATH, "hello {{name}}", "{}")
        self.assertEqual(out, "hello {{name}}")

    def test_reserved_own_key_still_blocked(self) -> None:
        # 即便 caller 用 ``Object.defineProperty`` 硬塞 ``__proto__`` own property，也必须拒绝
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
