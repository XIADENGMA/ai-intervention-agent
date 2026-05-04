#!/usr/bin/env python3
"""CI 门禁：locale JSON 之间必须保持结构与占位符一致性。

与现有 ``scripts/check_locales.py`` 的区别：
- ``check_locales.py`` 只校验 key 集合，不检查嵌套类型与 ``{{placeholder}}``
  变量的一致性。
- 本脚本覆盖**三条**不变量（与 ``tests/test_i18n_locale_key_parity.py`` 同源）：
    1. 同一 locale 目录下所有 ``*.json`` 的 key 集合（递归展平）必须一致；
    2. 每个 key 的值类型（``str`` vs ``dict``）必须在所有 locale 中一致；
    3. 同一 key 对应的字符串里，``{{name}}`` 占位符集合必须一致——否则
       ``t('...', { name })`` 在部分 locale 会丢失参数。

覆盖目录：
- ``static/locales/`` —— Web UI locale
- ``packages/vscode/locales/`` —— VSCode webview locale

退出码：
- 0：全部一致
- 1：至少一个目录存在不一致
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

LOCALE_DIRS: tuple[tuple[Path, str], ...] = (
    (ROOT / "static" / "locales", "Web UI"),
    (ROOT / "packages" / "vscode" / "locales", "VSCode"),
)

PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _flatten_paths(data: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out[path] = "obj"
                out.update(_flatten_paths(v, path))
            else:
                out[path] = "str"
    return out


def _collect_placeholders(data: Any, prefix: str = "") -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_collect_placeholders(v, path))
            elif isinstance(v, str):
                out[path] = set(PLACEHOLDER_RE.findall(v))
    return out


def _load_locales(dir_path: Path) -> dict[str, Any]:
    """Return ``{locale_name: parsed_json}`` for every ``*.json`` in dir."""
    result: dict[str, Any] = {}
    for path in sorted(dir_path.glob("*.json")):
        result[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return result


def check_directory(dir_path: Path, label: str) -> list[str]:
    """Return a list of human-readable errors for the given locale directory."""
    errors: list[str] = []
    if not dir_path.is_dir():
        return errors
    locales = _load_locales(dir_path)
    if "en" not in locales:
        errors.append(f"[{label}] missing en.json in {dir_path}")
        return errors
    reference_paths = _flatten_paths(locales["en"])
    reference_placeholders = _collect_placeholders(locales["en"])
    ref_keys = set(reference_paths)
    for name, data in locales.items():
        if name == "en":
            continue
        got_paths = _flatten_paths(data)
        got_keys = set(got_paths)
        for missing in sorted(ref_keys - got_keys):
            errors.append(f"[{label}] {name}.json missing key: {missing}")
        for extra in sorted(got_keys - ref_keys):
            errors.append(f"[{label}] {name}.json has extra key: {extra}")
        for path, ref_type in reference_paths.items():
            got_type = got_paths.get(path)
            if got_type is None or got_type == ref_type:
                continue
            errors.append(
                f"[{label}] {name}.json type mismatch at {path!r}: "
                f"{got_type!r} vs en.json {ref_type!r}"
            )
        got_placeholders = _collect_placeholders(data)
        for path, ref_set in reference_placeholders.items():
            got_set = got_placeholders.get(path)
            if got_set is None or got_set == ref_set:
                continue
            missing = sorted(ref_set - got_set)
            extra = sorted(got_set - ref_set)
            errors.append(
                f"[{label}] {name}.json placeholder mismatch at {path!r}: "
                f"missing={missing} extra={extra}"
            )
    return errors


def main() -> int:
    all_errors: list[str] = []
    for dir_path, label in LOCALE_DIRS:
        all_errors.extend(check_directory(dir_path, label))
    if all_errors:
        print(f"Found {len(all_errors)} locale parity issue(s):")
        for err in all_errors:
            print(f"  - {err}")
        return 1
    print("OK: locale JSON parity checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
