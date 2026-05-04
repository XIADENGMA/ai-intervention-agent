"""单元测试：``scripts/bump_version.py`` 其余 6 个文件类型的 update/extract helper。

历史背景
---------
``scripts/bump_version.py`` 是发布流程的核心齿轮 —— 一旦 helper 之
一行为漂移（比如有人把 ``[[package]]`` 写成 ``[package]`` 然后
``_update_uv_lock_version`` 默默没匹配上），下一次 ``bump_version.py
1.5.23`` 会让某个文件偷偷停留在旧版本，``--check`` 也会跟着撒谎
（如果两个 helper 用同一份"看起来对"的正则，二者一起错就互相对得上）。

之前 v1.5.x 已经被 ``CITATION.cff`` **没纳入** 的事故咬过一次（见
``tests/test_bump_version_citation.py``）。本文件给剩下的六个文件
类型加对称测试，把 helper 行为冻结到合约层面：

  - **pyproject.toml**：``_update_pyproject_version`` /
    ``_extract_pyproject_version`` —— 行级 regex on
    ``[project]`` 节内的 ``version = "X.Y.Z"``；
  - **uv.lock**：``_update_uv_lock_version`` /
    ``_extract_uv_lock_version`` —— 多 ``[[package]]`` 数组，
    必须命中 ``name = "ai-intervention-agent"`` 的那条；
  - **package.json / packages/vscode/package.json**：
    ``_update_json_version_text`` —— 顶层 ``version`` 字段；
  - **package-lock.json**：``_update_package_lock_text`` ——
    三处 ``version`` 同步（``data.version`` /
    ``data.packages[""].version`` /
    ``data.packages["packages/vscode"].version``）；
  - **.github/ISSUE_TEMPLATE/bug_report.yml**：
    ``_update_bug_template`` /
    ``_extract_bug_template_example_version`` ——
    ``placeholder: e.g. X.Y.Z`` 行。

设计原则
--------
- **合约级断言**：测试每个 helper 在合法输入上 round-trip 正确，
  在边角输入（pre-release / build-metadata / 含点号或 hyphen
  的版本号）上不出错；
- **副作用保留**：除目标 version 行外的其他内容（``[tool.*]``
  其他段、``dependencies``、``description`` 等）字节级保留；
- **失败路径**：缺 ``[project]`` 节、找不到目标 ``[[package]]``、
  非 dict 顶层 JSON —— 必须 raise 而不是静默；
- **真仓 sanity**：每个 helper 至少跑一次实际仓库文件（``pyproject``
  ``uv.lock`` 等真实路径），确保正则与生产文件对得上。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.bump_version import (
    _extract_bug_template_example_version,
    _extract_pyproject_version,
    _extract_uv_lock_version,
    _update_bug_template,
    _update_json_version_text,
    _update_package_lock_text,
    _update_pyproject_version,
    _update_uv_lock_version,
)

# -----------------------------------------------------------------------------
# pyproject.toml
# -----------------------------------------------------------------------------


SAMPLE_PYPROJECT = """\
[build-system]
requires = ["hatchling"]

[project]
name = "ai-intervention-agent"
version = "1.5.22"
description = "Demo description"
authors = [
    { name = "xiadengma" },
]

[tool.ruff]
line-length = 100
"""


class TestPyprojectHelpers(unittest.TestCase):
    def test_extract_canonical_version(self) -> None:
        self.assertEqual(_extract_pyproject_version(SAMPLE_PYPROJECT), "1.5.22")

    def test_update_replaces_version(self) -> None:
        out = _update_pyproject_version(SAMPLE_PYPROJECT, "1.5.23")
        self.assertEqual(_extract_pyproject_version(out), "1.5.23")

    def test_update_preserves_other_project_fields(self) -> None:
        out = _update_pyproject_version(SAMPLE_PYPROJECT, "1.5.23")
        # 同 [project] 段的其他字段不能被擦掉
        self.assertIn('name = "ai-intervention-agent"', out)
        self.assertIn('description = "Demo description"', out)
        self.assertIn("authors = [", out)

    def test_update_preserves_other_sections(self) -> None:
        # [build-system] / [tool.ruff] 不能被影响
        out = _update_pyproject_version(SAMPLE_PYPROJECT, "1.5.23")
        self.assertIn("[build-system]", out)
        self.assertIn('requires = ["hatchling"]', out)
        self.assertIn("[tool.ruff]", out)
        self.assertIn("line-length = 100", out)

    def test_update_raises_when_project_section_missing(self) -> None:
        text = '[tool.ruff]\nline-length = 100\nversion = "0.0.0"\n'
        with self.assertRaises(ValueError):
            _update_pyproject_version(text, "1.5.23")

    def test_update_raises_when_version_missing_under_project(self) -> None:
        text = '[project]\nname = "demo"\ndescription = "no version yet"\n'
        with self.assertRaises(ValueError):
            _update_pyproject_version(text, "1.5.23")

    def test_handles_pre_release_versions(self) -> None:
        for new in ("1.5.23-rc.1", "2.0.0-alpha.0", "10.20.30+build.42"):
            with self.subTest(new=new):
                out = _update_pyproject_version(SAMPLE_PYPROJECT, new)
                self.assertEqual(_extract_pyproject_version(out), new)

    def test_real_pyproject_parses(self) -> None:
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        ver = _extract_pyproject_version(text)
        self.assertIsNotNone(
            ver, "real pyproject.toml must expose a version under [project]"
        )
        self.assertRegex(
            ver or "",
            r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
        )


# -----------------------------------------------------------------------------
# uv.lock
# -----------------------------------------------------------------------------


SAMPLE_UV_LOCK = """\
version = 1
requires-python = ">=3.11"

[[package]]
name = "anyio"
version = "4.4.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "ai-intervention-agent"
version = "1.5.22"
source = { editable = "." }
dependencies = [
    { name = "anyio" },
]

[[package]]
name = "httpx"
version = "0.27.0"
source = { registry = "https://pypi.org/simple" }
"""


class TestUvLockHelpers(unittest.TestCase):
    def test_extract_picks_target_package_only(self) -> None:
        self.assertEqual(_extract_uv_lock_version(SAMPLE_UV_LOCK), "1.5.22")

    def test_update_only_touches_target_package(self) -> None:
        out = _update_uv_lock_version(SAMPLE_UV_LOCK, "1.5.23")
        self.assertEqual(_extract_uv_lock_version(out), "1.5.23")
        # 其他 package 的 version 不受影响
        self.assertIn('name = "anyio"\nversion = "4.4.0"', out)
        self.assertIn('name = "httpx"\nversion = "0.27.0"', out)

    def test_update_preserves_dependencies_block(self) -> None:
        out = _update_uv_lock_version(SAMPLE_UV_LOCK, "1.5.23")
        self.assertIn("dependencies = [", out)
        self.assertIn('{ name = "anyio" }', out)

    def test_update_raises_when_target_package_absent(self) -> None:
        # 把 ai-intervention-agent 那块拿掉
        text = SAMPLE_UV_LOCK.replace(
            '[[package]]\nname = "ai-intervention-agent"\nversion = "1.5.22"\n'
            'source = { editable = "." }\ndependencies = [\n    { name = "anyio" },\n]\n\n',
            "",
        )
        with self.assertRaises(ValueError):
            _update_uv_lock_version(text, "1.5.23")

    def test_real_uv_lock_parses(self) -> None:
        text = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
        ver = _extract_uv_lock_version(text)
        self.assertIsNotNone(
            ver, 'real uv.lock must expose a version for "ai-intervention-agent"'
        )
        self.assertRegex(
            ver or "",
            r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
        )


# -----------------------------------------------------------------------------
# package.json / packages/vscode/package.json
# -----------------------------------------------------------------------------


SAMPLE_PACKAGE_JSON = """\
{
  "name": "ai-intervention-agent-frontend",
  "version": "1.5.22",
  "scripts": {
    "build": "esbuild ..."
  },
  "devDependencies": {
    "esbuild": "0.21.5"
  }
}
"""


class TestJsonVersionHelper(unittest.TestCase):
    def test_update_changes_top_level_version(self) -> None:
        out = _update_json_version_text(
            SAMPLE_PACKAGE_JSON, "1.5.23", label="package.json"
        )
        data = json.loads(out)
        self.assertEqual(data["version"], "1.5.23")

    def test_preserves_sibling_fields_and_ordering(self) -> None:
        out = _update_json_version_text(
            SAMPLE_PACKAGE_JSON, "1.5.23", label="package.json"
        )
        data = json.loads(out)
        self.assertEqual(data["name"], "ai-intervention-agent-frontend")
        self.assertEqual(data["scripts"]["build"], "esbuild ...")
        self.assertEqual(data["devDependencies"]["esbuild"], "0.21.5")

    def test_output_ends_with_newline(self) -> None:
        # 历史细节：bump_version 一直 append 一个 \n 末尾，pre-commit 的
        # `end-of-file-fixer` 也假设这一点。把它锁死。
        out = _update_json_version_text(
            SAMPLE_PACKAGE_JSON, "1.5.23", label="package.json"
        )
        self.assertTrue(out.endswith("\n"))

    def test_raises_on_non_object_top_level(self) -> None:
        for bad in ('["a", "b"]\n', '"just a string"\n', "42\n"):
            with self.subTest(input=bad), self.assertRaises(ValueError):
                _update_json_version_text(bad, "1.5.23", label="weird.json")


# -----------------------------------------------------------------------------
# package-lock.json
# -----------------------------------------------------------------------------


SAMPLE_PACKAGE_LOCK = """\
{
  "name": "ai-intervention-agent-frontend",
  "version": "1.5.22",
  "lockfileVersion": 3,
  "packages": {
    "": {
      "name": "ai-intervention-agent-frontend",
      "version": "1.5.22",
      "dependencies": {
        "lodash": "^4.17.21"
      }
    },
    "packages/vscode": {
      "name": "ai-intervention-agent-vscode",
      "version": "1.5.22"
    },
    "node_modules/lodash": {
      "version": "4.17.21",
      "license": "MIT"
    }
  }
}
"""


class TestPackageLockHelper(unittest.TestCase):
    def test_updates_all_three_version_locations(self) -> None:
        out = _update_package_lock_text(SAMPLE_PACKAGE_LOCK, "1.5.23")
        data = json.loads(out)
        self.assertEqual(data["version"], "1.5.23")
        self.assertEqual(data["packages"][""]["version"], "1.5.23")
        self.assertEqual(data["packages"]["packages/vscode"]["version"], "1.5.23")

    def test_does_not_touch_third_party_package_versions(self) -> None:
        out = _update_package_lock_text(SAMPLE_PACKAGE_LOCK, "1.5.23")
        data = json.loads(out)
        # node_modules/lodash 的 version 是上游 lodash 的版本，绝对不能被改
        self.assertEqual(data["packages"]["node_modules/lodash"]["version"], "4.17.21")

    def test_preserves_lockfile_version_and_dependencies(self) -> None:
        out = _update_package_lock_text(SAMPLE_PACKAGE_LOCK, "1.5.23")
        data = json.loads(out)
        self.assertEqual(data["lockfileVersion"], 3)
        self.assertEqual(data["packages"][""]["dependencies"]["lodash"], "^4.17.21")

    def test_handles_missing_optional_packages_keys(self) -> None:
        # vscode 子工作区不存在 / packages 不是 dict 的情况都不应该崩
        text = '{"name": "demo", "version": "1.0.0", "lockfileVersion": 3}\n'
        out = _update_package_lock_text(text, "2.0.0")
        data = json.loads(out)
        self.assertEqual(data["version"], "2.0.0")

    def test_raises_on_non_object_top_level(self) -> None:
        with self.assertRaises(ValueError):
            _update_package_lock_text("[]\n", "1.0.0")


# -----------------------------------------------------------------------------
# .github/ISSUE_TEMPLATE/bug_report.yml
# -----------------------------------------------------------------------------


SAMPLE_BUG_REPORT = """\
name: Bug Report
description: File a bug
labels: ["bug"]
body:
  - type: input
    id: version
    attributes:
      label: Version
      placeholder: e.g. 1.5.22
    validations:
      required: true
  - type: textarea
    id: repro
    attributes:
      label: Reproduction steps
      placeholder: |
        1. Run …
        2. See …
"""


class TestBugTemplateHelpers(unittest.TestCase):
    def test_extract_returns_placeholder_version(self) -> None:
        self.assertEqual(
            _extract_bug_template_example_version(SAMPLE_BUG_REPORT), "1.5.22"
        )

    def test_update_replaces_only_eg_placeholder(self) -> None:
        out = _update_bug_template(SAMPLE_BUG_REPORT, "1.5.23")
        self.assertEqual(_extract_bug_template_example_version(out), "1.5.23")

    def test_update_does_not_touch_textarea_placeholder_block(self) -> None:
        # textarea 的 `placeholder: |` 多行块不能被误改 —— `\n        1. Run …`
        # 之类的内容必须保留
        out = _update_bug_template(SAMPLE_BUG_REPORT, "1.5.23")
        self.assertIn("placeholder: |", out)
        self.assertIn("1. Run …", out)
        self.assertIn("2. See …", out)

    def test_real_bug_report_parses(self) -> None:
        text = (REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(
            encoding="utf-8"
        )
        ver = _extract_bug_template_example_version(text)
        self.assertIsNotNone(
            ver, "real bug_report.yml must expose a `placeholder: e.g. X.Y.Z` line"
        )
        self.assertRegex(
            ver or "",
            r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
        )


# -----------------------------------------------------------------------------
# 跨文件 round-trip：把所有 helper 同步到同一新版本，再提取，应该全部一致
# -----------------------------------------------------------------------------


class TestCrossFileRoundTrip(unittest.TestCase):
    """合约级 sanity：同一目标版本号灌进所有 helper，然后 extract 出来必须都相等。"""

    def test_all_helpers_converge_on_same_version(self) -> None:
        target = "9.9.9-test.1"

        out_pyproject = _update_pyproject_version(SAMPLE_PYPROJECT, target)
        out_uv_lock = _update_uv_lock_version(SAMPLE_UV_LOCK, target)
        out_package_json = _update_json_version_text(
            SAMPLE_PACKAGE_JSON, target, label="package.json"
        )
        out_package_lock = _update_package_lock_text(SAMPLE_PACKAGE_LOCK, target)
        out_bug = _update_bug_template(SAMPLE_BUG_REPORT, target)

        self.assertEqual(_extract_pyproject_version(out_pyproject), target)
        self.assertEqual(_extract_uv_lock_version(out_uv_lock), target)
        self.assertEqual(json.loads(out_package_json)["version"], target)
        lock_data = json.loads(out_package_lock)
        self.assertEqual(lock_data["version"], target)
        self.assertEqual(lock_data["packages"][""]["version"], target)
        self.assertEqual(lock_data["packages"]["packages/vscode"]["version"], target)
        self.assertEqual(_extract_bug_template_example_version(out_bug), target)


if __name__ == "__main__":
    unittest.main()
