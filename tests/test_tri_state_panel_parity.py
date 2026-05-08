"""Byte-parity guard for shared @aiia/tri-state-panel files (T1 · C10c).

BEST_PRACTICES_PLAN.tmp.md §T1 v3 mandates that the four shared
tri-state-panel assets live as a *single source of truth* under
``static/{js,css}/`` and are mirrored verbatim into ``packages/vscode/``
so the VSIX can ship them as local resources (a webview cannot read
across the extension root into ``../static/``). The mirroring is
performed by ``scripts/package_vscode_vsix.mjs::syncSharedTriStatePanel``
on every packaging run; this test enforces the invariant in CI:

* For each (Web UI source → VSCode mirror) pair, the SHA-256 of both
  files MUST match. Any discrepancy means a developer (or a tool) has
  edited the mirror in-place; revert and re-edit the Web UI source.
* All four mirror files MUST appear in ``packages/vscode/package.json::files[]``
  so ``vsce package`` actually ships them inside the .vsix (otherwise the
  webview at runtime gets a 404 on the asWebviewUri request).
* This test runs in the standard ``pytest tests/`` set (no pytest-mark
  needed) and is *fast* (4 file reads + 4 hashes). It runs both locally
  and in ``ci_gate.py`` Python phase.

Refusal modes covered:

1. Mirror file missing → fail with explicit "did you forget to run
   ``node scripts/package_vscode_vsix.mjs``?" hint.
2. Source file missing → fail with "single source of truth was deleted"
   hint (much louder than a generic FileNotFoundError).
3. SHA-256 mismatch → fail with the first 32 hex of each digest so the
   error log makes drift trivially detectable.
4. Mirror file not listed in package.json::files[] → fail with
   "vsce will silently drop this file" hint.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_PKG_JSON = REPO_ROOT / "packages" / "vscode" / "package.json"

# (Web UI source-of-truth, VSCode mirror) — kept in sync with
# scripts/package_vscode_vsix.mjs::SHARED_TRI_STATE_PANEL_FILES.
SHARED_PAIRS: tuple[tuple[Path, Path], ...] = (
    (
        REPO_ROOT
        / "src"
        / "ai_intervention_agent"
        / "static"
        / "js"
        / "tri-state-panel.js",
        REPO_ROOT / "packages" / "vscode" / "tri-state-panel.js",
    ),
    (
        REPO_ROOT
        / "src"
        / "ai_intervention_agent"
        / "static"
        / "js"
        / "tri-state-panel-loader.js",
        REPO_ROOT / "packages" / "vscode" / "tri-state-panel-loader.js",
    ),
    (
        REPO_ROOT
        / "src"
        / "ai_intervention_agent"
        / "static"
        / "js"
        / "tri-state-panel-bootstrap.js",
        REPO_ROOT / "packages" / "vscode" / "tri-state-panel-bootstrap.js",
    ),
    (
        REPO_ROOT
        / "src"
        / "ai_intervention_agent"
        / "static"
        / "css"
        / "tri-state-panel.css",
        REPO_ROOT / "packages" / "vscode" / "tri-state-panel.css",
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestTriStatePanelByteParity(unittest.TestCase):
    """Each shared tri-state panel file must be byte-identical between Web UI and VSCode mirror."""

    def test_all_pairs_byte_identical(self) -> None:
        mismatches: list[str] = []
        missing: list[str] = []
        for src, dest in SHARED_PAIRS:
            if not src.exists():
                missing.append(
                    f"single-source-of-truth missing: {src.relative_to(REPO_ROOT)} "
                    f"(was the @aiia/tri-state-panel module deleted? T1 v3 §C10c "
                    f"requires both halves to exist)"
                )
                continue
            if not dest.exists():
                missing.append(
                    f"VSCode mirror missing: {dest.relative_to(REPO_ROOT)} "
                    f"(run `node scripts/package_vscode_vsix.mjs` to regenerate, "
                    f"or `cp {src.relative_to(REPO_ROOT)} {dest.relative_to(REPO_ROOT)}`)"
                )
                continue
            src_hash = _sha256(src)
            dest_hash = _sha256(dest)
            if src_hash != dest_hash:
                mismatches.append(
                    f"{dest.relative_to(REPO_ROOT)} drifted from {src.relative_to(REPO_ROOT)}\n"
                    f"      static  sha256 = {src_hash[:32]}…\n"
                    f"      vscode  sha256 = {dest_hash[:32]}…\n"
                    f"      Fix: revert the in-place edit on the VSCode mirror, "
                    f"edit the static/ source instead, then `node scripts/package_vscode_vsix.mjs` "
                    f"(or just `cp {src.relative_to(REPO_ROOT)} {dest.relative_to(REPO_ROOT)}`)."
                )
        if missing:
            self.fail(
                "@aiia/tri-state-panel byte-parity check found missing files:\n  "
                + "\n  ".join(missing)
            )
        if mismatches:
            self.fail(
                "@aiia/tri-state-panel byte-parity check failed — VSCode mirror "
                "diverged from the Web UI source-of-truth:\n  "
                + "\n  ".join(mismatches)
            )

    def test_all_mirrors_listed_in_vscode_package_json(self) -> None:
        """``vsce package`` honors ``package.json::files[]`` exclusively;
        any file copied into ``packages/vscode/`` that is NOT listed
        there will be silently dropped from the .vsix, which would cause
        the webview to 404 on asWebviewUri at runtime."""
        pkg = json.loads(VSCODE_PKG_JSON.read_text(encoding="utf-8"))
        files_list = set(pkg.get("files", []))
        missing: list[str] = []
        for _, dest in SHARED_PAIRS:
            entry = dest.name
            if entry not in files_list:
                missing.append(entry)
        if missing:
            self.fail(
                "The following @aiia/tri-state-panel mirror files are present "
                "in packages/vscode/ but NOT listed in package.json::files[]; "
                "vsce package will silently drop them and the webview will "
                "404 on asWebviewUri at runtime:\n  "
                + "\n  ".join(missing)
                + "\n  Fix: add each filename to packages/vscode/package.json::files[]."
            )

    def test_packager_script_src_paths_match_test_source_paths(self) -> None:
        """R89 防回归：``scripts/package_vscode_vsix.mjs`` 内的源路径常量
        必须与本测试的 ``SHARED_PAIRS`` 第一列保持一致。

        历史教训：R76 PyPA src/ 布局迁移把真源从 ``static/js|css/`` 挪到了
        ``src/ai_intervention_agent/static/{js,css}/``。本测试的
        ``SHARED_PAIRS`` 跟着改了，但 .mjs script 内的
        ``SHARED_TRI_STATE_PANEL_FILES`` 数组没改 —— 结果：

        - 字节同源测试照样过（test 自己读新路径），
        - 但每次 ``node scripts/package_vscode_vsix.mjs`` 都直接
          ``process.exit(1)`` with ``@aiia/tri-state-panel 真源缺失``
          —— **VSIX 包从此打不出来**，CI 端 ``make vscode-check`` 也
          会 fail，但 ``ci_gate.py`` 的 Python 路径不调它，所以
          test_tri_state_panel_parity 一直绿，问题被隐藏。

        本测试做最小化的 contains 检查：要求每条 src 路径（相对仓库根）
        都以字符串字面量形式出现在 .mjs 的内容里。这种检查抓得住「.py
        测试改了路径但 .mjs 忘改」的不对称漂移；它不要求 JS 解析器，
        所以 Python 测试套件也能跑。
        """
        packager = REPO_ROOT / "scripts" / "package_vscode_vsix.mjs"
        self.assertTrue(packager.exists(), f"{packager} 必须存在")
        text = packager.read_text(encoding="utf-8")
        missing: list[str] = []
        for src, _ in SHARED_PAIRS:
            rel = src.relative_to(REPO_ROOT).as_posix()
            if rel not in text:
                missing.append(rel)
        if missing:
            self.fail(
                "scripts/package_vscode_vsix.mjs::SHARED_TRI_STATE_PANEL_FILES "
                "里找不到下列源路径的字面量：\n  "
                + "\n  ".join(missing)
                + "\n本 .py 测试与 .mjs 打包脚本必须共用同一组 src/ 路径前缀；"
                "如果迁移了真源目录，请同步把 .mjs 里的 "
                "SHARED_TRI_STATE_PANEL_FILES 数组改成新位置（参见 R89 修复）。"
            )


if __name__ == "__main__":
    unittest.main()
