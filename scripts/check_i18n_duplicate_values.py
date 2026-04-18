#!/usr/bin/env python3
"""CI 门禁（warn 级）：检测 locale JSON 里相同字符串值被多个 key 引用。

设计目标 —— 从 ``oliviertassinari/i18n-extract`` 的 highly-duplicated keys
检测思路演化而来，但针对本项目特点做了三点调优：

1. **按目录独立判定**：``static/locales`` 与 ``packages/vscode/locales``
   彼此独立。Web UI 和 VSCode webview 有各自的 key 空间，跨空间重复是
   正常的（例如两边都有 ``ui.submit.label``）。

2. **短值豁免**：长度 < ``MIN_LEN`` 字符的 value 不做判定。``"OK"`` /
   ``"Cancel"`` / ``"Retry"`` 这种词在多个命名空间下重复出现是**惯例**，
   合并反而会让 key 变成 ``common.ok`` 之类"上帝命名空间"，违反
   intlpull.com 2026 指南"按 feature 而非 ui-element 命名"原则。

3. **显式白名单**：``ALLOWLIST_VALUES`` 列出项目内已达成共识的
   常见重复值（例如 ``"Loading…"`` / ``"Copied"``）。进入白名单
   的条件应在 PR review 里显式讨论，避免 warn 噪声淹没真实信号。

---

**退出码**：
- ``0``：warn 级，总是成功（即使发现重复也不阻断 CI）；
- ``1``：保留给未来的 ``--strict`` 模式或 I/O 异常。

**为什么 warn 而不是 fail**：
duplicate value 天然是 lint hint，而不是 invariant。如果降级为 warn
级、但信号仍然抛在终端和 CI 日志里，维护者能在合并前主动合并 key；
升级为 fail 会在每次加合法短词时都卡住 PR，ROI 负数。
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

LOCALE_DIRS: tuple[tuple[Path, str], ...] = (
    (ROOT / "static" / "locales", "Web UI"),
    (ROOT / "packages" / "vscode" / "locales", "VSCode"),
)

# 短于此长度的 value 不纳入判定（见模块 docstring）。
MIN_LEN = 6

# 已达成共识的合理重复值。请在提交前确认：
# - 值在 ≥ 2 个不同 feature 命名空间下出现（不是同一命名空间内的抄袭）
# - 合并这些 key 会破坏 intlpull.com 命名规约（feature.component.modifier）
ALLOWLIST_VALUES: frozenset[str] = frozenset(
    {
        # Web UI: status 与 page 两个命名空间下的通用动作反馈
        "Copied",
        "Copy failed",
        # VSCode notify.hint + ui.task 也可能共用这个短词
        "Retry",
    }
)


def _walk_leaves(data: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten ``dict`` → ``[(dotted.path, value_str)]``。"""
    out: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.extend(_walk_leaves(v, path))
            elif isinstance(v, str):
                out.append((path, v))
    return out


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def detect_duplicates(
    dir_path: Path,
    label: str,
) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Return a list of ``(locale_name, value, [(path, same_value), ...])``
    tuples. Each tuple describes one value that appears at multiple keys
    within a single locale file."""
    reports: list[tuple[str, str, list[tuple[str, str]]]] = []
    if not dir_path.is_dir():
        return reports
    for json_path in sorted(dir_path.glob("*.json")):
        data = _load(json_path)
        leaves = _walk_leaves(data)
        by_value: dict[str, list[str]] = defaultdict(list)
        for p, v in leaves:
            if len(v) < MIN_LEN:
                continue
            if v in ALLOWLIST_VALUES:
                continue
            by_value[v].append(p)
        for value, paths in sorted(by_value.items()):
            if len(paths) < 2:
                continue
            reports.append(
                (
                    f"[{label}] {json_path.name}",
                    value,
                    [(p, value) for p in sorted(paths)],
                )
            )
    return reports


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    strict = "--strict" in argv

    total = 0
    for dir_path, label in LOCALE_DIRS:
        reports = detect_duplicates(dir_path, label)
        total += len(reports)
        for tag, value, paths in reports:
            print(f"WARN {tag} duplicate value:")
            print(f"       value = {value!r}")
            for p, _ in paths:
                print(f"       at    = {p}")

    if total == 0:
        print("OK: no duplicate locale values above threshold")
        return 0

    print(f"\n{total} duplicate value group(s) found above MIN_LEN={MIN_LEN}.")
    print("This is informational. Consider consolidating keys only if the ")
    print("duplicates belong to the same feature namespace.")
    if strict:
        print("(--strict set: exiting non-zero)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
