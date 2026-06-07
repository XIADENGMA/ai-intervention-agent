"""R416 · Version quintet sync invariant (cycle-47 #C1, **release infrastructure
强化 — 防 v1.7.5-style 多源 version drift release**)。

项目维护 5+ 个版本号来源, 历史上 v1.7.5 release 因为 ``pyproject.toml``
版本号已 bump 但 ``package.json`` 未同步导致 release 失败 (详见
``docs/release-checklist.md:71`` "B.1 Triplet sync (failure mode: v1.7.5
released with pyproject.toml ahead of package.json)"). R341 / R322 等历史
invariant 部分覆盖, 但缺少**单一 invariant 同时锁定所有 5+ 来源**。

R416 是 **完整版本来源 quintet sync invariant**, 一次性锁住:

1. ``pyproject.toml`` ``[project] version = "X.Y.Z"``
2. ``CITATION.cff`` ``version: "X.Y.Z"``
3. ``package.json`` ``"version": "X.Y.Z"`` (npm root)
4. ``packages/vscode/package.json`` ``"version": "X.Y.Z"`` (VS Code 插件子包)
5. ``package-lock.json`` 两处 (root metadata + packages."" self-reference)

可选第 6 源 ``uv.lock`` (含 ai-intervention-agent 自包 version), 但
``uv.lock`` 是 generated artifact 由 ``uv`` 工具自动维护, 不要求与其他源
严格同步 (uv 可能 lag 几秒), 因此不在本 invariant 锁定范围。

R416 invariant (4 层)
---------------------

1. **Layer 1 (Anchor)**: 所有 5 个源文件存在 + 含可解析的 version 字段;
2. **Layer 2 (Quintet 一致性)**: 所有 5 个版本号严格相等 (字符串完全相等,
   不做 semver normalization);
3. **Layer 3 (Semver 格式)**: 版本号匹配 ``^\\d+\\.\\d+\\.\\d+(-\\w+)?$`` (允许 prerelease tag);
4. **Layer 4 (lineage marker)**: release infrastructure + v1.7.5 历史教训
   引用。

为什么 quintet 不是 triplet
---------------------------

历史 release-checklist 称之为 "triplet" (pyproject.toml + CITATION.cff +
package.json), 但实际项目演化新增了 ``packages/vscode/package.json`` (cycle-30+
VS Code 插件子包) 和 ``package-lock.json`` 两处, 所以现状是 quintet (5 源)
或 sextet (6 源, 若计入 package-lock.json 的两处). R416 称之为 quintet 是
基于 "version 字段名" 计数:
- pyproject.toml (1)
- CITATION.cff (1)
- package.json (1)
- packages/vscode/package.json (1)
- package-lock.json (1, 但实际有 2 处 — root + packages."")

5 个文件, 6 个 version 字段。

R416 vs R341
------------

R341 是 v1.8.1 release prep 时的具体版本号锁 (硬编码 "1.8.1"), 每次 release
都要修改。R416 是 **结构化 invariant** — 不锁具体版本号, 只锁 "所有来源
必须相等且格式合法", release 时不需要修改 R416 (除非新增 version source)。

R416 一次写, 长期保护; R341 等具体版本锁是 release prep 的副产品。

methodology lineage
-------------------

R416 是 **release infrastructure 维度增强**:

- R341 (cycle-37): 具体版本号 (硬编码 "1.8.1") 多源锁
- R382 (cycle-43): v1.8.1 → v1.8.2 bump procedural validation
- R410 (cycle-46): v1.8.2 → v1.8.3 bump
- **R416 (cycle-47)**: **结构化 quintet sync invariant 一次性覆盖**

R416 与上述 release-prep 维度互补: 前者是 release 时 "做对" 的辅助
(R341/R382/R410 检查特定版本), 后者是 release 之间 "不退" 的保护 (R416 检
查结构一致性)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"
CITATION_CFF = REPO_ROOT / "CITATION.cff"
PACKAGE_JSON = REPO_ROOT / "package.json"
VSCODE_PACKAGE_JSON = REPO_ROOT / "packages" / "vscode" / "package.json"
PACKAGE_LOCK_JSON = REPO_ROOT / "package-lock.json"

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(-[\w.]+)?$")


def _extract_pyproject_version() -> str:
    text = PYPROJECT_TOML.read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', text)
    assert m is not None, f"R416: cannot parse version from {PYPROJECT_TOML}"
    return m.group(1)


def _extract_citation_version() -> str:
    text = CITATION_CFF.read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*:\s*["\']?([^"\'\n]+)["\']?\s*$', text)
    assert m is not None, f"R416: cannot parse version from {CITATION_CFF}"
    return m.group(1).strip().strip('"').strip("'")


def _extract_package_json_version(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    v = data.get("version")
    assert isinstance(v, str), f"R416: missing or non-string version in {path}"
    return v


def _extract_package_lock_versions() -> dict[str, str]:
    """package-lock.json 有 2 处 version: 顶层 + packages."" self-reference。"""
    data = json.loads(PACKAGE_LOCK_JSON.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    if isinstance(data.get("version"), str):
        out["root"] = data["version"]
    packages_self = data.get("packages", {}).get("", {})
    if isinstance(packages_self.get("version"), str):
        out["packages-self"] = packages_self["version"]
    return out


def _collect_all_versions() -> dict[str, str]:
    """收集所有版本号来源, 返回 {source_label: version_string}。"""
    out: dict[str, str] = {}
    out["pyproject.toml"] = _extract_pyproject_version()
    out["CITATION.cff"] = _extract_citation_version()
    out["package.json"] = _extract_package_json_version(PACKAGE_JSON)
    out["packages/vscode/package.json"] = _extract_package_json_version(
        VSCODE_PACKAGE_JSON
    )
    lock_versions = _extract_package_lock_versions()
    for k, v in lock_versions.items():
        out[f"package-lock.json[{k}]"] = v
    return out


class TestLayer1AnchorFilesExist:
    """Layer 1: 所有版本来源文件存在 + 可解析。"""

    def test_pyproject_toml_exists(self):
        assert PYPROJECT_TOML.is_file(), f"R416-L1: {PYPROJECT_TOML} missing"

    def test_citation_cff_exists(self):
        assert CITATION_CFF.is_file(), f"R416-L1: {CITATION_CFF} missing"

    def test_package_json_exists(self):
        assert PACKAGE_JSON.is_file(), f"R416-L1: {PACKAGE_JSON} missing"

    def test_vscode_package_json_exists(self):
        assert VSCODE_PACKAGE_JSON.is_file(), f"R416-L1: {VSCODE_PACKAGE_JSON} missing"

    def test_package_lock_json_exists(self):
        assert PACKAGE_LOCK_JSON.is_file(), f"R416-L1: {PACKAGE_LOCK_JSON} missing"

    def test_at_least_5_version_sources(self):
        versions = _collect_all_versions()
        assert len(versions) >= 5, (
            f"R416-L1: only {len(versions)} version source(s) found, "
            f"expected >= 5. Sources: {sorted(versions.keys())}"
        )


class TestLayer2QuintetConsistency:
    """Layer 2: 所有版本号严格相等 (字符串相等)。"""

    def test_all_versions_equal(self):
        versions = _collect_all_versions()
        unique_versions = set(versions.values())
        if len(unique_versions) != 1:
            details = "\n".join(
                f"  {src}: {ver!r}" for src, ver in sorted(versions.items())
            )
            raise AssertionError(
                f"R416-L2: version mismatch across {len(versions)} "
                f"sources ({len(unique_versions)} unique values):\n"
                f"{details}\n\n"
                f"Fix: ensure all sources have the same version string. "
                f"For release: bump using scripts/bump_version.py to "
                f"sync all sources atomically. v1.7.5 failed due to this "
                f"exact drift (pyproject.toml ahead of package.json)."
            )


class TestLayer3SemverFormat:
    """Layer 3: 版本号匹配 semver 格式。"""

    def test_all_versions_match_semver(self):
        versions = _collect_all_versions()
        violations: list[str] = []
        for src, ver in sorted(versions.items()):
            if not SEMVER_PATTERN.match(ver):
                violations.append(f"  {src}: {ver!r} not semver")
        assert not violations, (
            f"R416-L3: {len(violations)} version source(s) don't match "
            f"semver pattern ^\\d+\\.\\d+\\.\\d+(-\\w+)?$:\n" + "\n".join(violations)
        )


class TestLayer4LineageMarker:
    """Layer 4: methodology lineage + v1.7.5 历史教训引用。"""

    def test_this_file_contains_r416_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R416" in text

    def test_this_file_references_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R341", "R382", "R410"):
            assert prior in text, f"R416: must cite release lineage: {prior}"

    def test_this_file_marks_v1_7_5_lesson(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("v1.7.5", "quintet", "release infrastructure"):
            assert kw in text, f"R416: missing keyword: {kw!r}"
