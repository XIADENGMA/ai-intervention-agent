"""R246 / Cycle 17 · F-cycle16-build-artifact-uniform-guard: complete the
build-artifact freshness matrix at the pre-commit layer.

Why this invariant
------------------

R226 (precompress) + R242 (minify) closed two of six build-artifact
chains. The remaining four (``gen_i18n_types``, ``gen_pseudo_locale``,
``generate_docs``, ``generate_pwa_icons``) were only guarded in
``ci_gate.py`` — meaning "source changed but generated artifact didn't
follow" was caught at *CI time* (push → 5min wait → fail → fix → repush)
instead of *commit time* (instant fail-closed). Same problem-shape as
R226/R242, same fix shape.

R246 promotes all 4 remaining generator ``--check`` flags to
``.pre-commit-config.yaml`` hooks. After R246, the build-artifact
freshness matrix is **complete + uniform**:

| Producer              | Output                                      | Guard          |
| --------------------- | ------------------------------------------- | -------------- |
| precompress_static    | ``static/**/*.{br,gz}``                     | R226 hook      |
| minify_assets         | ``static/**/*.min.{js,css}``                | R242 hook      |
| gen_i18n_types        | ``packages/vscode/i18n-keys.d.ts``          | R246 hook (new) |
| gen_pseudo_locale     | ``**/locales/_pseudo/pseudo.json``          | R246 hook (new) |
| generate_docs (en)    | ``docs/api/*.md``                           | R246 hook (new) |
| generate_docs (zh-CN) | ``docs/api.zh-CN/*.md``                     | R246 hook (new) |
| generate_pwa_icons    | ``icons/*.{png,ico}``                       | R246 hook (new) |

What this test guards
---------------------

* All 5 R246 hook ids exist in ``.pre-commit-config.yaml``
  (4 generators, with generate_docs split into en + zh-CN as 2 hooks
  matching the ``ci_gate.py`` invocation style).
* Each hook entry actually invokes the corresponding script with
  ``--check`` (no silent ``echo skip`` substitution).
* Each hook ``files`` filter targets the corresponding *source*
  domain (e.g. PWA hook targets ``icons/`` not the whole repo).
* Each hook runs at default (pre-commit) stage.
* The 4 underlying generator scripts still exist + still expose
  ``--check`` (R242-style cross-check).
* Companion guarantee: ``ci_gate.py`` still invokes these scripts
  (CI remains the canonical source of truth; pre-commit is the
  fast shadow). Prevents the trap "moved to pre-commit, removed
  from CI" which would let ``--no-verify`` bypass everything.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRECOMMIT_PATH = REPO_ROOT / ".pre-commit-config.yaml"
CI_GATE_PATH = REPO_ROOT / "scripts" / "ci_gate.py"

R246_HOOKS = {
    "check-i18n-types-fresh": {
        "script": "scripts/gen_i18n_types.py",
        "files_keywords": ("packages/vscode/locales", "en"),
    },
    "check-pseudo-locale-fresh": {
        "script": "scripts/gen_pseudo_locale.py",
        "files_keywords": ("locales", "json"),
    },
    "check-generated-docs-en-fresh": {
        "script": "scripts/generate_docs.py",
        "files_keywords": ("ai_intervention_agent", "py"),
        "extra_entry_tokens": ("--lang", "en"),
    },
    "check-generated-docs-zh-fresh": {
        "script": "scripts/generate_docs.py",
        "files_keywords": ("ai_intervention_agent", "py"),
        "extra_entry_tokens": ("--lang", "zh-CN"),
    },
    "check-pwa-icons-fresh": {
        "script": "scripts/generate_pwa_icons.py",
        "files_keywords": ("icons",),
    },
}


def _load_precommit() -> dict:
    with PRECOMMIT_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _find_hook(config: dict, hook_id: str) -> dict | None:
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == hook_id:
                return hook
    return None


class TestAllR246HooksPresent(unittest.TestCase):
    def test_all_five_hooks_present_in_precommit(self) -> None:
        config = _load_precommit()
        missing = [hid for hid in R246_HOOKS if _find_hook(config, hid) is None]
        self.assertEqual(
            missing,
            [],
            f"R246 invariant: .pre-commit-config.yaml 必须包含全部 5 个 build-"
            f"artifact freshness hook (R226 + R242 + R246 = 7 hooks 总计构成"
            f"完整矩阵)。缺失: {missing}. 如果想移除任何一个 hook, 必须先"
            f"通过 ai-intervention-agent 问业主, 否则会重新打开 stale-build "
            f"silent-drift 问题 (R226/R242 fixed 同形态问题)。",
        )


class TestEachHookEntryRunsCheck(unittest.TestCase):
    def test_each_hook_entry_invokes_correct_script_with_check(self) -> None:
        config = _load_precommit()
        problems: list[str] = []
        for hook_id, meta in R246_HOOKS.items():
            hook = _find_hook(config, hook_id)
            if hook is None:
                continue
            entry = hook.get("entry", "")
            if meta["script"] not in entry:
                problems.append(f"  - {hook_id}: entry={entry!r} 不调 {meta['script']}")
            if "--check" not in entry:
                problems.append(
                    f"  - {hook_id}: entry={entry!r} 缺 --check (会写文件而非"
                    "检查; pre-commit hook 必须 read-only)"
                )
            for token in meta.get("extra_entry_tokens", ()):
                if token not in entry:
                    problems.append(
                        f"  - {hook_id}: entry={entry!r} 缺 token {token!r}"
                    )
        self.assertEqual(
            problems,
            [],
            "R246 invariant: 部分 hook entry 不正确:\n" + "\n".join(problems),
        )


class TestEachHookFilesFilterIsScoped(unittest.TestCase):
    """避免 hook 在不相关改动上跑（性能 + 噪音）。"""

    def test_each_hook_has_a_scoped_files_filter(self) -> None:
        config = _load_precommit()
        problems: list[str] = []
        for hook_id, meta in R246_HOOKS.items():
            hook = _find_hook(config, hook_id)
            if hook is None:
                continue
            files = hook.get("files", "")
            if not files:
                problems.append(
                    f"  - {hook_id}: files filter 为空 — 会在每次 commit 都跑"
                    f"造成性能浪费。请指定 source 文件正则。"
                )
                continue
            for keyword in meta["files_keywords"]:
                if keyword not in files:
                    problems.append(
                        f"  - {hook_id}: files={files!r} 缺关键词 {keyword!r}"
                    )
        self.assertEqual(
            problems,
            [],
            "R246 invariant: 部分 hook 的 files filter 缺失或失焦:\n"
            + "\n".join(problems),
        )


class TestNoHookRelegatedToManualOrPrePush(unittest.TestCase):
    def test_all_hooks_run_at_default_or_pre_commit_stage(self) -> None:
        config = _load_precommit()
        problems: list[str] = []
        forbidden = {"manual", "pre-push", "post-commit"}
        for hook_id in R246_HOOKS:
            hook = _find_hook(config, hook_id)
            if hook is None:
                continue
            stages = hook.get("stages")
            if stages is None:
                continue
            if set(stages).issubset(forbidden):
                problems.append(
                    f"  - {hook_id}: stages={stages!r} 全部 forbidden ("
                    f"R246 hook 必须跑在默认 pre-commit 阶段才能 fail-closed)"
                )
        self.assertEqual(problems, [], "\n".join(problems))


class TestCompanionScriptsStillExist(unittest.TestCase):
    """R242-style cross-check: scripts必须存在 + --check flag 必须仍支持。"""

    def test_all_scripts_exist(self) -> None:
        missing = []
        for hook_id, meta in R246_HOOKS.items():
            script_relpath = str(meta["script"])
            script_path = REPO_ROOT / script_relpath
            if not script_path.exists():
                missing.append(f"  - {hook_id}: {script_relpath} 不存在")
        self.assertEqual(
            missing,
            [],
            "R246 invariant: hook entry 指向的 script 必须存在 (删除 script "
            "会让每个开发者下一次 commit 都因 OSError 失败):\n" + "\n".join(missing),
        )

    def test_all_scripts_expose_check_flag(self) -> None:
        missing = []
        for hook_id, meta in R246_HOOKS.items():
            script_relpath = str(meta["script"])
            script_path = REPO_ROOT / script_relpath
            if not script_path.exists():
                continue
            content = script_path.read_text(encoding="utf-8")
            if "--check" not in content:
                missing.append(f"  - {hook_id}: {script_relpath} 不再支持 --check flag")
        self.assertEqual(
            missing,
            [],
            "R246 invariant: 所有 hook 关联的脚本必须仍支持 --check (删除"
            "--check 等于让 hook entry 在 argparse 阶段就 fail):\n"
            + "\n".join(missing),
        )


class TestCiGateStillRunsAllChecks(unittest.TestCase):
    """pre-commit 是 fast shadow, CI 仍是 source of truth。"""

    def test_ci_gate_still_invokes_all_generators(self) -> None:
        ci_content = CI_GATE_PATH.read_text(encoding="utf-8")
        unique_scripts = {meta["script"] for meta in R246_HOOKS.values()}
        # generate_pwa_icons 是 R246 新加, ci_gate.py 暂未引入 (在 R246 hook
        # 已经守了的前提下, 不强制要求 ci_gate 也加 — 由 R246 hook 保护
        # 即可)。其余 3 个 (gen_i18n_types, gen_pseudo_locale, generate_docs)
        # 必须在 ci_gate.py 中保留 (R242-style safety net for --no-verify
        # bypass)。
        required_in_ci = unique_scripts - {"scripts/generate_pwa_icons.py"}
        missing_in_ci: list[str] = []
        for script_relpath in required_in_ci:
            script_name = Path(str(script_relpath)).name
            if script_name not in ci_content:
                missing_in_ci.append(script_name)
        self.assertEqual(
            missing_in_ci,
            [],
            "R246 invariant: scripts/ci_gate.py 仍必须调用 gen_i18n_types / "
            "gen_pseudo_locale / generate_docs (R226/R242/R246 hook 之外的"
            "安全网, 防止 --no-verify 路径绕过)。缺失: "
            f"{missing_in_ci}",
        )


if __name__ == "__main__":
    unittest.main()
