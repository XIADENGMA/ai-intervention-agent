#!/usr/bin/env python3
"""R120 silent-failure 审计扫描器。

用法
====

::

    # 列出当前所有 ``except Exception: pass`` 站点（人工审阅）
    uv run python scripts/silent_failure_audit.py list

    # 与 baseline 对比，发现新增 site 时 exit 1（CI 用）
    uv run python scripts/silent_failure_audit.py check

    # 重新生成 baseline（人类审阅 + 显式批准 R107-R119 + 后续 R-series 文档化的
    # intentional silence 后才能跑这条命令；CI 不可调用）
    uv run python scripts/silent_failure_audit.py update-baseline

设计决策
========

R107-R110 / R114 / R117 / R118 / R119 累计把项目内 ``except Exception: pass``
从 ~21 处审计、归类、降到 ~11 处显式 intentional silence。R120 把这个
audit 的成果**机器可执行化**：

1. 用 ``ast`` 而不是 grep——避免 docstring 字符串 false positive（grep
   会匹配 ``"except Exception:\\n    pass"`` 字面量）。
2. 站点指纹用 **(filepath, qualified_name)** 而不是 (filepath, lineno)
   ——避免文件加注释或重排导致 lineno 漂移。
3. baseline 用 JSON 而不是 Python module——人类 PR diff 能直接看到
   "新增了哪个 site" / "删除了哪个 site"，code review 友好。
4. ``update-baseline`` 不能在 CI 里跑——必须人类 PR 显式提交新
   baseline，强制 R-series 审计纪律延续到未来。
5. 扫 **`except Exception:` 后跟 `pass`**，不扫 ``except:`` 裸块
   ——后者 Ruff E722 已经禁止；本脚本只解决「捕了 Exception 然后丢」
   这一个 anti-pattern。

为什么不只是写一个 pytest 测试
================================

测试库主要是给 pytest 用的；这个脚本也支持 CLI 用法（``list`` /
``update-baseline``），方便维护者本地审计、batch 更新 baseline。
对应的 pytest 测试 ``tests/test_silent_failure_regression_guard_r120.py``
直接调本脚本的函数，所以 CI 检查 + 本地审计共用同一份扫描逻辑。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "ai_intervention_agent"
BASELINE_PATH = REPO_ROOT / "tests" / "data" / "silent_failure_baseline_r120.json"


def _qualified_name(node: ast.AST, parents: list[ast.AST]) -> str:
    """根据 AST 父链拼出 ``ClassName.method_name`` / ``module_level`` 名字。

    用 qualified_name 而不是 lineno 做指纹，避免无关注释导致 baseline
    噪音 diff。同名嵌套函数会有 outer.inner.<innermost> 形式。
    """
    chain: list[str] = []
    for parent in parents:
        if isinstance(
            parent,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            name = getattr(parent, "name", "<lambda>")
            chain.append(name)
    if not chain:
        return "<module>"
    return ".".join(chain)


class _BareExceptPassScanner(ast.NodeVisitor):
    """收集 ``try/except Exception: pass`` 站点。

    匹配规则（必须全部满足才算 silent failure 站点）：
    - except 处理 ``Exception``（不是 ``Exception as e`` 配 logging，
      也不是其它具体类型如 ``except KeyError``）；
    - 处理体**仅**包含 ``pass`` 一条语句（不含 logging.debug / 别的
      副作用）；
    - 没有给 exception 起 alias（``except Exception as e:`` 通常会用
      e 做点什么，不在本扫描范围）。
    """

    def __init__(self) -> None:
        self.sites: list[dict[str, Any]] = []
        self._parent_stack: list[ast.AST] = []

    def generic_visit(self, node: ast.AST) -> None:
        self._parent_stack.append(node)
        try:
            super().generic_visit(node)
        finally:
            self._parent_stack.pop()

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # 必须捕 Exception 本类（不是子类如 KeyError，不是裸 except）
        is_bare_exception = (
            isinstance(node.type, ast.Name)
            and node.type.id == "Exception"
            and node.name is None  # 不允许 ``as e`` —— 那种通常会 logger.error
        )
        # 处理体**仅**包含 ``pass``
        body_is_only_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)

        if is_bare_exception and body_is_only_pass:
            self.sites.append(
                {
                    "lineno": node.lineno,
                    "qualified_name": _qualified_name(node, self._parent_stack),
                }
            )
        # **必须** call generic_visit：except 块体内部可以嵌套 try/except
        # （比如 server_feedback.py:543 的 ``except ValueError:`` 内嵌
        # ``try: ... except Exception: pass``），不调 generic_visit 就
        # 漏扫嵌套层。pre-fix 把 24 site 漏报成 22 site。
        self.generic_visit(node)


def scan_file(filepath: Path) -> list[dict[str, Any]]:
    """扫描单个 .py 文件，返回所有匹配的 site dict 列表。"""
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    scanner = _BareExceptPassScanner()
    scanner.visit(tree)
    # ``relative_to`` 在 filepath 不在 REPO_ROOT 子树时会抛
    # ValueError——R120 测试故意用 ``tempfile`` 在 ``/tmp/`` 调
    # ``scan_file`` 验证 scanner 的边缘行为，所以这里 graceful
    # fallback 到绝对路径字符串。生产路径下所有 src/ 文件都在 REPO_ROOT
    # 下，相对路径 always 命中 try 分支。
    try:
        rel_path = filepath.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel_path = filepath.as_posix()
    return [
        {
            "file": rel_path,
            "lineno": s["lineno"],
            "qualified_name": s["qualified_name"],
        }
        for s in scanner.sites
    ]


def scan_repo(root: Path = SRC_ROOT) -> list[dict[str, Any]]:
    """扫描 src/ 全部 .py，返回排序后的 site 列表。

    排序键：(file, qualified_name, lineno)——相同函数内多个 site 用
    lineno 区分；不同函数用 qualified_name；不同文件用 file。
    """
    all_sites: list[dict[str, Any]] = []
    for py_file in sorted(root.rglob("*.py")):
        all_sites.extend(scan_file(py_file))
    all_sites.sort(key=lambda s: (s["file"], s["qualified_name"], s["lineno"]))
    return all_sites


def load_baseline() -> list[dict[str, Any]]:
    """从 JSON 加载 baseline；不存在时返回空列表。"""
    if not BASELINE_PATH.exists():
        return []
    raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    sites = raw.get("approved_sites", [])
    sites.sort(key=lambda s: (s["file"], s["qualified_name"], s["lineno"]))
    return sites


def write_baseline(sites: list[dict[str, Any]]) -> None:
    """写 JSON baseline，包含元数据 + 站点列表。"""
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_doc": (
            "R120 silent-failure baseline — by-file 审计批准的 "
            "`except Exception: pass` 站点。**未在此列表的新 site 会让 "
            "tests/test_silent_failure_regression_guard_r120.py 失败**。"
            "新增条目须配套 R-series CHANGELOG 解释为什么这个 site 是 "
            "intentional silent。批准来源：R107-R110 / R114 / R117 / "
            "R118 / R119 audit + R120 baseline 初版（notification_manager "
            "stats 站点：外层 `except Exception as e: logger.error(...)` "
            "已提供 observability，同 R118 4th-site 排除模式）。"
        ),
        "_how_to_update": (
            "本地跑 `uv run python scripts/silent_failure_audit.py "
            "update-baseline`；CI 不允许调此命令。新增条目必须对应 "
            "R-series commit 文档化的 intentional silence。"
        ),
        "approved_sites": sites,
    }
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def diff_sites(
    current: list[dict[str, Any]], baseline: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 ``(新增, 已移除)`` 两个列表。

    指纹用 (file, qualified_name) 二元组——不带 lineno，所以同函数内
    加注释不会触发 false positive。同函数有多个 site 时通过 multiset
    计数比较。
    """
    from collections import Counter

    def _fingerprint(s: dict[str, Any]) -> tuple[str, str]:
        return (s["file"], s["qualified_name"])

    current_count = Counter(_fingerprint(s) for s in current)
    baseline_count = Counter(_fingerprint(s) for s in baseline)

    added_fps: list[tuple[str, str]] = []
    for fp, count in current_count.items():
        delta = count - baseline_count.get(fp, 0)
        if delta > 0:
            added_fps.extend([fp] * delta)

    removed_fps: list[tuple[str, str]] = []
    for fp, count in baseline_count.items():
        delta = count - current_count.get(fp, 0)
        if delta > 0:
            removed_fps.extend([fp] * delta)

    added = [s for s in current if _fingerprint(s) in added_fps]
    removed = [s for s in baseline if _fingerprint(s) in removed_fps]
    return added, removed


def cmd_list() -> int:
    """打印当前所有匹配 site，便于人工审阅。"""
    sites = scan_repo()
    print(f"# silent-failure audit — {len(sites)} site(s) found in src/")
    print()
    for site in sites:
        print(f"{site['file']}:{site['lineno']:>4d}  {site['qualified_name']}")
    return 0


def cmd_check() -> int:
    """对比 baseline，新增即 exit 1（CI 用）。"""
    current = scan_repo()
    baseline = load_baseline()
    added, removed = diff_sites(current, baseline)

    if not added and not removed:
        print(f"OK — {len(current)} approved site(s); none added, none removed.")
        return 0

    print(
        f"FAIL — silent-failure baseline drift detected ("
        f"current={len(current)}, baseline={len(baseline)}, "
        f"added={len(added)}, removed={len(removed)})"
    )
    if added:
        print()
        print("Added (not in baseline — new silent failure introduced?):")
        for s in added:
            print(f"  + {s['file']}:{s['lineno']:>4d}  {s['qualified_name']}")
        print()
        print(
            "If these sites are intentional, document each with a "
            "CHANGELOG R-series entry explaining the symptom-to-cause "
            "rationale, then run `uv run python scripts/silent_failure_audit.py "
            "update-baseline`."
        )
    if removed:
        print()
        print("Removed (in baseline but no longer in source — refactored?):")
        for s in removed:
            print(f"  - {s['file']}:{s['lineno']:>4d}  {s['qualified_name']}")
        print()
        print(
            "Removed sites are usually fine (cleanup), but please confirm "
            "they were not silently re-introduced under a different "
            "qualified_name. Run `update-baseline` once confirmed."
        )
    return 1


def cmd_update_baseline() -> int:
    """重写 baseline 为当前扫描结果（人类审阅后用）。"""
    current = scan_repo()
    write_baseline(current)
    print(f"Baseline updated: {len(current)} approved site(s) written to")
    print(f"  {BASELINE_PATH.relative_to(REPO_ROOT)}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "list":
        return cmd_list()
    if cmd == "check":
        return cmd_check()
    if cmd == "update-baseline":
        return cmd_update_baseline()
    print(f"Unknown command: {cmd}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
