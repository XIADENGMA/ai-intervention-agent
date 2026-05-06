"""npm 依赖安全 overrides 回归锁

R36 在根 ``package.json`` 加入 ``overrides`` 字段，将以下 dev-only 传递依赖
强制提升到带补丁的版本（``npm audit`` 之前报告 9 处漏洞 / 5 high；overrides
落地后 ``npm audit`` 报 0 漏洞）：

* ``flatted: ^3.4.2`` —— 修复 ``GHSA-25h7-pfq9-p65f`` (DoS via parse() 递归) 与
  ``GHSA-rf6f-7fwh-wjgh`` (Prototype Pollution via parse())。
* ``serialize-javascript: ^7.0.5`` —— 修复 ``GHSA-5c6j-r48x-rmvq``
  (RCE via RegExp.flags / Date.toISOString) 与 ``GHSA-qj8w-gfj5-8c6v``
  (CPU Exhaustion DoS)。``mocha 11.x`` 默认仍 pin ``serialize-javascript ^6.0.2``，
  必须用 npm overrides 才能拉到 7.0.5。
* ``diff: ^8.0.3`` —— 修复 ``GHSA-73rr-hh4g-fpgx``
  (jsdiff parsePatch / applyPatch DoS)。``mocha 11.x`` pin ``diff ^7.0.0``，
  同样必须用 overrides。

本测试做静态校验：``package.json`` 必须保留这三个 overrides。如果未来有人
"清理" ``overrides`` 块，CI 会立刻 fail，避免静默回退漏洞补丁。

不直接调用 ``npm audit``：
1. 网络请求（CI 离线时会假阳性 fail）；
2. CI 环境不一定装了 npm；
3. 静态校验已经能拦截最常见的 regression 路径（人为删 overrides）。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_PACKAGE_JSON = REPO_ROOT / "package.json"

REQUIRED_OVERRIDES: dict[str, str] = {
    "flatted": "^3.4.2",
    "serialize-javascript": "^7.0.5",
    "diff": "^8.0.3",
}

_SEMVER_RE = re.compile(
    r"^\^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-[\w.+-]+)?$"
)


def _load_root_pkg() -> dict:
    return json.loads(ROOT_PACKAGE_JSON.read_text(encoding="utf-8"))


def _parse_caret_min(spec: str) -> tuple[int, int, int]:
    m = _SEMVER_RE.match(spec)
    if not m:
        raise ValueError(f"unsupported semver spec: {spec!r}")
    return int(m.group("major")), int(m.group("minor")), int(m.group("patch"))


class TestNpmSecurityOverridesR36(unittest.TestCase):
    def test_root_package_has_overrides_block(self) -> None:
        """根 ``package.json`` 必须存在 ``overrides`` 字段。"""
        pkg = _load_root_pkg()
        self.assertIn(
            "overrides",
            pkg,
            "package.json 缺少 overrides 字段；R36 安全补丁会回退到带漏洞的版本",
        )
        self.assertIsInstance(
            pkg["overrides"],
            dict,
            "package.json overrides 必须是 object",
        )

    def test_each_required_override_present(self) -> None:
        """三个 overrides 缺一不可，且 caret 下限必须 ≥ patched 版本。"""
        pkg = _load_root_pkg()
        overrides = pkg.get("overrides", {})
        for name, expected_caret in REQUIRED_OVERRIDES.items():
            with self.subTest(package=name):
                self.assertIn(
                    name,
                    overrides,
                    (
                        f"package.json overrides 缺少 {name!r}；"
                        f"必须 pin 至 {expected_caret}（含安全补丁）"
                    ),
                )
                actual_spec = overrides[name]
                self.assertIsInstance(actual_spec, str)
                actual = _parse_caret_min(actual_spec)
                expected = _parse_caret_min(expected_caret)
                self.assertGreaterEqual(
                    actual,
                    expected,
                    (
                        f"package.json overrides[{name!r}] = {actual_spec}，"
                        f"低于 R36 要求的 {expected_caret}（含安全补丁）"
                    ),
                )

    def test_overrides_only_contain_security_pins(self) -> None:
        """防止 overrides 被滥用为 ad-hoc 版本管理槽。

        当前策略：只把 overrides 用于安全漏洞补丁。如果未来加入功能性
        override，应当在本测试 ``REQUIRED_OVERRIDES`` 同步登记，并且在
        commit message 里说明原因。
        """
        pkg = _load_root_pkg()
        overrides = pkg.get("overrides", {})
        unexpected = set(overrides) - set(REQUIRED_OVERRIDES)
        self.assertFalse(
            unexpected,
            (
                f"package.json overrides 出现未登记 key: {sorted(unexpected)}；"
                "若是新的安全补丁，请同时更新 tests/test_npm_security_overrides_r36.py 的 "
                "REQUIRED_OVERRIDES，方便审计追踪"
            ),
        )

    def test_root_package_overrides_does_not_silently_drop_workspace(self) -> None:
        """``overrides`` 是 npm 顶层独有特性，加入 overrides 不应误删 workspaces。"""
        pkg = _load_root_pkg()
        self.assertIn(
            "workspaces",
            pkg,
            "root package.json 必须保留 workspaces 字段",
        )
        self.assertIn(
            "packages/vscode",
            pkg["workspaces"],
            "workspaces 必须包含 packages/vscode",
        )


if __name__ == "__main__":
    unittest.main()
