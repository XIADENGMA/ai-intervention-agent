"""R120 · 项目级 silent-failure 回归守卫测试。

设计目标
========

R107-R110 / R114 / R117 / R118 / R119 累计把项目内 ``except Exception:
pass`` 从 ~21 处审计、归类、降到「~27 处显式 intentional silence + 0
处未审计 site」。R120 把这个 audit **机器可执行化**——任何未来的
contributor 引入新的 ``except Exception: pass`` 都会让本测试失败，
必须显式文档化（CHANGELOG R-series entry）+ 显式提交新 baseline 才能
过 CI。

为什么要 grep 之上再加 AST + baseline
=========================================

- **grep 的 false positive**：``"except Exception:\\n    pass"`` 字面字
  符串（出现在 docstring / 测试断言里）会被 grep 匹中。R119 测试
  ``tests/test_silent_failure_audit_r119.py`` 已经踩过这个坑——必须
  改用 ``\nXXX\n`` 拆开断言才不会自匹中文档字符串里的 marker。
- **AST 的精度**：``ast.ExceptHandler`` 节点 + ``body == [Pass()]``
  + ``except Exception`` (no alias) 三个条件可以零误报识别真站点。
- **baseline 的耐久性**：单纯 "数量 == N" 测试经不起 noise——加
  一行注释 / 重排函数都会让 lineno 漂移。指纹用 (file,
  qualified_name) 去掉了 lineno 噪音，可以无伤跨 commit 复用。

为什么不只是 grep + count
=========================

R114 之前的项目里，每次新增 silent-failure 都会过 review；review
依赖人类记忆 R107-R119 的政策。**机器执行的回归守卫**让政策从「记忆」
升级到「编译时强制」——R-series audit 的成果可以在未来 5 年里持续
受益，不会因为 contributor 流转而衰减。

CI 运行模型
===========

- 本测试 **始终** 跑（不被 marker 跳过、不被 ``-k`` 排除）。
- ``scripts/silent_failure_audit.py`` 是同源代码——CI 失败时贡献者
  可以本地跑 ``uv run python scripts/silent_failure_audit.py list``
  看到当前所有 site，跑 ``check`` 复现 CI 的诊断输出。
- 新增 site 必须：
  1. 在 PR 里写明为什么这个 site 是 intentional silent；
  2. 加 R-series CHANGELOG entry（与 R107-R119 一致的格式）；
  3. 在源码 site 旁加 ``[R-XXX]`` marker 注释；
  4. 跑 ``uv run python scripts/silent_failure_audit.py update-baseline``
     重新生成 ``tests/data/silent_failure_baseline_r120.json``；
  5. 把 baseline diff + CHANGELOG diff 一起提交。

这 5 步任何一步都不能跳——R-series doctrine 由 review check 强制。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

# 把 scripts/ 加进 sys.path，让 ``from silent_failure_audit import ...`` 工作
# 而不需要 install scripts 为 package
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class TestSilentFailureRegressionGuardR120(unittest.TestCase):
    """守护 ``src/`` 中的 ``except Exception: pass`` 站点不偏离 R120 baseline。"""

    def test_baseline_file_exists_and_well_formed(self) -> None:
        """baseline JSON 必须存在且能 load——pre-CI sanity。"""
        from silent_failure_audit import BASELINE_PATH

        self.assertTrue(
            BASELINE_PATH.exists(),
            f"R120 baseline {BASELINE_PATH} 必须存在；如果是新 fork，"
            "跑 `uv run python scripts/silent_failure_audit.py update-baseline`",
        )
        raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertIn("approved_sites", raw, "baseline 必须有 approved_sites 字段")
        self.assertIn("_doc", raw, "baseline 必须有 _doc 字段说明用途")
        self.assertIn(
            "_how_to_update", raw, "baseline 必须有 _how_to_update 字段告诉怎么更新"
        )
        self.assertIsInstance(raw["approved_sites"], list, "approved_sites 必须是 list")
        # 每个 site 必须有 file + qualified_name + lineno 三字段
        for site in raw["approved_sites"]:
            self.assertIn("file", site)
            self.assertIn("qualified_name", site)
            self.assertIn("lineno", site)

    def test_no_unapproved_silent_failures(self) -> None:
        """**核心守卫**：源码当前的 silent-failure site 必须全部在 baseline
        里——新增即视为引入 silent failure 必须被拦截。

        如果你看到这条测试失败，可能的两种情况：

        1. **你刚加了 ``except Exception: pass``（无心）**：把它改成
           ``except Exception as e: logger.debug(...)`` 加 R-XXX marker。
           看 R117 / R118 / R119 commit message 学怎么改。

        2. **你刚加了 intentional silent failure（有心）**：
           - 在源码 site 旁写注释 ``# R-XXX: 这里为什么必须静默``；
           - 在 CHANGELOG 写一段 R-XXX entry，参考 R119 的「LOW
             impact site」格式；
           - 跑 ``uv run python scripts/silent_failure_audit.py
             update-baseline`` 重新生成 baseline；
           - 把 baseline diff + 你的 source/CHANGELOG diff **同一个
             commit** 里提交（或者加一个 follow-up commit，注明
             「baseline approval for R-XXX」）。
        """
        from silent_failure_audit import diff_sites, load_baseline, scan_repo

        current = scan_repo()
        baseline = load_baseline()
        added, removed = diff_sites(current, baseline)

        if added or removed:
            msg_parts = [
                f"silent-failure baseline drift detected: "
                f"current={len(current)}, baseline={len(baseline)}, "
                f"added={len(added)}, removed={len(removed)}",
            ]
            if added:
                msg_parts.append("")
                msg_parts.append(
                    "Added (NEW silent failure introduced — fix or document):"
                )
                for s in added:
                    msg_parts.append(
                        f"  + {s['file']}:{s['lineno']} {s['qualified_name']}"
                    )
            if removed:
                msg_parts.append("")
                msg_parts.append(
                    "Removed (refactored away — usually OK, please confirm):"
                )
                for s in removed:
                    msg_parts.append(
                        f"  - {s['file']}:{s['lineno']} {s['qualified_name']}"
                    )
            msg_parts.append("")
            msg_parts.append(
                "How to fix: see this test's docstring + R117/R118/R119 commit "
                "messages for examples."
            )
            self.fail("\n".join(msg_parts))

    def test_baseline_count_is_not_silently_growing(self) -> None:
        """**软上限**：当前 baseline 大小 ≤ 30 site。

        rationale：R107-R119 已经把数量从 ~21 降到 27（数字增长是因
        R120 修了 nested traversal bug，多发现了 5 处 nested intentional
        silence——不是真增加 silent failure）。R120 之后不应该再增长，
        除非有非常充分的理由。

        如果你看到这条测试失败，意味着 baseline 已经膨胀到 >30 site
        ——通常是 silent-failure audit 政策被绕过的信号。回去 review
        最近的 baseline diff，确认每条新增 site 都有 R-series CHANGELOG
        entry 论证。
        """
        from silent_failure_audit import load_baseline

        baseline = load_baseline()
        self.assertLessEqual(
            len(baseline),
            30,
            f"R120 baseline 已膨胀到 {len(baseline)} site (>30)——"
            "audit 政策可能被绕过，请 review CHANGELOG 是否每条新 site "
            "都有充分论证",
        )

    def test_scanner_handles_nested_except_handlers(self) -> None:
        """**回归 R120 自身的 bug fix**：scanner 必须能进入 ``except``
        块体内部继续找嵌套 try/except——pre-fix 把
        ``except ValueError:`` 内嵌的 ``except Exception: pass`` 漏报。

        ``server_feedback.py:543`` 是 canonical 例子——外层
        ``except ValueError:`` 包了一个 ``try: response.text...
        except Exception: pass`` 用于 best-effort 错误信息提取。
        baseline 里必须有 ``server_feedback.py`` 的 ``launch_feedback_ui``
        条目；如果消失，说明 scanner 又被改回不递归的版本。
        """
        from silent_failure_audit import load_baseline

        baseline = load_baseline()
        nested_known_sites = [
            ("src/ai_intervention_agent/server_feedback.py", "launch_feedback_ui"),
            ("src/ai_intervention_agent/server_feedback.py", "interactive_feedback"),
        ]
        for file, qname in nested_known_sites:
            with self.subTest(file=file, qname=qname):
                hits = [
                    s
                    for s in baseline
                    if s["file"] == file and s["qualified_name"] == qname
                ]
                self.assertTrue(
                    len(hits) >= 1,
                    f"R120 baseline 应该包含 {file} 的 {qname} 嵌套 site；"
                    "如果消失说明 scanner 的 nested visit 被回退到 R120-fix 之前",
                )

    def test_scanner_excludes_pure_docstring_pattern(self) -> None:
        """**反向**：scanner 不能误报 docstring 里的字面 ``except Exception:
        \\npass``——R119 测试踩过同样坑，所以 R120 用 AST 而非 grep。
        """
        # 临时 .py 文件：纯 docstring 里的 except 字符串不应该被 AST
        # 当成代码节点
        import tempfile

        from silent_failure_audit import scan_file

        sample = '''
"""Some docstring text that mentions::

    try:
        do_something()
    except Exception:
        pass

But the above is a docstring, not real code.
"""

def real_function() -> None:
    """No silent failure here."""
    return None
'''
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(sample)
            tmp_path = Path(tmp.name)

        try:
            sites = scan_file(tmp_path)
            self.assertEqual(
                len(sites),
                0,
                f"AST scanner 不能误报 docstring 里的字面 except Exception\n: pass: "
                f"实际匹配到 {sites}",
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_scanner_correctly_distinguishes_alias_form(self) -> None:
        """**反向**：``except Exception as e: pass`` 也是 silent failure，
        但常见做法是 alias + ``logger.error(..., e)``——只有
        **完全无 alias 也无 logging** 才算 R120 关注的「最劣」silent。

        ``except Exception as e: pass`` 在 R120 当前定义里 **不算**
        scanner 匹配——这条测试守护这个语义边界，避免未来有人把
        scanner 收紧而引入大量 false positive（每个 ``except Exception
        as e:`` 块都是 candidate）。
        """
        import tempfile

        from silent_failure_audit import scan_file

        sample = """
def f1() -> None:
    try:
        x = 1
    except Exception as e:
        pass

def f2() -> None:
    try:
        x = 1
    except Exception:
        pass

def f3() -> None:
    try:
        x = 1
    except Exception:
        x = 2
        pass
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(sample)
            tmp_path = Path(tmp.name)

        try:
            sites = scan_file(tmp_path)
            qnames = {s["qualified_name"] for s in sites}
            self.assertIn("f2", qnames, "f2 (no alias, body=[Pass]) 必须被识别为 site")
            self.assertNotIn(
                "f1", qnames, "f1 (有 alias) 不应该被识别——alias 通常配 logging"
            )
            self.assertNotIn(
                "f3",
                qnames,
                "f3 (body=[Assign, Pass]) 不应该被识别——body 不止 pass",
            )
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
