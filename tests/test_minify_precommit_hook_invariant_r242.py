"""R242 / Cycle 16 · F-cycle15-9: ``.min.js`` / ``.min.css`` freshness hook.

Why this invariant
------------------

The runtime helper ``_get_minified_file()`` (``web_ui.py`` L1387-1429)
prefers same-directory ``.min.js`` / ``.min.css`` when they exist as a
parse-time optimisation for local dev / VSCode extension. The selection
predicate is **only** ``minified_path.exists()`` — there is **no**
content / mtime comparison to the source ``.js`` / ``.css``.

Consequence: when a developer edits ``app.js`` without re-running
``minify_assets.py``, Flask keeps serving the **stale** ``app.min.js``,
and the browser sees the previous-revision code. R234 (textarea
disabled CSS), R238 (modal focus trap), R240 (inert background) and
R241 (DRY inert helper) all silently shipped to local dev with stale
minified copies until the R242 audit surfaced the gap — 4 cycles of
"runs locally, looks broken in browser" risk slipped through.

This is structurally identical to R226 (precompress freshness), which
covers the parallel ``.gz`` / ``.br`` chain:

| Build artifact     | Producer                | Freshness guard            |
| ------------------ | ----------------------- | -------------------------- |
| ``.gz`` / ``.br``  | ``precompress_static``  | R226 pre-commit hook ✓     |
| ``.min.js`` / ``.min.css`` | ``minify_assets``  | R242 pre-commit hook (this) |

``.gitignore`` excludes ``*.min.js`` / ``*.min.css`` so production
fresh checkouts are unaffected (``_get_minified_file()`` falls back to
the source ``.js``). **R242 protects the local dev loop**, not
production.

What this test guards
---------------------

* ``id='check-static-minified-fresh'`` hook present in
  ``.pre-commit-config.yaml``.
* The hook entry actually invokes ``minify_assets.py --check`` (a
  no-op rename would silently disable detection).
* The hook ``files`` filter targets ``src/.../static/(css|js)/``
  paths so any .css / .js touch triggers the check.
* Hook runs at default (``pre-commit``) stage — not banished to
  ``manual``/``pre-push`` which would defeat the local feedback purpose.
* The companion script ``scripts/minify_assets.py`` still exists and
  exposes a ``--check`` flag (deleting it would silently break the
  hook entry).
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRECOMMIT_PATH = REPO_ROOT / ".pre-commit-config.yaml"
MINIFY_SCRIPT_PATH = REPO_ROOT / "scripts" / "minify_assets.py"

HOOK_ID = "check-static-minified-fresh"


def _load_precommit() -> dict:
    with PRECOMMIT_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _find_hook(config: dict, hook_id: str) -> dict | None:
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == hook_id:
                return hook
    return None


class TestMinifyCheckHookExists(unittest.TestCase):
    def test_minify_check_hook_present(self) -> None:
        config = _load_precommit()
        hook = _find_hook(config, HOOK_ID)
        self.assertIsNotNone(
            hook,
            msg=(
                f"R242 invariant: .pre-commit-config.yaml 必须包含 "
                f"id={HOOK_ID!r} hook。R242 防止编辑 .js/.css 后, Flask "
                "继续 serve 旧的 .min.js / .min.css (因为 _get_minified_file() "
                "只判定文件存在, 不判定新鲜度)。移除该 hook 会让 "
                "R234/R238/R240/R241 类的 silent-stale-asset 问题再次发生。"
                "如果想移除, 必须先在 ai-intervention-agent 里问业主理由。"
            ),
        )

    def test_minify_check_hook_entry_actually_runs_minify_check(self) -> None:
        config = _load_precommit()
        hook = _find_hook(config, HOOK_ID)
        assert hook is not None
        entry = hook.get("entry", "")
        self.assertIn(
            "minify_assets.py",
            entry,
            msg=(
                f"R242 invariant: {HOOK_ID!r} hook 的 entry 必须真正运行 "
                f"minify_assets.py (当前: {entry!r})。被静默改成 'echo skip' "
                "会让 hook 永远 pass 但实际什么都没检查。"
            ),
        )
        self.assertIn(
            "--check",
            entry,
            msg=(
                f"R242 invariant: {HOOK_ID!r} hook 的 entry 必须带 --check "
                f"(当前: {entry!r})。不带 --check 会**写**新的 .min 文件, "
                "把 pre-commit 从 'verification' 变成 'mutation', "
                "用户会突然看到 dirty working tree 而困惑。"
            ),
        )

    def test_minify_check_hook_filters_css_or_js_files(self) -> None:
        config = _load_precommit()
        hook = _find_hook(config, HOOK_ID)
        assert hook is not None
        files = hook.get("files", "")
        self.assertTrue(
            "css" in files and "js" in files,
            msg=(
                f"R242 invariant: {HOOK_ID!r} hook 的 files filter 必须同时"
                f"匹配 .css 和 .js (当前: {files!r})。只匹配其中一个会让"
                "另一边的 stale .min 问题逃逸 (R234 主要是 .css, "
                "R238/R240/R241 主要是 .js, 两边都得守)。"
            ),
        )

    def test_minify_check_hook_targets_static_directory(self) -> None:
        config = _load_precommit()
        hook = _find_hook(config, HOOK_ID)
        assert hook is not None
        files = hook.get("files", "")
        self.assertIn(
            "static",
            files,
            msg=(
                f"R242 invariant: {HOOK_ID!r} hook 的 files filter 必须"
                f"限定 static 目录 (当前: {files!r})。否则每次任意 .js "
                "改动都触发, 包括 docs / fixtures, 浪费 ~50ms × 大量 commit。"
            ),
        )


class TestMinifyCheckHookRunsAtPreCommitStage(unittest.TestCase):
    def test_hook_not_relegated_to_manual_or_pre_push_only(self) -> None:
        config = _load_precommit()
        hook = _find_hook(config, HOOK_ID)
        assert hook is not None
        stages = hook.get("stages")
        if stages is None:
            return
        forbidden_only_stages = {"manual", "pre-push", "post-commit"}
        if set(stages).issubset(forbidden_only_stages):
            self.fail(
                f"R242 invariant: {HOOK_ID!r} hook stages = {stages!r}, "
                f"但 minify check 必须在 [pre-commit] 阶段 (default) 跑才能"
                "在 commit 前 fail-closed。只跑在 manual/pre-push/post-commit "
                "等于把检测推回到 push 之后, 失去 R242 缩短反馈链的全部意义。"
            )


class TestMinifyScriptStillExists(unittest.TestCase):
    """hook entry 指向脚本, 删了脚本会让 hook 在每次 commit 都 OSError。"""

    def test_minify_assets_script_still_exists(self) -> None:
        self.assertTrue(
            MINIFY_SCRIPT_PATH.exists(),
            msg=(
                f"R242 invariant: scripts/minify_assets.py 仍必须存在 "
                f"(检查路径: {MINIFY_SCRIPT_PATH}). 该脚本是 R242 hook entry "
                "的目标; 删除会让每个开发者的下一次 commit 都因 'No such "
                "file' 而失败。如果想替换为新脚本, 必须同步更新本测试 + "
                ".pre-commit-config.yaml + web_ui.py 的 _get_minified_file。"
            ),
        )

    def test_minify_assets_script_exposes_check_flag(self) -> None:
        contents = MINIFY_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "--check",
            contents,
            msg=(
                "R242 invariant: scripts/minify_assets.py 必须仍支持 "
                "--check 参数。R242 hook entry 依赖该 flag 做内容比较 "
                "(content_drifts) 而不是 mtime 比较 (在 fresh clone / CI "
                "上 mtime 不可信)。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
